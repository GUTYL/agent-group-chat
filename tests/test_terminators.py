"""单元测试 — 终止检测器"""

from agc.core.agent import AgentConfig
from agc.core.message import Message, MessageType
from agc.terminators.max_rounds import MaxRoundsTerminator
from agc.terminators.consensus import ConsensusTerminator
from agc.terminators.composite import CompositeTerminator


def _make_agents():
    return [
        AgentConfig(name="alice", role="研究员", goal="调研", backstory=""),
        AgentConfig(name="bob", role="架构师", goal="设计", backstory=""),
    ]


def test_max_rounds_terminator():
    agents = _make_agents()
    terminator = MaxRoundsTerminator(max_rounds=3)

    # 2条消息 = 1轮，不到3轮
    messages = [
        Message(sender="alice", content="hi", round_idx=0),
        Message(sender="bob", content="hello", round_idx=1),
    ]
    stop, reason = terminator.should_stop(messages, agents)
    assert not stop

    # 6条消息 = 3轮，到上限
    for i in range(4):
        messages.append(Message(sender="alice" if i % 2 == 0 else "bob", content="msg", round_idx=2 + i))
    stop, reason = terminator.should_stop(messages, agents)
    assert stop
    assert "3" in reason


def test_consensus_terminator():
    agents = _make_agents()
    terminator = ConsensusTerminator(window=3, threshold=2.0)

    # 太少消息，不该停止
    messages = [
        Message(sender="alice", content="我同意这个方案", round_idx=0),
    ]
    stop, _ = terminator.should_stop(messages, agents)
    assert not stop

    # 足够多的共识信号
    messages = [
        Message(sender="alice", content="我觉得可以，同意这个方案", round_idx=0),
        Message(sender="bob", content="赞同，总结一下我们的共识", round_idx=1),
        Message(sender="alice", content="同意，结论是这样做", round_idx=2),
        Message(sender="bob", content="赞同", round_idx=3),
        Message(sender="alice", content="一致的看法", round_idx=4),
        Message(sender="bob", content="综上所述", round_idx=5),
    ]
    stop, reason = terminator.should_stop(messages, agents)
    assert stop


def test_composite_terminator():
    agents = _make_agents()
    terminator = CompositeTerminator([
        ConsensusTerminator(window=3),
        MaxRoundsTerminator(max_rounds=5),
    ])

    # 还没到
    messages = [Message(sender="alice", content="hi", round_idx=i) for i in range(4)]
    stop, _ = terminator.should_stop(messages, agents)
    assert not stop