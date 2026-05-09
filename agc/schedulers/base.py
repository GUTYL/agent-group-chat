"""调度器基类"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agc.core.agent import AgentConfig
from agc.core.message import Message


class SchedulerBase(ABC):
    """决定下一个发言的Agent"""

    def __init__(self, agents: list[AgentConfig]):
        self.agents = agents
        self.agent_map = {a.name: a for a in agents}

    @abstractmethod
    def next_speaker(
        self,
        history: list[Message],
        round_idx: int,
    ) -> AgentConfig:
        """选择下一个发言的Agent"""
        ...

    def get_agent(self, name: str) -> AgentConfig | None:
        return self.agent_map.get(name)