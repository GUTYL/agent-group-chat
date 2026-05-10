"""TUI Display — 桥接 ChatRoom 回调与 Textual 界面"""

from __future__ import annotations

import json
import time
from typing import Any

from agc.core.message import Message, MessageType
from agc.core.human_in_loop import HumanMode
from agc.ui.base import DisplayBase
from agc.ui.tui_app import ChatTuiApp


class TuiDisplay(DisplayBase):
    """Textual 交互式终端显示

    ChatRoom 运行在后台线程，通过 call_from_thread 安全更新 UI。
    """

    def __init__(self, app: ChatTuiApp) -> None:
        self.app = app
        self._agent_meta: dict[str, dict[str, str]] = {}
        self._tool_start: float = 0
        self._stream_name = ""

    def on_message(self, message: Message) -> None:
        handlers = {
            MessageType.system: self._on_system,
            MessageType.tool_call: self._on_tool_call,
            MessageType.tool_result: self._on_tool_result,
            MessageType.human_input: self._on_human,
        }
        handler = handlers.get(message.msg_type, self._on_chat)
        handler(message)

    def on_chunk(self, text: str) -> None:
        self.app.add_chunk(text)

    def begin_stream(self, agent_name: str, agent_role: str, agent_model: str = "") -> None:
        self._stream_name = agent_name
        self._agent_meta[agent_name] = {"role": agent_role, "model": agent_model}
        self.app.begin_agent(agent_name, agent_role, agent_model)

    def print_header(self, topic: str, agents: list[Any], human_loop: Any = None) -> None:
        self.app.add_system(f"讨论话题: {topic}")
        for a in agents:
            model = getattr(a, "model", "")
            self._agent_meta[a.name] = {"role": a.role, "model": model}
            model_str = f" ({model})" if model else ""
            self.app.add_system(f"  @{a.name} · {a.role}{model_str}")
        if human_loop and human_loop.mode != HumanMode.off:
            self.app.add_system(f"  @{human_loop.name} (人类) — 参与者")

    def print_result(self, result: Any) -> None:
        if result.summary:
            self.app.add_system(f"群聊总结: {result.summary}")
        self.app.add_system(
            f"轮数: {result.rounds} | 消息数: {len(result.messages)} | 总token: {result.total_tokens:,}"
        )
        self.app.stop()

    # ── Message handlers ──────────────────────────────────

    def _on_chat(self, msg: Message) -> None:
        if msg.sender == self._stream_name:
            self.app.finish_agent(msg.content, msg.mentions)
            self._stream_name = ""
        else:
            meta = self._agent_meta.get(msg.sender, {})
            self.app.begin_agent(msg.sender, meta.get("role", ""), meta.get("model", ""))
            self.app.finish_agent(msg.content, msg.mentions)

    def _on_system(self, msg: Message) -> None:
        self.app.add_system(msg.content)

    def _on_tool_call(self, msg: Message) -> None:
        self._tool_start = time.time()
        for tc in msg.tool_calls:
            func_name = tc.get("function", {}).get("name", "?")
            func_args = tc.get("function", {}).get("arguments", "{}")
            self.app.add_tool_call(func_name, func_args)

    def _on_tool_result(self, msg: Message) -> None:
        dur = time.time() - self._tool_start if self._tool_start else 0
        tool_name = msg.metadata.get("tool_name", "tool")
        self.app.add_tool_result(tool_name, msg.content, dur)

    def _on_human(self, msg: Message) -> None:
        self.app.add_human(msg.sender, msg.content)
