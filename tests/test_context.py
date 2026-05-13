"""单元测试 — ContextManager"""

from unittest.mock import MagicMock

from agc.core.agent import AgentConfig
from agc.core.context import ContextManager
from agc.core.message import Message, MessageType


def _make_agent(name="researcher"):
    return AgentConfig(name=name, role="研究员", goal="调研", backstory="")


def _make_msg(sender, content, msg_type=MessageType.chat, round_idx=0):
    return Message(sender=sender, content=content, msg_type=msg_type, round_idx=round_idx)


def _make_llm(token_count=100):
    llm = MagicMock()
    llm.count_tokens.return_value = token_count
    llm.chat.return_value = MagicMock(content="摘要内容")
    return llm


def test_build_messages_under_limit():
    llm = _make_llm(token_count=100)
    ctx = ContextManager(llm, max_tokens=8000, recent_window=6)
    history = [_make_msg("human", "hello"), _make_msg("researcher", "hi")]
    result = ctx.build_messages(_make_agent(), "topic", history, [_make_agent()])
    assert result[0]["role"] == "system"
    assert len(result) == 4


def test_build_messages_over_limit_triggers_summary():
    llm = _make_llm(token_count=10000)
    ctx = ContextManager(llm, max_tokens=8000, recent_window=3)
    history = [_make_msg("human", f"msg {i}") for i in range(10)]
    result = ctx.build_messages(_make_agent(), "topic", history, [_make_agent()])
    llm.chat.assert_called()
    assert any("摘要" in str(m.get("content", "")) for m in result)


def test_build_messages_no_summary_when_under_window():
    llm = _make_llm(token_count=100)
    ctx = ContextManager(llm, max_tokens=8000, recent_window=6)
    history = [_make_msg("human", "hello")]
    result = ctx.build_messages(_make_agent(), "topic", history, [_make_agent()])
    assert not any(
        m.get("role") == "system" and "摘要" in str(m.get("content", "")) for m in result
    )


def test_build_freechat_context_sliding_window():
    llm = _make_llm()
    ctx = ContextManager(llm, max_tokens=8000, recent_window=6)
    history = [_make_msg("human", f"msg {i}") for i in range(50)]
    result = ctx.build_freechat_context(
        agent=_make_agent(),
        history=history,
        all_agents=[_make_agent()],
        system_prompt="system",
        recent_window=10,
    )
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "system"


def test_build_freechat_context_with_topic():
    llm = _make_llm()
    ctx = ContextManager(llm)
    history = [_make_msg("human", "hello")]
    result = ctx.build_freechat_context(
        agent=_make_agent(),
        history=history,
        all_agents=[_make_agent()],
        system_prompt="system",
        current_topic="测试话题",
        recent_window=30,
    )
    assert any("测试话题" in str(m.get("content", "")) for m in result)


def test_adjust_for_tool_pairs_tool_result_at_start():
    filtered = [
        _make_msg("tool", "result", MessageType.tool_result),
        _make_msg("researcher", "response", MessageType.chat),
        _make_msg("tool", "result2", MessageType.tool_result),
    ]
    start = ContextManager._adjust_for_tool_pairs(filtered, 0)
    assert start == 0


def test_adjust_for_tool_pairs_no_adjustment_needed():
    filtered = [
        _make_msg("researcher", "response", MessageType.chat),
        _make_msg("tool", "result", MessageType.tool_result),
    ]
    start = ContextManager._adjust_for_tool_pairs(filtered, 0)
    assert start == 0


def test_adjust_for_tool_pairs_with_tool_call_before():
    filtered = [
        _make_msg("researcher", "thinking", MessageType.tool_call),
        _make_msg("tool", "result", MessageType.tool_result),
        _make_msg("researcher", "response", MessageType.chat),
    ]
    start = ContextManager._adjust_for_tool_pairs(filtered, 1)
    assert start == 0


def test_summarize_calls_llm():
    llm = _make_llm()
    ctx = ContextManager(llm)
    msgs = [_make_msg("human", "hello"), _make_msg("researcher", "hi there")]
    result = ctx._summarize(msgs)
    llm.chat.assert_called_once()
    assert result == "摘要内容"


def test_summarize_fallback_on_error():
    llm = _make_llm()
    llm.chat.side_effect = Exception("API error")
    ctx = ContextManager(llm)
    msgs = [_make_msg("human", "hello world")]
    result = ctx._summarize(msgs)
    assert "hello world" in result


def test_summary_cache_used():
    llm = _make_llm(token_count=10000)
    ctx = ContextManager(llm, max_tokens=8000, recent_window=3)
    history = [_make_msg("human", f"msg {i}") for i in range(10)]
    ctx.build_messages(_make_agent(), "topic", history, [_make_agent()])
    call_count = llm.chat.call_count
    ctx.build_messages(_make_agent(), "topic", history, [_make_agent()])
    assert llm.chat.call_count == call_count
