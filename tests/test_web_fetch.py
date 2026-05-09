"""单元测试 — 网页抓取工具"""

import json

from agc.tools.web_fetch import (
    WebFetchTool, _strip_tags, _normalize, _validate_url,
    _html_to_markdown, register_web_fetch_tool,
)
from agc.tools.base import get_tool


def test_validate_url():
    """URL校验"""
    ok, _ = _validate_url("https://example.com")
    assert ok

    ok, msg = _validate_url("ftp://bad.com")
    assert not ok
    assert "http" in msg

    ok, msg = _validate_url("not-a-url")
    assert not ok


def test_strip_tags():
    """去除HTML标签"""
    html_text = "<p>Hello <b>World</b></p><script>alert(1)</script>"
    result = _strip_tags(html_text)
    assert "Hello" in result
    assert "World" in result
    assert "<script>" not in result
    assert "alert" not in result


def test_normalize():
    """规范化空白"""
    assert _normalize("  hello   world  ") == "hello world"
    assert _normalize("a\n\n\n\nb") == "a\n\nb"


def test_html_to_markdown():
    """HTML转Markdown"""
    html_content = """
    <html>
    <head><title>Test</title></head>
    <body>
    <h1>Title</h1>
    <p>Paragraph with <strong>bold</strong> and <em>italic</em>.</p>
    <a href="https://example.com">link</a>
    </body>
    </html>
    """
    result = _html_to_markdown(html_content, title="My Page")
    assert "# My Page" in result
    assert "**bold**" in result
    assert "*italic*" in result
    assert "[link](https://example.com)" in result


def test_web_fetch_tool_schema():
    """工具schema格式正确"""
    tool = WebFetchTool()
    schema = tool.get_openai_schema()
    assert schema["function"]["name"] == "web_fetch"
    assert "url" in schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["required"] == ["url"]


def test_web_fetch_invalid_url():
    """无效URL返回错误"""
    tool = WebFetchTool()
    result = tool.execute(url="ftp://bad.com")
    assert not result.success
    assert "URL无效" in result.content


def test_web_fetch_bad_domain():
    """不存在的域名返回错误"""
    tool = WebFetchTool()
    result = tool.execute(url="https://this-domain-definitely-does-not-exist-99999.com")
    assert not result.success


def test_web_fetch_json_api():
    """抓取JSON API（httpbin）"""
    tool = WebFetchTool()
    result = tool.execute(url="https://httpbin.org/json")
    # httpbin可能不稳定，只检查格式
    if result.success:
        assert "json" in result.content.lower() or "slideshow" in result.content.lower()


def test_register_web_fetch_tool():
    """注册工具"""
    name = register_web_fetch_tool()
    assert name == "web_fetch"
    assert get_tool("web_fetch") is not None