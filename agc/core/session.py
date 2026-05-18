"""ChatSession ABC + SessionStore（JSONL 持久化）"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from agc import DEFAULT_SESSIONS_DIR
from agc.core.agent import AgentConfig
from agc.core.context import ContextManager
from agc.core.message import Message, MessageType
from agc.core.workspace import WorkspaceManager
from agc.llm.base import LLMBase
from agc.llm.openai_client import OpenAIClient
from agc.schedulers.base import SchedulerBase
from agc.schedulers.hybrid import HybridScheduler
from agc.schedulers.round_robin import RoundRobinScheduler
from agc.tools.base import execute_tool_call, get_schemas_for_tools

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
MAX_TOOL_RESULT_LENGTH = 2000


class ChatSession(ABC):
    """聊天会话基类 — 多Agent会话的共享逻辑"""

    def __init__(
        self,
        agents: list[AgentConfig],
        llm: LLMBase | None = None,
        context_window: int = 8000,
        base_url: str | None = None,
        api_key: str | None = None,
        stream: bool = True,
        workspace_root: str | None = None,
        tools: list[str] | None = None,
        scheduler: str = "hybrid",
        use_llm_route: bool = True,
    ):
        self.agents = agents
        self.history: list[Message] = []
        self._turn_counts: dict[str, int] = {a.name: 0 for a in agents}
        self._system_prompts: dict[str, str] = {}
        self._stream = stream

        self._workspace_mgr = self._init_workspace(workspace_root, agents)
        self._enabled_tools: list[str] = list(tools or [])
        self._auto_register_tools()
        self._llm_clients = self._init_llm_clients(agents, llm, base_url, api_key)
        self.llm = llm or self._llm_clients[agents[0].name]
        self._scheduler = self._init_scheduler(scheduler, agents, use_llm_route)
        self._context = ContextManager(self.llm, max_tokens=context_window)

        self._on_message_callbacks: list[Callable[[Message], None]] = []
        self._on_chunk_callbacks: list[Callable[[str], None]] = []
        self._on_speaker_callbacks: list[Callable[[str, str, str], None]] = []
        self._on_reasoning_callbacks: list[Callable[[str], None]] = []
        self._on_tool_batch_callbacks: list[Callable[[], None]] = []

    # ── Initializers ───────────────────────────────────────

    @staticmethod
    def _init_workspace(
        workspace_root: str | None, agents: list[AgentConfig]
    ) -> WorkspaceManager | None:
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
                    api_key=agent_api_key,
                    base_url=agent_base_url,
                    default_model=agent.model,
                )
        return clients

    def _init_scheduler(
        self, name: str, agents: list[AgentConfig], use_llm_route: bool = True
    ) -> SchedulerBase:
        if name == "round_robin":
            return RoundRobinScheduler(agents)
        if name == "hybrid":
            return HybridScheduler(agents, llm=self.llm, use_llm_router=use_llm_route)
        raise ValueError(f"未知调度策略: {name}")

    # ── Callback registration ──────────────────────────────

    def on_message(self, callback: Callable[[Message], None]) -> None:
        self._on_message_callbacks.append(callback)

    def on_chunk(self, callback: Callable[[str], None]) -> None:
        self._on_chunk_callbacks.append(callback)

    def on_speaker_start(self, callback: Callable[[str, str, str], None]) -> None:
        self._on_speaker_callbacks.append(callback)

    def on_reasoning(self, callback: Callable[[str], None]) -> None:
        self._on_reasoning_callbacks.append(callback)

    def on_tool_batch(self, callback: Callable[[], None]) -> None:
        self._on_tool_batch_callbacks.append(callback)

    def _emit_tool_batch(self) -> None:
        for cb in self._on_tool_batch_callbacks:
            cb()

    def _emit_chunk(self, text: str) -> None:
        for cb in self._on_chunk_callbacks:
            cb(text)

    def _emit_speaker_start(self, name: str, role: str, model: str) -> None:
        for cb in self._on_speaker_callbacks:
            cb(name, role, model)

    def _emit_reasoning(self, text: str) -> None:
        for cb in self._on_reasoning_callbacks:
            cb(text)

    def _emit_system(self, content: str) -> Message:
        msg = Message(
            sender="system",
            content=content,
            msg_type=MessageType.system,
            round_idx=len(self.history) // max(len(self.agents), 1),
        )
        self.history.append(msg)
        for cb in self._on_message_callbacks:
            cb(msg)
        return msg

    # ── Shared helpers ─────────────────────────────────────

    def _current_round(self) -> int:
        chat_msgs = sum(
            1 for m in self.history if m.msg_type in (MessageType.chat, MessageType.mention)
        )
        return max(chat_msgs, 1)

    def _notify_display(self, msg: Message) -> None:
        for cb in self._on_message_callbacks:
            cb(msg)

    def _parse_mentions(self, content: str) -> list[str]:
        agent_names = {a.name for a in self.agents}
        return [m for m in re.findall(r"@(\w+)", content) if m in agent_names]

    def _create_final_message(self, agent: AgentConfig, response, round_idx: int) -> Message:
        content = response.content.strip()
        # 部分模型会将 [name] 格式的 prompt 解析为对话格式，回复时以 ": " 开头
        if content.startswith(": "):
            content = content[2:].strip()
        mentions = self._parse_mentions(content)
        return Message(
            sender=agent.name,
            content=content,
            msg_type=MessageType.mention if mentions else MessageType.chat,
            mentions=mentions,
            round_idx=round_idx,
            reasoning_content=response.reasoning_content,
            metadata={
                "tokens": response.total_tokens,
                "model": response.model,
                "finish_reason": response.finish_reason,
            },
        )

    def _create_tool_messages(self, agent: AgentConfig, response, round_idx: int) -> list[Message]:
        messages = []
        assistant_msg = Message(
            sender=agent.name,
            content=response.content or "",
            msg_type=MessageType.tool_call,
            round_idx=round_idx,
            tool_calls=response.tool_calls,
            reasoning_content=response.reasoning_content,
            metadata={"tokens": response.total_tokens, "model": response.model, "_emitted": True},
        )
        messages.append(assistant_msg)
        for tc in response.tool_calls:
            func_name = tc["function"]["name"]
            func_args = tc["function"]["arguments"]
            tool_result = execute_tool_call(func_name, func_args, owner=agent.name)
            tool_msg = Message(
                sender="tool",
                content=tool_result.content[:MAX_TOOL_RESULT_LENGTH],
                msg_type=MessageType.tool_result,
                round_idx=round_idx,
                tool_call_id=tc["id"],
                metadata={
                    "tool_name": func_name,
                    "tool_success": tool_result.success,
                    "_emitted": True,
                },
            )
            messages.append(tool_msg)
        return messages

    # ── Unified response generation ────────────────────────

    def _generate_agent_response(
        self,
        agent: AgentConfig,
        *,
        emit_tool_to_history: bool = False,
        emit_final: bool = False,
    ) -> tuple[list[Message], int]:
        """统一的 agent 回复生成（带工具循环）

        Args:
            agent: 生成回复的 agent
            emit_tool_to_history: True 时 tool 消息立即加入 history（FreeChat 模式）
            emit_final: True 时最终消息立即 emit（FreeChat 模式）

        Returns:
            (result_messages, total_tokens)
        """
        agent_tools = self._resolve_tools(agent)
        llm = self._llm_clients.get(agent.name, self.llm)
        result_messages: list[Message] = []
        total_tokens = 0

        for tool_round in range(MAX_TOOL_ROUNDS + 1):
            ctx = self._build_response_context(agent, result_messages)
            t_start = time.monotonic()
            logger.info(
                "LLM调用 agent=%s model=%s msgs=%d tools=%d round=%d",
                agent.name,
                agent.model,
                len(ctx),
                len(agent_tools),
                tool_round,
            )
            response = llm.chat(
                messages=ctx,
                model=agent.model,
                temperature=agent.temperature,
                tools=agent_tools or None,
                on_chunk=self._emit_chunk if self._stream else None,
                on_reasoning_chunk=self._emit_reasoning if self._stream else None,
            )
            elapsed = time.monotonic() - t_start
            total_tokens += response.total_tokens
            logger.info(
                "LLM响应 agent=%s tokens=%d finish=%s elapsed=%.2fs",
                agent.name,
                response.total_tokens,
                response.finish_reason,
                elapsed,
            )

            if response.has_tool_calls:
                msgs = self._create_tool_messages(agent, response, self._current_round())
                result_messages.extend(msgs)
                if emit_tool_to_history:
                    for msg in msgs:
                        self.history.append(msg)
                for msg in msgs:
                    self._notify_display(msg)
                    if msg.msg_type == MessageType.tool_result:
                        tool_name = msg.metadata.get("tool_name", "?")
                        tool_ok = msg.metadata.get("tool_success", False)
                        logger.info(
                            "工具执行 agent=%s tool=%s success=%s",
                            agent.name,
                            tool_name,
                            tool_ok,
                        )
                self._emit_tool_batch()
                continue

            final_msg = self._create_final_message(agent, response, self._current_round())
            if emit_final:
                self._emit_message(final_msg)
            result_messages.append(final_msg)
            break
        else:
            logger.warning(
                "工具循环超限 agent=%s max_rounds=%d",
                agent.name,
                MAX_TOOL_ROUNDS,
            )
            self._force_text_response_fallback(agent, result_messages, emit_final)

        return result_messages, total_tokens

    @abstractmethod
    def _build_response_context(
        self, agent: AgentConfig, result_messages: list[Message]
    ) -> list[dict[str, Any]]:
        """构建 LLM 请求上下文。子类实现。"""

    @abstractmethod
    def _force_text_response_fallback(
        self, agent: AgentConfig, result_messages: list[Message], emit_final: bool
    ) -> None:
        """工具循环超限时强制生成文本回复。子类实现。"""

    def _emit_message(self, msg: Message) -> None:
        """发射消息到所有回调，同时加入 history。

        默认实现仅加入 history 并触发回调。子类可覆盖（如 FreeChatSession）。
        """
        self.history.append(msg)
        if not msg.metadata.get("_emitted"):
            for cb in self._on_message_callbacks:
                cb(msg)

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
        from agc.tools.memory import register_memory_tools
        from agc.tools.workspace import register_workspace_tools

        for name in register_workspace_tools(self._workspace_mgr):
            if name not in self._enabled_tools:
                self._enabled_tools.append(name)
        for name in register_memory_tools(self._workspace_mgr):
            if name not in self._enabled_tools:
                self._enabled_tools.append(name)

    def _resolve_tools(self, agent: AgentConfig) -> list[dict[str, Any]]:
        return get_schemas_for_tools(agent.tools) if agent.tools is not None else self._tool_schemas

    def _build_workspace_prompts(self) -> dict[str, str]:
        prompts: dict[str, str] = {}
        for agent in self.agents:
            parts: list[str] = []
            if self._workspace_mgr:
                ws_path = self._workspace_mgr.get(agent.name).path
                parts.extend(
                    [
                        "\n## 你的工作空间",
                        f"你有独立的工作空间目录: {ws_path}",
                        "可用工具: write_file / read_file / list_files / run_code",
                        "\n## 你的记忆",
                        "可用工具: save_memory / recall_memory / list_memories / delete_memory",
                    ]
                )
            web_tools = [t for t in self._enabled_tools if t.startswith("web_")]
            if web_tools:
                parts.extend(
                    [
                        "\n## 网络工具",
                        "可用: web_search, web_fetch",
                        "建议先用 web_search 找到链接，再用 web_fetch 阅读页面详情。",
                    ]
                )
            if parts:
                prompts[agent.name] = "\n".join(parts)
        return prompts

    @abstractmethod
    def run(self): ...


class SessionStore:
    """JSONL文件存储的会话持久化"""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(str(DEFAULT_SESSIONS_DIR))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> str:
        base = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        session_id = base
        path = self._session_path(session_id)
        counter = 1
        while path.exists():
            session_id = f"{base}_{counter}"
            path = self._session_path(session_id)
            counter += 1
        path.touch()
        logger.info(f"创建会话: {session_id}")
        return session_id

    def append(self, session_id: str, messages: list[Message]) -> None:
        path = self._resolve_path(session_id)
        with open(path, "a", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg.to_json(), ensure_ascii=False) + "\n")

    def load_session(self, session_id: str) -> list[Message]:
        path = self._resolve_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"会话不存在: {session_id}")
        messages = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                messages.append(Message.from_json(data))
        return messages

    def list_sessions(self) -> list[str]:
        sessions = []
        for f in sorted(self.base_dir.glob("*.jsonl")):
            sessions.append(f.stem)
        return sessions

    def rename_session(self, old_id: str, new_name: str) -> str:
        old_path = self._resolve_path(old_id)
        new_id = new_name
        new_path = self._session_path(new_id)
        old_path.rename(new_path)
        logger.info(f"会话重命名: {old_id} -> {new_id}")
        return new_id

    def delete_session(self, session_id: str) -> None:
        path = self._resolve_path(session_id)
        if path.exists():
            path.unlink()
            logger.info(f"删除会话: {session_id}")

    def _session_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.jsonl"

    def _resolve_path(self, session_id: str) -> Path:
        exact = self._session_path(session_id)
        if exact.exists():
            return exact
        matches = list(self.base_dir.glob(f"{session_id}*.jsonl"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"会话前缀 '{session_id}' 匹配到多个文件: {[m.stem for m in matches]}")
        return exact
