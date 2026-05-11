"""Round-Robin 调度器 — 轮流发言"""

from __future__ import annotations

from agc.core.agent import AgentConfig
from agc.core.message import Message

from .base import SchedulerBase


class RoundRobinScheduler(SchedulerBase):
    """简单的轮流发言：A → B → C → A → ..."""

    def next_speaker(
        self,
        history: list[Message],
        round_idx: int,
    ) -> AgentConfig:
        idx = round_idx % len(self.agents)
        return self.agents[idx]
