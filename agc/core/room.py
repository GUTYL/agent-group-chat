"""Room 配置模型"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .agent import AgentConfig


class RoomConfig(BaseModel):
    """群聊房间配置"""

    name: str                                    # 房间名
    agents: list[AgentConfig]                   # 参与者列表
    scheduler: str = "hybrid"                   # 调度策略: round_robin / hybrid
    max_rounds: int = 20                         # 最大总轮数
    terminator: str = "consensus"                # 终止策略: consensus / max_rounds / keyword
    human_in_loop: bool = False                 # 人类介入点
    context_window: int = 8000                   # 上下文token上限
    summary_on_overflow: bool = True            # 溢出时摘要压缩
    verbose: bool = True                         # 是否打印详细过程
    base_url: str | None = None                 # 全局LLM API端点
    api_key: str | None = None                  # 全局API Key