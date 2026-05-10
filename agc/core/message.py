"""消息模型 — 群聊中的每一条发言"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    chat = "chat"
    mention = "mention"
    broadcast = "broadcast"
    system = "system"
    summary = "summary"
    tool_call = "tool_call"
    tool_result = "tool_result"
    human_input = "human_input"


class Message(BaseModel):
    """群聊中的一条消息"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    sender: str
    content: str
    msg_type: MessageType = MessageType.chat
    mentions: list[str] = []
    round_idx: int = 0
    timestamp: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = {}
    tool_calls: list[dict[str, Any]] = []
    tool_call_id: str = ""
    reasoning_content: str = ""

    @property
    def is_system(self) -> bool:
        return self.msg_type == MessageType.system

    @property
    def has_mentions(self) -> bool:
        return len(self.mentions) > 0

    def format_display(self) -> str:
        if self.msg_type == MessageType.tool_result:
            return f"[工具结果]: {self.content[:300]}"
        if self.msg_type == MessageType.tool_call:
            calls = ", ".join(
                tc.get("function", {}).get("name", "?") for tc in self.tool_calls
            )
            return f"[{self.sender} 调用工具]: {calls}"
        if self.msg_type == MessageType.human_input:
            return f"👤 [{self.sender}]: {self.content}"

        mentions_str = " " + " ".join(f"@{m}" for m in self.mentions) if self.mentions else ""
        tag = f"[{self.msg_type.value}] " if self.msg_type != MessageType.chat else ""
        return f"{tag}{self.sender}{mentions_str}: {self.content}"

    def to_openai_msg(self) -> dict[str, Any]:
        if self.msg_type == MessageType.tool_call and self.tool_calls:
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": self.content or None,
                "tool_calls": self.tool_calls,
            }
            if self.reasoning_content:
                msg["reasoning_content"] = self.reasoning_content
            return msg

        if self.msg_type == MessageType.tool_result:
            return {"role": "tool", "tool_call_id": self.tool_call_id, "content": self.content}

        if self.msg_type == MessageType.human_input:
            return {"role": "user", "content": f"[{self.sender}]: {self.content}"}

        prefix = f"[{'System' if self.is_system else self.sender}]"
        msg = {
            "role": "system" if self.is_system else "user",
            "content": f"{prefix}: {self.content}",
        }
        # 有思考内容的非系统消息需要回传给 DeepSeek 等 thinking 模型
        if not self.is_system and self.reasoning_content:
            msg["role"] = "assistant"
            msg["reasoning_content"] = self.reasoning_content
        return msg
