"""人类参与会话 — human_in_loop 支持

两种模式：
1. always: 每轮结束后暂停，等人类输入
2. on_demand: 用户输入 "human" 或按快捷键手动介入

人类输入作为 [human] 消息注入到对话流中，
Agent 可以看到人类的发言并回复。
"""

from __future__ import annotations

import logging
from enum import Enum

from rich.console import Console
from rich.prompt import Prompt

from agc.core.message import Message, MessageType

logger = logging.getLogger(__name__)


class HumanMode(str, Enum):
    """人类介入模式"""
    off = "off"              # 不介入
    always = "always"        # 每轮都暂停等人类输入
    on_demand = "on_demand"  # 人类随时可介入，但默认继续


class HumanInTheLoop:
    """管理人类在群聊中的介入"""

    def __init__(
        self,
        mode: HumanMode = HumanMode.off,
        name: str = "human",
        on_input_callback=None,
    ):
        """
        Args:
            mode: 介入模式 off/always/on_demand
            name: 人类在群聊中的名字
            on_input_callback: 自定义输入回调（用于测试或非标准输入源）
        """
        self.mode = mode
        self.name = name
        self._on_input_callback = on_input_callback
        self._console = Console()

    def should_pause(self, round_idx: int) -> bool:
        """判断当前轮次是否需要暂停等人类输入"""
        if self.mode == HumanMode.off:
            return False
        if self.mode == HumanMode.always:
            return True
        # on_demand: 不主动暂停，人类自行触发
        return False

    def get_input(self, round_idx: int, last_speaker: str = "") -> Message | None:
        """获取人类输入，返回 Message 或 None（跳过）

        Args:
            round_idx: 当前轮次
            last_speaker: 上一个发言的Agent名

        Returns:
            Message(human_input) 或 None（人类选择跳过）
        """
        if self._on_input_callback:
            # 非交互模式：调用回调获取输入
            content = self._on_input_callback(round_idx, last_speaker)
            if content is None:
                return None
            return self._make_message(content, round_idx)

        # 交互模式：终端提示
        return self._prompt_terminal(round_idx, last_speaker)

    def _prompt_terminal(self, round_idx: int, last_speaker: str) -> Message | None:
        """终端交互式输入"""
        self._console.print()
        self._console.print(
            f"[bold yellow]👤 你的回合[/bold yellow] "
            f"(第{round_idx + 1}轮，上一个发言: {last_speaker or '无'})"
        )
        self._console.print("[dim]输入消息参与讨论 | 输入 'skip' 跳过 | 输入 'stop' 结束讨论[/dim]")

        try:
            user_input = Prompt.ask("[bold cyan]你[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            self._console.print("[dim]终止输入，继续讨论...[/dim]")
            return None

        if not user_input or user_input.lower() == "skip":
            self._console.print("[dim]跳过，继续讨论...[/dim]")
            return None

        if user_input.lower() == "stop":
            self._console.print("[bold red]人类要求结束讨论[/bold red]")
            return self._make_message("我要求结束本次讨论，请大家做最终总结。", round_idx, force_stop=True)

        return self._make_message(user_input, round_idx)

    def _make_message(
        self, content: str, round_idx: int, force_stop: bool = False
    ) -> Message:
        """构建人类输入消息"""
        return Message(
            sender=self.name,
            content=content,
            msg_type=MessageType.human_input,
            round_idx=round_idx,
            metadata={"force_stop": force_stop},
        )

    @staticmethod
    def create(mode_str: str, name: str = "human", callback=None) -> "HumanInTheLoop":
        """工厂方法：从字符串创建 HumanInTheLoop"""
        mode_map = {
            "off": HumanMode.off,
            "always": HumanMode.always,
            "on_demand": HumanMode.on_demand,
        }
        mode = mode_map.get(mode_str.lower(), HumanMode.off)
        return HumanInTheLoop(mode=mode, name=name, on_input_callback=callback)