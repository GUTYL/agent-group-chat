"""上下文管理 — 控制发给LLM的对话长度，防token爆炸，支持工具消息"""

from __future__ import annotations

import logging

from agc.core.agent import AgentConfig
from agc.core.message import Message, MessageType
from agc.llm.base import LLMBase

logger = logging.getLogger(__name__)


class ContextManager:
    """构建每个Agent看到的上下文，处理溢出时摘要压缩，支持工具消息"""

    def __init__(
        self,
        llm: LLMBase,
        max_tokens: int = 8000,
        recent_window: int = 6,
    ):
        """
        Args:
            llm: 用于生成摘要的LLM
            max_tokens: 上下文token上限（给对话历史留的额度）
            recent_window: 始终保留最近N条消息的完整内容
        """
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
    ) -> list[dict]:
        """构建发给LLM的完整消息列表，包含工具调用上下文"""
        # 1. System prompt（优先使用预构建的）
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}]
        else:
            sp = agent.build_system_prompt(topic, all_agents)
            messages = [{"role": "system", "content": sp}]

        # 2. 选择要包含的对话历史（过滤掉工具中间态消息）
        selected = self._select_history(history)

        # 如果有摘要，先插入摘要
        older = selected.get("summary")
        if older:
            messages.append({
                "role": "system",
                "content": f"[之前的讨论摘要]\n{older}",
            })

        # 完整的最近对话
        for msg in selected.get("recent", history):
            messages.append(msg.to_openai_msg())

        # 4. 提示当前agent发言
        messages.append({
            "role": "user",
            "content": f"[{agent.name}] 现在轮到你发言，请基于你的角色视角 contribute to the discussion。如果有想@的人请用 @名字 格式。",
        })

        return messages

    def _select_history(self, history: list[Message]) -> dict:
        """选择对话历史，必要时生成摘要。过滤掉工具中间态消息（tool_call），只保留最终结果（tool_result）。"""
        # 过滤：只保留对对话有意义的内容
        # tool_call 消息会在 _generate_response 的循环中单独处理，这里只保留 chat/mention/system/summary/tool_result
        filtered = [
            m for m in history
            if m.msg_type in (MessageType.chat, MessageType.mention, MessageType.system, MessageType.summary, MessageType.tool_call, MessageType.tool_result, MessageType.human_input)
        ]

        if len(filtered) <= self.recent_window:
            return {"recent": filtered, "summary": None}

        # 估算总token
        total_text = "\n".join(m.content for m in filtered)
        estimated_tokens = self.llm.count_tokens(total_text)

        if estimated_tokens <= self.max_tokens:
            return {"recent": filtered, "summary": None}

        # 溢出了：最近N条完整 + 更早的做摘要
        recent = filtered[-self.recent_window:]
        older = filtered[:-self.recent_window]

        cache_key = f"{older[0].id}-{older[-1].id}"
        summary = self._summary_cache.get(cache_key)

        if not summary:
            summary = self._summarize(older)
            self._summary_cache[cache_key] = summary

        return {"recent": recent, "summary": summary}

    def _summarize(self, messages: list[Message]) -> str:
        """用LLM压缩历史消息为摘要"""
        conversation = "\n".join(
            f"[{m.sender}]: {m.content[:500]}" for m in messages
        )

        prompt = f"""请将以下群聊讨论压缩为简洁的摘要，保留关键论点、结论和未解决的问题：

{conversation}

摘要："""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )
            logger.info(f"上下文压缩: {len(messages)}条消息 -> {response.completion_tokens} tokens摘要")
            return response.content
        except Exception as e:
            logger.warning(f"摘要生成失败: {e}, 回退到简单拼接")
            return "\n".join(
                f"[{m.sender}]: {m.content[:100]}..." for m in messages
            )