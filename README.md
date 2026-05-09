# Agent Group Chat (AGC)

多Agent群聊框架 — 多个AI角色在群中自由讨论、互相提问、协作解决问题。

## 特性

- **智能调度** — Hybrid调度策略支持 @提及、关键词路由、LLM路由，自动选择最合适的发言人
- **自动终止** — 共识检测 + 最大轮次双重保障，对话在达成结论或超时后自动结束
- **工具生态** — 内置网页搜索（DuckDuckGo）、网页抓取、工作空间（文件读写+代码执行）、持久化记忆
- **流式输出** — LLM 回复实时流式显示，打字机效果
- **人类介入** — 支持 `always`（每轮等待）/ `on_demand`（随时介入）/ `off` 三种模式
- **YAML配置** — 用声明式配置文件定义Agent和群聊参数
- **OpenAI兼容** — 支持所有OpenAI兼容的API端点（DeepSeek、本地模型等）
- **Rich终端UI** — 彩色角色标识、结构化消息展示

## 快速开始

### 安装

```bash
pip install -e .
```

配置API Key（任选一种）：

```bash
# 方式一：.env 文件（推荐）
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 方式二：环境变量
export OPENAI_API_KEY="sk-xxx"
export OPENAI_BASE_URL="https://api.deepseek.com/v1"
```

`.env` 支持的变量：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | API Key（必填） |
| `OPENAI_BASE_URL` | 自定义API端点（可选，默认 OpenAI） |
| `OPENAI_MODEL` | 默认模型（可选，默认 gpt-4o） |

### CLI 方式

```bash
# 默认角色组（研究员+架构师+审查者）
agc chat "API限流策略应该怎么选？"

# 自定义参数
agc chat "如何设计高并发消息队列" \
  --scheduler hybrid \
  --max-rounds 15 \
  --model gpt-4o \
  --tools web_search \
  --workspace ./data/workspaces \
  --human on_demand

# 使用YAML配置文件
agc chat "微服务还是单体？" --config examples/03_yaml_config.yaml

# 列出命令
agc --help
agc agents      # 列出预设Agent模板
agc tools-list  # 列出可用工具
```

### Python API 方式

```python
from agc.core.agent import AgentConfig
from agc.core.chatroom import ChatRoom
from agc.core.human_in_loop import HumanInTheLoop, HumanMode
from agc.ui import CliDisplay

agents = [
    AgentConfig(
        name="researcher",
        role="资深研究员",
        goal="深入调研问题，提供信息支撑",
        backstory="你擅长搜索事实、数据佐证，不凭直觉下结论。",
    ),
    AgentConfig(
        name="architect",
        role="系统架构师",
        goal="设计方案，评估可行性",
        backstory="你有10年架构经验，善于权衡取舍。",
    ),
]

human = HumanInTheLoop(mode=HumanMode.on_demand, name="主持人")

room = ChatRoom(
    name="demo",
    agents=agents,
    tools=["web_search"],
    workspace_root="./data/workspaces",
    human=human,
)

display = CliDisplay()
room.on_message(display.on_message)
display.print_header("如何处理分布式事务？", agents)

result = room.chat("如何处理分布式事务？")
display.print_result(result)
```

更多示例见 `examples/` 目录。

## 架构

```
agc/
├── cli.py           # CLI入口（typer）
├── core/            # 核心模块
│   ├── agent.py     # AgentConfig — 角色定义
│   ├── chatroom.py  # ChatRoom — 群聊编排引擎
│   ├── context.py   # ContextManager — Token感知的上下文窗口
│   ├── workspace.py # WorkspaceManager — 多Agent工作空间
│   └── message.py   # Message / MessageType 定义
├── llm/             # LLM客户端抽象
│   ├── base.py      # LLMBase 抽象接口
│   └── openai_client.py  # OpenAI SDK 封装
├── schedulers/      # 发言调度策略
│   ├── round_robin.py    # 简单轮转
│   └── hybrid.py         # 混合调度（@提及 > 关键词 > LLM路由 > 轮转兜底）
├── terminators/     # 终止检测
│   ├── consensus.py      # 共识检测（信号词计数）
│   ├── max_rounds.py     # 硬性轮次上限
│   └── composite.py      # 组合终止器（OR逻辑）
├── tools/           # Agent工具
│   ├── web_fetch.py      # 网页抓取（readability-lxml）
│   ├── search.py         # 网络搜索（DuckDuckGo）
│   ├── memory.py         # 持久化记忆（save/recall/list/delete）
│   └── workspace.py      # 工作空间（文件读写+代码执行）
├── ui/              # 终端界面
│   └── cli_display.py    # Rich彩色输出
└── templates/       # 预设Agent模板（6种角色）
```

## 核心概念

### Agent — AI参与者

每个Agent有独立的角色、目标和人设，通过 `AgentConfig` 定义：

| 字段 | 说明 |
|------|------|
| `name` | 唯一标识（英文，如 `researcher`） |
| `role` | 角色名（如 `资深研究员`） |
| `goal` | 在讨论中的目标 |
| `backstory` | 人设/背景描述 |
| `model` | LLM模型（默认 `gpt-4o`） |
| `tools` | 工具白名单（空=使用全局工具） |
| `max_turns` | 最大发言次数（0=不限） |
| `temperature` | 采样温度（默认 0.7） |

### ChatRoom — 群聊引擎

`ChatRoom` 是核心编排器，负责整个讨论生命周期：

1. 根据 `topic` 启动讨论，发出初始话题
2. 每轮由 `Scheduler` 选择下一个发言人
3. Agent生成回复（支持工具调用循环，最多3轮）
4. 解析 @提及，支持定向点名
5. 人类可在预设节点插入发言
6. `Terminator` 检测是否应结束对话
7. 生成结构化总结

### Scheduler — 调度策略

- **round_robin** — 简单轮转：A → B → C → A → ...
- **hybrid**（默认）— 四级优先级：
  1. @提及定向（如 `@architect 你觉得呢？`）
  2. 关键词路由（如提到"架构"则路由给architect）
  3. LLM路由（让AI决定谁该说话）
  4. 轮转兜底

### Terminator — 终止策略

- **consensus** — 检测最近N轮中共识信号词（同意、总结等）与异议信号词（反对、但是等）的比例，阈值达到即终止
- **max_rounds** — 硬性轮次上限，防止无限对话
- **composite** — 组合多个终止器，任一击中即止

### 工具系统

| 工具 | 说明 | 注册条件 |
|------|------|----------|
| `web_fetch` | 抓取网页全文，提取可读内容 | 始终自动注册 |
| `web_search` | 搜索互联网（DuckDuckGo，免费无需 API Key） | 自动注册 |
| `write_file` | 在Agent工作空间中写入文件 | 启用工作空间时注册 |
| `read_file` | 读取自己或其他Agent的文件 | 启用工作空间时注册 |
| `list_files` | 列出工作空间目录内容 | 启用工作空间时注册 |
| `run_code` | 执行Shell命令 | 启用工作空间时注册 |
| `save_memory` | 保存关键事实到持久化记忆 | 启用工作空间时注册 |
| `recall_memory` | 搜索已保存的记忆 | 启用工作空间时注册 |
| `list_memories` | 列出所有记忆 | 启用工作空间时注册 |
| `delete_memory` | 删除指定记忆 | 启用工作空间时注册 |

### 预设Agent模板

| 模板 | 描述 |
|------|------|
| `researcher` | 资深研究员 — 深入调研问题，提供信息支撑 |
| `architect` | 系统架构师 — 设计方案，评估可行性和风险 |
| `developer` | 高级开发者 — 提供具体实现方案和代码 |
| `reviewer` | 魔鬼代言人 — 质疑验证结论，防止共识谬误 |
| `pm` | 产品经理 — 关注用户需求和优先级 |
| `analyst` | 数据分析师 — 用数据说话，量化分析 |

## 运行测试

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
