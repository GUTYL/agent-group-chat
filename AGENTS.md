# AGENTS.md — Agent Group Chat (AGC)

## Setup & commands

```bash
uv sync --extra dev           # install all deps (including test)
uv run pytest tests/ -v       # run all 53 tests
uv run pytest tests/test_message.py::test_message_to_openai -v  # single test
```

No linter, typechecker, or formatter configured. Deps change → `uv lock && uv sync --extra dev`.

## Architecture

Single package `agc/`. Core flow:

```
cli.py (typer) → ChatRoom → Scheduler → LLM (OpenAI) → Tool execution
                   ↑ callback system → CliDisplay (Rich)
```

- **`agc/core/chatroom.py`** — orchestration engine. Owns main loop, tool execution, summary, termination.
- **`agc/core/context.py`** — token-aware context window builder. Has `_adjust_for_tool_pairs()` to prevent splitting `tool_call`/`tool_result` pairs (DeepSeek rejects orphaned `tool` messages).
- **`agc/core/message.py`** — `Message` model (Pydantic). `to_openai_msg()` handles DeepSeek `reasoning_content` round-trip.
- **`agc/llm/openai_client.py`** — OpenAI SDK wrapper. Streaming + reasoning_content extraction. `FALLBACK_ENCODING = "cl100k_base"`.
- **`agc/ui/`** — `DisplayBase` ABC → `CliDisplay` (Rich terminal output). TUI removed.

## Display

`CliDisplay` (always used, no `--plain` flag):
- Three callbacks: `begin_stream(name, role, model)`, `on_chunk(text)`, `on_message(Message)`
- Shows spinner (`Status` with `bouncingBar`) while agent thinks or calls tools
- Tool calls/results hidden by default; only failed tools (`tool_success: false`) shown in red
- Streaming text shown inline; final message wrapped in `Panel`

## DeepSeek / thinking model requirements

1. **`reasoning_content` must round-trip** — handled in `Message.to_openai_msg()` and `_execute_tool_calls`
2. **`tool_call` messages in history** — `VISIBLE_MESSAGE_TYPES` includes `tool_call`, do not remove
3. **Tool call/result pairing** — `_adjust_for_tool_pairs()` ensures context window never cuts between a `tool_call` and its `tool_result`

## Key constants (chatroom.py)

- `MAX_TOOL_ROUNDS = 8` — tool call loop limit, then forced text response. Exceeded → `logger.debug` (not warning)
- `MAX_TOOL_RESULT_LENGTH = 2000` — truncated before storage
- `_emitted` metadata flag — prevents duplicate tool message display during streaming

## Tool system

- Search: DuckDuckGo via `ddgs` library (`DDGS.text()`)
- **Auto-registered tools:** `web_fetch`, `web_search`, workspace tools (`write_file`, `read_file`, `list_files`, `run_code`, `save_memory`, `recall_memory`, `list_memories`, `delete_memory`)
- **All tools injected by default** — agents with `tools=[]` get every registered tool schema via `_resolve_tools()`
- Workspace always enabled at `./data/workspaces/` (no `--human` requirement)

## web_fetch gotchas

- `_sanitize()` removes NULL bytes and control characters before lxml parsing
- `Accept-Encoding` must NOT include `br` — brotli not installed, causes garbled output
- 403 responses get hint `(站点反爬拦截)` appended to error message

## CLI

```
agc chat "topic"              # start group chat
agc chat "topic" -c cfg.yaml  # YAML config
agc agents                    # list agent templates
agc tools-list                # list registered tools
```

`.env` loaded by `cli.py:load_dotenv()`. Relevant vars: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`.

## Context

- Current time injected into system prompt (agent-visible), not displayed as user message
- `_select_history` summarizes older messages with LLM when over token limit
