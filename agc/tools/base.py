"""工具基类和注册表"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """工具执行结果"""

    success: bool
    content: str  # 结果文本（会注入到对话中）
    raw: Any = None  # 原始数据
    metadata: dict = field(default_factory=dict)


class ToolBase(ABC):
    """工具抽象基类"""

    name: str = ""
    description: str = ""

    @abstractmethod
    def get_openai_schema(self) -> dict:
        """返回 OpenAI function calling 的 JSON Schema"""
        ...

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        ...


# ── 全局工具注册表 ──────────────────────────────────────────────

_REGISTRY: dict[str, ToolBase] = {}


def register_tool(tool: ToolBase) -> None:
    """注册工具到全局注册表"""
    _REGISTRY[tool.name] = tool


def get_tool(name: str) -> ToolBase | None:
    """按名获取工具"""
    return _REGISTRY.get(name)


def list_tools() -> dict[str, str]:
    """列出所有已注册工具 {name: description}"""
    return {name: t.description for name, t in _REGISTRY.items()}


def get_schemas_for_tools(tool_names: list[str]) -> list[dict]:
    """获取指定工具的 OpenAI function schemas"""
    schemas = []
    for name in tool_names:
        tool = _REGISTRY.get(name)
        if tool:
            schemas.append(tool.get_openai_schema())
    return schemas


def execute_tool_call(name: str, arguments: str | dict, owner: str = "") -> ToolResult:
    """执行工具调用（统一入口）

    Args:
        name: 工具名
        arguments: JSON字符串或dict
        owner: 调用者agent名（用于工作区工具路由）
    """
    tool = _REGISTRY.get(name)
    if not tool:
        return ToolResult(success=False, content=f"未知工具: {name}")

    # 参数可能是 JSON 字符串或已解析的 dict
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return ToolResult(success=False, content=f"工具参数JSON解析失败: {arguments}")

    # 注入 _owner 参数（工作区工具需要知道调用者是谁）
    kwargs = dict(arguments)
    if owner:
        kwargs["_owner"] = owner

    try:
        return tool.execute(**kwargs)
    except Exception as e:
        logger.error(f"工具 {name} 执行失败: {e}")
        return ToolResult(success=False, content=f"工具执行出错: {e}")
