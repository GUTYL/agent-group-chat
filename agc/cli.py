"""AGC 命令行入口"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv

from agc import DEFAULT_SESSIONS_DIR, DEFAULT_WORKSPACES_DIR
from agc.core.agent import AgentConfig
from agc.core.chatroom import TopicSession
from agc.core.freechat import FreeChatSession
from agc.core.human_in_loop import HumanInTheLoop, HumanMode
from agc.core.session import SessionStore
from agc.log_config import setup_logging
from agc.tools.search import create_search_tool

# 启动时加载 .env 文件
load_dotenv()

app = typer.Typer(
    name="agc",
    help="Agent Group Chat — 多Agent群聊框架",
    add_completion=False,
    pretty_exceptions_enable=False,
)


def version_callback(value: bool) -> None:
    if value:
        from agc import __version__

        typer.echo(f"agc v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", help="显示版本号", callback=version_callback, is_eager=True
    ),
) -> None:
    """Agent Group Chat — 多Agent群聊框架"""


def _load_config(path: Path) -> dict:
    """加载YAML配置文件"""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        typer.echo(f"配置文件语法错误: {e}")
        raise typer.Exit(1) from None
    except OSError as e:
        typer.echo(f"无法读取配置文件: {e}")
        raise typer.Exit(1) from None


def _build_agents(config: dict) -> list[AgentConfig]:
    """从配置构建Agent列表"""
    agents = []
    for a in config.get("agents", []):
        agents.append(AgentConfig(**a))
    return agents


def _setup_tools(tools_str: str | None, search_provider: str) -> list[str]:
    """初始化搜索工具（如果显式指定）

    注意：web_fetch, workspace, memory 工具由 TopicSession 自动注册，
    这里只处理搜索工具的显式指定和后端注册。
    """
    tool_names = [t.strip() for t in tools_str.split(",") if t.strip()] if tools_str else []

    for name in tool_names:
        if name == "web_search":
            create_search_tool(provider=search_provider)

    return tool_names


def _safe_log_id(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", text)[:50]


def _wire_display(session, display) -> None:
    """统一注册 display 回调到 session，避免两个命令间重复 wiring。"""
    session.on_message(display.on_message)
    session.on_chunk(display.on_chunk)
    session.on_speaker_start(display.begin_stream)
    session.on_reasoning(display.on_reasoning_chunk)
    session.on_tool_batch(display.flush_tool_status)


_DEFAULT_AGENT_NAMES = ["researcher", "architect", "reviewer"]


def _make_default_agents(model: str, tool_names: list[str]) -> list[AgentConfig]:
    """从 templates 模块构建默认 Agent 列表，避免硬编码重复。"""
    from agc.templates import TEMPLATES

    agents = []
    for name in _DEFAULT_AGENT_NAMES:
        cfg = dict(TEMPLATES[name]["config"])
        cfg["model"] = model
        cfg["tools"] = tool_names if tool_names else []
        agents.append(AgentConfig(**cfg))
    return agents


def _save_topic_session(topic: str, result) -> None:
    """保存话题讨论总结到 data/sessions/topics/"""
    sessions_dir = DEFAULT_SESSIONS_DIR / "topics"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_topic = re.sub(r'[\\/:*?"<>|]', "_", topic)[:30]
    filename = f"{ts}_{safe_topic}.json"
    data = {
        "topic": topic,
        "timestamp": ts,
        "rounds": result.rounds,
        "total_tokens": result.total_tokens,
        "stop_reason": result.stop_reason,
        "summary": result.summary,
        "message_count": len(result.messages),
    }
    try:
        with open(sessions_dir / filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        typer.echo(f"会话总结保存失败: {e}")


@app.command()
def topic(
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
    log_level: str = typer.Option("INFO", "--log-level", help="日志级别: DEBUG/INFO/WARNING/ERROR"),
    log_dir: str = typer.Option("data/logs", "--log-dir", help="日志目录"),
    no_llm_route: bool = typer.Option(
        False, "--no-llm-route", help="禁用LLM智能路由，仅用关键词+轮询"
    ),
):
    """启动一个多Agent群聊讨论"""

    setup_logging(
        "topic",
        f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{_safe_log_id(topic)}",
        log_dir=log_dir,
        level=log_level,
    )

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
        agents = _make_default_agents(model, tool_names)

    # API Key: CLI参数 > 环境变量 > 配置文件
    effective_api_key = api_key or os.environ.get("OPENAI_API_KEY")
    effective_base_url = base_url or os.environ.get("OPENAI_BASE_URL")

    # 工作空间
    workspace_root = workspace or DEFAULT_WORKSPACES_DIR

    # 人类参与
    human_loop = HumanInTheLoop.create(mode_str=human, name=human_name)

    # 创建群聊
    room = TopicSession(
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
        use_llm_route=not no_llm_route,
    )

    # 设置输出
    from agc.ui import CliDisplay

    display = CliDisplay()
    _wire_display(room, display)
    display.print_header(topic, agents, human_loop=human_loop)
    result = room.chat(topic)
    display.print_result(result)

    # 保存会话总结
    _save_topic_session(topic, result)

    # 交互式追问循环：讨论结束后可以继续追问
    while True:
        try:
            follow_up = input("\n输入追问继续讨论，或按 Enter 退出: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not follow_up:
            break

        result = room.continue_chat(follow_up)
        display.print_result(result)
        _save_topic_session(topic, result)


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
    recent_window: int = typer.Option(
        50, "--recent-window", help="上下文滑动窗口大小（最近N条消息），长会话自动摘要压缩"
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="日志级别: DEBUG/INFO/WARNING/ERROR"),
    log_dir: str = typer.Option("data/logs", "--log-dir", help="日志目录"),
    no_llm_route: bool = typer.Option(
        False, "--no-llm-route", help="禁用LLM智能路由，仅用关键词+轮询"
    ),
):
    """启动IM风格自由群聊"""

    # --list: 列出所有会话
    if list_sessions:
        store = SessionStore(DEFAULT_SESSIONS_DIR / "freechat")
        sessions = store.list_sessions()
        if not sessions:
            typer.echo("暂无保存的会话。")
        else:
            typer.echo("已保存的会话:")
            for s in sessions:
                typer.echo(f"  {s}")
        return

    setup_logging("freechat", resume or name or "", log_dir=log_dir, level=log_level)

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
        agents = _make_default_agents(model, tool_names)

    effective_api_key = api_key or os.environ.get("OPENAI_API_KEY")
    effective_base_url = base_url or os.environ.get("OPENAI_BASE_URL")
    workspace_root = workspace or DEFAULT_WORKSPACES_DIR

    store = SessionStore(DEFAULT_SESSIONS_DIR / "freechat")
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
        use_llm_route=not no_llm_route,
        recent_window=recent_window,
    )

    # 设置显示
    from agc.ui import CliDisplay

    display = CliDisplay()
    _wire_display(session, display)
    session._display = display

    if resume and session_id:
        try:
            session.load_session(session_id)
            session._build_system_prompts()
        except Exception as e:
            typer.echo(f"加载会话失败: {e}")
            return

    session.run()


@app.command(name="templates")
@app.command(name="agents", hidden=True)
def list_templates():
    """列出可用的预设Agent模板"""
    from agc.templates import list_templates

    templates = list_templates()
    for name, desc in templates.items():
        typer.echo(f"  {name}: {desc}")


@app.command()
def tools_list():
    """列出可用的工具"""
    from agc.tools.base import _REGISTRY, list_tools

    # 预注册核心工具（无 workspace 需求）
    if "web_fetch" not in _REGISTRY:
        register_preview_tools()

    available = list_tools()
    if not available:
        typer.echo("暂无已注册工具。")
    else:
        for name, desc in available.items():
            typer.echo(f"  {name}: {desc}")


def register_preview_tools() -> None:
    """为预览/列表注册不依赖 workspace 的工具"""
    from agc.tools.base import _REGISTRY, register_tool
    from agc.tools.search import DuckDuckGoSearchTool
    from agc.tools.web_fetch import WebFetchTool

    if "web_fetch" not in _REGISTRY:
        register_tool(WebFetchTool())
    if "web_search" not in _REGISTRY:
        register_tool(DuckDuckGoSearchTool())


@app.command(name="sessions")
def sessions(
    list_all: bool = typer.Option(False, "--list", "-l", help="列出所有会话"),
    delete: str | None = typer.Option(None, "--delete", "-d", help="删除会话（前缀匹配）"),
    rename_old: str | None = typer.Option(None, "--rename", help="重命名会话（旧名/前缀）"),
    rename_new: str | None = typer.Option(None, "--to", help="重命名的新名称"),
):
    """管理已保存的会话（话题讨论 + 自由群聊）"""

    topics_dir = DEFAULT_SESSIONS_DIR / "topics"
    freechat_store = SessionStore(DEFAULT_SESSIONS_DIR / "freechat")

    def _list_topic_sessions() -> list[str]:
        if not topics_dir.exists():
            return []
        return sorted(f.stem for f in topics_dir.glob("*.json"))

    def _find_topic_session(prefix: str) -> Path | None:
        if not topics_dir.exists():
            return None
        matches = list(topics_dir.glob(f"{prefix}*.json"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            typer.echo(f"前缀 '{prefix}' 匹配到多个话题会话: {[m.stem for m in matches]}")
        return None

    # --list
    if list_all:
        topic_sessions = _list_topic_sessions()
        freechat_sessions = freechat_store.list_sessions()

        if not topic_sessions and not freechat_sessions:
            typer.echo("暂无保存的会话。")
            return

        if topic_sessions:
            typer.echo("话题讨论会话 (topics):")
            for s in topic_sessions:
                typer.echo(f"  {s}")
        if freechat_sessions:
            typer.echo("自由群聊会话 (freechat):")
            for s in freechat_sessions:
                typer.echo(f"  {s}")
        return

    # --delete
    if delete:
        # 尝试话题会话
        topic_path = _find_topic_session(delete)
        if topic_path:
            try:
                topic_path.unlink()
                typer.echo(f"已删除话题会话: {topic_path.stem}")
            except OSError as e:
                typer.echo(f"删除失败: {e}")
            return

        # 尝试自由群聊会话
        try:
            fc_path = freechat_store._resolve_path(delete)
            if not fc_path.exists():
                typer.echo(f"未找到会话 '{delete}'")
                return
            freechat_store.delete_session(delete)
            typer.echo(f"已删除自由群聊会话: {delete}")
        except Exception as e:
            typer.echo(f"未找到会话 '{delete}': {e}")
        return

    # --rename
    if rename_old:
        if not rename_new:
            typer.echo("请指定新名称: --to <新名称>")
            raise typer.Exit(1)

        # 自由群聊会话支持 rename
        try:
            new_id = freechat_store.rename_session(rename_old, rename_new)
            typer.echo(f"已重命名: {rename_old} → {new_id}")
            return
        except Exception:
            pass  # 不是 freechat 会话，尝试 topic

        # 话题会话 rename
        topic_path = _find_topic_session(rename_old)
        if topic_path:
            new_path = topics_dir / f"{rename_new}.json"
            try:
                topic_path.rename(new_path)
                typer.echo(f"已重命名: {topic_path.stem} → {rename_new}")
            except OSError as e:
                typer.echo(f"重命名失败: {e}")
            return

        typer.echo(f"未找到会话 '{rename_old}'")
        return

    # 无参数时显示帮助
    typer.echo("用法: agc sessions --list | --delete <前缀> | --rename <旧名> --to <新名>")


if __name__ == "__main__":
    app()
