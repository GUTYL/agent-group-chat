"""LLM 抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    """LLM 响应"""

    content: str  # 回复文本
    model: str = ""  # 使用的模型
    prompt_tokens: int = 0  # 输入token数
    completion_tokens: int = 0  # 输出token数
    finish_reason: str = ""  # 结束原因
    metadata: dict = field(default_factory=dict)  # 扩展字段
    tool_calls: list[dict] | None = None  # OpenAI格式 tool_calls（None=没调用工具）
    reasoning_content: str = ""  # DeepSeek等thinking模型的推理内容

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def has_tool_calls(self) -> bool:
        """是否请求了工具调用"""
        return bool(self.tool_calls)


class LLMBase(ABC):
    """LLM 调用抽象基类"""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """发送聊天请求，返回响应

        Args:
            messages: OpenAI格式消息列表
            model: 模型名（None=用默认）
            temperature: 温度
            max_tokens: 最大输出token
            tools: OpenAI function calling schema 列表
            on_chunk: 流式输出回调，接收增量文本
            on_reasoning_chunk: 推理过程流式回调（用于thinking模型）
        """
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """估算token数量"""
        ...
