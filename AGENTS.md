# AGENTS.md — Agent Group Chat (AGC)

## Setup & commands

```bash
uv sync --extra dev           # install all deps (including test)
uv run pytest tests/ -v       # run all 53 tests
uv run pytest tests/test_message.py -v         # single test file
uv run pytest tests/test_message.py::test_message_to_openai -v  # single test
```

No linter, typechecker, or formatter is configured. No CI. Deps change → run `uv lock && uv sync --extra dev`.

## Architecture

Single package `agc/`. Core flow:

```
cli.py (typer) → ChatRoom → Scheduler → LLM (OpenAI) → Tool execution
                   ↑ callback system → Display (TUI / Cli)
```

- **`agc/core/chatroom.py`** — orchestration engine (466 lines). Owns the main loop, tool execution, summary.
- **`agc/core/context.py`** — token-aware context window builder. Must include `tool_call` in `VISIBLE_MESSAGE_TYPES` for DeepSeek.
- **`agc/core/message.py`** — `Message` model (Pydantic). `to_openai_msg()` has critical DeepSeek logic.
- **`agc/llm/openai_client.py`** — OpenAI SDK wrapper. Streaming + reasoning_content extraction.
- **`agc/ui/`** — `DisplayBase` ABC → `TuiDisplay` (Textual, default) + `CliDisplay` (Rich, `--plain` flag).

## Display system

```
DisplayBase (agc/ui/base.py)
├── TuiDisplay  — Textual TUI, default for `agc chat`
└── CliDisplay  — Rich terminal output with --plain
```

Three callbacks drive display: `begin_stream(name, role, model)`, `on_chunk(text)`, `on_message(Message)`.

TUI threading: `ChatTuiApp.run()` on main thread, `room.chat()` in background daemon thread. All UI updates go through `call_from_thread()`.

TUI does NOT support human-in-the-loop. Use `--plain` for that.

## DeepSeek / thinking model requirements

1. **`reasoning_content` must round-trip.** If you receive `reasoning_content` in a response, it must be sent back in the next request's message under the same role, or the API errors. This is handled at two layers:
   - `Message.to_openai_msg()`: non-system messages with `reasoning_content` are set `role="assistant"` and include the field
   - `tool_call` messages with tool_calls also pass `reasoning_content` through
2. **`tool_call` messages must be in context history.** `context.py:VISIBLE_MESSAGE_TYPES` includes `tool_call` — do not remove it.
3. **Tool call/result ordering matters.** After a `tool_call` assistant message, there must be a `tool` role response before the next assistant message.

## Key constants

- `MAX_TOOL_ROUNDS = 3` (chatroom.py) — tool call loop limit, then forced text response
- `MAX_TOOL_RESULT_LENGTH = 2000` — truncated before storage
- `_emitted` metadata flag — prevents duplicate tool message display during streaming

## Tool system

Search is DuckDuckGo only (Serper/Tavily removed). Uses `ddgs` library (`DDGS.text()`), NOT `duckduckgo_search`.

Tools auto-register in ChatRoom constructor: `web_fetch` (always), `web_search` (always, if ddgs available), workspace tools (if `workspace_root` set).

## Message threading for display

Tool messages use `metadata["_emitted"] = True` to skip the generic `_process_messages` callback loop, since they're explicitly emitted in `_execute_tool_calls`. Without this, tool output would appear twice.

## CLI

```
agc chat "topic"              # TUI (default)
agc chat "topic" --plain      # raw Rich output, supports human-in-the-loop
agc chat "topic" -c cfg.yaml  # YAML config
agc agents                    # list agent templates
agc tools-list                # list registered tools
```

`.env` loaded by `cli.py:load_dotenv()`. Relevant vars: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` (sets CLI `--model` default).
