# Agent 工具调用与思考过程 Panel 展示

> 创建日期: 2026-05-12

## 目标

让 agent 调用工具和思考（reasoning）过程在终端 Stream Panel 中实时可见，
形成完整的"思考 → 调工具 → 看结果 → 回复"可视化链路。

## 需求摘要

1. **Reasoning 实时流式显示** — DeepSeek thinking 模型返回的 `reasoning_content` 在 Panel 中逐字流式展示
2. **工具调用详情** — 显示工具名称 + 参数摘要（非仅名称）
3. **工具结果摘要** — 成功和失败都在 Panel 中可见
4. **动作日志累积** — 多轮工具调用按时间顺序全部展示
5. **两模式统一** — TopicSession 和 FreeChatSession 都展示工具调用

## 设计

### 1. 数据流架构

新增 `on_reasoning_chunk` 回调链，与现有 `on_message`/`on_chunk`/`on_speaker_start` 并列：

```
DeepSeek API ─(streaming)─→ OpenAIClient._streamed_chat()
    │ delta.reasoning_content
    ▼
on_reasoning_chunk(text)
    │
    ▼
ChatSession._emit_reasoning(text)
    │
    ▼
CliDisplay.on_reasoning_chunk(text)
    │
    ▼
_reasoning_buf += text → _update_live()
```

### 2. Panel 状态模型

```python
# CliDisplay 实例状态
self._streaming: bool         # 是否正在流式输出（保留）
self._stream_name: str        # 当前说话 agent（保留）
self._stream_buf: str         # 回复内容缓冲区（保留）
self._reasoning_buf: str      # 当前轮 reasoning 缓冲区（新增）
self._action_log: list[str]   # 已完成动作日志（新增，替代 _tool_status）
```

### 3. Panel 内容布局（`_build_panel()`）

语法: 三段式，`\n\n` 分隔：

```
[dim]💭 思考: {reasoning_buf}[/dim]       ← reasoning 流式中
[dim]🔧 调用 xxx(...)[/dim]               ← action_log 每行一条
[dim]✅ xxx → 结果摘要[/dim]
{stream_buf}                              ← 回复内容
```

如果三段均为空 → `[dim]⏳ 思考中...[/dim]`

### 4. 事件处理

| 事件 | 操作 |
|---|---|
| `begin_stream()` | 重置 `_reasoning_buf=""`, `_action_log=[]`, 创建 Live |
| `on_reasoning_chunk(t)` | `_reasoning_buf += t`, `_update_live()` |
| `on_message(tool_call)` | flush reasoning→action_log; 添加 `"🔧 调用 {name}({args})"`; 清空 `_reasoning_buf`; `_update_live()` |
| `on_message(tool_result)` | 添加 `"✅/❌ {name} → {摘要}"`; `_update_live()` |
| `on_message(chat, sender)` | flush reasoning; `_stop_live()` |

**Flush 规则**: 触发 tool_call 或最终消息时，若 `_reasoning_buf` 非空，格式化为 `"💭 {内容}"` 追加到 `_action_log`，然后清空。

### 5. 工具参数摘要

从 `message.tool_calls[].function.arguments` (JSON) 提取：

```
web_search(query="AI trends 2025", max_results=5)
```

- 单行，超 60 字符截断加 `...`
- 格式: `🔧 调用 {name}({key1}="{val1}", {key2}={val2}...)`

### 6. 工具结果摘要

```python
# 成功: content 前 80 字符，去换行
"✅ {name} → {content[:80]}..."

# 失败: content 前 120 字符
"❌ {name} → {content[:120]}"
```

### 7. FreeChatSession 修复

`_execute_tool_calls()` 改用 `_notify_display(msg)`（与 TopicSession 一致），
绕过 `_emit_message()` 中的 `_emitted` 检查。

## 改动文件

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `agc/llm/base.py` | Modify | `chat()` 签名加 `on_reasoning_chunk` 参数 |
| `agc/llm/openai_client.py` | Modify | `_streamed_chat()` 调用 reasoning 回调 |
| `agc/ui/base.py` | Modify | 新增 `on_reasoning_chunk()` 方法 |
| `agc/ui/cli_display.py` | Modify | `_reasoning_buf`, `_action_log`, 新 `on_reasoning_chunk()`, 新 `_build_panel()` |
| `agc/core/session.py` | Modify | 新增 `_on_reasoning_callbacks`, `_emit_reasoning()` |
| `agc/core/chatroom.py` | Modify | `llm.chat()` 传 `on_reasoning_chunk` 回调 |
| `agc/core/freechat.py` | Modify | `llm.chat()` 传 reasoning 回调; `_execute_tool_calls()` 用 `_notify_display` |

## 测试

### 新增单元测试

- `test_reasoning_shown_in_live`
- `test_tool_call_adds_to_action_log`
- `test_tool_result_adds_to_action_log`
- `test_reasoning_flushed_on_tool_call`
- `test_begin_stream_resets_state`
- `test_tool_result_failure_shown`
- `test_no_reasoning_no_action_shows_thinking`

### 回归

```bash
uv run pytest tests/ -v
uv run ruff check
```
