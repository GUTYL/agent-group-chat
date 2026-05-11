"""Agent 配置模型"""

from __future__ import annotations

from pydantic import BaseModel


class AgentConfig(BaseModel):
    """群聊中的 Agent 参与者配置"""

    name: str  # 唯一标识（英文，如 researcher）
    role: str  # 角色名（如 "资深研究员"）
    goal: str  # 目标（如 "深入调研问题，提供信息支撑"）
    backstory: str  # 背景人设
    model: str = "gpt-4o"  # 使用的LLM模型
    base_url: str | None = None  # LLM API端点（None=用默认/全局配置）
    api_key: str | None = None  # API Key（None=用环境变量）
    system_prompt_extra: str = ""  # 额外追加到system prompt的内容
    tools: list[str] = []  # 可用工具名列表（如 ["web_search"]）
    max_turns: int = 0  # 该agent最多发言次数，0=不限
    temperature: float = 0.7  # 生成温度

    def build_system_prompt(
        self, topic: str, all_agents: list[AgentConfig], extra: str = ""
    ) -> str:
        """构建完整的 system prompt"""
        agents_desc = "\n".join(f"- {a.name} ({a.role}): {a.goal}" for a in all_agents)
        prompt = f"""你正在参与一个群聊讨论。

## 你的身份
- 名字: {self.name}
- 角色: {self.role}
- 目标: {self.goal}
- 人设: {self.backstory}

## 讨论话题
{topic}

## 群聊其他成员
{agents_desc}

## 群聊规则
1. 基于你的角色和专业视角发言，不要越界到其他角色的领域
2. 如果需要某个成员的意见，用 @名字 提及ta，例如 "@architect 你怎么看？"
3. 可以质疑、补充、同意其他成员的观点
4. 当你认为讨论已经充分，可以总结并给出你的最终建议
5. 不要重复别人已经说过的内容，要么补充新信息，要么表示同意并说明原因
6. 发言简洁有力，避免空话
"""
        # 工具使用说明
        if self.tools:
            tool_names = ", ".join(self.tools)
            prompt += f"""
## 可用工具
你可以使用以下工具：{tool_names}

当你需要搜索信息、验证事实或查找最新数据时，应该主动使用 web_search 工具。
使用工具后，你会获得搜索结果，请基于搜索结果继续讨论，并自然地引用信息来源。
不要在每轮都搜索——只在确实需要新信息时才搜索。
"""
        if self.system_prompt_extra:
            prompt += f"\n## 额外指令\n{self.system_prompt_extra}\n"
        if extra:
            prompt += f"\n{extra}"
        return prompt
