"""Hybrid 调度器 — @mention优先 + 关键词路由 + LLM兜底"""

from __future__ import annotations

import re

from agc.core.agent import AgentConfig
from agc.core.message import Message
from agc.llm.base import LLMBase

from .base import SchedulerBase


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
        self._round_idx = 0

    def next_speaker(
        self,
        history: list[Message],
        round_idx: int,
    ) -> AgentConfig:
        self._round_idx = round_idx

        # 1. @mention 优先
        if history and history[-1].has_mentions:
            mentioned = history[-1].mentions[0]  # 取第一个@的人
            agent = self.get_agent(mentioned)
            if agent:
                return agent

        # 2. 关键词路由
        if history:
            agent = self._keyword_route(history[-1].content)
            if agent:
                return agent

        # 3. LLM路由（可选，消耗token）
        if self.use_llm_router and self.llm and history:
            agent = self._llm_route(history)
            if agent:
                return agent

        # 4. RoundRobin 兜底
        return self.agents[round_idx % len(self.agents)]

    def _keyword_route(self, content: str) -> AgentConfig | None:
        """基于关键词匹配角色"""
        for agent in self.agents:
            keywords = ROLE_KEYWORDS.get(agent.name, [])
            if any(kw in content for kw in keywords):
                return agent
        return None

    def _llm_route(self, history: list[Message]) -> AgentConfig | None:
        """用LLM决定谁应该说话（短prompt，省token）"""
        agent_names = [a.name for a in self.agents]
        agent_descs = [f"- {a.name}({a.role}): {a.goal}" for a in self.agents]

        # 只取最近几条消息做判断
        recent = history[-4:]
        recent_text = "\n".join(f"[{m.sender}]: {m.content[:200]}" for m in recent)

        prompt = f"""Based on the conversation, which agent should speak next?
Agents:
{chr(10).join(agent_descs)}

Recent messages:
{recent_text}

Reply with ONLY the agent name, nothing else. Options: {', '.join(agent_names)}"""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.llm.default_model,
                temperature=0.0,
                max_tokens=20,
            )
            name = response.content.strip().lower()
            # 清理可能的引号、标点
            name = re.sub(r'[^a-z0-9_-]', '', name)
            agent = self.get_agent(name)
            if agent:
                return agent
        except Exception:
            pass

        return None