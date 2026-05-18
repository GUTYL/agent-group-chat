"""共享的测试夹具和工厂函数"""

from unittest.mock import MagicMock

import pytest

from agc.core.agent import AgentConfig
from agc.core.message import Message, MessageType


def make_agent(name, role="研究员", goal="调研", backstory="", model="gpt-4o"):
    return AgentConfig(name=name, role=role, goal=goal, backstory=backstory, model=model)


def make_msg(sender, content, *, msg_type=MessageType.chat, round_idx=0, mentions=None, **kwargs):
    return Message(
        sender=sender,
        content=content,
        msg_type=msg_type,
        round_idx=round_idx,
        mentions=mentions or [],
        **kwargs,
    )


def make_mock_response(
    *,
    content="回复内容",
    reasoning_content="",
    model="gpt-4o",
    finish_reason="stop",
    prompt_tokens=50,
    completion_tokens=50,
):
    return MagicMock(
        content=content,
        reasoning_content=reasoning_content,
        model=model,
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tool_calls=None,
        has_tool_calls=False,
    )


@pytest.fixture
def researcher():
    return make_agent("researcher", "研究员", "调研")


@pytest.fixture
def architect():
    return make_agent("architect", "架构师", "设计")


@pytest.fixture
def reviewer():
    return make_agent("reviewer", "审查", "质疑")


@pytest.fixture
def two_agents(researcher, architect):
    return [researcher, architect]


@pytest.fixture
def three_agents(researcher, architect, reviewer):
    return [researcher, architect, reviewer]


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    return llm
