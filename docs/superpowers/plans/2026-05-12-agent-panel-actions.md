# Agent Panel Actions Display — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display agent tool calls and thinking (reasoning_content) in real-time within the streaming Live Panel, forming a complete "think → call tools → see results → respond" visual chain.

**Architecture:** Add a new `on_reasoning_chunk` callback chain (parallel to existing `on_message`/`on_chunk`/`on_speaker_start`) from LLM client through session to display. Replace `_tool_status: str` with `_action_log: list[str]` + `_reasoning_buf: str` in CliDisplay for accumulated action display. Unify tool display across TopicSession and FreeChatSession.

**Tech Stack:** Python, Rich (Panel/Live), Pydantic, pytest

---

## File Structure

Each file has one clear responsibility:
- `agc/llm/base.py` — LLM interface contracts
- `agc/llm/openai_client.py` — OpenAI streaming with reasoning support
- `agc/ui/base.py` — Display interface contracts
- `agc/ui/cli_display.py` — Rich terminal panel rendering
- `agc/core/session.py` — Shared callback infrastructure
- `agc/core/chatroom.py` — Topic mode (passes new callbacks)
- `agc/core/freechat.py` — IM mode (passes new callbacks + fix tool display)
- `tests/test_cli_display.py` — Display unit tests (new)

---

### Task 1: Add `on_reasoning_chunk` to LLM interface

**Files:**
- Modify: `agc/llm/base.py:35-55`

- [ ] **Step 1: Add `on_reasoning_chunk` parameter to `chat()` method**

```python
# agc/llm/base.py — modify the abstract method
@abstractmethod
def chat(
    self,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    tools: list[dict] | None = None,
    on_chunk: Callable[[str], None] | None = None,
    on_reasoning_chunk: Callable[[str], None] | None = None,
) -> LLMResponse:
```

- [ ] **Step 2: Run ruff check**

- [ ] **Step 3: Commit**

```bash
git add agc/llm/base.py agc/llm/openai_client.py
git commit -m "feat: add on_reasoning_chunk parameter to LLMBase.chat() interface"
```

---

### Task 2: Wire reasoning callback in OpenAIClient

**Files:**
- Modify: `agc/llm/openai_client.py:35-86`

- [ ] **Step 1: Update `chat()` to accept and forward `on_reasoning_chunk`**

```python
# agc/llm/openai_client.py — line 35-47
def chat(
    self,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    on_chunk: Callable[[str], None] | None = None,
    on_reasoning_chunk: Callable[[str], None] | None = None,
) -> LLMResponse:
    kwargs = self._build_kwargs(messages, model, temperature, max_tokens, tools)
    if on_chunk is not None:
        return self._streamed_chat(kwargs, on_chunk, on_reasoning_chunk)
    return self._normal_chat(kwargs)
```

- [ ] **Step 2: Update `_streamed_chat()` to accept and invoke reasoning callback**

```python
# agc/llm/openai_client.py — line 84-86
def _streamed_chat(
    self, kwargs: dict[str, Any], on_chunk: Callable[[str], None],
    on_reasoning_chunk: Callable[[str], None] | None = None,
) -> LLMResponse:
```
And inside the chunk loop, after `if rc:`:
```python
# agc/llm/openai_client.py — inside the for chunk in stream loop, replace lines 109-111
rc = getattr(delta, "reasoning_content", None)
if rc:
    reasoning_parts.append(rc)
    if on_reasoning_chunk:
        on_reasoning_chunk(rc)
```

- [ ] **Step 3: Run ruff check**

- [ ] **Step 4: Commit**

```bash
git add agc/llm/openai_client.py
git commit -m "feat: invoke on_reasoning_chunk callback in OpenAI streaming"
```

---

### Task 3: Add reasoning callback infrastructure to ChatSession

**Files:**
- Modify: `agc/core/session.py:60-136`

- [ ] **Step 1: Add `_on_reasoning_callbacks` and registration method**

Add after line 62 (`self._on_speaker_callbacks`):
```python
# agc/core/session.py — after line 62
self._on_reasoning_callbacks: list[Callable[[str], None]] = []
```

Add after `on_speaker_start` method (after line 115):
```python
# agc/core/session.py — after line 115
def on_reasoning(self, callback: Callable[[str], None]) -> None:
    self._on_reasoning_callbacks.append(callback)

def _emit_reasoning(self, text: str) -> None:
    for cb in self._on_reasoning_callbacks:
        cb(text)
```

- [ ] **Step 2: Run ruff check**

- [ ] **Step 3: Commit**

```bash
git add agc/core/session.py
git commit -m "feat: add reasoning callback chain to ChatSession"
```

---

### Task 4: Wire reasoning callbacks in TopicSession and FreeChatSession

**Files:**
- Modify: `agc/core/chatroom.py:226-232` and `agc/core/chatroom.py:267-274`
- Modify: `agc/core/freechat.py:212-219` and `agc/core/freechat.py:263-274`

- [ ] **Step 1: Pass `on_reasoning_chunk` in TopicSession._generate_response()**

```python
# agc/core/chatroom.py — line 226-232, add on_reasoning_chunk
response = llm.chat(
    messages=ctx,
    model=agent.model,
    temperature=agent.temperature,
    tools=agent_tools or None,
    on_chunk=self._emit_chunk if self._stream else None,
    on_reasoning_chunk=self._emit_reasoning if self._stream else None,
)
```

- [ ] **Step 2: Pass `on_reasoning_chunk` in TopicSession._force_text_response()**

```python
# agc/core/chatroom.py — line 279-286
response = llm.chat(
    messages=ctx,
    model=agent.model,
    temperature=agent.temperature,
    tools=None,
    on_chunk=self._emit_chunk if self._stream else None,
    on_reasoning_chunk=self._emit_reasoning if self._stream else None,
)
```

- [ ] **Step 3: Pass `on_reasoning_chunk` in FreeChatSession._generate_response()**

```python
# agc/core/freechat.py — line 213-219
response = llm.chat(
    messages=ctx,
    model=agent.model,
    temperature=agent.temperature,
    tools=agent_tools or None,
    on_chunk=self._emit_chunk if self._stream else None,
    on_reasoning_chunk=self._emit_reasoning if self._stream else None,
)
```

- [ ] **Step 4: Fix FreeChatSession._execute_tool_calls() to use _notify_display**

Replace lines 256-257 in `agc/core/freechat.py`:
```python
# Before:
for msg in msgs:
    self._emit_message(msg)

# After:
for msg in msgs:
    self._notify_display(msg)
```

- [ ] **Step 5: Pass `on_reasoning_chunk` in FreeChatSession._force_text_response()**

```python
# agc/core/freechat.py — line 268-274
response = llm.chat(
    messages=ctx,
    model=agent.model,
    temperature=agent.temperature,
    tools=None,
    on_chunk=self._emit_chunk if self._stream else None,
    on_reasoning_chunk=self._emit_reasoning if self._stream else None,
)
```

- [ ] **Step 6: Run ruff check**

- [ ] **Step 7: Commit**

```bash
git add agc/core/chatroom.py agc/core/freechat.py
git commit -m "feat: wire on_reasoning_chunk callback in both chat modes"
```

---

### Task 5: Enhance CliDisplay with reasoning + action log

**Files:**
- Modify: `agc/ui/base.py`
- Modify: `agc/ui/cli_display.py`

- [ ] **Step 1: Add `on_reasoning_chunk` to DisplayBase**

```python
# agc/ui/base.py — add method after on_chunk
def on_reasoning_chunk(self, text: str) -> None:
    """接收推理过程的增量文本"""
```

- [ ] **Step 2: Rewrite CliDisplay — replace _tool_status with _reasoning_buf + _action_log**

In `agc/ui/cli_display.py`, replace:
```python
# Line 43 — before:
self._tool_status = ""
# After:
self._reasoning_buf = ""
self._action_log: list[str] = []
```

- [ ] **Step 3: Add `_flush_reasoning()` helper**

```python
# agc/ui/cli_display.py — new method after _stop_live()
def _flush_reasoning(self) -> None:
    if self._reasoning_buf:
        self._action_log.append(f"💭 {self._reasoning_buf}")
        self._reasoning_buf = ""
```

- [ ] **Step 4: Rewrite `_build_panel()` to render three sections**

```python
# agc/ui/cli_display.py — replace _build_panel()
def _build_panel(self) -> Panel:
    color = self._get_color(self._stream_name)
    meta = self._agent_meta.get(self._stream_name, {})
    title = self._header(self._stream_name, meta.get("role", ""), meta.get("model", ""), color)

    parts: list[str] = []
    if self._action_log:
        parts.append("\n".join(f"[dim]{a}[/dim]" for a in self._action_log))
    if self._reasoning_buf:
        parts.append(f"[dim]💭 思考: {self._reasoning_buf}[/dim]")
    if self._stream_buf:
        parts.append(self._stream_buf)

    content = "\n\n".join(parts) if parts else "[dim]⏳ 思考中...[/dim]"
    return Panel(content, title=title, title_align="left", border_style=color, padding=(0, 1))
```

- [ ] **Step 5: Rewrite `begin_stream()` to reset new state**

```python
# agc/ui/cli_display.py — replace begin_stream()
def begin_stream(self, agent_name: str, agent_role: str, agent_model: str = "") -> None:
    self._stop_live()
    self._streaming = True
    self._stream_name = agent_name
    self._stream_buf = ""
    self._reasoning_buf = ""
    self._action_log = []
    self._agent_meta[agent_name] = {"role": agent_role, "model": agent_model}
    self._live = Live(self._build_panel(), console=self.console, refresh_per_second=10, transient=False)
    self._live.start()
```

- [ ] **Step 6: Add `on_reasoning_chunk()` method**

```python
# agc/ui/cli_display.py — new method after on_chunk()
def on_reasoning_chunk(self, text: str) -> None:
    if not self._streaming:
        return
    self._reasoning_buf += text
    self._update_live()
```

- [ ] **Step 7: Rewrite `on_message()` for tool_call with args summary**

Replace the tool_call handler block (lines 97-101):
```python
# agc/ui/cli_display.py — in on_message(), replace tool_call handler
import json

if message.msg_type == MessageType.tool_call:
    self._flush_reasoning()
    tc_names = []
    for tc in message.tool_calls:
        name = tc.get("function", {}).get("name", "?")
        args_str = tc.get("function", {}).get("arguments", "{}")
        try:
            args_dict = json.loads(args_str)
            args_parts = []
            for k, v in args_dict.items():
                v_str = json.dumps(v, ensure_ascii=False) if isinstance(v, str) else str(v)
                args_parts.append(f"{k}={v_str}")
            args_display = ", ".join(args_parts)
        except (json.JSONDecodeError, Exception):
            args_display = args_str[:60]
        if len(args_display) > 60:
            args_display = args_display[:57] + "..."
        tc_names.append(f"{name}({args_display})")
    for tc_name in tc_names:
        self._action_log.append(f"🔧 调用 {tc_name}")
    self._update_live()
    return
```

- [ ] **Step 8: Rewrite `on_message()` for tool_result with content summary**

Replace the tool_result handler block (lines 103-109):
```python
# agc/ui/cli_display.py — in on_message(), replace tool_result handler
if message.msg_type == MessageType.tool_result:
    tool_name = message.metadata.get("tool_name", "工具")
    tool_success = message.metadata.get("tool_success", True)
    if tool_success:
        summary = message.content[:80].replace("\n", " ")
        self._action_log.append(f"✅ {tool_name} → {summary}...")
    else:
        summary = message.content[:120]
        self._action_log.append(f"❌ {tool_name} → {summary}")
    self._update_live()
    return
```

- [ ] **Step 9: Rewrite final message handler to flush reasoning before stop**

Replace lines 111-114:
```python
# agc/ui/cli_display.py — in on_message(), replace the streaming sender match block
if self._streaming and self._stream_name == message.sender:
    self._flush_reasoning()
    self._streaming = False
    self._stop_live()
    return
```

- [ ] **Step 10: Run ruff check**

- [ ] **Step 11: Commit**

```bash
git add agc/ui/base.py agc/ui/cli_display.py
git commit -m "feat: enhance CliDisplay with reasoning stream and action log"
```

---

### Task 6: Write unit tests

**Files:**
- Create: `tests/test_cli_display.py`

- [ ] **Step 1: Write all tests**

```python
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
        rendered = panel.renderable if hasattr(panel, 'renderable') else str(panel)
        assert "Let me think" in str(rendered)
        assert "思考" in str(rendered)

    def test_tool_call_adds_to_action_log(self, display):
        display.begin_stream("researcher", "研究员")
        msg = Message(
            sender="researcher",
            content="",
            msg_type=MessageType.tool_call,
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query": "AI trends"}'},
            }],
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
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query": "test"}'},
            }],
        )
        display.on_message(msg)

        # reasoning should be flushed to action_log
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
        rendered = panel.renderable if hasattr(panel, 'renderable') else str(panel)
        assert "思考中" in str(rendered)

    def test_action_log_accumulates_multiple_calls(self, display):
        display.begin_stream("researcher", "研究员")

        # tool call 1
        msg1 = Message(
            sender="researcher",
            content="",
            msg_type=MessageType.tool_call,
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query": "AI"}'},
            }],
        )
        display.on_message(msg1)

        # result 1
        msg2 = Message(
            sender="tool",
            content="Got 5 results",
            msg_type=MessageType.tool_result,
            metadata={"tool_name": "web_search", "tool_success": True},
        )
        display.on_message(msg2)

        # tool call 2
        msg3 = Message(
            sender="researcher",
            content="",
            msg_type=MessageType.tool_call,
            tool_calls=[{
                "id": "call_2",
                "type": "function",
                "function": {"name": "web_fetch", "arguments": '{"url": "https://example.com"}'},
            }],
        )
        display.on_message(msg3)

        # result 2
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
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "test_tool", "arguments": json.dumps({"data": long_arg})},
            }],
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
        rendered = str(panel.renderable if hasattr(panel, 'renderable') else panel)
        assert "web_search" in rendered
        assert "Still thinking" in rendered
        assert "My answer" in rendered
```

- [ ] **Step 2: Run tests to verify they fail (new import)**

```bash
uv run pytest tests/test_cli_display.py -v
```

- [ ] **Step 3: Run all tests**

```bash
uv run pytest tests/ -v
```

- [ ] **Step 4: Run ruff check**

```bash
uv run ruff check
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli_display.py
git commit -m "test: add CliDisplay action log and reasoning tests"
```

---

### Task 7: Verify and finalize

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all tests pass (83 existing + ~13 new = 96)

- [ ] **Step 2: Run ruff check**

```bash
uv run ruff check
```

- [ ] **Step 3: Run ruff format**

```bash
uv run ruff format
```

- [ ] **Step 4: Final commit if any format changes**

```bash
git add -u && git diff --cached --quiet || git commit -m "style: ruff format after panel actions feature"
```
