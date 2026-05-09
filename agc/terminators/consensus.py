"""共识终止检测 — 检测群聊是否达成共识"""

from __future__ import annotations

from agc.core.agent import AgentConfig
from agc.core.message import Message

from .base import TerminatorBase

# 共识信号词（中文 + 英文）
CONSENSUS_SIGNALS = [
    "共识", "同意", "赞同", "一致", "认可", "没有异议",
    "总结一下", "综上所述", "结论是", "最终方案",
    "agree", "consensus", "settled", "conclude",
]

# 明确反对信号（有这些说明还没共识）
DISSENT_SIGNALS = [
    "反对", "不同意", "质疑", "但是", "不过", "然而",
    "disagree", "but", "however", "oppose",
]


class ConsensusTerminator(TerminatorBase):
    """检测群聊是否达成共识

    判定逻辑：
    - 最近N轮中，共识信号数量 > 反对信号数量 × 阈值
    - 或者所有参与者都表示了同意/总结
    """

    def __init__(self, window: int = 3, threshold: float = 2.0):
        """
        Args:
            window: 检测最近几轮（每轮=所有agent各发言一次）
            threshold: 共识信号/反对信号 的比例阈值
        """
        self.window = window
        self.threshold = threshold

    def should_stop(
        self,
        history: list[Message],
        agents: list[AgentConfig],
    ) -> tuple[bool, str]:
        # 至少要有一轮完整讨论
        n_agents = len(agents)
        min_messages = n_agents * self.window
        if len(history) < min_messages:
            return False, ""

        recent = history[-min_messages:]

        # 统计信号
        consensus_count = 0
        dissent_count = 0
        for msg in recent:
            content_lower = msg.content.lower()
            if any(s in content_lower for s in CONSENSUS_SIGNALS):
                consensus_count += 1
            if any(s in content_lower for s in DISSENT_SIGNALS):
                dissent_count += 1

        # 防止除零
        if consensus_count == 0:
            return False, ""

        if dissent_count == 0:
            # 没有反对 + 有共识信号 → 达成共识
            if consensus_count >= n_agents:
                return True, f"所有参与者都表达了共识（{consensus_count}个共识信号，0个反对）"

        # 共识/反对 比例判断
        ratio = consensus_count / max(dissent_count, 1)
        if ratio >= self.threshold and consensus_count >= n_agents:
            return True, f"共识信号({consensus_count})远多于反对信号({dissent_count})，比例={ratio:.1f}"

        return False, ""