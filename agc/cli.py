"""AGC 命令行入口"""

from __future__ import annotations

import os
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv

from agc.core.agent import AgentConfig
from agc.core.chatroom import ChatRoom
from agc.core.freechat import FreeChatSession
from agc.core.human_in_loop import HumanInTheLoop, HumanMode
from agc.core.session import SessionStore
from agc.tools.search import create_search_tool

# 启动时加载 .env 文件
load_dotenv()

app = typer.Typer(
    name="agc",
    help="Agent Group Chat — 多Agent群聊框架",
    add_completion=False,
)


def _load_config(path: Path) -> dict:
    """加载YAML配置文件"""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_agents(config: dict) -> list[AgentConfig]:
    """从配置构建Agent列表"""
    agents = []
    for a in config.get("agents", []):
        agents.append(AgentConfig(**a))
    return agents


def _setup_tools(tools_str: str | None, search_provider: str) -> list[str]:
    """初始化搜索工具（如果显式指定）

    注意：web_fetch, workspace, memory 工具由 ChatRoom 自动注册，
    这里只处理搜索工具的显式指定和后端注册。
    """
    tool_names = [t.strip() for t in tools_str.split(",") if t.strip()] if tools_str else []

    for name in tool_names:
        if name == "web_search":
            create_search_tool(provider=search_provider)

    return tool_names


@app.command()
def chat(
    topic: str = typer.Argument(help="讨论话题"),
    config: Path | None = typer.Option(None, "--config", "-c", help="YAML配置文件路径"),
    scheduler: str = typer.Option(
        "hybrid", "--scheduler", "-s", help="调度策略: round_robin / hybrid"
    ),
    max_rounds: int = typer.Option(20, "--max-rounds", "-r", help="最大轮数"),
    model: str = typer.Option(
        os.environ.get("OPENAI_MODEL", "gpt-4o"), "--model", "-m", help="默认LLM模型"
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", "-b", help="LLM API端点(如 https://api.deepseek.com/v1)"
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", "-k", help="API Key(也可用OPENAI_API_KEY环境变量)"
    ),
    tools: str | None = typer.Option(
        None, "--tools", "-t", help="额外启用的工具(逗号分隔)，如: web_search。其他工具自动注册。"
    ),
    search: str = typer.Option("duckduckgo", "--search", help="搜索后端: duckduckgo"),
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="工作空间目录(默认: ./data/workspaces)"
    ),
    human: str = typer.Option("off", "--human", help="人类介入模式: off / always / on_demand"),
    human_name: str = typer.Option("human", "--human-name", help="人类在群聊中的名字"),
    verbose: bool = typer.Option(True, "--verbose/--quiet", help="是否显示详细过程"),
):
    """启动一个多Agent群聊讨论"""

    # 初始化工具（搜索后端等显式指定项）
    tool_names = _setup_tools(tools, search)

    # 构建agents
    if config and config.exists():
        cfg = _load_config(config)
        agents = _build_agents(cfg)
        scheduler = cfg.get("scheduler", scheduler)
        max_rounds = cfg.get("max_rounds", max_rounds)
        model = cfg.get("model", model)
        base_url = cfg.get("base_url", base_url)
        api_key = cfg.get("api_key", api_key)
        if not tool_names and "tools" in cfg:
            tool_names = _setup_tools(",".join(cfg["tools"]), search)
        # 从配置读human和workspace
        if human == "off":
            human = cfg.get("human", "off")
        if not workspace:
            workspace = cfg.get("workspace")
    else:
        # 默认3人组
        agents = [
            AgentConfig(
                name="researcher",
                role="资深研究员",
                goal="深入调研问题，提供信息支撑，善于发现关键细节",
                backstory="你是一位严谨的研究员，擅长搜索和整理信息。你总是先搞清楚问题的全貌，再让别人介入讨论。你会用数据和事实说话，不凭直觉下结论。",
                model=model,
                tools=tool_names if tool_names else [],
            ),
            AgentConfig(
                name="architect",
                role="系统架构师",
                goal="设计方案，评估可行性和风险，做出权衡取舍",
                backstory="你有10年架构经验，善于权衡取舍。你会指出别人忽略的边界条件和系统风险。你倾向简洁可靠的方案，而不是过度设计。",
                model=model,
                tools=tool_names if tool_names else [],
            ),
            AgentConfig(
                name="reviewer",
                role="魔鬼代言人",
                goal="质疑和验证结论，防止团队思维和共识谬误",
                backstory="你天生怀疑一切，不轻易认同。你总是找反例和漏洞，逼迫团队思考得更深入。你的价值在于别人都同意时你说'等等，万一呢？'",
                model=model,
                tools=tool_names if tool_names else [],
            ),
        ]

    # API Key: CLI参数 > 环境变量 > 配置文件
    effective_api_key = api_key or os.environ.get("OPENAI_API_KEY")
    effective_base_url = base_url or os.environ.get("OPENAI_BASE_URL")

    # 工作空间
    workspace_root = workspace or "./data/workspaces"

    # 人类参与
    human_loop = HumanInTheLoop.create(mode_str=human, name=human_name)

    # 创建群聊
    room = ChatRoom(
        name="group-chat",
        agents=agents,
        scheduler=scheduler,
        max_rounds=max_rounds,
        verbose=verbose,
        base_url=effective_base_url,
        api_key=effective_api_key,
        tools=tool_names if tool_names else [],
        workspace_root=workspace_root,
        human=human_loop if human_loop.mode != HumanMode.off else None,
    )

    # 设置输出
    from agc.ui import CliDisplay

    display = CliDisplay()
    room.on_message(display.on_message)
    room.on_chunk(display.on_chunk)
    room.on_speaker_start(display.begin_stream)
    display.print_header(topic, agents, human_loop=human_loop)
    result = room.chat(topic)
    display.print_result(result)


@app.command()
def room(
    config: Path | None = typer.Option(None, "--config", "-c", help="YAML配置文件路径"),
    name: str | None = typer.Option(None, "--name", help="指定会话名称（跳过LLM自动命名）"),
    resume: str | None = typer.Option(None, "--resume", help="恢复历史会话（支持前缀匹配）"),
    list_sessions: bool = typer.Option(False, "--list", help="列出所有历史会话"),
    model: str = typer.Option(
        os.environ.get("OPENAI_MODEL", "gpt-4o"), "--model", "-m", help="默认LLM模型"
    ),
    base_url: str | None = typer.Option(None, "--base-url", "-b", help="LLM API端点"),
    api_key: str | None = typer.Option(None, "--api-key", "-k", help="API Key"),
    tools: str | None = typer.Option(None, "--tools", "-t", help="额外启用的工具(逗号分隔)"),
    search: str = typer.Option("duckduckgo", "--search", help="搜索后端: duckduckgo"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="工作空间目录"),
    user_name: str = typer.Option("human", "--user-name", help="人类用户在群聊中的名字"),
):
    """启动IM风格自由群聊"""

    # --list: 列出所有会话
    if list_sessions:
        store = SessionStore()
        sessions = store.list_sessions()
        if not sessions:
            typer.echo("暂无保存的会话。")
        else:
            typer.echo("已保存的会话:")
            for s in sessions:
                typer.echo(f"  {s}")
        return

    tool_names = _setup_tools(tools, search)

    # 构建agents
    if config and config.exists():
        cfg = _load_config(config)
        agents = _build_agents(cfg)
        base_url = base_url or cfg.get("base_url")
        api_key = api_key or cfg.get("api_key")
        if not tool_names and "tools" in cfg:
            tool_names = _setup_tools(",".join(cfg["tools"]), search)
    else:
        agents = [
            AgentConfig(
                name="researcher",
                role="资深研究员",
                goal="深入调研问题，提供信息支撑",
                backstory="你是一位严谨的研究员，擅长搜索和整理信息。你会用数据和事实说话，不凭直觉下结论。",
                model=model,
                tools=tool_names if tool_names else [],
            ),
            AgentConfig(
                name="architect",
                role="系统架构师",
                goal="设计方案，评估可行性和风险，做出权衡取舍",
                backstory="你有10年架构经验，善于权衡取舍。你会指出别人忽略的边界条件和系统风险。",
                model=model,
                tools=tool_names if tool_names else [],
            ),
            AgentConfig(
                name="reviewer",
                role="魔鬼代言人",
                goal="质疑和验证结论，防止团队思维",
                backstory="你天生怀疑一切，不轻易认同。你的价值在于别人都同意时你说'等等，万一呢？'",
                model=model,
                tools=tool_names if tool_names else [],
            ),
        ]

    effective_api_key = api_key or os.environ.get("OPENAI_API_KEY")
    effective_base_url = base_url or os.environ.get("OPENAI_BASE_URL")
    workspace_root = workspace or "./data/workspaces"

    store = SessionStore()
    session_id = None

    # --resume: 恢复会话
    if resume:
        try:
            sessions = store.list_sessions()
            matched = [s for s in sessions if s.startswith(resume)]
            if len(matched) == 1:
                session_id = matched[0]
            elif len(matched) > 1:
                typer.echo(f"前缀 '{resume}' 匹配到多个会话: {matched}")
                return
            else:
                session_id = resume
        except Exception as e:
            typer.echo(f"无法找到会话: {e}")
            return

    # --name: 指定名称
    if name and not resume:
        session_id = store.create_session()
        session_id = store.rename_session(session_id, name)

    session = FreeChatSession(
        agents=agents,
        user_name=user_name,
        base_url=effective_base_url,
        api_key=effective_api_key,
        tools=tool_names if tool_names else [],
        workspace_root=workspace_root,
        session_id=session_id,
        session_store=store,
    )

    # 设置显示
    from agc.ui import CliDisplay

    display = CliDisplay()
    session.on_message(display.on_message)
    session.on_chunk(display.on_chunk)
    session.on_speaker_start(display.begin_stream)

    if resume and session_id:
        try:
            session.load_session(session_id)
            session._build_system_prompts()
        except Exception as e:
            typer.echo(f"加载会话失败: {e}")
            return

    session.run()


@app.command()
def agents():
    """列出可用的预设Agent模板"""
    from agc.templates import list_templates

    templates = list_templates()
    for name, desc in templates.items():
        typer.echo(f"  {name}: {desc}")


@app.command()
def tools_list():
    """列出可用的工具"""
    from agc.tools.base import list_tools

    available = list_tools()
    if not available:
        typer.echo("暂无已注册工具。工具会在启动群聊时自动注册。")
    else:
        for name, desc in available.items():
            typer.echo(f"  {name}: {desc}")


if __name__ == "__main__":
    app()
