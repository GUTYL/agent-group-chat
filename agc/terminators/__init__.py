"""终止检测器 — 判断群聊是否该结束"""

from .base import TerminatorBase
from .composite import CompositeTerminator
from .consensus import ConsensusTerminator
from .max_rounds import MaxRoundsTerminator

__all__ = ["TerminatorBase", "ConsensusTerminator", "MaxRoundsTerminator", "CompositeTerminator"]
