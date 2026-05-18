"""01 最简群聊示例 — 用Python API启动"""

from agc.core.agent import AgentConfig
from agc.core.chatroom import TopicSession
from agc.llm import OpenAIClient
from agc.ui import CliDisplay


def main():
    llm = OpenAIClient()
    agents = [
        AgentConfig(
            name="researcher",
            role="研究员",
            goal="深入调研",
            backstory="严谨的研究员",
            model="gpt-4o",
        ),
        AgentConfig(
            name="architect",
            role="架构师",
            goal="设计方案",
            backstory="经验丰富的架构师",
            model="gpt-4o",
        ),
    ]
    room = TopicSession(
        name="demo",
        agents=agents,
        llm=llm,
        workspace_root="./data/workspaces",
    )
    display = CliDisplay()
    room.on_message(display.on_message)
    room.on_chunk(display.on_chunk)
    room.on_speaker_start(display.begin_stream)
    display.print_header("API限流策略应该怎么选？", agents)
    result = room.chat("API限流策略应该怎么选？")
    display.print_result(result)


if __name__ == "__main__":
    main()
