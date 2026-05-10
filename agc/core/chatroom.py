"""ChatRoom — 群聊核心运行逻辑"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from agc.core.agent import AgentConfig
from agc.core.context import ContextManager
from agc.core.human_in_loop import HumanInTheLoop
from agc.core.message import Message, MessageType
from agc.core.room import RoomConfig
from agc.core.workspace import WorkspaceManager
from agc.llm.base import LLMBase
from agc.llm.openai_client import OpenAIClient
from agc.schedulers.base import SchedulerBase
from agc.schedulers.hybrid import HybridScheduler
from agc.schedulers.round_robin import RoundRobinScheduler
from agc.terminators.composite import CompositeTerminator
from agc.terminators.consensus import ConsensusTerminator
from agc.terminators.max_rounds import MaxRoundsTerminator
from agc.tools.base import execute_tool_call, get_schemas_for_tools

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
MAX_TOOL_RESULT_LENGTH = 2000
SUMMARY_TEMPERATURE = 0.3
SUMMARY_MAX_TOKENS = 800
SUMMARY_RECENT_MSGS = 20


@dataclass
class ChatResult:
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
        stream: bool = True,
    ):
        self.config = RoomConfig(
            name=name, agents=agents, scheduler=scheduler,
            max_rounds=max_rounds, context_window=context_window,
            verbose=verbose, base_url=base_url, api_key=api_key,
        )
        self.history: list[Message] = []
        self._turn_counts: dict[str, int] = {}
        self._system_prompts: dict[str, str] = {}
        self._stream = stream

        self._workspace_mgr = self._init_workspace(workspace_root, agents)
        self._human = human
        self._enabled_tools: list[str] = list(tools or [])
        self._auto_register_tools()
        self._llm_clients = self._init_llm_clients(agents, llm, base_url, api_key)
        self.llm = llm or self._llm_clients[agents[0].name]
        self._scheduler = self._init_scheduler(scheduler, agents)
        self._context = ContextManager(self.llm, max_tokens=context_window)
        self._terminator = CompositeTerminator([
            ConsensusTerminator(window=3, threshold=2.0),
            MaxRoundsTerminator(max_rounds=max_rounds),
        ])

        self._on_message_callbacks: list[Callable[[Message], None]] = []
        self._on_chunk_callbacks: list[Callable[[str], None]] = []
        self._on_speaker_callbacks: list[Callable[[str, str, str], None]] = []

    # ── Initializers ───────────────────────────────────────

    @staticmethod
    def _init_workspace(workspace_root: str | None, agents: list[AgentConfig]) -> WorkspaceManager | None:
        if not workspace_root:
            return None
        mgr = WorkspaceManager(workspace_root)
        for agent in agents:
            mgr.get(agent.name)
        logger.info(f"工作空间已初始化: {workspace_root}")
        return mgr

    @staticmethod
    def _init_llm_clients(
        agents: list[AgentConfig],
        llm: LLMBase | None,
        base_url: str | None,
        api_key: str | None,
    ) -> dict[str, LLMBase]:
        clients: dict[str, LLMBase] = {}
        for agent in agents:
            agent_base_url = agent.base_url or base_url
            agent_api_key = agent.api_key or api_key
            if llm and not agent_base_url and not agent_api_key:
                clients[agent.name] = llm
            else:
                clients[agent.name] = OpenAIClient(
                    api_key=agent_api_key, base_url=agent_base_url, default_model=agent.model,
                )
        return clients

    @staticmethod
    def _init_scheduler(name: str, agents: list[AgentConfig]) -> SchedulerBase:
        if name == "round_robin":
            return RoundRobinScheduler(agents)
        if name == "hybrid":
            return HybridScheduler(agents, use_llm_router=True)
        raise ValueError(f"未知调度策略: {name}")

    # ── Callback registration ──────────────────────────────

    def on_message(self, callback: Callable[[Message], None]) -> None:
        self._on_message_callbacks.append(callback)

    def on_chunk(self, callback: Callable[[str], None]) -> None:
        self._on_chunk_callbacks.append(callback)

    def on_speaker_start(self, callback: Callable[[str, str, str], None]) -> None:
        self._on_speaker_callbacks.append(callback)

    def _emit_chunk(self, text: str) -> None:
        for cb in self._on_chunk_callbacks:
            cb(text)

    def _emit_speaker_start(self, name: str, role: str, model: str) -> None:
        for cb in self._on_speaker_callbacks:
            cb(name, role, model)

    def _emit_system(self, content: str) -> Message:
        msg = Message(
            sender="system", content=content, msg_type=MessageType.system,
            round_idx=len(self.history) // max(len(self.config.agents), 1),
        )
        self.history.append(msg)
        for cb in self._on_message_callbacks:
            cb(msg)
        return msg

    # ── Main loop ──────────────────────────────────────────

    def chat(self, topic: str) -> ChatResult:
        self._reset_state()
        self._build_system_prompts(topic)
        self._emit_system(f"讨论话题: {topic}")

        round_idx = 0
        total_tokens = 0

        while True:
            speaker = self._scheduler.next_speaker(self.history, round_idx)
            if self._speaker_exhausted(speaker):
                if self._all_exhausted():
                    self._emit_system("所有参与者已达到发言上限，讨论结束。")
                    break
                continue

            self._emit_speaker_start(speaker.name, speaker.role, speaker.model)
            messages, tokens = self._generate_response(speaker, topic)
            self._process_messages(messages, speaker.name, tokens)
            total_tokens += tokens

            if self._handle_human_pause(round_idx, speaker.name):
                break

            if self._check_termination():
                break

            round_idx += 1
            if self._hit_hard_limit():
                break

        summary = self._generate_summary(topic)
        return ChatResult(
            topic=topic, messages=self.history, summary=summary,
            total_tokens=total_tokens, rounds=round_idx,
            stop_reason=self.history[-1].content if self.history else "",
        )

    def _reset_state(self) -> None:
        self.history = []
        self._turn_counts = {a.name: 0 for a in self.config.agents}
        self._system_prompts = {}

    def _build_system_prompts(self, topic: str) -> None:
        extra_prompts = self._build_workspace_prompts()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        time_hint = f"\n\n当前时间: {now}"
        for agent in self.config.agents:
            self._system_prompts[agent.name] = agent.build_system_prompt(
                topic, self.config.agents,
                extra=extra_prompts.get(agent.name, "") + time_hint,
            )

    def _speaker_exhausted(self, speaker: AgentConfig) -> bool:
        """返回 True 表示需要跳过该发言人（未耗尽则 False）"""
        if speaker.max_turns <= 0:
            return False
        if self._turn_counts[speaker.name] < speaker.max_turns:
            return False
        return True

    def _all_exhausted(self) -> bool:
        return all(
            a.max_turns > 0 and self._turn_counts.get(a.name, 0) >= a.max_turns
            for a in self.config.agents
        )

    def _process_messages(self, messages: list[Message], speaker_name: str, tokens: int) -> None:
        for msg in messages:
            self.history.append(msg)
            if msg.msg_type == MessageType.chat:
                self._turn_counts[speaker_name] += 1
            if msg.metadata.get("_emitted"):
                continue
            for cb in self._on_message_callbacks:
                cb(msg)

    def _handle_human_pause(self, round_idx: int, speaker_name: str) -> bool:
        if not self._human or not self._human.should_pause(round_idx):
            return False
        human_msg = self._human.get_input(round_idx, speaker_name)
        if not human_msg:
            return False
        self.history.append(human_msg)
        for cb in self._on_message_callbacks:
            cb(human_msg)
        if human_msg.metadata.get("force_stop"):
            self._emit_system("人类参与者在讨论中要求结束。")
            return True
        return False

    def _check_termination(self) -> bool:
        should_stop, reason = self._terminator.should_stop(self.history, self.config.agents)
        if should_stop:
            self._emit_system(f"讨论结束: {reason}")
        return should_stop

    def _hit_hard_limit(self) -> bool:
        limit = self.config.max_rounds * len(self.config.agents)
        if len(self.history) >= limit:
            self._emit_system(f"达到硬性上限 {limit} 轮发言，讨论结束。")
            return True
        return False

    # ── Tools ──────────────────────────────────────────────

    def _auto_register_tools(self) -> None:
        self._register_web_fetch()
        self._register_web_search()
        if self._workspace_mgr:
            self._register_workspace_tools()
        self._tool_schemas: list[dict[str, Any]] = get_schemas_for_tools(self._enabled_tools)

    def _register_web_fetch(self) -> None:
        if "web_fetch" in self._enabled_tools:
            return
        from agc.tools.web_fetch import register_web_fetch_tool
        register_web_fetch_tool()
        self._enabled_tools.append("web_fetch")
        logger.info("自动注册工具: web_fetch")

    def _register_web_search(self) -> None:
        if "web_search" in self._enabled_tools:
            return
        try:
            from agc.tools.search import create_search_tool
            if create_search_tool(provider="duckduckgo"):
                self._enabled_tools.append("web_search")
                logger.info("自动注册工具: web_search")
        except Exception:
            logger.debug("无可用的搜索后端，跳过 web_search")

    def _register_workspace_tools(self) -> None:
        from agc.tools.workspace import register_workspace_tools
        from agc.tools.memory import register_memory_tools
        for name in register_workspace_tools(self._workspace_mgr):
            if name not in self._enabled_tools:
                self._enabled_tools.append(name)
        for name in register_memory_tools(self._workspace_mgr):
            if name not in self._enabled_tools:
                self._enabled_tools.append(name)

    def _build_workspace_prompts(self) -> dict[str, str]:
        prompts: dict[str, str] = {}
        for agent in self.config.agents:
            parts: list[str] = []
            if self._workspace_mgr:
                ws_path = self._workspace_mgr.get(agent.name).path
                parts.extend([
                    f"\n## 你的工作空间",
                    f"你有独立的工作空间目录: {ws_path}",
                    f"可用工具: write_file / read_file / list_files / run_code",
                    f"\n## 你的记忆",
                    f"可用工具: save_memory / recall_memory / list_memories / delete_memory",
                ])
            web_tools = [t for t in self._enabled_tools if t.startswith("web_")]
            if web_tools:
                parts.extend([
                    f"\n## 网络工具",
                    f"可用: web_search, web_fetch",
                    f"建议先用 web_search 找到链接，再用 web_fetch 阅读页面详情。",
                ])
            if parts:
                prompts[agent.name] = "\n".join(parts)
        return prompts

    # ── Response generation ────────────────────────────────

    def _generate_response(self, agent: AgentConfig, topic: str) -> tuple[list[Message], int]:
        agent_tools = self._resolve_tools(agent)
        llm = self._llm_clients.get(agent.name, self.llm)
        result_messages: list[Message] = []
        total_tokens = 0
        round_idx = self._current_round()

        for _ in range(MAX_TOOL_ROUNDS + 1):
            ctx = self._build_context(agent, topic, result_messages)
            response = llm.chat(
                messages=ctx, model=agent.model, temperature=agent.temperature,
                tools=agent_tools or None,
                on_chunk=self._emit_chunk if self._stream else None,
            )
            total_tokens += response.total_tokens

            if response.has_tool_calls:
                self._execute_tool_calls(agent, response, result_messages, round_idx)
                continue

            result_messages.append(self._create_final_message(agent, response, round_idx))
            break
        else:
            logger.debug(f"Agent {agent.name} 工具调用超过 {MAX_TOOL_ROUNDS} 轮，强制生成文本回复")
            self._force_text_response(agent, topic, llm, result_messages, round_idx, total_tokens)

        return result_messages, total_tokens

    def _current_round(self) -> int:
        return len(self.history) // max(len(self.config.agents), 1)

    def _build_context(self, agent: AgentConfig, topic: str, result_messages: list[Message]) -> list[dict[str, Any]]:
        ctx = self._context.build_messages(
            agent, topic, self.history, self.config.agents,
            system_prompt=self._system_prompts.get(agent.name),
        )
        for rm in result_messages:
            ctx.append(rm.to_openai_msg())
        return ctx

    def _execute_tool_calls(self, agent: AgentConfig, response, result_messages: list[Message], round_idx: int) -> None:
        assistant_msg = Message(
            sender=agent.name, content=response.content or "",
            msg_type=MessageType.tool_call, round_idx=round_idx,
            tool_calls=response.tool_calls,
            reasoning_content=response.reasoning_content,
            metadata={"tokens": response.total_tokens, "model": response.model, "_emitted": True},
        )
        result_messages.append(assistant_msg)
        for cb in self._on_message_callbacks:
            cb(assistant_msg)

        for tc in response.tool_calls:
            func_name = tc["function"]["name"]
            func_args = tc["function"]["arguments"]
            tool_result = execute_tool_call(func_name, func_args, owner=agent.name)
            tool_msg = Message(
                sender="tool", content=tool_result.content[:MAX_TOOL_RESULT_LENGTH],
                msg_type=MessageType.tool_result, round_idx=round_idx,
                tool_call_id=tc["id"],
                metadata={"tool_name": func_name, "tool_success": tool_result.success, "_emitted": True},
            )
            result_messages.append(tool_msg)
            for cb in self._on_message_callbacks:
                cb(tool_msg)

    def _force_text_response(self, agent: AgentConfig, topic: str, llm, result_messages: list[Message], round_idx: int, total_tokens: int) -> None:
        try:
            ctx = self._build_context(agent, topic, result_messages)
            response = llm.chat(
                messages=ctx, model=agent.model, temperature=agent.temperature,
                tools=None, on_chunk=self._emit_chunk if self._stream else None,
            )
            result_messages.append(self._create_final_message(agent, response, round_idx))
        except Exception as e:
            logger.warning(f"强制无工具回复失败: {e}")

    def _create_final_message(self, agent: AgentConfig, response, round_idx: int) -> Message:
        content = response.content.strip()
        mentions = self._parse_mentions(content)
        return Message(
            sender=agent.name, content=content,
            msg_type=MessageType.mention if mentions else MessageType.chat,
            mentions=mentions, round_idx=round_idx,
            reasoning_content=response.reasoning_content,
            metadata={
                "tokens": response.total_tokens, "model": response.model,
                "finish_reason": response.finish_reason,
            },
        )

    def _resolve_tools(self, agent: AgentConfig) -> list[dict[str, Any]]:
        return get_schemas_for_tools(agent.tools) if agent.tools else self._tool_schemas

    def _parse_mentions(self, content: str) -> list[str]:
        agent_names = {a.name for a in self.config.agents}
        if self._human:
            agent_names.add(self._human.name)
        return [m for m in re.findall(r"@(\w+)", content) if m in agent_names]

    # ── Summary ────────────────────────────────────────────

    def _generate_summary(self, topic: str) -> str:
        conversation = "\n".join(
            m.format_display() for m in self.history[-SUMMARY_RECENT_MSGS:]
        )
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
                temperature=SUMMARY_TEMPERATURE, max_tokens=SUMMARY_MAX_TOKENS,
            )
            return response.content
        except Exception as e:
            logger.warning(f"总结生成失败: {e}")
            return "（总结生成失败）"
