"""OpenAI SDK 调用客户端"""

from __future__ import annotations

import os
from typing import Callable

import tiktoken
from openai import OpenAI

from .base import LLMBase, LLMResponse


class OpenAIClient(LLMBase):
    """基于 OpenAI SDK 的 LLM 客户端，支持 tool calling 和流式输出"""

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
        on_chunk: Callable[[str], None] | None = None,
    ) -> LLMResponse:
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

        if on_chunk is not None:
            return self._streamed_chat(kwargs, on_chunk)

        response = self.client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        usage = response.usage

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

        reasoning_content = getattr(message, "reasoning_content", "")

        return LLMResponse(
            content=message.content or "",
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            finish_reason=choice.finish_reason or "",
            tool_calls=tool_calls,
            reasoning_content=reasoning_content or "",
        )

    def _streamed_chat(self, kwargs: dict, on_chunk: Callable[[str], None]) -> LLMResponse:
        kwargs["stream"] = True
        stream = self.client.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict] = {}
        model = ""
        finish_reason = ""
        prompt_tokens = 0
        completion_tokens = 0

        for chunk in stream:
            if chunk.usage:
                prompt_tokens = chunk.usage.prompt_tokens or 0
                completion_tokens = chunk.usage.completion_tokens or 0

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason or finish_reason
            model = model or getattr(chunk, "model", "")

            # 推理内容
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                reasoning_parts.append(rc)

            # 文本内容
            content = getattr(delta, "content", None)
            if content:
                content_parts.append(content)
                on_chunk(content)

            # 工具调用
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {
                            "id": tc.id or "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc.id:
                        tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls[idx]["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls[idx]["function"]["arguments"] += tc.function.arguments

        tc_list = [tool_calls[k] for k in sorted(tool_calls.keys())] if tool_calls else None

        return LLMResponse(
            content="".join(content_parts),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
            tool_calls=tc_list,
            reasoning_content="".join(reasoning_parts),
        )

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """用 tiktoken 估算 token 数"""
        use_model = model or self.default_model
        try:
            encoding = tiktoken.encoding_for_model(use_model)
        except KeyError:
            encoding = tiktoken.get_encoding("clk100k_base")
        return len(encoding.encode(text))