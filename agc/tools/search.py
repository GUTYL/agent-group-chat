"""网页搜索工具 — DuckDuckGo"""

from __future__ import annotations

import logging

from .base import ToolBase, ToolResult, register_tool

logger = logging.getLogger(__name__)


class DuckDuckGoSearchTool(ToolBase):
    """DuckDuckGo 搜索（免费，无需 API Key）"""

    name = "web_search"
    description = "搜索互联网获取最新信息（DuckDuckGo，免费）"

    def get_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "搜索互联网获取最新信息。当你需要查找事实、数据、新闻或其他你不了解的信息时使用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    @property
    def available(self) -> bool:
        return True

    def execute(self, query: str, **kwargs) -> ToolResult:
        try:
            from ddgs import DDGS
        except ImportError:
            return ToolResult(
                success=False,
                content="DuckDuckGo 搜索不可用：请安装 ddgs 包 (pip install ddgs)",
            )

        try:
            with DDGS(timeout=10) as ddgs:
                raw = list(ddgs.text(query, max_results=6))
        except Exception as e:
            return ToolResult(success=False, content=f"搜索请求失败: {e}")

        if not raw:
            return ToolResult(
                success=True,
                content=f"🔍 搜索: {query}\n\n无结果",
                metadata={"query": query, "source": "duckduckgo"},
            )

        parts = []
        for item in raw:
            title = item.get("title", "")
            body = item.get("body", "")
            href = item.get("href", "")
            parts.append(f"- {title}\n  {body}\n  {href}")

        content = f"🔍 搜索: {query}\n\n" + "\n\n".join(parts)

        return ToolResult(
            success=True,
            content=content,
            raw={"results": raw},
            metadata={"query": query, "source": "duckduckgo"},
        )


def create_search_tool(
    provider: str = "duckduckgo",
) -> ToolBase:
    """创建搜索工具

    Args:
        provider: "duckduckgo"（目前仅支持 DuckDuckGo）
    """
    if provider not in ("duckduckgo", "auto"):
        logger.warning(f"未知搜索后端: {provider}，使用 DuckDuckGo")
    tool = DuckDuckGoSearchTool()
    register_tool(tool)
    return tool
