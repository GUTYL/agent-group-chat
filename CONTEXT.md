# Agent Group Chat (AGC)

A terminal-based multi-agent group chat tool where AI personas discuss, debate, and collaborate in structured discussions or free-form conversations.

## Language

**Workspace**:
An agent's isolated sandbox directory (`data/workspaces/<name>/`) for file operations and code execution.
Agents can read each other's workspaces but only write to their own.
_Avoid_: "global workspace", "shared workspace"

**Session**:
A single run of a multi-agent chat, either topic-driven (TopicSession, one-shot) or free-form (FreeChatSession, persistent/resumable).
Both share a common base but differ in lifecycle and persistence format.

**Agent** (runtime):
An AI persona actively participating in a Session, defined by an AgentConfig with name, role, goal, model, and tools.
_Avoid_: using "agent" for template definitions.

**Agent Template** (template):
A predefined recipe for creating Agents. Six built-in templates exist (researcher, architect, developer, reviewer, pm, analyst).
Exposed via the `agc templates` CLI command (currently `agc agents`).

**Turn**:
A single agent's utterance (one LLM response, possibly with tool calls).
_Avoid_: "message", "reply"

**Round**:
A complete conversation cycle containing one or more Turns.
In TopicSession: one Round = one Turn (one agent speaks).
In FreeChatSession: one Round starts with a user message and may include chained Turns from @mentions (up to 3 extra sub-rounds).

**Scheduler**:
Determines which Agent speaks next using a 4-level priority fallback:
1. @mention — user explicitly names an agent
2. Keyword match — message content matches agent-related keywords
3. LLM route — LLM selects the best responder
4. Round-robin — sequential fallback

**Routing**:
The strategy used by the Scheduler to select speakers. Each level above is a "route."
_Avoid_: "speaker selection", "turn assignment"

**Context Window**:
The messages sent to the LLM for generating a response. Two strategies:
- **Summarization** (TopicSession): LLM compresses older messages into a summary; recent messages kept verbatim.
- **Sliding Window** (FreeChatSession): Last N messages sent as-is, no compression.
FreeChatSession enforces a hard memory cap (default 500 messages) — excess is archived to cold storage.

**SessionStore**:
Unified persistence layer for all Session types. TopicSessions save summary JSON; FreeChatSessions save JSONL message streams.
Exposes list/delete/rename operations via CLI (`agc sessions`).
_Avoid_: "save file", "output file"

**Tool**:
A callable capability available to Agents during a Turn. Registered globally at startup.
Built-in tools: web_fetch, web_search, and workspace tools (write_file, read_file, list_files, run_code, memory CRUD).

**Display**:
The presentation layer for rendering messages and UI elements in the terminal.
`DisplayBase` ABC defines the contract; `CliDisplay` is the Rich-based implementation.
All user-visible output (messages, help text, agent lists, welcome) must go through Display, never raw print().

**Message**:
A single piece of chat content (Pydantic model). Has type (chat/system/tool_call/tool_result), sender, content, and metadata.
Serialized to/from JSON for persistence. Converts to OpenAI API format for LLM calls.

## Relationships

- A **Session** runs one or more **Rounds**
- A **Round** contains one or more **Turns**
- A **Turn** is taken by exactly one **Agent** and may involve multiple **Tools**
- An **Agent** is built from an **Agent Template** with optional per-session overrides
- A **Session** persists through **SessionStore**; reads are gated by **Context Window** strategy
- All user-visible output goes through **Display**

## Example dialogue

> **Dev:** "If I call Scheduler.next_speaker() mid-Round, does that start a new Round?"
> **User:** "No — new Rounds are explicit. In TopicSession, a Round is one iteration of the main loop. In FreeChatSession, a Round is triggered by a user message."
>
> **Dev:** "Can an Agent's Turn in FreeChatSession trigger another Agent's Turn?"
> **User:** "Yes — up to 3 extra chained Turns if the first Agent @mentions another. All within the same Round."

## Flagged ambiguities

- "agent" was used for both **Agent Template** and **Agent** — resolved: `agc agents` renamed to `agc templates`.
- "round" was conflated with "turn" in `session.py:_emit_system` — resolved: Turn = single utterance, Round = complete cycle.
- `_saved` in FreeChatSession was stored in `metadata` dict but checked via `getattr` — bug to fix.

