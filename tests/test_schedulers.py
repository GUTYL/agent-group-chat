"""单元测试 — 调度器"""

from agc.core.agent import AgentConfig
from agc.core.message import Message, MessageType
from agc.schedulers.round_robin import RoundRobinScheduler
from agc.schedulers.hybrid import HybridScheduler


def _make_agents():
    return [
        AgentConfig(name="researcher", role="研究员", goal="调研", backstory=""),
        AgentConfig(name="architect", role="架构师", goal="设计", backstory=""),
        AgentConfig(name="reviewer", role="审查", goal="质疑", backstory=""),
    ]


def test_round_robin():
    agents = _make_agents()
    scheduler = RoundRobinScheduler(agents)

    # round 0 -> researcher, round 1 -> architect, round 2 -> reviewer
    assert scheduler.next_speaker([], 0).name == "researcher"
    assert scheduler.next_speaker([], 1).name == "architect"
    assert scheduler.next_speaker([], 2).name == "reviewer"
    assert scheduler.next_speaker([], 3).name == "researcher"  # wrap around


def test_hybrid_mention_priority():
    agents = _make_agents()
    scheduler = HybridScheduler(agents)

    # 消息 @architect，下一轮应该让 architect 说话
    msg = Message(
        sender="researcher",
        content="这个架构你怎么看？@architect",
        mentions=["architect"],
        round_idx=0,
    )
    next_speaker = scheduler.next_speaker([msg], 1)
    assert next_speaker.name == "architect"


def test_hybrid_keyword_route():
    agents = _make_agents()
    scheduler = HybridScheduler(agents)

    # 消息含"搜索"关键词，应该路由到 researcher
    msg = Message(
        sender="architect",
        content="我们需要搜索一下相关资料",
        round_idx=0,
    )
    next_speaker = scheduler.next_speaker([msg], 1)
    assert next_speaker.name == "researcher"


def test_hybrid_fallback_to_round_robin():
    agents = _make_agents()
    scheduler = HybridScheduler(agents, use_llm_router=False)

    # 无@mention，无关键词命中 → RoundRobin 兜底
    msg = Message(sender="architect", content="今天天气不错", round_idx=0)
    next_speaker = scheduler.next_speaker([msg], 2)
    assert next_speaker.name == "reviewer"  # round 2 % 3 = 2