"""终端输出 — 简洁的群聊过程显示

流式显示: Live + Panel 边框全程可见，内容逐字增长。
整个 agent 回合只维持一个 Live 实例，tool call 期间只更新内容不停止 Live。
"""

from __future__ import annotations

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
        self._tool_status = ""
        self._spinner = None
        self._live: Live | None = None

    def _get_color(self, name: str) -> str:
        if name not in self._agent_colors:
            self._agent_colors[name] = AGENT_COLORS[self._color_idx % len(AGENT_COLORS)]
            self._color_idx += 1
        return self._agent_colors[name]

    def _header(self, name: str, role: str, model: str, color: str) -> str:
        model_str = f" [dim]({model})[/dim]" if model else ""
        return f"[bold {color}]{name}[/bold {color}] [dim]{role}[/dim]{model_str}"

    def _spin(self, text: str) -> None:
        self._stop_spin()
        self._spinner = self.console.status(text, spinner="bouncingBar")
        self._spinner.start()

    def _stop_spin(self) -> None:
        if self._spinner:
            self._spinner.stop()
            self._spinner = None

    # ── Streaming ──────────────────────────────────────────

    def _build_panel(self) -> Panel:
        """Build the Panel renderable with current stream content. 边框全程可见。"""
        color = self._get_color(self._stream_name)
        meta = self._agent_meta.get(self._stream_name, {})
        title = self._header(self._stream_name, meta.get("role", ""), meta.get("model", ""), color)

        content = self._stream_buf if self._stream_buf else "[dim]⏳ 思考中...[/dim]"
        if self._tool_status:
            content += f"\n\n[dim]🔧 {self._tool_status}[/dim]"

        return Panel(
            content,
            title=title,
            title_align="left",
            border_style=color,
            padding=(0, 1),
        )

    def _update_stream(self) -> None:
        if self._live is not None:
            self._live.update(self._build_panel())

    def _stop_live(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    def begin_stream(self, agent_name: str, agent_role: str, agent_model: str = "") -> None:
        self._stop_spin()
        self._stop_live()
        self._streaming = True
        self._stream_name = agent_name
        self._stream_buf = ""
        self._tool_status = ""
        self._agent_meta[agent_name] = {"role": agent_role, "model": agent_model}
        self._live = Live(
            self._build_panel(),
            console=self.console,
            refresh_per_second=10,
            transient=False,
        )
        self._live.start()

    def on_chunk(self, text: str) -> None:
        if not self._streaming:
            return
        self._stream_buf += text
        self._update_stream()

    # ── Message dispatch ───────────────────────────────────

    def on_message(self, message: Message) -> None:
        if message.msg_type == MessageType.tool_call:
            tc_names = [tc.get("function", {}).get("name", "?") for tc in message.tool_calls]
            self._tool_status = f"执行工具: {', '.join(tc_names)}"
            if self._live is not None:
                self._update_stream()
            else:
                self._spin(f"  🔧 执行工具: {', '.join(tc_names)}")
            return

        if message.msg_type == MessageType.tool_result:
            if self._live is not None:
                if not message.metadata.get("tool_success", True):
                    self._tool_status = f"❌ 错误: {message.content[:200]}"
                else:
                    self._tool_status = ""
                self._update_stream()
            else:
                self._stop_spin()
                if not message.metadata.get("tool_success", True):
                    self.console.print(f"  [red]{message.content[:300]}[/red]")
            return

        self._stop_spin()
        if self._streaming and self._stream_name == message.sender:
            self._streaming = False
            self._stop_live()
            # Panel 边框已由最后一次 Live.update 渲染并保留 (transient=False)
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
        stats = (
            f"轮数: {result.rounds} | "
            f"消息数: {len(result.messages)} | "
            f"总token: {result.total_tokens:,}"
        )
        self.console.print(f"[dim]{stats}[/dim]")

    # ── Message renderers ──────────────────────────────────

    def _print_chat(self, msg: Message) -> None:
        self._stop_live()
        self._stop_spin()

        color = self._get_color(msg.sender)
        meta = self._agent_meta.get(msg.sender, {})
        title = self._header(msg.sender, meta.get("role", ""), meta.get("model", ""), color)

        self.console.print()
        self.console.print(
            Panel(
                msg.content,
                title=title,
                title_align="left",
                border_style=color,
                padding=(0, 1),
            )
        )

    def _print_system(self, msg: Message) -> None:
        self.console.print()
        self.console.print(f"[system]── {msg.content} ──[/system]")

    def _print_human_input(self, msg: Message) -> None:
        color = self._get_color(msg.sender)
        title = f"[bold {color}]{msg.sender}[/bold {color}] [dim]用户[/dim]"
        self.console.print()
        self.console.print(
            Panel(
                msg.content,
                title=title,
                title_align="left",
                border_style=color,
                padding=(0, 1),
            )
        )
