"""Textual TUI 群聊界面 — 每个 agent 发言独立窗口，工具输出折叠"""

from __future__ import annotations

import json
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Collapsible, Footer, Header, RichLog, Static

AGENT_COLORS = [
    "cyan", "green", "yellow", "magenta", "blue",
    "red", "bright_cyan", "bright_green", "bright_yellow", "bright_magenta",
]

TOOL_EMOJI: dict[str, str] = {
    "web_search":    "🔍",
    "web_fetch":     "📄",
    "write_file":    "✍️",
    "read_file":     "📖",
    "list_files":    "📂",
    "run_code":      "🐍",
    "save_memory":   "🧠",
    "recall_memory": "🔍",
    "list_memories": "📋",
    "delete_memory": "🗑️",
}

MAX_BODY_HEIGHT = 16


class _AgentCard(Vertical):
    """单个 agent 的一条发言卡片 — 正文可滚动"""

    def __init__(self, name: str, role: str, model: str, color: str) -> None:
        super().__init__()
        self._color = color
        model_str = f" [dim]({model})[/dim]" if model else ""
        self._header = Static(
            f"[bold {color}]{name}[/bold {color}] [dim]{role}{model_str}[/dim]",
            id="card-header",
        )
        self._body = RichLog(id="card-body", max_lines=MAX_BODY_HEIGHT, wrap=True)
        self.mount(self._header)
        self.mount(self._body)

    def write(self, text: str) -> None:
        self._body.write(text)

    def set_text(self, text: str) -> None:
        self._body.clear()
        self._body.write(text)


class ChatTuiApp(App):
    """Textual 群聊 App"""

    TITLE = "Agent Group Chat"
    CSS = """
    #chat-area {
        overflow-y: auto;
    }

    .agent-card {
        border: wide $primary-darken-2;
        margin: 1 0;
        padding: 0 1;
    }

    .agent-card #card-header {
        text-style: bold;
        padding: 0 1;
        margin-bottom: 1;
    }

    .agent-card RichLog {
        min-height: 1;
    }

    .system-msg {
        color: $text-disabled;
        text-style: italic;
        margin: 1 0;
        padding: 0 1;
        text-align: center;
    }

    .human-card {
        border: wide $accent;
        margin: 1 0;
        padding: 0 1;
    }

    .human-card #card-header {
        text-style: bold;
        padding: 0 1;
    }

    .tool-collapsible {
        margin: 0 2;
    }

    .tool-collapsible CollapsibleTitle {
        color: $text-muted;
        text-style: dim;
    }

    .mentions-bar {
        color: $warning;
        text-style: bold;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._color_idx = 0
        self._agent_colors: dict[str, str] = {}
        self._current_card: Optional[_AgentCard] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Vertical(id="chat-log"), id="chat-area")
        yield Footer()

    def _get_color(self, name: str) -> str:
        if name not in self._agent_colors:
            self._agent_colors[name] = AGENT_COLORS[self._color_idx % len(AGENT_COLORS)]
            self._color_idx += 1
        return self._agent_colors[name]

    # ── Thread-safe public API ──────────────────────────────

    def add_system(self, text: str) -> None:
        self.call_from_thread(self._add_system, text)

    def begin_agent(self, name: str, role: str, model: str) -> None:
        self.call_from_thread(self._begin_agent, name, role, model)

    def add_chunk(self, text: str) -> None:
        self.call_from_thread(self._add_chunk, text)

    def finish_agent(self, text: str, mentions: list[str] | None = None) -> None:
        self.call_from_thread(self._finish_agent, text, mentions)

    def add_tool_call(self, tool_name: str, tool_args: str) -> None:
        self.call_from_thread(self._add_tool_call, tool_name, tool_args)

    def add_tool_result(self, tool_name: str, content: str, duration: float = 0) -> None:
        self.call_from_thread(self._add_tool_result, tool_name, content, duration)

    def add_human(self, name: str, text: str) -> None:
        self.call_from_thread(self._add_human, name, text)

    def stop(self) -> None:
        self.call_from_thread(self.exit)

    # ── Internal UI helpers (run on main thread) ────────────

    def _chat_log(self) -> Vertical:
        return self.query_one("#chat-log", Vertical)

    def _scroll_bottom(self) -> None:
        area = self.query_one("#chat-area", VerticalScroll)
        area.scroll_end(animate=False)

    def _add_system(self, text: str) -> None:
        w = Static(f"── {text} ──", classes="system-msg")
        self._chat_log().mount(w)
        self._scroll_bottom()

    def _begin_agent(self, name: str, role: str, model: str) -> None:
        color = self._get_color(name)
        card = _AgentCard(name, role, model, color)
        card.add_class("agent-card")
        self._current_card = card
        self._chat_log().mount(card)

    def _add_chunk(self, text: str) -> None:
        if self._current_card:
            self._current_card.write(text)
            self._scroll_bottom()

    def _finish_agent(self, text: str, mentions: list[str] | None) -> None:
        if self._current_card:
            if text:
                self._current_card.set_text(text)
            if mentions:
                bar = Static(" → " + " ".join(f"@{m}" for m in mentions), classes="mentions-bar")
                self._current_card.mount(bar)
            self._current_card = None
            self._scroll_bottom()

    def _add_tool_call(self, tool_name: str, tool_args: str) -> None:
        emoji = TOOL_EMOJI.get(tool_name, "⚡")
        try:
            pretty = json.dumps(json.loads(tool_args), ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            pretty = tool_args or "(无参数)"
        body = Static(pretty)
        collapsible = Collapsible(
            body,
            title=f"{emoji} {tool_name}",
            collapsed_symbol="▶",
            expanded_symbol="▼",
        )
        collapsible.add_class("tool-collapsible")
        collapsible.collapsed = True
        self._chat_log().mount(collapsible)
        self._scroll_bottom()

    def _add_tool_result(self, tool_name: str, content: str, duration: float) -> None:
        dur = f" ({duration:.1f}s)" if duration > 0 else ""
        emoji = TOOL_EMOJI.get(tool_name, "📋")
        preview = content[:500] + ("..." if len(content) > 500 else "")
        body = Static(preview)
        collapsible = Collapsible(
            body,
            title=f"{emoji} {tool_name} 结果{dur}",
            collapsed_symbol="▶",
            expanded_symbol="▼",
        )
        collapsible.add_class("tool-collapsible")
        collapsible.collapsed = True
        self._chat_log().mount(collapsible)
        self._scroll_bottom()

    def _add_human(self, name: str, text: str) -> None:
        card = Vertical(classes="human-card")
        header = Static(f"👤 {name}", id="card-header")
        body = RichLog(max_lines=MAX_BODY_HEIGHT, wrap=True)
        body.write(text)
        card.mount(header)
        card.mount(body)
        self._chat_log().mount(card)
        self._scroll_bottom()
