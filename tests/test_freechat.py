import pytest

from agc.core.agent import AgentConfig
from agc.core.freechat import FreeChatSession
from agc.core.message import Message, MessageType


@pytest.fixture(autouse=True)
def _set_dummy_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-dummy-key")


def _make_agents():
    return [
        AgentConfig(
            name="researcher", role="研究员", goal="研究", backstory="研究员背景", model="test"
        ),
        AgentConfig(
            name="architect", role="架构师", goal="设计", backstory="架构师背景", model="test"
        ),
    ]


def test_freechat_init():
    session = FreeChatSession(agents=_make_agents(), user_name="alice")
    assert session.user_name == "alice"
    assert session.current_topic is None


def test_handle_command_quit():
    session = FreeChatSession(agents=_make_agents())
    result = session._handle_command("/quit")
    assert result == "quit"


def test_handle_command_exit():
    session = FreeChatSession(agents=_make_agents())
    result = session._handle_command("/exit")
    assert result == "quit"


def test_handle_command_topic():
    session = FreeChatSession(agents=_make_agents())
    session._handle_command("/topic AI趋势")
    assert session.current_topic == "AI趋势"


def test_handle_command_topic_no_args():
    session = FreeChatSession(agents=_make_agents())
    session._handle_command("/topic")


def test_handle_command_agents(capsys):
    session = FreeChatSession(agents=_make_agents())
    session._handle_command("/agents")
    captured = capsys.readouterr()
    assert "researcher" in captured.out or "研究员" in captured.out


def test_create_user_message():
    session = FreeChatSession(agents=_make_agents(), user_name="alice")
    msg = session._create_user_message("大家好 @researcher")
    assert msg.sender == "alice"
    assert msg.content == "大家好 @researcher"
    assert msg.msg_type == MessageType.human_input
    assert "researcher" in msg.mentions


def test_create_user_message_no_mention():
    session = FreeChatSession(agents=_make_agents())
    msg = session._create_user_message("随便聊聊")
    assert msg.mentions == []


def test_parse_mentions():
    session = FreeChatSession(agents=_make_agents())
    mentions = session._parse_mentions("@researcher @architect 你们好")
    assert "researcher" in mentions
    assert "architect" in mentions
    assert len(mentions) == 2


def test_handle_command_history_empty():
    session = FreeChatSession(agents=_make_agents())
    session._handle_command("/history")


def test_handle_command_clear():
    session = FreeChatSession(agents=_make_agents())
    session.history = [
        Message(sender="human", content="hello", msg_type=MessageType.human_input),
    ]
    session._handle_command("/clear")
    assert len(session.history) == 1
    assert session.history[0].msg_type == MessageType.system
