"""上下文管理 — 控制发给LLM的对话长度，防token爆炸"""

from __future__ import annotations

import logging
from typing import Any

from agc.core.agent import AgentConfig
from agc.core.message import Message, MessageType
from agc.llm.base import LLMBase

logger = logging.getLogger(__name__)

VISIBLE_MESSAGE_TYPES = (
    MessageType.chat,
    MessageType.mention,
    MessageType.system,
    MessageType.summary,
    MessageType.tool_call,
    MessageType.tool_result,
    MessageType.human_input,
)

SUMMARY_MAX_MSG_CHARS = 500
SUMMARY_COMPRESSION_TOKENS = 500
SUMMARY_TEMPERATURE = 0.3
FALLBACK_MSG_TRUNCATION = 100


class ContextManager:
    """构建每个Agent看到的上下文，处理溢出时摘要压缩"""

    def __init__(self, llm: LLMBase, max_tokens: int = 8000, recent_window: int = 6):
        self.llm = llm
        self.max_tokens = max_tokens
        self.recent_window = recent_window
        self._summary_cache: dict[str, str] = {}

    def build_messages(
        self,
        agent: AgentConfig,
        topic: str,
        history: list[Message],
        all_agents: list[AgentConfig],
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": system_prompt or agent.build_system_prompt(topic, all_agents),
            },
        ]

        selected = self._select_history(history)
        if selected["summary"]:
            messages.append(
                {"role": "system", "content": f"[之前的讨论摘要]\n{selected['summary']}"}
            )
        for msg in selected["recent"]:
            messages.append(msg.to_openai_msg())

        messages.append(
            {
                "role": "user",
                "content": f"（轮到 @{agent.name}）请基于你的角色视角参与讨论。如果有想@的人请用 @名字 格式。",
            }
        )
        return messages

    def build_freechat_context(
        self,
        agent: AgentConfig,
        history: list[Message],
        all_agents: list[AgentConfig],
        system_prompt: str,
        current_topic: str | None = None,
        recent_window: int = 30,
    ) -> list[dict[str, Any]]:
        """构建FreeChat模式的上下文（滑动窗口，无需总结压缩）"""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        if current_topic:
            messages.append(
                {
                    "role": "system",
                    "content": f"[当前话题: {current_topic}]",
                }
            )

        filtered = [m for m in history if m.msg_type in VISIBLE_MESSAGE_TYPES]
        start = max(0, len(filtered) - recent_window)
        start = self._adjust_for_tool_pairs(filtered, start)
        recent = filtered[start:]

        for msg in recent:
            messages.append(msg.to_openai_msg())

        messages.append(
            {
                "role": "user",
                "content": f"（@{agent.name} 该你了）有人发了一条消息，根据需要简洁回应。如果跟你无关可以不用回复。@名字 来指定对话对象。",
            }
        )
        return messages

    def _select_history(self, history: list[Message]) -> dict[str, Any]:
        filtered = [m for m in history if m.msg_type in VISIBLE_MESSAGE_TYPES]

        if len(filtered) <= self.recent_window:
            return {"recent": filtered, "summary": None}

        total_text = "\n".join(m.content for m in filtered)
        if self.llm.count_tokens(total_text) <= self.max_tokens:
            return {"recent": filtered, "summary": None}

        # 截取最近的窗口，但保证不切断 tool_call / tool_result 配对
        start = len(filtered) - self.recent_window
        start = self._adjust_for_tool_pairs(filtered, start)

        recent = filtered[start:]
        older = filtered[:start]

        cache_key = f"{older[0].id}-{older[-1].id}" if older else ""
        summary = self._summary_cache.get(cache_key) if cache_key else ""
        if older and not summary:
            summary = self._summarize(older)
            if cache_key:
                self._summary_cache[cache_key] = summary

        return {"recent": recent, "summary": summary}

    @staticmethod
    def _adjust_for_tool_pairs(filtered: list[Message], start: int) -> int:
        """向前扩展 start 以包含孤立的 tool_result 前面的 tool_call"""
        first = filtered[start]
        if first.msg_type == MessageType.tool_result:
            for i in range(start - 1, -1, -1):
                if filtered[i].msg_type == MessageType.tool_call:
                    return i
            return max(start - 1, 0)
        return start

    def _summarize(self, messages: list[Message]) -> str:
        conversation = "\n".join(
            f"[{m.sender}]: {m.content[:SUMMARY_MAX_MSG_CHARS]}" for m in messages
        )
        prompt = f"请将以下群聊讨论压缩为简洁的摘要，保留关键论点、结论和未解决的问题：\n\n{conversation}\n\n摘要："

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=SUMMARY_TEMPERATURE,
                max_tokens=SUMMARY_COMPRESSION_TOKENS,
            )
            logger.info(
                f"上下文压缩: {len(messages)}条消息 -> {response.completion_tokens} tokens摘要"
            )
            return response.content
        except Exception as e:
            logger.warning(f"摘要生成失败: {e}, 回退到简单拼接")
            return "\n".join(
                f"[{m.sender}]: {m.content[:FALLBACK_MSG_TRUNCATION]}..." for m in messages
            )
