"""终端输出 — 简洁的群聊过程显示

流式显示: Live + Panel 边框全程可见，内容逐字增长。
整个 agent 回合只维持一个 Live 实例，tool call 期间只更新内容不停止 Live。
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.theme import Theme

from agc.core.human_in_loop import HumanMode
from agc.core.message import Message, MessageType
from agc.ui.base import DisplayBase

AGENT_COLORS = [
    "cyan",
    "green",
    "yellow",
    "magenta",
    "blue",
    "red",
    "bright_cyan",
    "bright_green",
    "bright_yellow",
    "bright_magenta",
]

AGC_THEME = Theme(
    {
        "system": "dim italic",
        "summary": "bold green",
        "human": "bold white on blue",
    }
)


class CliDisplay(DisplayBase):
    """终端彩色输出"""

    def __init__(self) -> None:
        self.console = Console(theme=AGC_THEME)
        self._agent_colors: dict[str, str] = {}
        self._agent_meta: dict[str, dict[str, str]] = {}
        self._color_idx = 0
        self._streaming = False
        self._stream_name = ""
        self._stream_buf = ""
        self._reasoning_buf = ""
        self._action_log: list[str] = []
        self._live: Live | None = None

    def _get_color(self, name: str) -> str:
        if name not in self._agent_colors:
            self._agent_colors[name] = AGENT_COLORS[self._color_idx % len(AGENT_COLORS)]
            self._color_idx += 1
        return self._agent_colors[name]

    def _header(self, name: str, role: str, model: str, color: str) -> str:
        model_str = f" [dim]({model})[/dim]" if model else ""
        return f"[bold {color}]{name}[/bold {color}] [dim]{role}[/dim]{model_str}"

    # ── Streaming ──────────────────────────────────────────

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
            display = self._stream_buf
            if display.startswith(": "):
                display = display[2:].strip()
            parts.append(display)

        content = "\n\n".join(parts) if parts else "[dim]⏳ 思考中...[/dim]"
        return Panel(content, title=title, title_align="left", border_style=color, padding=(0, 1))

    def _update_live(self) -> None:
        if self._live is not None:
            self._live.update(self._build_panel())

    def _stop_live(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    def _flush_reasoning(self) -> None:
        if self._reasoning_buf:
            self._action_log.append(f"💭 {self._reasoning_buf}")
            self._reasoning_buf = ""

    def begin_stream(self, agent_name: str, agent_role: str, agent_model: str = "") -> None:
        self._stop_live()
        self._streaming = True
        self._stream_name = agent_name
        self._stream_buf = ""
        self._reasoning_buf = ""
        self._action_log = []
        self._agent_meta[agent_name] = {"role": agent_role, "model": agent_model}
        self._live = Live(
            self._build_panel(), console=self.console, refresh_per_second=10, transient=False
        )
        self._live.start()

    def on_chunk(self, text: str) -> None:
        if not self._streaming:
            return
        self._stream_buf += text
        self._update_live()

    def on_reasoning_chunk(self, text: str) -> None:
        if not self._streaming:
            return
        self._reasoning_buf += text
        self._update_live()

    # ── Message dispatch ───────────────────────────────────

    def on_message(self, message: Message) -> None:
        if message.msg_type == MessageType.tool_call:
            self._reasoning_buf = ""
            for tc in message.tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "?")
                args_str = func.get("arguments", "{}")
                try:
                    args_dict = json.loads(args_str)
                    args_parts = []
                    for k, v in args_dict.items():
                        if isinstance(v, str):
                            args_parts.append(f'{k}="{v}"')
                        else:
                            args_parts.append(f"{k}={v}")
                    args_display = ", ".join(args_parts)
                except (json.JSONDecodeError, Exception):
                    args_display = args_str[:60]
                if len(args_display) > 60:
                    args_display = args_display[:57] + "..."
                self._action_log.append(f"🔧 调用 {name}({args_display})")
            if len(self._action_log) > 20:
                self._action_log = self._action_log[-20:]
            self._update_live()
            return

        if message.msg_type == MessageType.tool_result:
            tool_name = message.metadata.get("tool_name", "工具")
            tool_success = message.metadata.get("tool_success", True)
            if tool_success:
                self._action_log.append(f"✅ {tool_name}")
            else:
                summary = message.content[:80].replace("\n", " ")
                self._action_log.append(f"❌ {tool_name} → {summary}")
            if len(self._action_log) > 20:
                self._action_log = self._action_log[-20:]
            self._update_live()
            return

        if self._streaming and self._stream_name == message.sender:
            self._flush_reasoning()
            self._streaming = False
            self._stop_live()
            return

        handlers = {
            MessageType.system: self._print_system,
            MessageType.human_input: self._print_human_input,
        }
        handler = handlers.get(message.msg_type, self._print_chat)
        handler(message)

    # ── Header / Result ────────────────────────────────────

    def print_header(self, topic: str, agents: list[Any], human_loop: Any = None) -> None:
        agent_lines = []
        for a in agents:
            color = self._get_color(a.name)
            model = getattr(a, "model", "")
            self._agent_meta[a.name] = {"role": a.role, "model": model}
            model_str = f" [dim]({model})[/dim]" if model else ""
            agent_lines.append(f"  [{color}]@{a.name}[/{color}] [dim]· {a.role}{model_str}[/dim]")

        if human_loop and human_loop.mode != HumanMode.off:
            agent_lines.append(
                f"  [bold white on blue]@{human_loop.name}[/bold white on blue] (人类) — 参与者"
            )

        agents_text = "\n".join(agent_lines)
        self.console.print(
            Panel(
                f"[bold]话题:[/bold] {topic}\n\n[bold]参与者:[/bold]\n{agents_text}",
                title="群聊开始",
                border_style="bright_blue",
            )
        )
        self.console.print()

    def print_result(self, result: Any) -> None:
        if result.summary:
            self.console.print(Panel(result.summary, title="群聊总结", border_style="green"))
        stats = f"轮数: {result.rounds} | 消息数: {len(result.messages)} | 总token: {result.total_tokens:,}"
        self.console.print(f"[dim]{stats}[/dim]")

    # ── Message renderers ──────────────────────────────────

    def _render_panel(self, sender: str, content: str) -> None:
        """渲染带边框的消息 Panel"""
        color = self._get_color(sender)
        meta = self._agent_meta.get(sender, {})
        title = self._header(sender, meta.get("role", ""), meta.get("model", ""), color)
        self.console.print()
        self.console.print(
            Panel(content, title=title, title_align="left", border_style=color, padding=(0, 1))
        )

    def _print_chat(self, msg: Message) -> None:
        self._stop_live()
        self._render_panel(msg.sender, msg.content)

    def _print_system(self, msg: Message) -> None:
        self.console.print()
        self.console.print(f"[system]── {msg.content} ──[/system]")

    def _print_human_input(self, msg: Message) -> None:
        color = self._get_color(msg.sender)
        title = f"[bold {color}]{msg.sender}[/bold {color}] [dim]用户[/dim]"
        self.console.print()
        self.console.print(
            Panel(msg.content, title=title, title_align="left", border_style=color, padding=(0, 1))
        )
