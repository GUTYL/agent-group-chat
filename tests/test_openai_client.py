"""单元测试 — OpenAIClient"""

import os
from unittest.mock import MagicMock, patch

import pytest

from agc.llm.openai_client import OpenAIClient


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-dummy-key")


def test_init_with_explicit_key():
    client = OpenAIClient(api_key="explicit-key", base_url="https://example.com/v1")
    assert client.api_key == "explicit-key"
    assert client.base_url == "https://example.com/v1"


def test_init_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    client = OpenAIClient()
    assert client.api_key == "env-key"


def test_init_empty_key_raises():
    with patch.dict(os.environ, {}, clear=True), pytest.raises(ValueError, match="API key"):
        OpenAIClient()


@pytest.mark.parametrize(
    "model",
    [
        "gpt-4o",
        "unknown-model-xyz",
    ],
)
def test_count_tokens_positive(model):
    client = OpenAIClient(default_model="gpt-4o")
    count = client.count_tokens(
        "hello world", model=model if model != "unknown-model-xyz" else model
    )
    assert count > 0

    count2 = client.count_tokens("hello world")
    assert count2 > 0


def test_build_kwargs_uses_default_model():
    client = OpenAIClient(default_model="gpt-4o-mini")
    kwargs = client._build_kwargs([{"role": "user", "content": "hi"}], None, 0.7, None, None)
    assert kwargs["model"] == "gpt-4o-mini"


def test_build_kwargs_overrides_model():
    client = OpenAIClient(default_model="gpt-4o-mini")
    kwargs = client._build_kwargs([{"role": "user", "content": "hi"}], "gpt-4", 0.7, None, None)
    assert kwargs["model"] == "gpt-4"


def test_build_kwargs_includes_tools():
    client = OpenAIClient()
    tools = [{"type": "function", "function": {"name": "test"}}]
    kwargs = client._build_kwargs([{"role": "user", "content": "hi"}], None, 0.7, None, tools)
    assert "tools" in kwargs
    assert kwargs["tools"] == tools


def test_build_kwargs_excludes_empty_tools():
    client = OpenAIClient()
    kwargs = client._build_kwargs([{"role": "user", "content": "hi"}], None, 0.7, None, None)
    assert "tools" not in kwargs


def test_build_kwargs_includes_max_tokens():
    client = OpenAIClient()
    kwargs = client._build_kwargs([{"role": "user", "content": "hi"}], None, 0.7, 100, None)
    assert kwargs["max_tokens"] == 100


def test_build_kwargs_excludes_max_tokens_when_none():
    client = OpenAIClient()
    kwargs = client._build_kwargs([{"role": "user", "content": "hi"}], None, 0.7, None, None)
    assert "max_tokens" not in kwargs


def test_accumulate_tool_calls_merges_chunks():
    acc = {}
    delta1 = MagicMock()
    delta1.index = 0
    delta1.id = "call_1"
    delta1.function = MagicMock()
    delta1.function.name = "search"
    delta1.function.arguments = '{"q":'
    OpenAIClient._accumulate_tool_calls([delta1], acc)

    delta2 = MagicMock()
    delta2.index = 0
    delta2.id = None
    delta2.function = MagicMock()
    delta2.function.name = ""
    delta2.function.arguments = '"hello"}'
    OpenAIClient._accumulate_tool_calls([delta2], acc)

    assert acc[0]["id"] == "call_1"
    assert acc[0]["function"]["name"] == "search"
    assert acc[0]["function"]["arguments"] == '{"q":"hello"}'
