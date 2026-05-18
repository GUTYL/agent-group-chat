"""TopicSession — 群聊核心运行逻辑"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from agc.core.agent import AgentConfig
from agc.core.human_in_loop import HumanInTheLoop
from agc.core.message import Message, MessageType
from agc.core.session import ChatSession
from agc.terminators.composite import CompositeTerminator
from agc.terminators.consensus import ConsensusTerminator
from agc.terminators.max_rounds import MaxRoundsTerminator

logger = logging.getLogger(__name__)

SUMMARY_TEMPERATURE = 0.3
SUMMARY_MAX_TOKENS = 800
SUMMARY_RECENT_MSGS = 20


class RoomConfig(BaseModel):
    """群聊房间配置 — 仅存活的字段"""

    name: str
    agents: list[AgentConfig]
    scheduler: str = "hybrid"
    max_rounds: int = 20
    context_window: int = 8000
    verbose: bool = True
    base_url: str | None = None
    api_key: str | None = None


@dataclass
class ChatResult:
    topic: str
    messages: list[Message]
    summary: str = ""
    total_tokens: int = 0
    rounds: int = 0
    stop_reason: str = ""


class TopicSession(ChatSession):
    """群聊会话 — 管理多Agent讨论的完整生命周期"""

    def __init__(
        self,
        name: str,
        agents: list[AgentConfig],
        llm=None,
        scheduler: str = "hybrid",
        max_rounds: int = 20,
        context_window: int = 8000,
        verbose: bool = True,
        base_url: str | None = None,
        api_key: str | None = None,
        tools: list[str] | None = None,
        workspace_root: str | None = None,
        human: HumanInTheLoop | None = None,
        stream: bool = True,
        use_llm_route: bool = True,
    ):
        from agc.llm.base import LLMBase

        super().__init__(
            agents=agents,
            llm=llm if isinstance(llm, LLMBase) else None,
            context_window=context_window,
            base_url=base_url,
            api_key=api_key,
            stream=stream,
            workspace_root=workspace_root,
            tools=tools,
            scheduler=scheduler,
            use_llm_route=use_llm_route,
        )
        self.config = RoomConfig(
            name=name,
            agents=agents,
            scheduler=scheduler,
            max_rounds=max_rounds,
            context_window=context_window,
            verbose=verbose,
            base_url=base_url,
            api_key=api_key,
        )
        self._human = human
        self._terminator = CompositeTerminator(
            [
                ConsensusTerminator(window=3, threshold=2.0),
                MaxRoundsTerminator(max_rounds=max_rounds),
            ]
        )
        self._max_rounds = max_rounds

    # ── Main loop ──────────────────────────────────────────

    def run(self, topic: str) -> ChatResult:
        return self.chat(topic)

    def chat(self, topic: str) -> ChatResult:
        self._reset_state()
        self._current_topic = topic
        self._build_system_prompts(topic)
        self._emit_system(f"讨论话题: {topic}")

        logger.info(
            "话题讨论开始 topic=%s agents=%d max_rounds=%d",
            topic,
            len(self.agents),
            self._max_rounds,
        )
        round_idx = 0
        total_tokens = 0

        while True:
            speaker = self._scheduler.next_speaker(self.history, round_idx)
            if self._speaker_exhausted(speaker):
                if self._all_exhausted():
                    self._emit_system("所有参与者已达到发言上限，讨论结束。")
                    logger.info(
                        "话题讨论结束 reason=all_exhausted rounds=%d tokens=%d",
                        round_idx,
                        total_tokens,
                    )
                    break
                round_idx += 1
                continue

            self._emit_speaker_start(speaker.name, speaker.role, speaker.model)
            messages, tokens = self._generate_response(speaker, topic)
            self._process_messages(messages, speaker.name, tokens)
            total_tokens += tokens

            if self._handle_human_pause(round_idx, speaker.name):
                logger.info(
                    "话题讨论结束 reason=human_stop rounds=%d tokens=%d", round_idx, total_tokens
                )
                break

            if self._check_termination():
                logger.info(
                    "话题讨论结束 reason=terminator rounds=%d tokens=%d", round_idx, total_tokens
                )
                break

            round_idx += 1

        summary = self._generate_summary(topic)
        logger.info("话题讨论完成 summary_len=%d total_tokens=%d", len(summary), total_tokens)
        return ChatResult(
            topic=topic,
            messages=self.history,
            summary=summary,
            total_tokens=total_tokens,
            rounds=round_idx,
            stop_reason=self.history[-1].content if self.history else "",
        )

    def _reset_state(self) -> None:
        self.history = []
        self._turn_counts = {a.name: 0 for a in self.agents}
        self._system_prompts = {}

    def _build_system_prompts(self, topic: str) -> None:
        extra_prompts = self._build_workspace_prompts()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        time_hint = f"\n\n当前时间: {now}"
        for agent in self.agents:
            self._system_prompts[agent.name] = agent.build_system_prompt(
                topic,
                self.agents,
                extra=extra_prompts.get(agent.name, "") + time_hint,
            )

    def _speaker_exhausted(self, speaker: AgentConfig) -> bool:
        """返回 True 表示需要跳过该发言人（未耗尽则 False）"""
        if speaker.max_turns <= 0:
            return False
        return self._turn_counts[speaker.name] >= speaker.max_turns

    def _all_exhausted(self) -> bool:
        return all(
            a.max_turns > 0 and self._turn_counts.get(a.name, 0) >= a.max_turns for a in self.agents
        )

    def _process_messages(self, messages: list[Message], speaker_name: str, tokens: int) -> None:
        for msg in messages:
            self.history.append(msg)
            if msg.msg_type in (MessageType.chat, MessageType.mention):
                self._turn_counts[speaker_name] += 1
            if msg.metadata.get("_emitted"):
                continue
            for cb in self._on_message_callbacks:
                cb(msg)

    def _handle_human_pause(self, round_idx: int, speaker_name: str) -> bool:
        if not self._human or not self._human.should_pause(round_idx):
            return False
        human_msg = self._human.get_input(round_idx, speaker_name)
        if not human_msg:
            return False
        self.history.append(human_msg)
        for cb in self._on_message_callbacks:
            cb(human_msg)
        if human_msg.metadata.get("force_stop"):
            self._emit_system("人类参与者在讨论中要求结束。")
            return True
        return False

    def _check_termination(self) -> bool:
        should_stop, reason = self._terminator.should_stop(self.history, self.agents)
        if should_stop:
            self._emit_system(f"讨论结束: {reason}")
        return should_stop

    # ── Response generation ────────────────────────────────

    def _generate_response(self, agent: AgentConfig, topic: str) -> tuple[list[Message], int]:
        return self._generate_agent_response(agent)

    def _build_response_context(
        self, agent: AgentConfig, result_messages: list[Message]
    ) -> list[dict[str, Any]]:
        ctx = self._context.build_messages(
            agent,
            self._current_topic,
            self.history,
            self.agents,
            system_prompt=self._system_prompts.get(agent.name),
        )
        for rm in result_messages:
            ctx.append(rm.to_openai_msg())
        return ctx

    def _force_text_response_fallback(
        self, agent: AgentConfig, result_messages: list[Message], emit_final: bool
    ) -> None:
        try:
            ctx = self._build_response_context(agent, result_messages)
            llm = self._llm_clients.get(agent.name, self.llm)
            response = llm.chat(
                messages=ctx,
                model=agent.model,
                temperature=agent.temperature,
                tools=None,
                on_chunk=self._emit_chunk if self._stream else None,
                on_reasoning_chunk=self._emit_reasoning if self._stream else None,
            )
            result_messages.append(
                self._create_final_message(agent, response, self._current_round())
            )
        except Exception as e:
            logger.warning(f"强制无工具回复失败: {e}")

    def _parse_mentions(self, content: str) -> list[str]:
        agent_names = {a.name for a in self.agents}
        if self._human:
            agent_names.add(self._human.name)
        return [m for m in re.findall(r"@(\w+)", content) if m in agent_names]

    # ── Summary ────────────────────────────────────────────

    def _generate_summary(self, topic: str) -> str:
        conversation = "\n".join(m.format_display() for m in self.history[-SUMMARY_RECENT_MSGS:])
        ws_info = ""
        if self._workspace_mgr:
            ws_info = f"\n\n各Agent工作空间:\n{self._workspace_mgr.get_all_summaries()}"

        prompt = f"""请对以下群聊讨论进行总结，包括：
1. 讨论的核心问题
2. 各方主要观点
3. 达成的共识
4. 未解决的分歧
5. 最终建议

讨论话题: {topic}

对话记录:
{conversation}
{ws_info}

总结："""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=SUMMARY_TEMPERATURE,
                max_tokens=SUMMARY_MAX_TOKENS,
            )
            return response.content
        except Exception as e:
            logger.warning(f"总结生成失败: {e}")
            return "（总结生成失败）"
