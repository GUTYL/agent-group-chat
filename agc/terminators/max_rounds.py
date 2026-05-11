"""最大轮次终止检测"""

from __future__ import annotations

from agc.core.agent import AgentConfig
from agc.core.message import Message

from .base import TerminatorBase


class MaxRoundsTerminator(TerminatorBase):
    """硬性轮次上限兜底"""

    def __init__(self, max_rounds: int = 20):
        self.max_rounds = max_rounds

    def should_stop(
        self,
        history: list[Message],
        agents: list[AgentConfig],
    ) -> tuple[bool, str]:
        n_agents = len(agents)
        total_turns = len(history)
        rounds = total_turns / n_agents if n_agents else total_turns

        if rounds >= self.max_rounds:
            return True, f"达到最大轮数限制 {self.max_rounds}"

        return False, ""
