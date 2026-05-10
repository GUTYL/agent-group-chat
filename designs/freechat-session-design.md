# FreeChat Session Design — IM-Style Group Chat

## Overview

Add an IM-style free group chat mode to AGC alongside the existing topic-driven discussion mode. In the new mode, a single human user chats freely with multiple agents — the human types whenever they want, and the HybridScheduler decides which agent(s) respond. Conversations support natural topic switching and are persisted to disk for later resumption.

## Requirements

1. **Two modes**: topic-driven (existing) + IM-style free group chat (new)
2. **IM mode**: terminal REPL, human inputs anytime, LLM routing decides responder
3. **Multi-topic within one session**: topics can naturally interleave; `/topic` command sets context
4. **Persistence**: sessions saved to `data/sessions/`, resumable by name
5. **Single human + multiple agents**: only one real user, multiple LLM agents
6. **LLM-generated session names**: first user message triggers LLM to name the session file

## Architecture

### Class Hierarchy

```
ChatSession (ABC)                    # New base class
├── history: list[Message]
├── agents: list[AgentConfig]
├── context_manager: ContextManager
├── scheduler: SchedulerBase
├── display: DisplayBase
├── save() / load()                   # Persistence
└── run()  (abstract)                 # Main loop, subclasses implement

TopicSession(ChatSession)             # Renamed from ChatRoom
├── topic: str
├── terminators: list[TerminatorBase]
├── max_rounds: int
└── run() → ChatResult               # Terminates on consensus/max-rounds

FreeChatSession(ChatSession)          # New IM mode
├── session_id: str
├── user_name: str                    # Default "human"
└── run() → None                     # REPL loop, exits on /quit
```

`ChatRoom` kept as alias for `TopicSession` for backward compatibility.

### Key Differences from TopicSession

| Aspect | TopicSession | FreeChatSession |
|--------|-------------|-----------------|
| Termination | Consensus / max rounds | User `/quit` |
| Topic | Fixed at start | Switchable via `/topic` |
| Scheduling | Round-robin + @mention + LLM | @mention + LLM routing only |
| Context | Full history + summarization | Sliding window (last 30 messages) |
| Human input | HumanMode controlled pauses | Always available |
| Persistence | None | JSONL per session |

## FreeChatSession REPL Flow

```python
def run(self):
    self._load_or_create_session()
    self._show_welcome()
    while True:
        user_input = prompt(f"[{self.user_name}] ")  # Rich PromptSession
        if not user_input.strip(): continue           # Empty input = no-op
        if user_input in ("/quit", "/exit"): break
        if user_input.startswith("/"): handle_command(user_input); continue

        # 1. Write user message to history
        user_msg = Message(sender=self.user_name, content=user_input, msg_type=MessageType.human_input)
        self.history.append(user_msg)
        self.display.on_message(user_msg)

        # 2. Schedule: decide who responds
        response_plan = self.scheduler.plan_responses(self.history)

        # 3. Each scheduled agent responds in turn
        for agent in response_plan:
            self._generate_and_display(agent)

        # 4. Persist after each turn
        self.session_store.append(self.session_id, [user_msg] + new_agent_msgs)
```

### Scheduling in FreeChat Mode

New method `plan_responses()` on `HybridScheduler`:

- **@mention detected** → mentioned agents respond (supports multiple @mentions)
- **@all or "大家"** → all agents respond in sequence
- **No mention** → LLM router picks the single most relevant agent
- **LLM returns no agent** → empty response list, no agent speaks (valid for casual remarks that don't need a reply)
- Keyword routing and round-robin are NOT used in FreeChat mode

### Slash Commands

| Command | Description |
|---------|-------------|
| `/quit`, `/exit` | Exit the session |
| `/history [N]` | Show last N messages (default 10) |
| `/agents` | List agents in the chat |
| `/topic <text>` | Set current topic context for agents |
| `/clear` | Clear session history (in-memory AND persisted file) |
| `/help` | Show all commands |

## Context Management

### FreeChat Context Strategy

Sliding window of recent messages, no summarization:

```python
def build_context_freechat(self, agent, history, recent_window=30, ...):
    recent = history[-recent_window:]
    recent = self._adjust_for_tool_pairs(recent)
    messages = [system_prompt] + [m.to_openai_msg() for m in recent]
    messages.append(turn_cue)  # "[agent.name] It's your turn to speak..."
    return messages
```

Topic context injection: if `/topic` has been set, system prompt includes `[当前话题: {topic}]`.

## Persistence

### SessionStore

```python
class SessionStore:
    base_dir: Path  # Default: data/sessions/

    def create_session(self) -> str                    # Returns session_id
    def append(self, session_id, messages)             # Append messages to session file
    def load_session(self, session_id) -> list[Message] # Load full history
    def list_sessions(self) -> list[str]               # List all session names (without .jsonl)
    def rename_session(self, old_id, new_id)            # Rename session file
    def delete_session(self, session_id)               # Delete session file
```

### Storage Format

- Each session = one `.jsonl` file in `data/sessions/`
- One JSON object per line = one Message
- File naming: LLM-generated slug (Chinese preserved, e.g., `探索AI产品设计方案.jsonl`)
- Fallback: `{timestamp}.jsonl` if LLM fails

```
data/sessions/
├── 探索AI产品设计方案.jsonl
├── 代码审查讨论.jsonl
└── 2026-05-10_143000.jsonl       # Fallback naming
```

### Session Naming Flow

1. Session starts with a temp name (timestamp)
2. After the first user message, use the configured LLM client to generate a concise title (same `OpenAIClient` as the agents)
3. Rename the file from `{timestamp}.jsonl` to `{title}.jsonl`
4. If LLM call fails, keep the timestamp name

### Session Resumption

- `agc room --resume <name_or_prefix>` — fuzzy-match session name
- On resume, display last 10 messages as recap
- Context window starts from the continuation point

## CLI Commands

```bash
# Existing (unchanged)
agc chat "topic"              # Topic discussion mode
agc agents                    # List agent templates
agc tools-list                 # List tools

# New
agc room                      # Start IM free chat (default agents)
agc room -c config.yaml       # Use config file for agent definitions
agc room --name "我的群聊"     # Specify session name (skip LLM naming)
agc room --resume 探索AI       # Resume session (fuzzy prefix match)
agc room --list                # List all saved sessions
agc room --model deepseek      # Specify default model
```

## Message Model Changes

`Message` additions:

- `session_id: str = ""` — which session this message belongs to
- `to_json() -> dict` — serialize to JSON-compatible dict
- `Message.from_json(data: dict) -> Message` — deserialize

## UI Adjustments for FreeChat Mode

- **User input**: displayed as `[human] 你说的话` (compact, no Panel)
- **Agent replies**: keep existing Panel style (colored border + name)
- **System messages**: keep existing dim style
- **Topic switch**: show `── 话题已切换为: {topic} ──`
- **Session resume**: show last 10 messages as recap

## File Change Summary

| File | Change | Description |
|------|--------|-------------|
| `agc/core/session.py` | **New** | ChatSession ABC + SessionStore |
| `agc/core/chatroom.py` | Refactor | ChatRoom → TopicSession, extract shared logic to base class |
| `agc/core/freechat.py` | **New** | FreeChatSession implementation |
| `agc/core/message.py` | Modify | Add session_id field + JSON serialization |
| `agc/core/context.py` | Modify | Add build_context_freechat() |
| `agc/schedulers/hybrid.py` | Modify | Add plan_responses() method |
| `agc/ui/cli_display.py` | Modify | Adapt for FreeChatSession display needs |
| `agc/cli.py` | Modify | Add `agc room` command group |
| `agc/core/__init__.py` | Modify | Export new classes |

## Out of Scope (for initial implementation)

- Multi-human user support
- Web UI
- Thread/sub-topic forking (Slack-style threads)
- Real-time streaming across network
- Message search/retrieval across sessions