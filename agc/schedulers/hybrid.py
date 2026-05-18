"""Hybrid 调度器 — @mention优先 + 关键词路由 + LLM兜底"""

from __future__ import annotations

import logging

from agc.core.agent import AgentConfig
from agc.core.message import Message, MessageType
from agc.llm.base import LLMBase

from .base import SchedulerBase

logger = logging.getLogger(__name__)

# 角色关键词映射（零成本路由）
ROLE_KEYWORDS: dict[str, list[str]] = {
    "researcher": ["搜索", "调研", "查", "找", "搜索", "研究", "论文", "数据", "信息", "背景"],
    "architect": ["架构", "设计", "方案", "系统", "结构", "评估", "选型", "权衡"],
    "developer": ["实现", "代码", "写", "开发", "编码", "部署", "构建", "编程", "函数"],
    "reviewer": ["审查", "问题", "质疑", "风险", "漏洞", "测试", "验证", "检查", "反例"],
    "pm": ["需求", "优先级", "排期", "里程碑", "用户", "产品", "验收"],
    "analyst": ["分析", "数据", "指标", "统计", "趋势", "对比", "量化"],
}


class HybridScheduler(SchedulerBase):
    """混合调度：@mention → 关键词路由 → RoundRobin兜底

    优先级：
    1. 上一条消息中 @mentions 指定的人
    2. 关键词命中对应角色
    3. LLM路由（可选，需要传入llm）
    4. RoundRobin兜底
    """

    def __init__(
        self,
        agents: list[AgentConfig],
        llm: LLMBase | None = None,
        use_llm_router: bool = False,
    ):
        super().__init__(agents)
        self.llm = llm
        self.use_llm_router = use_llm_router

    def next_speaker(
        self,
        history: list[Message],
        round_idx: int,
    ) -> AgentConfig:
        # 1. @mention 优先
        if history and history[-1].has_mentions:
            mentioned = history[-1].mentions[0]  # 取第一个@的人
            agent = self.get_agent(mentioned)
            if agent:
                logger.info("调度决策 method=mention target=%s", agent.name)
                return agent

        # 2. 关键词路由
        if history:
            agent = self._keyword_route(history[-1].content)
            if agent:
                logger.info("调度决策 method=keyword target=%s", agent.name)
                return agent

        # 3. LLM路由（可选，消耗token）
        if self.use_llm_router and self.llm and history:
            agent = self._llm_route(history)
            if agent:
                logger.info("调度决策 method=llm_route target=%s", agent.name)
                return agent

        # 4. RoundRobin 兜底
        agent = self.agents[round_idx % len(self.agents)]
        logger.info("调度决策 method=round_robin target=%s", agent.name)
        return agent

    def plan_responses(self, history: list[Message]) -> list[AgentConfig]:
        """FreeChat模式：决定哪些agent应该回应

        优先级：
        1. @mention — 被提到的agent都回应
        2. "大家" / "@all" — 所有agent回应
        3. 关键词路由 — 匹配角色关键词
        4. LLM路由 — 选最相关的一个agent
        5. 首个agent兜底 — 确保不冷场
        """
        if not history:
            return []

        last_msg = history[-1]

        # 1. @mention → 被提到的agents回应
        if last_msg.has_mentions:
            mentioned = []
            for name in last_msg.mentions:
                agent = self.get_agent(name)
                if agent and agent not in mentioned:
                    mentioned.append(agent)
            if mentioned:
                targets = [a.name for a in mentioned]
                logger.info("调度决策 method=mention target=%s", ", ".join(targets))
                return mentioned

        # 2. "@all" 或 "大家" → 所有agent回应
        if last_msg.msg_type == MessageType.human_input:
            content_lower = last_msg.content.lower()
            if "@all" in content_lower or "大家" in content_lower:
                logger.info("调度决策 method=all target=all(%d agents)", len(self.agents))
                return list(self.agents)

            # 3. 关键词路由
            agent = self._keyword_route(last_msg.content)
            if agent:
                logger.info("调度决策 method=keyword target=%s", agent.name)
                return [agent]

        # 4. LLM路由 → 选最相关的一个agent
        if self.use_llm_router and self.llm:
            agent = self._llm_route(history)
            if agent:
                logger.info("调度决策 method=llm_route target=%s", agent.name)
                return [agent]
            logger.info("调度决策 method=llm_route result=miss")

        # 5. 默认兜底：首个agent回应
        if self.agents:
            agent = self.agents[0]
            logger.info("调度决策 method=fallback target=%s", agent.name)
            return [agent]

        return []

    def _keyword_route(self, content: str) -> AgentConfig | None:
        """基于关键词匹配角色"""
        for agent in self.agents:
            keywords = ROLE_KEYWORDS.get(agent.name, [])
            if any(kw in content for kw in keywords):
                return agent
        return None

    def _llm_route(self, history: list[Message]) -> AgentConfig | None:
        """用LLM决定谁应该说话"""
        agent_names = [a.name for a in self.agents]
        recent = history[-4:]
        recent_text = "\n".join(f"[{m.sender}]: {m.content[:200]}" for m in recent)

        prompt = f"""基于对话选择最合适的发言人。只回复一个名字，不要解释。

可选的发言人: {", ".join(agent_names)}

最近消息:
{recent_text}"""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.llm.default_model,
                temperature=0.0,
                max_tokens=50,
            )
            raw = (response.content or response.reasoning_content or "").strip().lower()
            # 从回复中找第一个匹配的agent名
            for name in agent_names:
                if name in raw:
                    return self.get_agent(name)
            logger.warning("LLM路由返回未知内容: '%s'", raw[:80])
        except Exception as e:
            logger.warning("LLM路由调用失败: %s", e)

        return None
