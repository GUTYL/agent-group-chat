"""单元测试 — TopicSession (ChatRoom)"""

from unittest.mock import MagicMock, patch

import pytest

from agc.core.agent import AgentConfig
from agc.core.chatroom import ChatResult, ChatRoom, TopicSession
from agc.core.message import Message, MessageType


def _make_agents():
    return [
        AgentConfig(name="researcher", role="研究员", goal="调研", backstory="", model="gpt-4o"),
        AgentConfig(name="architect", role="架构师", goal="设计", backstory="", model="gpt-4o"),
    ]


def _make_mock_response(content="回复内容", has_tool_calls=False, tool_calls=None):
    return MagicMock(
        content=content,
        reasoning_content="",
        total_tokens=100,
        model="gpt-4o",
        finish_reason="stop",
        has_tool_calls=has_tool_calls,
        tool_calls=tool_calls,
    )


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-dummy-key")


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.chat.return_value = _make_mock_response()
    llm.count_tokens.return_value = 50
    return llm


@pytest.fixture
def patched_room(mock_llm):
    """创建使用 mock LLM 的 ChatRoom"""
    with patch("agc.core.session.OpenAIClient") as mock_client_cls:
        mock_client_cls.return_value = mock_llm
        agents = _make_agents()
        room = ChatRoom(name="test", agents=agents, llm=mock_llm, max_rounds=5, workspace_root=None)
        yield room


def test_topic_session_init():
    agents = _make_agents()
    room = ChatRoom(name="test", agents=agents, max_rounds=5, workspace_root=None)
    assert room.config.name == "test"
    assert room.config.max_rounds == 5
    assert len(room.agents) == 2


def test_topic_session_chat_single_round(patched_room):
    result = patched_room.chat("测试话题")
    assert isinstance(result, ChatResult)
    assert result.topic == "测试话题"
    assert len(result.messages) > 0


def test_topic_session_chat_respects_max_rounds(mock_llm):
    call_count = 0

    def mock_chat(**_kwargs):
        nonlocal call_count
        call_count += 1
        return _make_mock_response(content=f"回复 {call_count}")

    mock_llm.chat = mock_chat

    with patch("agc.core.session.OpenAIClient") as mock_client_cls:
        mock_client_cls.return_value = mock_llm
        agents = _make_agents()
        room = ChatRoom(name="test", agents=agents, llm=mock_llm, max_rounds=2, workspace_root=None)
        result = room.chat("话题")
    assert result.rounds <= 2


def test_speaker_exhausted_allows_unlimited(mock_llm):
    agents = _make_agents()
    agents[0].max_turns = 1
    agents[1].max_turns = 0

    call_count = 0

    def mock_chat(**_kwargs):
        nonlocal call_count
        call_count += 1
        return _make_mock_response(content=f"回复 {call_count}")

    mock_llm.chat = mock_chat

    with patch("agc.core.session.OpenAIClient") as mock_client_cls:
        mock_client_cls.return_value = mock_llm
        room = ChatRoom(name="test", agents=agents, llm=mock_llm, max_rounds=5, workspace_root=None)
        room.chat("话题")
    assert call_count > 1


def test_turn_counts_include_mention_messages():
    agents = _make_agents()
    msg = Message(
        sender="researcher",
        content="看看这个 @architect",
        msg_type=MessageType.mention,
        mentions=["architect"],
        round_idx=0,
    )
    room = ChatRoom(name="test", agents=agents, max_rounds=5, workspace_root=None)
    room._turn_counts["researcher"] = 0
    room._process_messages([msg], "researcher", 0)
    assert room._turn_counts["researcher"] == 1


def test_all_exhausted_returns_true():
    agents = _make_agents()
    agents[0].max_turns = 1
    agents[1].max_turns = 1
    room = ChatRoom(name="test", agents=agents, max_rounds=5, workspace_root=None)
    room._turn_counts["researcher"] = 1
    room._turn_counts["architect"] = 1
    assert room._all_exhausted() is True


def test_all_exhausted_returns_false_with_unlimited():
    agents = _make_agents()
    agents[0].max_turns = 1
    agents[1].max_turns = 0
    room = ChatRoom(name="test", agents=agents, max_rounds=5, workspace_root=None)
    room._turn_counts["researcher"] = 1
    room._turn_counts["architect"] = 0
    assert room._all_exhausted() is False


def test_generate_summary_on_error(mock_llm):
    call_count = 0

    def mock_chat(**_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_mock_response(content="第一轮回复")
        raise Exception("API error")

    mock_llm.chat = mock_chat

    with patch("agc.core.session.OpenAIClient") as mock_client_cls:
        mock_client_cls.return_value = mock_llm
        agents = _make_agents()
        room = ChatRoom(name="test", agents=agents, llm=mock_llm, max_rounds=1, workspace_root=None, use_llm_route=False)
        room.chat("话题")
        summary = room._generate_summary("话题")
        assert "失败" in summary


def test_chatroom_alias():
    assert ChatRoom is TopicSession
