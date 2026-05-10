"""终端输出 — 参考 Hermes Agent 风格，彩色显示群聊过程"""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme

from agc.core.message import Message, MessageType
from agc.core.human_in_loop import HumanMode
from agc.ui.base import DisplayBase

AGENT_COLORS = [
    "cyan", "green", "yellow", "magenta", "blue",
    "red", "bright_cyan", "bright_green", "bright_yellow", "bright_magenta",
]

MAX_TOOL_RESULT_DISPLAY = 250
MAX_TOOL_PREVIEW_LEN = 50
MAX_PATH_DISPLAY = 40

AGC_THEME = Theme({
    "system": "dim italic",
    "summary": "bold green",
    "human": "bold white on blue",
})


class CliDisplay(DisplayBase):
    """终端彩色输出"""

    def __init__(self) -> None:
        self.console = Console(theme=AGC_THEME)
        self._agent_colors: dict[str, str] = {}
        self._agent_meta: dict[str, dict[str, str]] = {}
        self._color_idx = 0
        self._streaming = False
        self._stream_color = ""
        self._stream_name = ""
        self._chunk_started = False
        self._tool_start: float = 0

    def _get_color(self, name: str) -> str:
        if name not in self._agent_colors:
            self._agent_colors[name] = AGENT_COLORS[self._color_idx % len(AGENT_COLORS)]
            self._color_idx += 1
        return self._agent_colors[name]

    def _bar(self, color: str) -> str:
        return f"[dim {color}]┊[/dim {color}] "

    def _header(self, name: str, role: str, model: str, color: str) -> str:
        model_str = f" [dim]({model})[/dim]" if model else ""
        return f"[bold {color}]{name}[/bold {color}] [dim]{role}[/dim]{model_str}"

    def _format_mentions(self, mentions: list[str]) -> str:
        return " ".join(f"[bold yellow]@{m}[/bold yellow]" for m in mentions)

    def _in_stream(self, sender: str = "") -> bool:
        return bool(self._stream_color and (not sender or self._stream_name == sender))

    # ── Streaming ──────────────────────────────────────────

    def begin_stream(self, agent_name: str, agent_role: str, agent_model: str = "") -> None:
        self._close_stream()
        color = self._get_color(agent_name)
        self._agent_meta[agent_name] = {"role": agent_role, "model": agent_model}
        self._stream_color = color
        self._stream_name = agent_name
        self._streaming = True
        self._chunk_started = False
        self.console.print()
        self.console.print(self._header(agent_name, agent_role, agent_model, color))

    def on_chunk(self, text: str) -> None:
        if self._streaming and not self._chunk_started:
            self.console.print(f"{self._bar(self._stream_color)} ", end="")
            self._chunk_started = True
        if self._streaming:
            self.console.print(text, end="", highlight=False)

    def _close_stream(self) -> None:
        if self._chunk_started:
            self.console.print()
        self._streaming = False
        self._stream_color = ""
        self._stream_name = ""
        self._chunk_started = False

    # ── Message dispatch ───────────────────────────────────

    _HANDLERS: dict[MessageType, str] = {}

    def on_message(self, message: Message) -> None:
        handlers = {
            MessageType.system: self._print_system,
            MessageType.tool_call: self._print_tool_call,
            MessageType.tool_result: self._print_tool_result,
            MessageType.human_input: self._print_human_input,
        }
        handler = handlers.get(message.msg_type, self._print_chat_mention)
        handler(message)

    # ── Header / Result ────────────────────────────────────

    def print_header(self, topic: str, agents: list[Any], human_loop: Any = None) -> None:
        agent_lines = []
        for a in agents:
            color = self._get_color(a.name)
            model = getattr(a, "model", "")
            self._agent_meta[a.name] = {"role": a.role, "model": model}
            model_str = f" [dim]({model})[/dim]" if model else ""
            agent_lines.append(
                f"  [{color}]@{a.name}[/{color}] [dim]· {a.role}{model_str}[/dim]"
            )

        if human_loop and human_loop.mode != HumanMode.off:
            agent_lines.append(
                f"  [bold white on blue]@{human_loop.name}[/bold white on blue] (人类) — 参与者"
            )

        agents_text = "\n".join(agent_lines)
        self.console.print(Panel(
            f"[bold]话题:[/bold] {topic}\n\n[bold]参与者:[/bold]\n{agents_text}",
            title="群聊开始", border_style="bright_blue",
        ))
        self.console.print()

    def print_result(self, result: Any) -> None:
        if result.summary:
            self.console.print(Panel(result.summary, title="群聊总结", border_style="green"))
        stats = (
            f"轮数: {result.rounds} | "
            f"消息数: {len(result.messages)} | "
            f"总token: {result.total_tokens:,}"
        )
        self.console.print(f"[dim]{stats}[/dim]")

    # ── Message renderers ──────────────────────────────────

    def _print_chat_mention(self, msg: Message) -> None:
        color = self._get_color(msg.sender)

        if self._streaming and self._stream_name == msg.sender:
            self._close_stream()
            if msg.mentions:
                self.console.print(f"  [dim]→ {self._format_mentions(msg.mentions)}[/dim]")
            return

        meta = self._agent_meta.get(msg.sender, {})
        title = self._header(msg.sender, meta.get("role", ""), meta.get("model", ""), color)
        if msg.mentions:
            title += f"  [dim]→ {self._format_mentions(msg.mentions)}[/dim]"

        self.console.print()
        self.console.print(Panel(msg.content, title=title, title_align="left", border_style=color, padding=(0, 1)))

    def _print_system(self, msg: Message) -> None:
        self.console.print()
        self.console.print(f"[system]── {msg.content} ──[/system]")

    def _print_tool_call(self, msg: Message) -> None:
        self._tool_start = time.time()
        bar = self._bar(self._stream_color) if self._in_stream(msg.sender) else "  "
        for tc in msg.tool_calls:
            func_name = tc.get("function", {}).get("name", "?")
            try:
                import json
                args = json.loads(tc.get("function", {}).get("arguments", "{}"))
            except Exception:
                args = {}
            self.console.print(f"{bar}[dim]{self._tool_preview(func_name, args)}[/dim]")

    def _print_tool_result(self, msg: Message) -> None:
        dur = time.time() - self._tool_start if self._tool_start else 0
        bar = self._bar(self._stream_color) if self._in_stream() else "  "
        preview = msg.content[:MAX_TOOL_RESULT_DISPLAY]
        if len(msg.content) > MAX_TOOL_RESULT_DISPLAY:
            preview += "..."
        dur_str = f" {dur:.1f}s" if dur > 0 else ""
        self.console.print(f"{bar}[dim]  {preview}  {dur_str}[/dim]")

    def _print_human_input(self, msg: Message) -> None:
        self.console.print()
        self.console.print(Panel(
            msg.content, title=f"[bold]👤 {msg.sender}[/bold]",
            title_align="left", border_style="bright_white",
        ))

    # ── Tool preview ───────────────────────────────────────

    _TOOL_PREVIEWS: dict[str, str] = {
        "web_search":         "query",
        "web_fetch":          "url",
        "write_file":         "filepath",
        "read_file":          "filepath",
        "list_files":         "path",
        "run_code":           "command",
        "save_memory":        "key",
        "recall_memory":      "query",
        "delete_memory":      "key",
    }

    _TOOL_EMOJI: dict[str, str] = {
        "web_search":       "🔍",
        "web_fetch":        "📄",
        "write_file":       "✍️",
        "read_file":        "📖",
        "list_files":       "📂",
        "run_code":         "🐍",
        "save_memory":      "🧠",
        "recall_memory":    "🔍",
        "list_memories":    "📋",
        "delete_memory":    "🗑️",
    }

    def _tool_preview(self, tool_name: str, args: dict[str, Any]) -> str:
        emoji = self._TOOL_EMOJI.get(tool_name, "⚡")

        if tool_name == "web_fetch":
            url = str(args.get("url", ""))
            domain = url.replace("https://", "").replace("http://", "").split("/")[0]
            return f"{emoji} fetch    {domain[:MAX_PATH_DISPLAY]}"
        if tool_name == "web_search":
            return f"{emoji} search   \"{self._trunc(args.get('query', ''))}\""
        if tool_name == "run_code":
            cmd = str(args.get("command", ""))
            first_line = cmd.strip().split("\n")[0] if cmd.strip() else ""
            return f"{emoji} exec     {self._trunc(first_line)}"
        if tool_name == "list_memories":
            tag = args.get("tag", "")
            return f"{emoji} memories {self._trunc(tag)}" if tag else f"{emoji} memories list"

        key = self._TOOL_PREVIEWS.get(tool_name)
        if key and key in args:
            return f"{emoji} {tool_name:<9} {self._trunc(str(args[key]))}"

        return f"{emoji} {tool_name}  {self._trunc(str(list(args.values())[0]) if args else '')}"

    @staticmethod
    def _trunc(s: Any, n: int = MAX_TOOL_PREVIEW_LEN) -> str:
        s = str(s)
        return (s[:n - 3] + "...") if len(s) > n else s
