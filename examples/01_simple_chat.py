"""01 最简群聊示例 — 用Python API启动"""

from agc.core.agent import AgentConfig
from agc.core.chatroom import ChatRoom
from agc.core.human_in_loop import HumanInTheLoop, HumanMode
from agc.llm import OpenAIClient
from agc.tools.search import create_search_tool
from agc.ui import CliDisplay


def main():
    # 1. 定义角色
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

    # 2. 创建LLM客户端（也可传 base_url 指向兼容OpenAI的服务）
    # llm = OpenAIClient(base_url="https://api.deepseek.com/v1")
    llm = OpenAIClient()  # 从环境变量读取 OPENAI_API_KEY

    # 3. 初始化搜索工具（可选）
    create_search_tool(provider="duckduckgo")

    # 4. 创建人类参与模块（可选）
    # HumanMode.always = 每轮暂停等人类输入
    # HumanMode.on_demand = 人类随时可介入
    # HumanMode.off = 不参与
    human = HumanInTheLoop(mode=HumanMode.on_demand, name="主持人")

    # 5. 创建群聊房间
    room = ChatRoom(
        name="demo",
        agents=agents,
        llm=llm,
        tools=["web_search"],  # 启用搜索
        workspace_root="./data/workspaces",  # 每个agent独立工作空间
        human=human,  # 人类参与
    )

    # 6. 设置输出
    display = CliDisplay()
    room.on_message(display.on_message)
    display.print_header("API限流策略应该怎么选？", agents, human_loop=human)

    # 7. 开始讨论
    result = room.chat("API限流策略应该怎么选？")
    display.print_result(result)


if __name__ == "__main__":
    main()
