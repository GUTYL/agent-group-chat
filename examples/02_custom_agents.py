"""02 自定义Agent配置示例"""

from agc.core.agent import AgentConfig
from agc.core.chatroom import ChatRoom
from agc.llm import OpenAIClient
from agc.templates import get_template
from agc.ui import CliDisplay


def main():
    # 使用预设模板 + 自定义
    researcher = get_template("researcher")
    architect = get_template("architect")
    developer = get_template("developer")
    reviewer = get_template("reviewer")

    # 自定义额外指令
    researcher.system_prompt_extra = "请特别关注性能和数据层面的考量。"
    architect.system_prompt_extra = "请考虑可扩展性和运维成本。"

    llm = OpenAIClient()
    room = ChatRoom(
        name="custom-team",
        agents=[researcher, architect, developer, reviewer],
        llm=llm,
        scheduler="hybrid",  # @mention + 关键词路由 + LLM兜底
        max_rounds=15,
    )

    display = CliDisplay()
    room.on_message(display.on_message)
    display.print_header("如何设计一个高并发的消息队列系统？", room.config.agents)

    result = room.chat("如何设计一个高并发的消息队列系统？需要考虑哪些关键设计决策？")
    display.print_result(result)


if __name__ == "__main__":
    main()