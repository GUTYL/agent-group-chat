"""终止检测器基类"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agc.core.agent import AgentConfig
from agc.core.message import Message


class TerminatorBase(ABC):
    """判断群聊是否应该终止"""

    @abstractmethod
    def should_stop(
        self,
        history: list[Message],
        agents: list[AgentConfig],
    ) -> tuple[bool, str]:
        """返回 (是否停止, 停止原因)"""
        ...