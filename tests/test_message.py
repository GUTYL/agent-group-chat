"""单元测试 — Message模型"""

from agc.core.message import Message, MessageType


def test_message_creation():
    msg = Message(
        sender="alice", content="Hello @bob", mentions=["bob"], msg_type=MessageType.mention
    )
    assert msg.sender == "alice"
    assert msg.content == "Hello @bob"
    assert msg.mentions == ["bob"]
    assert msg.msg_type == MessageType.mention
    assert msg.has_mentions is True


def test_message_format_display():
    msg = Message(
        sender="alice", content="Hello @bob", mentions=["bob"], msg_type=MessageType.mention
    )
    display = msg.format_display()
    assert "alice" in display
    assert "Hello @bob" in display


def test_message_to_openai():
    msg = Message(sender="alice", content="Hello", round_idx=1)
    openai_msg = msg.to_openai_msg()
    assert openai_msg["role"] == "user"
    assert "alice" in openai_msg["content"]


def test_system_message():
    msg = Message(sender="system", content="Game started", msg_type=MessageType.system)
    assert msg.is_system is True
    openai_msg = msg.to_openai_msg()
    assert openai_msg["role"] == "system"


def test_tool_call_message():
    """工具调用消息的格式化"""
    msg = Message(
        sender="researcher",
        content="",
        msg_type=MessageType.tool_call,
        round_idx=2,
        tool_calls=[
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "web_search",
                    "arguments": '{"query": "限流算法"}',
                },
            }
        ],
    )
    assert msg.msg_type == MessageType.tool_call
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0]["function"]["name"] == "web_search"

    # to_openai_msg 应该是 assistant + tool_calls
    openai_msg = msg.to_openai_msg()
    assert openai_msg["role"] == "assistant"
    assert "tool_calls" in openai_msg
    assert openai_msg["tool_calls"][0]["function"]["name"] == "web_search"


def test_tool_result_message():
    """工具结果消息的格式化"""
    msg = Message(
        sender="tool",
        content="搜索结果：令牌桶算法...",
        msg_type=MessageType.tool_result,
        round_idx=2,
        tool_call_id="call_abc123",
    )
    assert msg.msg_type == MessageType.tool_result

    # to_openai_msg 应该是 role=tool
    openai_msg = msg.to_openai_msg()
    assert openai_msg["role"] == "tool"
    assert openai_msg["tool_call_id"] == "call_abc123"
    assert "搜索结果" in openai_msg["content"]


def test_tool_call_format_display():
    """工具调用消息的显示格式"""
    msg = Message(
        sender="researcher",
        content="",
        msg_type=MessageType.tool_call,
        tool_calls=[
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query": "test"}'},
            }
        ],
    )
    display = msg.format_display()
    assert "web_search" in display
    assert "调用工具" in display


def test_tool_result_format_display():
    """工具结果消息的显示格式（截断）"""
    msg = Message(
        sender="tool",
        content="A" * 500,
        msg_type=MessageType.tool_result,
    )
    display = msg.format_display()
    assert "工具结果" in display


def test_message_json_roundtrip():
    original = Message(
        sender="architect",
        content="@developer please review",
        msg_type=MessageType.mention,
        mentions=["developer"],
        round_idx=3,
        metadata={"tokens": 150},
    )
    data = original.to_json()
    restored = Message.from_json(data)
    assert restored.sender == original.sender
    assert restored.content == original.content
    assert restored.msg_type == original.msg_type
    assert restored.mentions == original.mentions
    assert restored.round_idx == original.round_idx
