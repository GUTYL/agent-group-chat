# Agent Group Chat (AGC)

多Agent群聊框架 — 多个AI角色在群中自由讨论、互相提问、协作解决问题。

## 快速开始

```bash
pip install -e .

# CLI 方式
agc chat --topic "API限流策略应该怎么选？"

# Python 方式
python examples/01_simple_chat.py
```

## 核心概念

- **Agent** — 带角色、目标、人设的AI参与者
- **Room** — 群聊房间，管理调度和上下文
- **Scheduler** — 决定谁该说话（@mention优先 / Router兜底）
- **Terminator** — 检测对话是否该结束（共识 / 最大轮次）

## License

MIT