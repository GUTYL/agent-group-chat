"""单元测试 — 记忆工具"""

import os
import tempfile

from agc.core.workspace import WorkspaceManager
from agc.tools.memory import (
    SaveMemoryTool, RecallMemoryTool, ListMemoriesTool, DeleteMemoryTool,
    register_memory_tools,
)
from agc.tools.base import execute_tool_call, get_tool


def _make_mgr():
    """创建临时工作空间管理器"""
    return WorkspaceManager(tempfile.mkdtemp())


def test_save_and_recall():
    """保存并召回记忆"""
    mgr = _make_mgr()
    save = SaveMemoryTool(mgr)
    recall = RecallMemoryTool(mgr)

    # 保存
    result = save.execute(key="限流方案", value="令牌桶适合突发流量", tags="架构,限流", _owner="researcher")
    assert result.success
    assert "已保存" in result.content

    # 召回
    result = recall.execute(query="限流", _owner="researcher")
    assert result.success
    assert "令牌桶" in result.content


def test_save_updates_existing():
    """重复保存同一key会更新"""
    mgr = _make_mgr()
    save = SaveMemoryTool(mgr)
    recall = RecallMemoryTool(mgr)

    save.execute(key="结论", value="方案A最好", _owner="architect")
    save.execute(key="结论", value="方案B更好", _owner="architect")

    result = recall.execute(query="结论", _owner="architect")
    assert result.success
    assert "方案B" in result.content
    assert "方案A" not in result.content


def test_recall_not_found():
    """搜索不存在的记忆"""
    mgr = _make_mgr()
    recall = RecallMemoryTool(mgr)

    result = recall.execute(query="不存在的key", _owner="researcher")
    assert not result.success
    assert "没有找到" in result.content


def test_list_memories():
    """列出所有记忆"""
    mgr = _make_mgr()
    save = SaveMemoryTool(mgr)
    lst = ListMemoriesTool(mgr)

    # 空记忆
    result = lst.execute(_owner="researcher")
    assert result.success
    assert "为空" in result.content

    # 添加几条
    save.execute(key="A", value="val a", tags="架构", _owner="researcher")
    save.execute(key="B", value="val b", tags="限流", _owner="researcher")

    result = lst.execute(_owner="researcher")
    assert result.success
    assert "2 条" in result.content

    # 按标签筛选
    result = lst.execute(tag="架构", _owner="researcher")
    assert result.success
    assert "A" in result.content


def test_delete_memory():
    """删除记忆"""
    mgr = _make_mgr()
    save = SaveMemoryTool(mgr)
    delete = DeleteMemoryTool(mgr)
    recall = RecallMemoryTool(mgr)

    save.execute(key="要删的", value="内容", _owner="researcher")
    result = delete.execute(key="要删的", _owner="researcher")
    assert result.success
    assert "已删除" in result.content

    # 删除后再搜
    result = recall.execute(query="要删的", _owner="researcher")
    assert not result.success


def test_delete_nonexistent():
    """删除不存在的记忆"""
    mgr = _make_mgr()
    delete = DeleteMemoryTool(mgr)
    result = delete.execute(key="不存在", _owner="researcher")
    assert not result.success


def test_memory_isolation():
    """不同agent的记忆互相隔离"""
    mgr = _make_mgr()
    save = SaveMemoryTool(mgr)
    recall = RecallMemoryTool(mgr)

    save.execute(key="架构", value="微服务", _owner="architect")
    save.execute(key="架构", value="单体", _owner="researcher")

    r1 = recall.execute(query="架构", _owner="architect")
    assert "微服务" in r1.content

    r2 = recall.execute(query="架构", _owner="researcher")
    assert "单体" in r2.content


def test_tag_search():
    """通过标签搜索（recall也应匹配标签）"""
    mgr = _make_mgr()
    save = SaveMemoryTool(mgr)
    recall = RecallMemoryTool(mgr)

    save.execute(key="部署策略", value="蓝绿部署最安全", tags="部署,运维", _owner="architect")
    save.execute(key="限流策略", value="令牌桶算法", tags="限流,架构", _owner="architect")

    # 用标签关键词搜索
    result = recall.execute(query="运维", _owner="architect")
    assert result.success
    assert "蓝绿部署" in result.content


def test_register_memory_tools():
    """注册所有记忆工具"""
    mgr = _make_mgr()
    names = register_memory_tools(mgr)
    assert "save_memory" in names
    assert "recall_memory" in names
    assert "list_memories" in names
    assert "delete_memory" in names

    # 验证注册到全局工具库
    assert get_tool("save_memory") is not None
    assert get_tool("recall_memory") is not None


def test_execute_tool_call_memory():
    """通过 execute_tool_call 使用记忆工具"""
    mgr = _make_mgr()
    register_memory_tools(mgr)

    result = execute_tool_call("save_memory", {
        "key": "测试key",
        "value": "测试value",
        "tags": "test",
    }, owner="researcher")
    assert result.success

    result = execute_tool_call("recall_memory", {
        "query": "测试",
    }, owner="researcher")
    assert result.success
    assert "测试value" in result.content