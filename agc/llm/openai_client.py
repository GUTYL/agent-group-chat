"""OpenAI SDK 调用客户端"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

import tiktoken
from openai import OpenAI

from .base import LLMBase, LLMResponse

logger = logging.getLogger(__name__)

FALLBACK_ENCODING = "cl100k_base"


class OpenAIClient(LLMBase):
    """基于 OpenAI SDK 的 LLM 客户端，支持 tool calling 和流式输出"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "gpt-4o",
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("API key 未设置。请提供 api_key 参数或设置 OPENAI_API_KEY 环境变量。")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.default_model = default_model

        client_kwargs: dict[str, str] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = OpenAI(**client_kwargs)

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        on_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(messages, model, temperature, max_tokens, tools)
        if on_chunk is not None:
            return self._streamed_chat(kwargs, on_chunk, on_reasoning_chunk)
        return self._normal_chat(kwargs)

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
        return kwargs

    def _normal_chat(self, kwargs: dict[str, Any]) -> LLMResponse:
        model = kwargs.get("model", "?")
        msg_count = len(kwargs.get("messages", []))
        tool_count = len(kwargs.get("tools", []))
        logger.info("API请求 model=%s msgs=%d tools=%d stream=False", model, msg_count, tool_count)
        try:
            t_start = time.monotonic()
            response = self.client.chat.completions.create(**kwargs)
            elapsed = time.monotonic() - t_start
        except Exception:
            logger.exception("API请求失败 model=%s", model)
            raise

        choice = response.choices[0]
        usage = response.usage
        message = choice.message

        result = LLMResponse(
            content=message.content or "",
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            finish_reason=choice.finish_reason or "",
            tool_calls=self._extract_tool_calls(message),
            reasoning_content=getattr(message, "reasoning_content", "") or "",
        )
        logger.info(
            "API响应 model=%s prompt_tokens=%d completion_tokens=%d finish=%s elapsed=%.2fs",
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
            result.finish_reason,
            elapsed,
        )
        return result

    def _streamed_chat(
        self,
        kwargs: dict[str, Any],
        on_chunk: Callable[[str], None],
        on_reasoning_chunk: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        model = kwargs.get("model", "?")
        msg_count = len(kwargs.get("messages", []))
        tool_count = len(kwargs.get("tools", []))
        logger.info("API请求 model=%s msgs=%d tools=%d stream=True", model, msg_count, tool_count)

        kwargs["stream"] = True
        t_start = time.monotonic()
        try:
            stream = self.client.chat.completions.create(**kwargs)
        except Exception:
            logger.exception("API流式请求失败 model=%s", model)
            raise

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_by_idx: dict[int, dict[str, Any]] = {}
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

            rc = getattr(delta, "reasoning_content", None)
            if rc:
                reasoning_parts.append(rc)
                if on_reasoning_chunk:
                    on_reasoning_chunk(rc)

            text = getattr(delta, "content", None)
            if text:
                content_parts.append(text)
                on_chunk(text)

            if getattr(delta, "tool_calls", None):
                self._accumulate_tool_calls(delta.tool_calls, tool_calls_by_idx)

        elapsed = time.monotonic() - t_start
        tc_list = (
            [tool_calls_by_idx[k] for k in sorted(tool_calls_by_idx)] if tool_calls_by_idx else None
        )

        result = LLMResponse(
            content="".join(content_parts),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
            tool_calls=tc_list,
            reasoning_content="".join(reasoning_parts),
        )
        logger.info(
            "API响应 model=%s prompt_tokens=%d completion_tokens=%d finish=%s elapsed=%.2fs",
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
            result.finish_reason,
            elapsed,
        )
        return result

    # ── Tool call helpers ──────────────────────────────────

    @staticmethod
    def _extract_tool_calls(message: Any) -> list[dict[str, Any]] | None:
        tcs = getattr(message, "tool_calls", None)
        if not tcs:
            return None
        return [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in tcs
        ]

    @staticmethod
    def _accumulate_tool_calls(delta_tcs: list[Any], acc: dict[int, dict[str, Any]]) -> None:
        for tc in delta_tcs:
            idx = tc.index
            if idx not in acc:
                acc[idx] = {
                    "id": tc.id or "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                }
            if tc.id:
                acc[idx]["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    acc[idx]["function"]["name"] += tc.function.name
                if tc.function.arguments:
                    acc[idx]["function"]["arguments"] += tc.function.arguments

    # ── Token counting ─────────────────────────────────────

    def count_tokens(self, text: str, model: str | None = None) -> int:
        use_model = model or self.default_model
        try:
            encoding = tiktoken.encoding_for_model(use_model)
        except KeyError:
            encoding = tiktoken.get_encoding(FALLBACK_ENCODING)
        return len(encoding.encode(text))
