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


def _make_two_agents():
    return [
        AgentConfig(name="researcher", role="研究员", goal="研究", backstory="研究员", model="gpt-4o"),
        AgentConfig(name="architect", role="架构师", goal="设计", backstory="架构师", model="gpt-4o"),
    ]


def test_plan_responses_with_mention():
    agents = _make_two_agents()
    scheduler = HybridScheduler(agents)
    msg = Message(sender="human", content="@architect 请设计一下", msg_type=MessageType.human_input, mentions=["architect"])
    history = [msg]
    result = scheduler.plan_responses(history)
    assert len(result) == 1
    assert result[0].name == "architect"


def test_plan_responses_with_multiple_mentions():
    agents = _make_two_agents()
    scheduler = HybridScheduler(agents)
    msg = Message(sender="human", content="@researcher @architect 大家看看", msg_type=MessageType.human_input, mentions=["researcher", "architect"])
    history = [msg]
    result = scheduler.plan_responses(history)
    assert len(result) == 2
    names = [a.name for a in result]
    assert "researcher" in names
    assert "architect" in names


def test_plan_responses_with_all_keyword():
    agents = _make_two_agents()
    scheduler = HybridScheduler(agents)
    msg = Message(sender="human", content="大家有什么想法", msg_type=MessageType.human_input)
    history = [msg]
    result = scheduler.plan_responses(history)
    assert len(result) == len(agents)


def test_plan_responses_empty_history():
    agents = _make_two_agents()
    scheduler = HybridScheduler(agents)
    result = scheduler.plan_responses([])
    assert result == []


def test_plan_responses_no_signal_falls_back():
    agents = _make_two_agents()
    scheduler = HybridScheduler(agents, use_llm_router=False)
    msg = Message(sender="human", content="随便聊聊", msg_type=MessageType.human_input)
    history = [msg]
    result = scheduler.plan_responses(history)
    # 无mention/关键词/LLM路由 → 默认首位agent回应
    assert len(result) == 1
    assert result[0].name == agents[0].name