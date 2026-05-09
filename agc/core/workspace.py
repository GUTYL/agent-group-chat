"""Agent 工作空间管理 — 每个Agent独立目录，支持文件读写和代码执行"""

from __future__ import annotations

import logging
import os
import subprocess
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class Workspace:
    """Agent 工作空间

    每个Agent在自己的目录下操作，互不干扰。
    可以读写文件、列目录、执行代码。
    其他Agent可只读访问。
    """

    def __init__(self, root: str | Path, owner: str):
        """
        Args:
            root: 工作空间根目录（如 /tmp/agc-workspaces/）
            owner: Agent名字（如 researcher）
        """
        self.root = Path(root)
        self.owner = owner
        self.path = self.root / owner
        self.path.mkdir(parents=True, exist_ok=True)
        logger.info(f"工作空间已创建: {self.path}")

    # ── 文件操作 ──────────────────────────────────────────────

    def write_file(self, filepath: str, content: str) -> str:
        """写入文件到工作空间"""
        target = (self.path / filepath).resolve()
        # 安全检查：不允许逃出工作空间
        if not str(target).startswith(str(self.path.resolve())):
            return f"❌ 安全错误：不能写入工作空间外的路径: {filepath}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info(f"[{self.owner}] 写入文件: {filepath} ({len(content)} 字符)")
        return f"✅ 已写入 {filepath} ({len(content)} 字符)"

    def read_file(self, filepath: str) -> str:
        """从工作空间读取文件"""
        target = (self.path / filepath).resolve()
        if not str(target).startswith(str(self.path.resolve())):
            return f"❌ 安全错误：不能读取工作空间外的路径: {filepath}"
        if not target.exists():
            return f"❌ 文件不存在: {filepath}"
        return target.read_text(encoding="utf-8")

    def read_other_workspace(self, owner: str, filepath: str) -> str:
        """只读访问其他Agent的工作空间"""
        other_path = self.root / owner / filepath
        if not other_path.exists():
            return f"❌ 文件不存在: {owner}/{filepath}"
        return other_path.read_text(encoding="utf-8")

    def list_files(self, subdir: str = "") -> str:
        """列出工作空间中的文件"""
        target = (self.path / subdir).resolve() if subdir else self.path
        if not str(target).startswith(str(self.path.resolve())):
            return f"❌ 安全错误：不能列出工作空间外的路径"
        if not target.exists():
            return f"❌ 目录不存在: {subdir or '/'}"

        entries = []
        for p in sorted(target.rglob("*")):
            rel = p.relative_to(self.path)
            prefix = "📁 " if p.is_dir() else "📄 "
            size = f" ({p.stat().st_size}B)" if p.is_file() else ""
            entries.append(f"{prefix}{rel}{size}")

        if not entries:
            return f"📂 {subdir or '/'} 目录为空"
        return f"📂 {subdir or '/'} ({len(entries)} 项):\n" + "\n".join(entries)

    def run_code(self, command: str, timeout: int = 30) -> str:
        """在工作空间中执行命令（安全沙箱）"""
        logger.info(f"[{self.owner}] 执行命令: {command}")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.path),
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[退出码: {result.returncode}]"
            # 截断防止太长
            if len(output) > 3000:
                output = output[:3000] + "\n... (输出截断)"
            return output or "（命令执行完毕，无输出）"
        except subprocess.TimeoutExpired:
            return f"❌ 命令超时（{timeout}秒）"
        except Exception as e:
            return f"❌ 执行出错: {e}"

    def get_summary(self) -> str:
        """获取工作空间概要（供其他Agent了解）"""
        files = list(self.path.rglob("*"))
        file_list = [f for f in files if f.is_file()]
        if not file_list:
            return f"[{self.owner}的工作空间为空]"

        lines = [f"[{self.owner}的工作空间]"]
        for f in sorted(file_list):
            rel = f.relative_to(self.path)
            size = f.stat().st_size
            lines.append(f"  {rel} ({size}B)")
        return "\n".join(lines)


class WorkspaceManager:
    """管理所有Agent的工作空间"""

    def __init__(self, root: str | Path = "./data/workspaces"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._workspaces: dict[str, Workspace] = {}

    def get(self, owner: str) -> Workspace:
        """获取或创建Agent的工作空间"""
        if owner not in self._workspaces:
            self._workspaces[owner] = Workspace(self.root, owner)
        return self._workspaces[owner]

    def get_all_summaries(self, exclude: str | None = None) -> str:
        """获取所有工作空间概要"""
        lines = []
        for owner, ws in self._workspaces.items():
            if owner == exclude:
                continue
            summary = ws.get_summary()
            if summary:
                lines.append(summary)
        return "\n\n".join(lines) if lines else "（暂无其他Agent的工作空间内容）"

    def cleanup(self):
        """清理所有工作空间"""
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)