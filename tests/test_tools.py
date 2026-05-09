"""单元测试 — 搜索工具"""

import json

from agc.tools.base import ToolResult, execute_tool_call, get_tool, list_tools, register_tool
from agc.tools.search import DuckDuckGoSearchTool, SerperSearchTool, TavilySearchTool, create_search_tool


def test_duckduckgo_schema():
    """DuckDuckGo工具的schema格式正确"""
    tool = DuckDuckGoSearchTool()
    schema = tool.get_openai_schema()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "web_search"
    assert "query" in schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["required"] == ["query"]


def test_duckduckgo_always_available():
    """DuckDuckGo不需要API key，始终可用"""
    tool = DuckDuckGoSearchTool()
    assert tool.available is True


def test_serper_not_available_without_key():
    """Serper没有API key时不可用"""
    tool = SerperSearchTool(api_key="")
    assert tool.available is False


def test_tavily_not_available_without_key():
    """Tavily没有API key时不可用"""
    tool = TavilySearchTool(api_key="")
    assert tool.available is False


def test_create_search_tool_duckduckgo():
    """工厂方法默认创建DuckDuckGo"""
    # 没有环境变量时回退到duckduckgo
    tool = create_search_tool(provider="duckduckgo")
    assert tool.name == "web_search"
    assert isinstance(tool, DuckDuckGoSearchTool)


def test_register_and_get_tool():
    """工具注册和获取"""
    tool = create_search_tool(provider="duckduckgo")
    assert get_tool("web_search") is tool


def test_execute_unknown_tool():
    """调用未知工具返回失败"""
    result = execute_tool_call("nonexistent_tool", "{}")
    assert result.success is False
    assert "未知工具" in result.content


def test_execute_duckduckgo_search():
    """DuckDuckGo实际搜索（网络测试，可能因网络问题失败）"""
    tool = DuckDuckGoSearchTool()
    register_tool(tool)
    result = tool.execute(query="Python programming language")
    # 只验证结构正确，不验证结果内容（网络可能不通）
    assert isinstance(result, ToolResult)
    assert isinstance(result.success, bool)
    assert isinstance(result.content, str)


def test_list_tools():
    """列出已注册工具"""
    create_search_tool(provider="duckduckgo")
    tools = list_tools()
    assert "web_search" in tools