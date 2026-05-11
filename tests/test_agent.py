"""单元测试 — AgentConfig"""

from agc.core.agent import AgentConfig


def test_agent_config_build_system_prompt():
    agents = [
        AgentConfig(name="alice", role="研究员", goal="调研", backstory=""),
        AgentConfig(name="bob", role="架构师", goal="设计", backstory=""),
    ]
    prompt = agents[0].build_system_prompt("测试话题", agents)
    assert "alice" in prompt
    assert "研究员" in prompt
    assert "测试话题" in prompt
    assert "bob" in prompt


def test_agent_config_extra_prompt():
    agent = AgentConfig(
        name="test",
        role="测试",
        goal="测试",
        backstory="",
        system_prompt_extra="请用中文回答",
    )
    prompt = agent.build_system_prompt("话题", [agent])
    assert "请用中文回答" in prompt
