"""终端输出 — 简洁的群聊过程显示"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.theme import Theme

from agc.core.message import Message, MessageType
from agc.core.human_in_loop import HumanMode
from agc.ui.base import DisplayBase

AGENT_COLORS = [
    "cyan", "green", "yellow", "magenta", "blue",
    "red", "bright_cyan", "bright_green", "bright_yellow", "bright_magenta",
]

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
        self._stream_name = ""
        self._stream_buf = ""
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

    def begin_stream(self, agent_name: str, agent_role: str, agent_model: str = "") -> None:
        self._streaming = True
        self._stream_name = agent_name
        self._stream_buf = ""
        color = self._get_color(agent_name)
        self._agent_meta[agent_name] = {"role": agent_role, "model": agent_model}
        title = self._header(agent_name, agent_role, agent_model, color)
        self.console.print()
        self._live = Live(
            Panel("", title=title, title_align="left", border_style=color, padding=(0, 1)),
            console=self.console, refresh_per_second=10, transient=False,
        )
        self._live.start()

    def on_chunk(self, text: str) -> None:
        if not self._streaming:
            return
        if self._live is None:
            self._restart_live()
        self._stream_buf += text
        self._update_live()

    def _restart_live(self) -> None:
        color = self._get_color(self._stream_name)
        meta = self._agent_meta.get(self._stream_name, {})
        title = self._header(self._stream_name, meta.get("role", ""), meta.get("model", ""), color)
        self._live = Live(
            Panel(self._stream_buf, title=title, title_align="left", border_style=color, padding=(0, 1)),
            console=self.console, refresh_per_second=10, transient=False,
        )
        self._live.start()

    def _update_live(self) -> None:
        if self._live is None:
            return
        color = self._get_color(self._stream_name)
        meta = self._agent_meta.get(self._stream_name, {})
        title = self._header(self._stream_name, meta.get("role", ""), meta.get("model", ""), color)
        self._live.update(Panel(
            self._stream_buf, title=title, title_align="left",
            border_style=color, padding=(0, 1),
        ))

    def _stop_live(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    # ── Message dispatch ───────────────────────────────────

    def on_message(self, message: Message) -> None:
        if message.msg_type == MessageType.tool_call:
            tc_names = [tc.get("function", {}).get("name", "?") for tc in message.tool_calls]
            self._stop_live()
            self._spin(f"  执行工具: {', '.join(tc_names)}")
            return

        if message.msg_type == MessageType.tool_result:
            if message.metadata.get("tool_success", True):
                return
            self._stop_spin()
            self.console.print(f"  [red]{message.content[:300]}[/red]")
            return

        self._stop_spin()
        if self._streaming and self._stream_name == message.sender:
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

    # ── FreeChat display ───────────────────────────────────

    def print_freechat_header(self, user_name: str, agents: list[Any]) -> None:
        agent_lines = []
        for a in agents:
            color = self._get_color(a.name)
            self._agent_meta[a.name] = {"role": a.role, "model": getattr(a, "model", "")}
            model = getattr(a, "model", "")
            model_str = f" [dim]({model})[/dim]" if model else ""
            agent_lines.append(
                f"  [{color}]@{a.name}[/{color}] [dim]· {a.role}{model_str}[/dim]"
            )
        agents_text = "\n".join(agent_lines)
        self.console.print(Panel(
            f"群聊已开始！输入消息参与讨论。\n\n[bold]参与者:[/bold]\n{agents_text}\n\n[dim]/help 查看命令 | /quit 退出[/dim]",
            title="自由群聊",
            border_style="bright_blue",
        ))
        self.console.print()

    def print_freechat_input(self, sender: str, content: str) -> None:
        color = self._get_color(sender)
        title = f"[bold {color}]{sender}[/bold {color}] [dim]用户[/dim]"
        self.console.print(Panel(
            content, title=title, title_align="left",
            border_style=color, padding=(0, 1),
        ))

    def print_topic_change(self, topic: str) -> None:
        self.console.print()
        self.console.print(f"[system]── 话题已切换为: {topic} ──[/system]")

    # ── Message renderers ──────────────────────────────────

    def _print_chat(self, msg: Message) -> None:
        self._stop_live()
        self._stop_spin()
        if self._streaming and self._stream_name == msg.sender:
            self._streaming = False

        color = self._get_color(msg.sender)
        meta = self._agent_meta.get(msg.sender, {})
        title = self._header(msg.sender, meta.get("role", ""), meta.get("model", ""), color)

        self.console.print()
        self.console.print(Panel(
            msg.content, title=title, title_align="left",
            border_style=color, padding=(0, 1),
        ))

    def _print_system(self, msg: Message) -> None:
        self.console.print()
        self.console.print(f"[system]── {msg.content} ──[/system]")

    def _print_human_input(self, msg: Message) -> None:
        color = self._get_color(msg.sender)
        title = f"[bold {color}]{msg.sender}[/bold {color}] [dim]用户[/dim]"
        self.console.print()
        self.console.print(Panel(
            msg.content, title=title, title_align="left",
            border_style=color, padding=(0, 1),
        ))
