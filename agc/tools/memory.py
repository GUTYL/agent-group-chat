"""记忆工具 — Agent 持久化关键事实和结论

每个Agent在自己的工作空间 memory.json 中存储记忆。
支持保存、召回、列出、删除四个操作。
记忆是纯本地文件操作，不需要任何API Key。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .base import ToolBase, ToolResult, register_tool

logger = logging.getLogger(__name__)


class MemoryToolBase(ToolBase):
    """记忆工具基类，提供共享的文件操作辅助方法"""

    def __init__(self, workspace_manager=None):
        self.workspace_manager = workspace_manager

    def _get_memory_path(self, owner: str) -> Path | None:
        if not self.workspace_manager:
            return None
        ws = self.workspace_manager.get(owner)
        return ws.path / "memory.json"

    def _load_memories(self, path: Path) -> dict:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                backup = path.with_suffix(".json.bak")
                try:
                    import shutil

                    shutil.copy2(path, backup)
                    logger.warning("记忆文件 %s 损坏，已备份到 %s", path, backup)
                except OSError:
                    pass
                return {}
        return {}

    def _save_memories(self, path: Path, memories: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(memories, ensure_ascii=False, indent=2), encoding="utf-8")

    def _search(self, memories: dict, query: str) -> list[tuple[str, dict]]:
        query_lower = query.lower()
        results = []
        for key, entry in memories.items():
            score = 0
            if query_lower == key.lower():
                score += 10
            elif query_lower in key.lower():
                score += 5
            if query_lower in entry.get("value", "").lower():
                score += 3
            for tag in entry.get("tags", []):
                if query_lower in tag.lower():
                    score += 4
            if score > 0:
                results.append((score, key, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        return [(key, entry) for _, key, entry in results]


class SaveMemoryTool(MemoryToolBase):
    """保存一条记忆"""

    name = "save_memory"
    description = "保存一条关键事实、结论或笔记到记忆中，后续可用 recall_memory 取回"

    def get_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "保存一条重要信息到你的记忆中。用于记住关键事实、分析结论、决策依据等，避免后续重复研究。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "记忆的简短标题/标签，如 '限流方案选型' 或 'API错误码含义'",
                        },
                        "value": {
                            "type": "string",
                            "description": "记忆的详细内容，如 '令牌桶适合突发流量，漏桶适合匀速场景'",
                        },
                        "tags": {
                            "type": "string",
                            "description": "可选：逗号分隔的标签，如 '架构,限流,性能'，方便后续检索",
                        },
                    },
                    "required": ["key", "value"],
                },
            },
        }

    def execute(self, key: str, value: str, tags: str = "", **kwargs) -> ToolResult:
        owner = kwargs.get("_owner", "unknown")
        memory_file = self._get_memory_path(owner)
        if not memory_file:
            return ToolResult(success=False, content="❌ 工作空间未初始化，无法保存记忆")

        memories = self._load_memories(memory_file)

        # 若key已存在则更新
        existing = memories.get(key)
        saved_at = existing["saved_at"] if existing else time.strftime("%Y-%m-%d %H:%M:%S")
        memories[key] = {
            "value": value,
            "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
            "saved_at": saved_at,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        self._save_memories(memory_file, memories)
        tag_str = f" [{tags}]" if tags else ""
        return ToolResult(success=True, content=f"✅ 已保存记忆: {key}{tag_str}")


class RecallMemoryTool(MemoryToolBase):
    """召回记忆"""

    name = "recall_memory"
    description = "从记忆中搜索之前保存的信息"

    def get_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "搜索你的记忆，找回之前保存的关键信息。可按关键词、标签或模糊匹配搜索。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词，如 '限流' 或 'API设计'",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def execute(self, query: str, **kwargs) -> ToolResult:
        owner = kwargs.get("_owner", "unknown")
        memory_file = self._get_memory_path(owner)
        if not memory_file or not memory_file.exists():
            return ToolResult(success=False, content=f"📭 没有找到与 '{query}' 相关的记忆")

        memories = self._load_memories(memory_file)
        results = self._search(memories, query)

        if not results:
            return ToolResult(success=False, content=f"📭 没有找到与 '{query}' 相关的记忆")

        lines = [f"找到 {len(results)} 条记忆：", ""]
        for key, entry in results:
            tags_str = f" [{', '.join(entry['tags'])}]" if entry.get("tags") else ""
            lines.append(f"📝 {key}{tags_str}")
            lines.append(f"   {entry['value']}")
            lines.append(f"   保存于 {entry.get('saved_at', '未知时间')}")
            lines.append("")

        return ToolResult(success=True, content="\n".join(lines))


class ListMemoriesTool(MemoryToolBase):
    """列出所有记忆"""

    name = "list_memories"
    description = "列出你保存的所有记忆"

    def get_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "列出你保存的所有记忆条目，查看你记住了哪些信息。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tag": {
                            "type": "string",
                            "description": "可选：按标签筛选，如 '架构'",
                        },
                    },
                    "required": [],
                },
            },
        }

    def execute(self, tag: str = "", **kwargs) -> ToolResult:
        owner = kwargs.get("_owner", "unknown")
        memory_file = self._get_memory_path(owner)
        if not memory_file or not memory_file.exists():
            return ToolResult(success=True, content="📭 记忆为空，还没有保存任何信息")

        memories = self._load_memories(memory_file)

        if tag:
            memories = {k: v for k, v in memories.items() if tag in v.get("tags", [])}

        if not memories:
            tag_msg = f" 标签为 '{tag}'" if tag else ""
            return ToolResult(success=True, content=f"📭 没有{tag_msg}的记忆条目")

        lines = [f"共有 {len(memories)} 条记忆：", ""]
        for key, entry in memories.items():
            tags_str = f" [{', '.join(entry['tags'])}]" if entry.get("tags") else ""
            lines.append(f"  📝 {key}{tags_str}")
            lines.append(f"     {entry['value'][:100]}{'...' if len(entry['value']) > 100 else ''}")
        lines.append("")
        lines.append("使用 recall_memory 搜索具体内容")

        return ToolResult(success=True, content="\n".join(lines))


class DeleteMemoryTool(MemoryToolBase):
    """删除一条记忆"""

    name = "delete_memory"
    description = "删除一条不再需要的记忆"

    def get_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "删除一条之前保存的记忆。当你发现之前的结论有误或不再相关时使用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "要删除的记忆的标题/标签",
                        },
                    },
                    "required": ["key"],
                },
            },
        }

    def execute(self, key: str, **kwargs) -> ToolResult:
        owner = kwargs.get("_owner", "unknown")
        memory_file = self._get_memory_path(owner)
        if not memory_file or not memory_file.exists():
            return ToolResult(success=False, content=f"❌ 记忆 '{key}' 不存在")

        memories = self._load_memories(memory_file)
        if key not in memories:
            return ToolResult(success=False, content=f"❌ 记忆 '{key}' 不存在")

        del memories[key]
        self._save_memories(memory_file, memories)
        return ToolResult(success=True, content=f"🗑️ 已删除记忆: {key}")


def register_memory_tools(workspace_manager) -> list[str]:
    """注册所有记忆工具，返回工具名列表"""
    tools = [
        SaveMemoryTool(workspace_manager),
        RecallMemoryTool(workspace_manager),
        ListMemoriesTool(workspace_manager),
        DeleteMemoryTool(workspace_manager),
    ]
    for tool in tools:
        register_tool(tool)
    return [t.name for t in tools]
