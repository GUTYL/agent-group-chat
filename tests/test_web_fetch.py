"""单元测试 — 网页抓取工具"""

import pytest

from agc.tools.base import get_tool
from agc.tools.web_fetch import (
    WebFetchTool,
    _html_to_markdown,
    _is_private_ip,
    _normalize,
    _strip_tags,
    _validate_url,
    _validate_url_safe,
    register_web_fetch_tool,
)


def test_validate_url():
    ok, _ = _validate_url("https://example.com")
    assert ok

    ok, msg = _validate_url("ftp://bad.com")
    assert not ok
    assert "http" in msg

    ok, msg = _validate_url("not-a-url")
    assert not ok


@pytest.mark.parametrize(
    "ip,expected",
    [
        ("10.0.0.1", True),
        ("10.255.255.255", True),
        ("172.16.0.1", True),
        ("172.31.255.255", True),
        ("192.168.1.1", True),
        ("127.0.0.1", True),
        ("0.0.0.0", True),
        ("169.254.1.1", True),
        ("::1", True),
        ("fc00::1", True),
        ("fe80::1", True),
        ("8.8.8.8", False),
        ("1.1.1.1", False),
        ("93.184.216.34", False),
        ("not-an-ip", False),
    ],
)
def test_is_private_ip(ip, expected):
    assert _is_private_ip(ip) is expected


def test_validate_url_safe():
    """SSRF安全校验"""
    # 公网域名放行
    ok, _ = _validate_url_safe("https://example.com")
    assert ok

    # 公网IP放行
    ok, _ = _validate_url_safe("https://8.8.8.8")
    assert ok

    # 私有IP拒绝
    ok, msg = _validate_url_safe("http://127.0.0.1")
    assert not ok
    assert "禁止" in msg

    ok, msg = _validate_url_safe("https://10.0.0.1")
    assert not ok

    ok, msg = _validate_url_safe("http://192.168.1.1")
    assert not ok

    ok, msg = _validate_url_safe("http://[::1]")
    assert not ok

    # 无效scheme拒绝
    ok, msg = _validate_url_safe("ftp://example.com")
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
    assert "http" in result.content.lower()


def test_web_fetch_localhost_rejected():
    """SSRF: localhost 被拒绝"""
    tool = WebFetchTool()
    result = tool.execute(url="http://localhost/")
    assert not result.success
    assert "禁止" in result.content


def test_web_fetch_private_ip_rejected():
    """SSRF: 私有IP被拒绝"""
    tool = WebFetchTool()
    for url in ("http://192.168.1.1/", "http://10.0.0.1/", "http://127.0.0.1/"):
        result = tool.execute(url=url)
        assert not result.success, f"Should reject {url}"
        assert "禁止" in result.content


def test_web_fetch_bad_domain():
    """不存在的域名返回错误"""
    tool = WebFetchTool()
    result = tool.execute(url="https://this-domain-definitely-does-not-exist-99999.com")
    assert not result.success


def test_web_fetch_json_api():
    """抓取JSON API（httpbin）"""
    tool = WebFetchTool()
    result = tool.execute(url="https://httpbin.org/json")
    if result.success:
        assert "json" in result.content.lower() or "slideshow" in result.content.lower()


def test_web_fetch_public_url_accepted():
    """公网IP应通过SSRF检查不被拒绝"""
    tool = WebFetchTool()
    result = tool.execute(url="https://8.8.8.8")
    # SSRF 不应拦截公网IP（无论网络请求是否成功）
    assert "禁止" not in result.content


def test_register_web_fetch_tool():
    """注册工具"""
    name = register_web_fetch_tool()
    assert name == "web_fetch"
    assert get_tool("web_fetch") is not None
