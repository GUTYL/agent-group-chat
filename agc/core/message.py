"""消息模型 — 群聊中的每一条发言"""

from __future__ import annotations

import time
import uuid
from enum import Enum

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    chat = "chat"                # 正常发言
    mention = "mention"           # @某人
    broadcast = "broadcast"      # 广播给所有人
    system = "system"            # 系统消息（轮次提示、终止通知等）
    summary = "summary"          # 总结收敛
    tool_call = "tool_call"      # LLM 请求调用工具
    tool_result = "tool_result"  # 工具执行结果
    human_input = "human_input"  # 人类参与者输入


class Message(BaseModel):
    """群聊中的一条消息"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    sender: str                  # 发送者 agent name
    content: str                 # 发言内容
    msg_type: MessageType = MessageType.chat
    mentions: list[str] = []     # @了谁（agent names）
    round_idx: int = 0           # 第几轮
    timestamp: float = Field(default_factory=time.time)
    metadata: dict = {}          # 扩展字段（token数等）
    tool_calls: list[dict] = []  # OpenAI tool_calls 格式
    tool_call_id: str = ""       # 工具调用ID（tool_result消息用）
    reasoning_content: str = ""  # DeepSeek等thinking模型的推理内容（需回传）

    @property
    def is_system(self) -> bool:
        return self.msg_type == MessageType.system

    @property
    def has_mentions(self) -> bool:
        return len(self.mentions) > 0

    def format_display(self) -> str:
        """格式化显示，带@标记"""
        if self.msg_type == MessageType.tool_result:
            return f"[工具结果]: {self.content[:300]}"
        if self.msg_type == MessageType.tool_call:
            calls = ", ".join(tc.get("function", {}).get("name", "?") for tc in self.tool_calls)
            return f"[{self.sender} 调用工具]: {calls}"
        if self.msg_type == MessageType.human_input:
            return f"👤 [{self.sender}]: {self.content}"

        mentions_str = " " + " ".join(f"@{m}" for m in self.mentions) if self.mentions else ""
        tag = f"[{self.msg_type.value}] " if self.msg_type != MessageType.chat else ""
        return f"{tag}{self.sender}{mentions_str}: {self.content}"

    def to_openai_msg(self) -> dict:
        """转换为 OpenAI API 消息格式"""
        role = "system" if self.is_system else "assistant"
        prefix = f"[{self.sender}]" if not self.is_system else "[System]"

        if self.msg_type == MessageType.tool_call and self.tool_calls:
            msg = {
                "role": "assistant",
                "content": self.content or None,
                "tool_calls": self.tool_calls,
            }
            if self.reasoning_content:
                msg["reasoning_content"] = self.reasoning_content
            return msg

        if self.msg_type == MessageType.tool_result:
            return {
                "role": "tool",
                "tool_call_id": self.tool_call_id,
                "content": self.content,
            }

        if self.msg_type == MessageType.human_input:
            return {
                "role": "user",
                "content": f"[{self.sender}]: {self.content}",
            }

        msg = {
            "role": role if self.is_system else "user",
            "content": f"{prefix}: {self.content}",
        }
        if not self.is_system and self.reasoning_content:
            msg["role"] = "assistant"
            msg["reasoning_content"] = self.reasoning_content
        return msg