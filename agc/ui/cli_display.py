"""终端输出 — 彩色格式化显示群聊过程"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from agc.core.message import Message, MessageType
from agc.core.human_in_loop import HumanMode

# 角色颜色映射（给每个agent分配不同颜色）
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

# 自定义主题
AGC_THEME = Theme({
    "system": "dim italic",
    "chat": "white",
    "mention": "bold yellow",
    "summary": "bold green",
    "human": "bold white on blue",
})


class CliDisplay:
    """终端彩色输出"""

    def __init__(self):
        self.console = Console(theme=AGC_THEME)
        self._agent_color_map: dict[str, str] = {}
        self._color_idx = 0

    def _get_agent_color(self, name: str) -> str:
        if name not in self._agent_color_map:
            self._agent_color_map[name] = AGENT_COLORS[
                self._color_idx % len(AGENT_COLORS)
            ]
            self._color_idx += 1
        return self._agent_color_map[name]

    def on_message(self, message: Message) -> None:
        """回调：实时打印新消息"""
        if message.msg_type == MessageType.system:
            self._print_system(message)
        elif message.msg_type == MessageType.summary:
            self._print_summary(message)
        elif message.msg_type == MessageType.mention:
            self._print_mention(message)
        elif message.msg_type == MessageType.tool_call:
            self._print_tool_call(message)
        elif message.msg_type == MessageType.tool_result:
            self._print_tool_result(message)
        elif message.msg_type == MessageType.human_input:
            self._print_human_input(message)
        else:
            self._print_chat(message)

    def print_header(self, topic: str, agents: list, human_loop=None) -> None:
        """打印群聊开始信息"""
        agent_lines = []
        for a in agents:
            color = self._get_agent_color(a.name)
            agent_lines.append(f"  [{color}]@{a.name}[/{color}] ({a.role}) — {a.goal}")

        if human_loop and human_loop.mode != HumanMode.off:
            agent_lines.append(f"  [bold white on blue]@{human_loop.name}[/bold white on blue] (人类) — 参与者")

        agents_text = "\n".join(agent_lines)
        panel = Panel(
            f"[bold]话题:[/bold] {topic}\n\n[bold]参与者:[/bold]\n{agents_text}",
            title="🏠 群聊开始",
            border_style="bright_blue",
        )
        self.console.print(panel)
        self.console.print()

    def print_result(self, result) -> None:
        """打印群聊最终结果"""
        panel = Panel(
            f"{result.summary}",
            title="📋 群聊总结",
            border_style="green",
        )
        self.console.print(panel)

        stats = (
            f"轮数: {result.rounds} | "
            f"消息数: {len(result.messages)} | "
            f"总token: {result.total_tokens:,}"
        )
        self.console.print(f"[dim]{stats}[/dim]")

    def _print_chat(self, msg: Message) -> None:
        color = self._get_agent_color(msg.sender)
        prefix = f"[bold {color}]{msg.sender}[/bold {color}]"
        self.console.print(f"{prefix}: {msg.content}")
        self.console.print()

    def _print_mention(self, msg: Message) -> None:
        color = self._get_agent_color(msg.sender)
        mentions_str = " ".join(f"[bold yellow]@{m}[/bold yellow]" for m in msg.mentions)
        prefix = f"[bold {color}]{msg.sender}[/bold {color}] → {mentions_str}"
        self.console.print(f"{prefix}")
        self.console.print(f"  {msg.content}")
        self.console.print()

    def _print_system(self, msg: Message) -> None:
        self.console.print(f"[system]--- {msg.content} ---[/system]")
        self.console.print()

    def _print_summary(self, msg: Message) -> None:
        self.console.print(f"[summary]📊 {msg.sender} 总结: {msg.content}[/summary]")
        self.console.print()

    def _print_tool_call(self, msg: Message) -> None:
        """打印工具调用消息"""
        calls_desc = []
        for tc in msg.tool_calls:
            func_name = tc.get("function", {}).get("name", "?")
            try:
                import json
                args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            except Exception:
                args_str = "..."
            calls_desc.append(f"{func_name}({args_str})")
        color = self._get_agent_color(msg.sender) if msg.sender != "system" else "dim"
        self.console.print(f"  [{color}]{msg.sender}[/{color}] 🔍 调用: {', '.join(calls_desc)}")

    def _print_tool_result(self, msg: Message) -> None:
        """打印工具执行结果（截断显示）"""
        preview = msg.content[:200]
        if len(msg.content) > 200:
            preview += "..."
        self.console.print(f"  [dim]📄 搜索结果: {preview}[/dim]")
        self.console.print()

    def _print_human_input(self, msg: Message) -> None:
        """打印人类输入消息"""
        self.console.print()
        self.console.print(f"[human]👤 {msg.sender}: {msg.content}[/human]")
        self.console.print()