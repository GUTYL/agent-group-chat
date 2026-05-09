"""网页搜索工具 — 支持 Serper、Tavily、DuckDuckGo"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from .base import ToolBase, ToolResult, register_tool

logger = logging.getLogger(__name__)


class SerperSearchTool(ToolBase):
    """Serper.dev 搜索（Google Results API，便宜好用）"""

    name = "web_search"
    description = "搜索互联网获取最新信息"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("SERPER_API_KEY", "")
        if not self.api_key:
            logger.warning("SERPER_API_KEY 未设置，搜索工具将不可用")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

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

    def execute(self, query: str, **kwargs) -> ToolResult:
        if not self.api_key:
            return ToolResult(
                success=False,
                content="搜索不可用：SERPER_API_KEY 未设置。请设置环境变量或传入 api_key。",
            )

        try:
            resp = httpx.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "hl": "zh-cn", "num": 6},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            return ToolResult(success=False, content=f"搜索请求失败: {e}")

        # 组织搜索结果
        results = []
        # 有机搜索结果
        for item in data.get("organic", [])[:5]:
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            link = item.get("link", "")
            results.append(f"- {title}\n  {snippet}\n  来源: {link}")

        # 知识图谱（如有）
        kg = data.get("knowledgeGraph")
        if kg:
            results.insert(0, f"📖 {kg.get('title', '')}: {kg.get('description', '')}")

        content = f"🔍 搜索: {query}\n\n" + "\n\n".join(results) if results else f"🔍 搜索 '{query}' 无结果"

        return ToolResult(
            success=True,
            content=content,
            raw=data,
            metadata={"query": query, "source": "serper"},
        )


class TavilySearchTool(ToolBase):
    """Tavily 搜索（针对 AI agent 优化）"""

    name = "web_search"
    description = "搜索互联网获取最新信息（Tavily）"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        if not self.api_key:
            logger.warning("TAVILY_API_KEY 未设置，搜索工具将不可用")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

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

    def execute(self, query: str, **kwargs) -> ToolResult:
        if not self.api_key:
            return ToolResult(
                success=False,
                content="搜索不可用：TAVILY_API_KEY 未设置。",
            )

        try:
            resp = httpx.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": 5,
                    "include_answer": True,
                    "search_depth": "basic",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            return ToolResult(success=False, content=f"搜索请求失败: {e}")

        parts = []
        # Tavily 的 AI 回答
        if data.get("answer"):
            parts.append(f"💡 AI 摘要: {data['answer']}")

        for item in data.get("results", [])[:5]:
            title = item.get("title", "")
            content = item.get("content", "")
            url = item.get("url", "")
            parts.append(f"- {title}\n  {content}\n  来源: {url}")

        content = f"🔍 搜索: {query}\n\n" + "\n\n".join(parts)

        return ToolResult(
            success=True,
            content=content,
            raw=data,
            metadata={"query": query, "source": "tavily"},
        )


class DuckDuckGoSearchTool(ToolBase):
    """DuckDuckGo 搜索（免费，无需 API Key，但结果质量较低）"""

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
        return True  # DuckDuckGo 不需要 key

    def execute(self, query: str, **kwargs) -> ToolResult:
        try:
            resp = httpx.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": 1,
                    "skip_disambig": 1,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            return ToolResult(success=False, content=f"搜索请求失败: {e}")

        parts = []
        abstract = data.get("AbstractText")
        if abstract:
            parts.append(f"📖 {data.get('AbstractTitle', '摘要')}: {abstract}")

        for item in data.get("RelatedTopics", [])[:5]:
            text = item.get("Text", "")
            url = item.get("FirstURL", "")
            if text:
                parts.append(f"- {text}\n  来源: {url}")

        content = f"🔍 搜索: {query}\n\n" + ("\n\n".join(parts) if parts else "无结果")

        return ToolResult(
            success=True,
            content=content,
            raw=data,
            metadata={"query": query, "source": "duckduckgo"},
        )


def create_search_tool(
    provider: str = "auto",
    api_key: str | None = None,
) -> ToolBase:
    """工厂方法：创建搜索工具

    Args:
        provider: "serper" / "tavily" / "duckduckgo" / "auto"（自动检测）
        api_key: 显式传入API key（否则从环境变量读取）
    """
    if provider == "auto":
        # 优先级：显式key > 环境变量 > 免费方案
        if api_key or os.environ.get("SERPER_API_KEY"):
            provider = "serper"
        elif os.environ.get("TAVILY_API_KEY"):
            provider = "tavily"
        else:
            provider = "duckduckgo"

    if provider == "serper":
        tool = SerperSearchTool(api_key=api_key)
    elif provider == "tavily":
        tool = TavilySearchTool(api_key=api_key)
    elif provider == "duckduckgo":
        tool = DuckDuckGoSearchTool()
    else:
        raise ValueError(f"未知搜索提供商: {provider}，可选: serper / tavily / duckduckgo / auto")

    register_tool(tool)
    return tool