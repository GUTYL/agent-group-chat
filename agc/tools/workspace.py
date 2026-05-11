"""工作区工具 — Agent 在独立目录中读写文件、执行代码"""

from __future__ import annotations

from .base import ToolBase, ToolResult, register_tool


class WriteFileTool(ToolBase):
    """在工作空间中写入文件"""

    name = "write_file"
    description = "在工作空间中创建或覆盖文件"

    def __init__(self, workspace_manager=None):
        self.workspace_manager = workspace_manager

    def get_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "在你的工作空间中创建或写入文件。可用于保存分析报告、代码、笔记等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "文件路径（相对于你的工作空间根目录），如 'report.md' 或 'src/main.py'",
                        },
                        "content": {
                            "type": "string",
                            "description": "要写入的文件内容",
                        },
                    },
                    "required": ["filepath", "content"],
                },
            },
        }

    def execute(self, filepath: str, content: str, **kwargs) -> ToolResult:
        owner = kwargs.get("_owner", "unknown")
        ws = self.workspace_manager.get(owner) if self.workspace_manager else None
        if not ws:
            return ToolResult(success=False, content="工作空间未初始化")
        result = ws.write_file(filepath, content)
        return ToolResult(success=True, content=result)


class ReadFileTool(ToolBase):
    """读取工作空间中的文件"""

    name = "read_file"
    description = "读取工作空间中的文件内容"

    def __init__(self, workspace_manager=None):
        self.workspace_manager = workspace_manager

    def get_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "读取你工作空间中的文件内容。也可以读取其他Agent工作空间的文件（只读）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "文件路径（相对于工作空间根目录）",
                        },
                        "owner": {
                            "type": "string",
                            "description": "可选：要读取的Agent名字。留空则为自己的工作空间。",
                        },
                    },
                    "required": ["filepath"],
                },
            },
        }

    def execute(self, filepath: str, owner: str = "", **kwargs) -> ToolResult:
        caller = kwargs.get("_owner", "unknown")
        ws = self.workspace_manager.get(caller) if self.workspace_manager else None
        if not ws:
            return ToolResult(success=False, content="工作空间未初始化")

        target_owner = owner or caller
        if target_owner == caller:
            content = ws.read_file(filepath)
        else:
            content = ws.read_other_workspace(target_owner, filepath)

        success = not content.startswith("❌")
        return ToolResult(success=success, content=content)


class ListFilesTool(ToolBase):
    """列出工作空间中的文件"""

    name = "list_files"
    description = "列出工作空间中的文件和目录"

    def __init__(self, workspace_manager=None):
        self.workspace_manager = workspace_manager

    def get_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "列出你工作空间中的文件和目录结构。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subdir": {
                            "type": "string",
                            "description": "子目录路径，留空列出根目录",
                        },
                    },
                    "required": [],
                },
            },
        }

    def execute(self, subdir: str = "", **kwargs) -> ToolResult:
        owner = kwargs.get("_owner", "unknown")
        ws = self.workspace_manager.get(owner) if self.workspace_manager else None
        if not ws:
            return ToolResult(success=False, content="工作空间未初始化")
        content = ws.list_files(subdir)
        return ToolResult(success=True, content=content)


class RunCodeTool(ToolBase):
    """在工作空间中执行命令"""

    name = "run_code"
    description = "在工作空间中执行shell命令"

    def __init__(self, workspace_manager=None):
        self.workspace_manager = workspace_manager

    def get_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "在你的工作空间中执行shell命令。可用于运行代码、安装包、运行测试等。命令在工作空间目录下执行。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的shell命令，如 'python script.py' 或 'pip install requests'",
                        },
                    },
                    "required": ["command"],
                },
            },
        }

    def execute(self, command: str, **kwargs) -> ToolResult:
        owner = kwargs.get("_owner", "unknown")
        ws = self.workspace_manager.get(owner) if self.workspace_manager else None
        if not ws:
            return ToolResult(success=False, content="工作空间未初始化")
        result = ws.run_code(command, timeout=30)
        success = not result.startswith("❌")
        return ToolResult(success=success, content=result)


def register_workspace_tools(workspace_manager) -> list[str]:
    """注册所有工作区工具，返回工具名列表"""
    tools = [
        WriteFileTool(workspace_manager),
        ReadFileTool(workspace_manager),
        ListFilesTool(workspace_manager),
        RunCodeTool(workspace_manager),
    ]
    for tool in tools:
        register_tool(tool)
    return [t.name for t in tools]
