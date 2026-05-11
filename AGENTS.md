# AGENTS.md — Agent Group Chat (AGC)

## Setup & commands

```bash
uv sync --extra dev           # install all deps (including test + prompt_toolkit + ruff)
uv run pytest tests/ -v       # run all 78 tests
uv run pytest tests/test_message.py::test_message_to_json -v  # single test
uv run ruff check             # lint
uv run ruff format            # auto-format
uv run ruff check --fix       # auto-fix lint issues
```

Ruff 配置在 `pyproject.toml` 中: E/W/F/I/B/C4/SIM/UP 规则集，行宽 100，双引号。

## Architecture

Single package `agc/`. Two chat modes share a common base:

```
cli.py (typer)
├── agc chat "topic" → TopicSession (ChatRoom alias)
└── agc room          → FreeChatSession (REPL)
         ↓
    ChatSession (ABC)
    ├── history, agents, _scheduler, _context, _llm_clients
    └── subclasses implement run()
```

- **`agc/core/session.py`** — `ChatSession` ABC + `SessionStore` (JSONL persistence in `data/sessions/`)
- **`agc/core/chatroom.py`** — `TopicSession(ChatSession)`. Topic-driven discussion with terminators. `ChatRoom = TopicSession` backward-compat alias.
- **`agc/core/freechat.py`** — `FreeChatSession(ChatSession)`. IM-style REPL group chat. User inputs anytime, scheduler picks responder(s).
- **`agc/core/context.py`** — `ContextManager`. `build_messages()` for topic mode (summarization). `build_freechat_context()` for IM mode (sliding window, no summarization). `_adjust_for_tool_pairs()` prevents splitting tool pairs.
- **`agc/core/message.py`** — `Message` (Pydantic). `to_openai_msg()` handles DeepSeek `reasoning_content`. `to_json()`/`from_json()` for persistence. `session_id` field.
- **`agc/llm/openai_client.py`** — OpenAI SDK wrapper. Streaming + reasoning_content extraction. `FALLBACK_ENCODING = "cl100k_base"`.
- **`agc/ui/`** — `DisplayBase` ABC → `CliDisplay` (Rich terminal). Uses `Live` for streaming Panel updates.

**Important:** `ChatSession` stores agents as `self.agents` (plain list). TopicSession adds `self.config` (RoomConfig) separately. When writing code that works across both modes, use `self.agents`, not `self.config.agents`.

## Display

`CliDisplay` (always used):
- Three callbacks: `begin_stream(name, role, model)`, `on_chunk(text)`, `on_message(Message)`
- **Streaming**: `begin_stream` starts a Rich `Live` Panel (empty, grows as chunks arrive). Content shows `⏳ 思考中...` until first text.
- **Tool calls**: stop `Live`, show spinner. Next `on_chunk` auto-restarts `Live` Panel.
- **Final message**: streaming agent → `Live` already displayed, just stop. Non-streaming → render Panel directly.
- Human messages rendered in same Panel format as agents (unified `_header` style).
- Only failed tools (`tool_success: false`) shown in red.

## Scheduling

### TopicSession (next_speaker)
@mention → keyword route → LLM route → round-robin

### FreeChatSession (plan_responses)
@mention (all mentioned) → "大家"/@all (all) → keyword route → LLM route → first agent (fallback)

LLM routing logs to stdout: `🤖 LLM路由 → @name` on success, `⚡ LLM路由未命中` on miss, `⚡ LLM路由调用失败: ...` on error. Reads `reasoning_content` as fallback for thinking models.

## DeepSeek / thinking model requirements

1. **`reasoning_content` must round-trip** — handled in `Message.to_openai_msg()` and `_execute_tool_calls`
2. **`tool_call` messages in history** — `VISIBLE_MESSAGE_TYPES` includes `tool_call`, do not remove
3. **Tool call/result pairing** — `_adjust_for_tool_pairs()` ensures context window never cuts between a `tool_call` and its `tool_result`
4. **LLM routing uses `reasoning_content`** — `_llm_route()` checks `response.reasoning_content` when `response.content` is empty

## Key constants

- `MAX_TOOL_ROUNDS = 8` — tool call loop limit (in both chatroom.py and freechat.py)
- `MAX_TOOL_RESULT_LENGTH = 2000` — truncated before storage
- `_emitted` metadata flag — prevents duplicate tool message display during streaming
- `SessionStore` base dir: `data/sessions/` (auto-created)

## Tool system

- Search: DuckDuckGo via `ddgs` library (`DDGS.text()`)
- **Auto-registered tools:** `web_fetch`, `web_search`, workspace tools (`write_file`, `read_file`, `list_files`, `run_code`, `save_memory`, `recall_memory`, `list_memories`, `delete_memory`)
- **All tools injected by default** — agents with `tools=[]` get every registered tool schema via `_resolve_tools()`
- Workspace always enabled at `./data/workspaces/`

## web_fetch gotchas

- `_sanitize()` removes NULL bytes and control characters before lxml parsing
- `Accept-Encoding` must NOT include `br` — brotli not installed, causes garbled output
- 403 responses get hint `(站点反爬拦截)` appended to error message

## FreeChatSession specifics

- Requires `prompt_toolkit` for proper CJK input (falls back to `input()` if missing)
- **Persistence**: sessions saved as JSONL in `data/sessions/`, one file per session. LLM auto-names on first message. Resume with `agc room --resume <name>` (prefix match).
- **Slash commands**: `/quit`, `/history [N]`, `/agents`, `/topic <text>`, `/clear`, `/help`
- **`/clear`**: deletes session file, creates new one. Only works if `session_id` is set.
- `_emit_message()` adds to history AND calls display callbacks. Don't append to history separately.

## CLI

```
agc chat "topic"              # topic-driven discussion (TopicSession)
agc chat "topic" -c cfg.yaml  # YAML config
agc room                      # IM-style free group chat (FreeChatSession)
agc room --resume <prefix>    # resume saved session (fuzzy prefix match)
agc room --list               # list all saved sessions
agc agents                    # list agent templates
agc tools-list                # list registered tools
```

`.env` loaded by `cli.py:load_dotenv()`. Relevant vars: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`.

## Context

- Current time injected into system prompt (agent-visible), not displayed as user message
- TopicSession: `_select_history` summarizes older messages with LLM when over token limit
- FreeChatSession: `build_freechat_context` uses sliding window (default 30 messages), no summarization
- `current_topic` injected as system message when set via `/topic` command
