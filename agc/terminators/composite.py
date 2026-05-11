"""组合终止检测器 — 多个条件取并集"""

from __future__ import annotations

from agc.core.agent import AgentConfig
from agc.core.message import Message

from .base import TerminatorBase


class CompositeTerminator(TerminatorBase):
    """组合多个终止检测器，任一触发即停止"""

    def __init__(self, terminators: list[TerminatorBase]):
        self.terminators = terminators

    def should_stop(
        self,
        history: list[Message],
        agents: list[AgentConfig],
    ) -> tuple[bool, str]:
        for terminator in self.terminators:
            should_stop, reason = terminator.should_stop(history, agents)
            if should_stop:
                return True, f"[{terminator.__class__.__name__}] {reason}"
        return False, ""
