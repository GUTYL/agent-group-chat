"""ChatRoom — 群聊核心运行逻辑"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from agc.core.agent import AgentConfig
from agc.core.context import ContextManager
from agc.core.human_in_loop import HumanInTheLoop, HumanMode
from agc.core.message import Message, MessageType
from agc.core.room import RoomConfig
from agc.core.workspace import WorkspaceManager
from agc.llm.base import LLMBase
from agc.schedulers.base import SchedulerBase
from agc.schedulers.hybrid import HybridScheduler
from agc.schedulers.round_robin import RoundRobinScheduler
from agc.terminators.composite import CompositeTerminator
from agc.terminators.consensus import ConsensusTerminator
from agc.terminators.max_rounds import MaxRoundsTerminator
from agc.tools.base import execute_tool_call, get_schemas_for_tools

logger = logging.getLogger(__name__)

# 工具调用最大轮次（防止死循环）
MAX_TOOL_ROUNDS = 3


@dataclass
class ChatResult:
    """群聊结果"""

    topic: str
    messages: list[Message]
    summary: str = ""
    total_tokens: int = 0
    rounds: int = 0
    stop_reason: str = ""


class ChatRoom:
    """群聊房间 — 管理多Agent讨论的完整生命周期"""

    def __init__(
        self,
        name: str,
        agents: list[AgentConfig],
        llm: LLMBase | None = None,
        scheduler: str = "hybrid",
        max_rounds: int = 20,
        context_window: int = 8000,
        verbose: bool = True,
        base_url: str | None = None,
        api_key: str | None = None,
        tools: list[str] | None = None,
        workspace_root: str | None = None,
        human: HumanInTheLoop | None = None,
    ):
        """
        Args:
            name: 房间名
            agents: 参与者列表
            llm: 默认LLM客户端
            scheduler: 调度策略 "round_robin" 或 "hybrid"
            max_rounds: 最大轮数
            context_window: 上下文token上限
            verbose: 是否打印过程
            base_url: 全局LLM API端点
            api_key: 全局API Key
            tools: 启用的工具名列表
            workspace_root: 工作空间根目录（None=不使用工作空间）
            human: 人类参与模块（None=不参与）
        """
        self.config = RoomConfig(
            name=name,
            agents=agents,
            scheduler=scheduler,
            max_rounds=max_rounds,
            context_window=context_window,
            verbose=verbose,
            base_url=base_url,
            api_key=api_key,
        )
        self.history: list[Message] = []
        self._turn_counts: dict[str, int] = {}

        # ── 工作空间 ──────────────────────────────────────
        self._workspace_mgr: WorkspaceManager | None = None
        if workspace_root:
            self._workspace_mgr = WorkspaceManager(workspace_root)
            for agent in agents:
                self._workspace_mgr.get(agent.name)
            logger.info(f"工作空间已初始化: {workspace_root}")

        # ── 人类参与 ─────────────────────────────────────
        self._human: HumanInTheLoop | None = human

        # ── 工具配置 ──────────────────────────────────────
        self._enabled_tools: list[str] = list(tools or [])

        # 如果有工作空间，自动注册工作区工具
        if self._workspace_mgr:
            from agc.tools.workspace import register_workspace_tools
            ws_tool_names = register_workspace_tools(self._workspace_mgr)
            for tn in ws_tool_names:
                if tn not in self._enabled_tools:
                    self._enabled_tools.append(tn)

            # 有工作空间就自动注册记忆工具（纯本地，无需API Key）
            from agc.tools.memory import register_memory_tools
            mem_tool_names = register_memory_tools(self._workspace_mgr)
            for tn in mem_tool_names:
                if tn not in self._enabled_tools:
                    self._enabled_tools.append(tn)

        self._tool_schemas: list[dict] = get_schemas_for_tools(self._enabled_tools)

        # ── LLM客户端 ────────────────────────────────────
        self._llm_clients: dict[str, LLMBase] = {}
        for agent in agents:
            agent_base_url = agent.base_url or base_url
            agent_api_key = agent.api_key or api_key
            if llm and not agent_base_url and not agent_api_key:
                self._llm_clients[agent.name] = llm
            else:
                from agc.llm.openai_client import OpenAIClient
                self._llm_clients[agent.name] = OpenAIClient(
                    api_key=agent_api_key,
                    base_url=agent_base_url,
                    default_model=agent.model,
                )

        # 默认LLM
        self.llm = llm or self._llm_clients[agents[0].name]

        # ── 调度器 ─────────────────────────────────────────
        if scheduler == "round_robin":
            self._scheduler: SchedulerBase = RoundRobinScheduler(agents)
        elif scheduler == "hybrid":
            self._scheduler = HybridScheduler(agents, llm=self.llm, use_llm_router=True)
        else:
            raise ValueError(f"未知调度策略: {scheduler}")

        # ── 上下文管理器 ──────────────────────────────────
        self._context = ContextManager(self.llm, max_tokens=context_window)

        # ── 终止检测器 ────────────────────────────────────
        self._terminator = CompositeTerminator([
            ConsensusTerminator(window=3, threshold=2.0),
            MaxRoundsTerminator(max_rounds=max_rounds),
        ])

        # system prompt 缓存
        self._system_prompts: dict[str, str] = {}

        # 回调钩子
        self._on_message_callbacks: list = []

    def on_message(self, callback):
        """注册消息回调"""
        self._on_message_callbacks.append(callback)

    def chat(self, topic: str) -> ChatResult:
        """启动群聊讨论"""
        self.history = []
        self._turn_counts = {a.name: 0 for a in self.config.agents}
        self._system_prompts = {}

        # 预构建每个agent的system prompt（含工具+工作空间说明）
        extra_prompts = self._build_workspace_prompts()
        for agent in self.config.agents:
            prompt = agent.build_system_prompt(
                topic, self.config.agents,
                extra=extra_prompts.get(agent.name, ""),
            )
            self._system_prompts[agent.name] = prompt

        # 发出初始话题
        self._emit_system(f"讨论话题: {topic}")

        round_idx = 0
        total_tokens = 0

        while True:
            # 选择下一个发言者
            speaker = self._scheduler.next_speaker(self.history, round_idx)

            # 检查该agent是否超过发言次数限制
            if speaker.max_turns > 0 and self._turn_counts[speaker.name] >= speaker.max_turns:
                round_idx += 1
                all_exhausted = all(
                    (a.max_turns > 0 and self._turn_counts[a.name] >= a.max_turns)
                    for a in self.config.agents
                )
                if all_exhausted:
                    self._emit_system("所有参与者已达到发言上限，讨论结束。")
                    break
                continue

            # 调用LLM生成回复（含工具调用循环）
            messages, tokens = self._generate_response(speaker, topic)
            for msg in messages:
                self.history.append(msg)
                self._turn_counts[speaker.name] += 1 if msg.msg_type == MessageType.chat else 0
                total_tokens += msg.metadata.get("tokens", 0)
                for cb in self._on_message_callbacks:
                    cb(msg)

            # ── 人类参与：暂停等人类输入 ────────────────────
            if self._human and self._human.should_pause(round_idx):
                human_msg = self._human.get_input(round_idx, speaker.name)
                if human_msg:
                    self.history.append(human_msg)
                    for cb in self._on_message_callbacks:
                        cb(human_msg)
                    # 检查人类是否要求停止
                    if human_msg.metadata.get("force_stop"):
                        self._emit_system("人类参与者在讨论中要求结束。")
                        break

            # 检查终止条件
            should_stop, reason = self._terminator.should_stop(
                self.history, self.config.agents
            )
            if should_stop:
                self._emit_system(f"讨论结束: {reason}")
                break

            round_idx += 1

            # 安全阀：硬性上限
            total_turns = len(self.history)
            hard_limit = self.config.max_rounds * len(self.config.agents)
            if total_turns >= hard_limit:
                self._emit_system(f"达到硬性上限 {hard_limit} 轮发言，讨论结束。")
                break

        # 生成总结
        summary = self._generate_summary(topic)

        # 打印工作空间概要
        if self._workspace_mgr:
            ws_summary = self._workspace_mgr.get_all_summaries()
            if ws_summary:
                logger.info(f"工作空间最终状态:\n{ws_summary}")

        return ChatResult(
            topic=topic,
            messages=self.history,
            summary=summary,
            total_tokens=total_tokens,
            rounds=round_idx,
            stop_reason=self.history[-1].content if self.history else "",
        )

    def _build_workspace_prompts(self) -> dict[str, str]:
        """为每个agent构建工作空间相关的system prompt补充"""
        if not self._workspace_mgr:
            return {}

        prompts = {}
        for agent in self.config.agents:
            lines = [
                f"\n## 你的工作空间",
                f"你有独立的工作空间目录: {self._workspace_mgr.get(agent.name).path}",
                f"你可以用以下工具管理你的工作空间：",
                f"- write_file: 写入文件",
                f"- read_file: 读取文件（也可以读取其他agent的文件）",
                f"- list_files: 列出文件目录",
                f"- run_code: 执行shell命令",
                f"",
                f"建议：分析问题后，把关键发现或代码写入工作空间文件，方便其他agent参考。",
                f"其他agent可以通过 read_file(owner='你的名字', filepath=...) 读取你的文件。",
                f"",
                f"## 你的记忆",
                f"你有专属的记忆工具，用于保存和检索关键信息：",
                f"- save_memory: 保存重要事实、结论、决策依据",
                f"- recall_memory: 搜索之前保存的记忆",
                f"- list_memories: 列出所有记忆",
                f"- delete_memory: 删除不再需要的记忆",
                f"",
                f"重要：当你发现关键事实或做出重要结论时，立即用 save_memory 保存，",
                f"避免后续重复研究。讨论中需要引用之前的信息时，用 recall_memory 查找。",
            ]
            prompts[agent.name] = "\n".join(lines)
        return prompts

    def _generate_response(self, agent: AgentConfig, topic: str) -> tuple[list[Message], int]:
        """调用LLM生成agent回复，支持工具调用循环"""
        # 确定这个agent可用的工具schema
        agent_tools = self._resolve_tools(agent)
        llm = self._llm_clients.get(agent.name, self.llm)
        result_messages: list[Message] = []
        total_tokens = 0
        round_idx = len(self.history) // max(len(self.config.agents), 1)

        for tool_round in range(MAX_TOOL_ROUNDS + 1):
            context_messages = self._context.build_messages(
                agent, topic, self.history, self.config.agents,
                system_prompt=self._system_prompts.get(agent.name),
            )
            # 把本轮已有的工具交互消息加入上下文
            for rm in result_messages:
                context_messages.append(rm.to_openai_msg())

            response = llm.chat(
                messages=context_messages,
                model=agent.model,
                temperature=agent.temperature,
                tools=agent_tools or None,
            )
            total_tokens += response.total_tokens

            if response.has_tool_calls:
                assistant_msg = Message(
                    sender=agent.name,
                    content=response.content or "",
                    msg_type=MessageType.tool_call,
                    round_idx=round_idx,
                    tool_calls=response.tool_calls,
                    metadata={"tokens": response.total_tokens, "model": response.model},
                )
                result_messages.append(assistant_msg)
                for cb in self._on_message_callbacks:
                    cb(assistant_msg)

                for tc in response.tool_calls:
                    func_name = tc["function"]["name"]
                    func_args = tc["function"]["arguments"]

                    # 注入_owner用于工作区工具路由
                    tool_result = execute_tool_call(func_name, func_args, owner=agent.name)

                    tool_msg = Message(
                        sender="tool",
                        content=tool_result.content[:2000],
                        msg_type=MessageType.tool_result,
                        round_idx=round_idx,
                        tool_call_id=tc["id"],
                        metadata={"tool_name": func_name, "tool_success": tool_result.success},
                    )
                    result_messages.append(tool_msg)
                    for cb in self._on_message_callbacks:
                        cb(tool_msg)
                continue

            else:
                content = response.content.strip()
                mentions = self._parse_mentions(content)

                final_msg = Message(
                    sender=agent.name,
                    content=content,
                    msg_type=MessageType.mention if mentions else MessageType.chat,
                    mentions=mentions,
                    round_idx=round_idx,
                    metadata={
                        "tokens": response.total_tokens,
                        "model": response.model,
                        "finish_reason": response.finish_reason,
                    },
                )
                result_messages.append(final_msg)
                break
        else:
            logger.warning(f"Agent {agent.name} 工具调用超过 {MAX_TOOL_ROUNDS} 轮，强制停止")

        return result_messages, total_tokens

    def _resolve_tools(self, agent: AgentConfig) -> list[dict]:
        """确定agent可用的工具schema列表"""
        # agent.tools 是白名单，如果指定了就只用那些
        if agent.tools:
            return get_schemas_for_tools(agent.tools)
        # 否则用全局工具列表
        return self._tool_schemas

    def _generate_summary(self, topic: str) -> str:
        """生成群聊总结"""
        conversation = "\n".join(m.format_display() for m in self.history[-20:])

        # 工作空间信息
        ws_info = ""
        if self._workspace_mgr:
            ws_info = f"\n\n各Agent工作空间:\n{self._workspace_mgr.get_all_summaries()}"

        prompt = f"""请对以下群聊讨论进行总结，包括：
1. 讨论的核心问题
2. 各方主要观点
3. 达成的共识
4. 未解决的分歧
5. 最终建议

讨论话题: {topic}

对话记录:
{conversation}
{ws_info}

总结："""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
            )
            return response.content
        except Exception as e:
            logger.warning(f"总结生成失败: {e}")
            return "（总结生成失败）"

    def _parse_mentions(self, content: str) -> list[str]:
        """解析消息中的 @mentions"""
        agent_names = {a.name for a in self.config.agents}
        # 也允许 @human
        if self._human:
            agent_names.add(self._human.name)
        mentions = re.findall(r"@(\w+)", content)
        return [m for m in mentions if m in agent_names]

    def _emit_system(self, content: str) -> Message:
        """发出系统消息"""
        msg = Message(
            sender="system",
            content=content,
            msg_type=MessageType.system,
            round_idx=len(self.history) // max(len(self.config.agents), 1),
        )
        self.history.append(msg)
        for cb in self._on_message_callbacks:
            cb(msg)
        return msg