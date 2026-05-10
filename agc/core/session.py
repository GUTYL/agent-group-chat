"""ChatSession ABC + SessionStore（JSONL 持久化）"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from agc.core.agent import AgentConfig
from agc.core.context import ContextManager
from agc.core.message import Message, MessageType
from agc.core.workspace import WorkspaceManager
from agc.llm.base import LLMBase
from agc.llm.openai_client import OpenAIClient
from agc.schedulers.base import SchedulerBase
from agc.schedulers.hybrid import HybridScheduler
from agc.schedulers.round_robin import RoundRobinScheduler
from agc.tools.base import get_schemas_for_tools

logger = logging.getLogger(__name__)


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
        self._scheduler = self._init_scheduler(scheduler, agents)
        self._context = ContextManager(self.llm, max_tokens=context_window)

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
            round_idx=len(self.history) // max(len(self.agents), 1),
        )
        self.history.append(msg)
        for cb in self._on_message_callbacks:
            cb(msg)
        return msg

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

    def _resolve_tools(self, agent: AgentConfig) -> list[dict[str, Any]]:
        return get_schemas_for_tools(agent.tools) if agent.tools else self._tool_schemas

    def _build_workspace_prompts(self) -> dict[str, str]:
        prompts: dict[str, str] = {}
        for agent in self.agents:
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

    @abstractmethod
    def run(self):
        ...


class SessionStore:
    """JSONL文件存储的会话持久化"""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path("data/sessions")
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
        with open(path, "r", encoding="utf-8") as f:
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