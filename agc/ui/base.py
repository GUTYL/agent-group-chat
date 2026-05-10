"""Display 抽象基类 — 所有 UI 实现的统一接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agc.core.message import Message


class DisplayBase(ABC):
    """所有 UI 的统一接口

    ChatRoom 通过三个核心回调驱动 Display:
    - begin_stream: 某 agent 开始流式输出
    - on_chunk: 流式文本片段
    - on_message: 完整消息（chat/tool_call/tool_result/system/human_input）
    """

    @abstractmethod
    def on_message(self, message: Message) -> None:
        """接收一条完整消息"""

    @abstractmethod
    def on_chunk(self, text: str) -> None:
        """接收流式文本片段"""

    @abstractmethod
    def begin_stream(self, agent_name: str, agent_role: str, agent_model: str = "") -> None:
        """某 agent 开始流式输出"""

    def print_header(self, topic: str, agents: list[Any], human_loop: Any = None) -> None:
        """打印群聊开始标题（可选实现）"""

    def print_result(self, result: Any) -> None:
        """打印群聊结束结果（可选实现）"""

    def print_freechat_header(self, user_name: str, agents: list[Any]) -> None:
        """打印FreeChat开始标题（可选实现）"""

    def print_freechat_input(self, sender: str, content: str) -> None:
        """打印用户输入（IM风格，简洁格式）"""

    def print_topic_change(self, topic: str) -> None:
        """打印话题切换提示"""
