"""OpenAI SDK 调用客户端"""

from __future__ import annotations

import os

import tiktoken
from openai import OpenAI

from .base import LLMBase, LLMResponse


class OpenAIClient(LLMBase):
    """基于 OpenAI SDK 的 LLM 客户端，支持 tool calling"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "gpt-4o",
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.default_model = default_model

        client_kwargs: dict = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = OpenAI(**client_kwargs)

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """调用 OpenAI Chat Completion API

        Args:
            messages: 消息列表
            model: 模型名
            temperature: 温度
            max_tokens: 最大输出token
            tools: OpenAI function calling schema 列表
        """
        use_model = model or self.default_model

        kwargs: dict = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        usage = response.usage

        # 提取 tool_calls（如有）
        tool_calls = None
        message = choice.message
        if hasattr(message, "tool_calls") and message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]

        return LLMResponse(
            content=message.content or "",
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            finish_reason=choice.finish_reason or "",
            tool_calls=tool_calls,
        )

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """用 tiktoken 估算 token 数"""
        use_model = model or self.default_model
        try:
            encoding = tiktoken.encoding_for_model(use_model)
        except KeyError:
            # 模型不在映射中，用 cl100k 近似
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))