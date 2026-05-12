"""单元测试 — CliDisplay Panel 动作展示"""

import json

import pytest

from agc.core.message import Message, MessageType
from agc.ui.cli_display import CliDisplay


@pytest.fixture
def display():
    return CliDisplay()


class TestActionLog:
    """动作日志测试"""

    def test_begin_stream_resets_state(self, display):
        display._reasoning_buf = "old reasoning"
        display._action_log = ["old action"]
        display._stream_buf = "old content"

        display.begin_stream("alice", "研究员", "gpt-4")

        assert display._reasoning_buf == ""
        assert display._action_log == []
        assert display._stream_buf == ""

    def test_reasoning_shown_in_panel(self, display):
        display.begin_stream("alice", "研究员")
        display.on_reasoning_chunk("Let me think...")

        panel = display._build_panel()
        rendered = panel.renderable if hasattr(panel, "renderable") else str(panel)
        assert "Let me think" in str(rendered)
        assert "思考" in str(rendered)

    def test_tool_call_adds_to_action_log(self, display):
        display.begin_stream("researcher", "研究员")
        msg = Message(
            sender="researcher",
            content="",
            msg_type=MessageType.tool_call,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query": "AI trends"}'},
                }
            ],
        )
        display.on_message(msg)

        assert len(display._action_log) == 1
        assert "web_search" in display._action_log[0]
        assert "AI trends" in display._action_log[0]

    def test_tool_result_success_adds_to_action_log(self, display):
        display.begin_stream("researcher", "研究员")
        msg = Message(
            sender="tool",
            content="Found 8 results about AI...",
            msg_type=MessageType.tool_result,
            metadata={"tool_name": "web_search", "tool_success": True},
        )
        display.on_message(msg)

        assert len(display._action_log) == 1
        assert "✅" in display._action_log[0]
        assert "web_search" in display._action_log[0]

    def test_tool_result_failure_adds_to_action_log(self, display):
        display.begin_stream("researcher", "研究员")
        msg = Message(
            sender="tool",
            content="Connection timeout",
            msg_type=MessageType.tool_result,
            metadata={"tool_name": "web_search", "tool_success": False},
        )
        display.on_message(msg)

        assert len(display._action_log) == 1
        assert "❌" in display._action_log[0]
        assert "Connection timeout" in display._action_log[0]

    def test_reasoning_flushed_on_tool_call(self, display):
        display.begin_stream("researcher", "研究员")
        display.on_reasoning_chunk("I need to search")

        msg = Message(
            sender="researcher",
            content="",
            msg_type=MessageType.tool_call,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query": "test"}'},
                }
            ],
        )
        display.on_message(msg)

        assert display._reasoning_buf == ""
        assert any("I need to search" in entry for entry in display._action_log)

    def test_reasoning_flushed_on_final_message(self, display):
        display.begin_stream("alice", "研究员")
        display.on_reasoning_chunk("thinking...")

        msg = Message(
            sender="alice",
            content="Final answer",
            msg_type=MessageType.chat,
        )
        display.on_message(msg)

        assert display._reasoning_buf == ""
        assert any("thinking" in entry for entry in display._action_log)

    def test_empty_state_shows_thinking(self, display):
        display.begin_stream("alice", "研究员")

        panel = display._build_panel()
        rendered = panel.renderable if hasattr(panel, "renderable") else str(panel)
        assert "思考中" in str(rendered)

    def test_action_log_accumulates_multiple_calls(self, display):
        display.begin_stream("researcher", "研究员")

        msg1 = Message(
            sender="researcher",
            content="",
            msg_type=MessageType.tool_call,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query": "AI"}'},
                }
            ],
        )
        display.on_message(msg1)

        msg2 = Message(
            sender="tool",
            content="Got 5 results",
            msg_type=MessageType.tool_result,
            metadata={"tool_name": "web_search", "tool_success": True},
        )
        display.on_message(msg2)

        msg3 = Message(
            sender="researcher",
            content="",
            msg_type=MessageType.tool_call,
            tool_calls=[
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "web_fetch",
                        "arguments": '{"url": "https://example.com"}',
                    },
                }
            ],
        )
        display.on_message(msg3)

        msg4 = Message(
            sender="tool",
            content="Page content here",
            msg_type=MessageType.tool_result,
            metadata={"tool_name": "web_fetch", "tool_success": True},
        )
        display.on_message(msg4)

        assert len(display._action_log) == 4
        assert "web_search" in display._action_log[0]
        assert "✅" in display._action_log[1]
        assert "web_fetch" in display._action_log[2]
        assert "✅" in display._action_log[3]

    def test_tool_args_truncated(self, display):
        display.begin_stream("researcher", "研究员")
        long_arg = "x" * 100
        msg = Message(
            sender="researcher",
            content="",
            msg_type=MessageType.tool_call,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "test_tool", "arguments": json.dumps({"data": long_arg})},
                }
            ],
        )
        display.on_message(msg)

        entry = display._action_log[0]
        assert "..." in entry

    def test_on_chunk_streams_content(self, display):
        display.begin_stream("alice", "研究员")
        display.on_chunk("Hello ")
        display.on_chunk("World")

        assert display._stream_buf == "Hello World"

    def test_panel_includes_all_sections(self, display):
        display.begin_stream("alice", "研究员")
        display._action_log = ["🔧 调用 web_search(query=...)", "✅ web_search → ..."]
        display._reasoning_buf = "Still thinking..."
        display._stream_buf = "My answer"

        panel = display._build_panel()
        rendered = panel.renderable if hasattr(panel, "renderable") else str(panel)
        rendered_str = str(rendered)
        assert "web_search" in rendered_str
        assert "Still thinking" in rendered_str
        assert "My answer" in rendered_str
