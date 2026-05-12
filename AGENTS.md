# AGENTS.md — Agent Group Chat (AGC)

## Setup & commands

```bash
uv sync --extra dev           # install all deps (including test + prompt_toolkit + ruff)
uv run pytest tests/ -v       # run all 96 tests
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
├── agc topic "topic" → TopicSession (ChatRoom alias)
└── agc room          → FreeChatSession (REPL)
         ↓
    ChatSession (ABC)
    ├── history, agents, _scheduler, _context, _llm_clients
    └── subclasses implement run()
```

- **`agc/core/session.py`** — `ChatSession` ABC + `SessionStore` (JSONL persistence, default `data/sessions/`)
- **`agc/core/chatroom.py`** — `TopicSession(ChatSession)`. Topic-driven discussion with terminators. `ChatRoom = TopicSession` backward-compat alias.
- **`agc/core/freechat.py`** — `FreeChatSession(ChatSession)`. IM-style REPL group chat. User inputs anytime, scheduler picks responder(s).
- **`agc/core/context.py`** — `ContextManager`. `build_messages()` for topic mode (summarization). `build_freechat_context()` for IM mode (sliding window, no summarization). `_adjust_for_tool_pairs()` prevents splitting tool pairs.
- **`agc/core/message.py`** — `Message` (Pydantic). `to_openai_msg()` handles DeepSeek `reasoning_content`. `to_json()`/`from_json()` for persistence.
- **`agc/llm/openai_client.py`** — OpenAI SDK wrapper. Streaming + reasoning_content extraction. `FALLBACK_ENCODING = "cl100k_base"`.
- **`agc/ui/`** — `DisplayBase` ABC → `CliDisplay` (Rich terminal). Live + Panel for streaming.

**Important:** `ChatSession` stores agents as `self.agents` (plain list). TopicSession adds `self.config` (RoomConfig) separately. When writing code that works across both modes, use `self.agents`, not `self.config.agents`.

## Display

`CliDisplay` (always used):
- Three callbacks: `begin_stream(name, role, model)`, `on_chunk(text)`, `on_message(Message)`
- **Streaming**: `begin_stream` starts a Rich `Live` Panel (border visible from start, content grows). One `Live` instance per agent turn, **never stop/restart during tool calls** — only update content via `_update_live()`. This eliminates alt-screen switch flickering.
- **Tool calls**: `_tool_status` set → `_update_live()` appends tool status to existing Panel. `_stop_live()` is NOT called.
- **Final message**: streaming agent → `_stop_live()`, Panel stays visible (`transient=False`). Non-streaming → `_render_panel()` directly.
- `_render_panel(sender, content)` is a shared helper used by `_print_chat` and the streaming final-message path.
- Only failed tools (`tool_success: false`) shown via `_tool_status`.

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
- `_DEFAULT_MAX_CHARS = 50000` — web_fetch truncation limit
- `_MAX_REDIRECTS = 5` — web_fetch redirect limit

## Session persistence

- **FreeChatSession** → `data/sessions/freechat/{session_id}.jsonl` (JSONL per session)
- **TopicSession** → `data/sessions/topics/{timestamp}_{topic}.json` (summary only, auto-saved after `chat()` completes)
- `SessionStore` base dir defaults to `data/sessions/`; CLI explicitly passes subdirectory paths

## Tool system

- Search: DuckDuckGo via `ddgs` library (`DDGS.text()`)
- **web_fetch**: Jina Reader (`r.jina.ai`) as primary extractor (no API key needed, falls back on 429). readability-lxml as local fallback. SSRF protection via `_validate_url_safe()` — blocks private/internal IPs (10.x, 172.16-31.x, 192.168.x, 127.x, ::1, etc.)
- **Auto-registered tools:** `web_fetch`, `web_search`, workspace tools (`write_file`, `read_file`, `list_files`, `run_code`, `save_memory`, `recall_memory`, `list_memories`, `delete_memory`)
- **All tools injected by default** — agents with `tools=[]` get every registered tool schema via `_resolve_tools()`
- Workspace always enabled at `./data/workspaces/`

## web_fetch gotchas

- Jina Reader → readability-lxml dual extractor; `_format_result()` deduplicates output formatting
- SSRF: `_validate_url_safe()` resolves hostnames → blocks private IPs before making requests. Redirect targets also validated.
- `_sanitize()` removes NULL bytes and control characters before lxml parsing
- `Accept-Encoding` must NOT include `br` — brotli not installed, causes garbled output
- 403 responses get hint `(站点反爬拦截)` appended to error message

## FreeChatSession specifics

- Requires `prompt_toolkit` for proper CJK input (falls back to `input()` if missing)
- **Persistence**: sessions saved to `data/sessions/freechat/`. LLM auto-names on first message. Resume with `agc room --resume <name>` (prefix match).
- **Slash commands**: `/quit`, `/history [N]`, `/agents`, `/topic <text>`, `/clear`, `/help`
- **`/clear`**: deletes session file, creates new one. Only works if `session_id` is set.
- `_emit_message()` adds to history AND calls display callbacks. Don't append to history separately.

## CLI

```
agc topic "topic"             # topic-driven discussion (TopicSession)
agc topic "topic" -c cfg.yaml # YAML config
agc room                      # IM-style free group chat (FreeChatSession)
agc room --resume <prefix>    # resume saved session (fuzzy prefix match)
agc room --list               # list all saved sessions
agc agents                    # list agent templates
agc tools-list                # list registered tools
```

`.env` loaded by `cli.py:load_dotenv()`. Relevant vars: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`.

Default agents extracted to `_DEFAULT_AGENTS` dict list in `cli.py`; `_make_default_agents(model, tool_names)` builds `AgentConfig` list from it.

## Context

- Current time injected into system prompt (agent-visible), not displayed as user message
- TopicSession: `_select_history` summarizes older messages with LLM when over token limit
- FreeChatSession: `build_freechat_context` uses sliding window (default 30 messages), no summarization
- `current_topic` injected as system message when set via `/topic` command
