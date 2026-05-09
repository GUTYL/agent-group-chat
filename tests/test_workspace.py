"""单元测试 — 工作空间"""

import os
import tempfile

from agc.core.workspace import Workspace, WorkspaceManager


def test_workspace_write_read():
    """写入并读取文件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Workspace(tmpdir, "test_agent")
        result = ws.write_file("hello.txt", "Hello, World!")
        assert "已写入" in result

        content = ws.read_file("hello.txt")
        assert content == "Hello, World!"


def test_workspace_list_files():
    """列出文件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Workspace(tmpdir, "test_agent")
        ws.write_file("file1.txt", "content1")
        ws.write_file("sub/file2.txt", "content2")

        listing = ws.list_files()
        assert "file1.txt" in listing
        assert "file2.txt" in listing


def test_workspace_security():
    """不能逃出工作空间"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Workspace(tmpdir, "test_agent")
        result = ws.write_file("../escape.txt", "hack!")
        assert "安全错误" in result

        result = ws.read_file("../escape.txt")
        assert "安全错误" in result


def test_workspace_manager():
    """WorkspaceManager 创建和管理多个工作空间"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = WorkspaceManager(tmpdir)
        ws1 = mgr.get("agent_a")
        ws2 = mgr.get("agent_b")

        ws1.write_file("note.md", "# Agent A notes")
        ws2.write_file("code.py", "print('hello')")

        # agent_a 可以只读访问 agent_b 的文件
        content = ws1.read_other_workspace("agent_b", "code.py")
        assert "hello" in content

        # 获取概要
        summary = mgr.get_all_summaries()
        assert "agent_a" in summary
        assert "agent_b" in summary

        # 清理
        mgr.cleanup()
        assert not os.path.exists(mgr.root)


def test_workspace_default_path():
    """默认路径是 ./data/workspaces"""
    mgr = WorkspaceManager()
    assert str(mgr.root).endswith("data/workspaces")