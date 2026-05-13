"""FreeChatSession — IM风格自由群聊模式"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agc.core.agent import AgentConfig
from agc.core.message import Message, MessageType
from agc.core.session import ChatSession, SessionStore

logger = logging.getLogger(__name__)

FREECHAT_SYSTEM_PROMPT = """你是一个群聊助手。你的名字是{name}，角色是{role}。
{backstory}

你的目标：{goal}

群聊规则：
- 自然地回应消息，像在真正的聊天软件里一样
- 召唤发言用 @agent名（对方会收到消息并回应）
- 引用或总结他人观点时用纯文本 agent名（不加@），如：「architect 之前提到...」
- 如果消息与你无关，可以不回复
- 保持简洁，不要长篇大论
- 可以随时参与讨论，不需要等待轮流

其他参与者：{other_agents}"""

SLASH_COMMANDS = {
    "/quit": "退出群聊",
    "/exit": "退出群聊",
    "/history": "查看最近消息",
    "/agents": "列出群中的agent",
    "/topic": "设置当前话题语境",
    "/clear": "清空当前会话历史",
    "/help": "显示所有命令",
}

AUTO_CONTINUE_MAX = 3  # 用户发言后，agent 间 @mention 自动延续的最大轮数


class FreeChatSession(ChatSession):
    """IM风格自由群聊 — 用户随时输入，scheduler决定谁回应"""

    def __init__(
        self,
        agents: list[AgentConfig],
        llm: Any = None,
        user_name: str = "human",
        context_window: int = 8000,
        base_url: str | None = None,
        api_key: str | None = None,
        stream: bool = True,
        workspace_root: str | None = None,
        tools: list[str] | None = None,
        scheduler: str = "hybrid",
        session_id: str | None = None,
        session_store: SessionStore | None = None,
        recent_window: int = 30,
    ):
        super().__init__(
            agents=agents,
            llm=llm,
            context_window=context_window,
            base_url=base_url,
            api_key=api_key,
            stream=stream,
            workspace_root=workspace_root,
            tools=tools,
            scheduler=scheduler,
        )
        self.user_name = user_name
        self.current_topic: str | None = None
        self.session_id = session_id or ""
        self._session_store = session_store or SessionStore(Path("data/sessions/freechat"))
        self._recent_window = recent_window
        self._system_prompts: dict[str, str] = {}
        self._named = False
        self._total_tokens = 0

    def run(self) -> None:
        """REPL主循环"""
        if not self.session_id:
            self.session_id = self._session_store.create_session()

        try:
            self._build_system_prompts()
            self._show_welcome()

            try:
                from prompt_toolkit import PromptSession

                session = PromptSession()
                use_pt = True
            except ImportError:
                use_pt = False

            while True:
                try:
                    if use_pt:
                        user_input = session.prompt(f"[{self.user_name}] ").strip()
                    else:
                        user_input = input(f"[{self.user_name}] ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n再见！")
                    break

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    cmd_result = self._handle_command(user_input)
                    if cmd_result == "quit":
                        print("再见！")
                        break
                    continue

                user_msg = self._create_user_message(user_input)
                self._emit_message(user_msg)

                if not self._named and len(self.history) <= 2:
                    self._try_name_session(user_input)

                response_plan = self._scheduler.plan_responses(self.history)

                round_msgs = [user_msg]
                # 首轮：让 scheduler 选出该回的 agent
                for agent in response_plan:
                    self._emit_speaker_start(agent.name, agent.role, agent.model)
                    agent_msgs, tokens = self._generate_response(agent)
                    round_msgs.extend(agent_msgs)
                    self._total_tokens += tokens

                # 自动延续：agent @mention 其他人时，继续让被@的agent回应
                for _ in range(AUTO_CONTINUE_MAX):
                    last_msg = self.history[-1] if self.history else None
                    if not last_msg or not last_msg.has_mentions:
                        break
                    extra_plan = self._scheduler.plan_responses(self.history)
                    if not extra_plan:
                        break
                    for agent in extra_plan:
                        self._emit_speaker_start(agent.name, agent.role, agent.model)
                        agent_msgs, tokens = self._generate_response(agent)
                        round_msgs.extend(agent_msgs)
                        self._total_tokens += tokens

                self._session_store.append(self.session_id, round_msgs)
                for m in round_msgs:
                    m.metadata["_saved"] = True
        finally:
            if self.session_id and not self.history:
                self._session_store.delete_session(self.session_id)

    def _show_welcome(self) -> None:
        """显示欢迎信息"""
        try:
            from rich.console import Console
            from rich.panel import Panel

            console = Console()
            agents_text = "\n".join(f"  @{a.name} · {a.role}" for a in self.agents)
            console.print(
                Panel(
                    f"群聊已开始！输入消息参与讨论。\n\n[bold]参与者:[/bold]\n{agents_text}\n\n[dim]/help 查看命令 | /quit 退出[/dim]",
                    title="自由群聊",
                    border_style="bright_blue",
                )
            )
        except ImportError:
            print(f"\n群聊已开始！参与者: {', '.join(f'@{a.name}' for a in self.agents)}")
            print("输入消息参与讨论。/help 查看命令 | /quit 退出\n")

    def _build_system_prompts(self) -> None:
        """为每个agent构建系统提示"""
        extra_prompts = self._build_workspace_prompts()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        time_hint = f"\n\n当前时间: {now}"

        for agent in self.agents:
            other_agents = ", ".join(
                f"@{a.name}({a.role})" for a in self.agents if a.name != agent.name
            )
            other_agents += f", @{self.user_name}(用户)"

            prompt = FREECHAT_SYSTEM_PROMPT.format(
                name=agent.name,
                role=agent.role,
                backstory=agent.backstory,
                goal=agent.goal,
                other_agents=other_agents,
            )
            prompt += extra_prompts.get(agent.name, "") + time_hint
            self._system_prompts[agent.name] = prompt

    def _create_user_message(self, content: str) -> Message:
        """创建用户消息"""
        mentions = self._parse_mentions(content)
        return Message(
            sender=self.user_name,
            content=content,
            msg_type=MessageType.human_input,
            mentions=mentions,
        )

    def _generate_response(self, agent: AgentConfig) -> tuple[list[Message], int]:
        """生成单个agent的回复（带工具循环）"""
        return self._generate_agent_response(agent, emit_tool_to_history=True, emit_final=True)

    def _build_response_context(
        self, agent: AgentConfig, result_messages: list[Message]
    ) -> list[dict[str, Any]]:
        return self._context.build_freechat_context(
            agent=agent,
            history=self.history,
            all_agents=self.agents,
            system_prompt=self._system_prompts.get(agent.name, ""),
            current_topic=self.current_topic,
            recent_window=self._recent_window,
        )

    def _force_text_response_fallback(
        self, agent: AgentConfig, result_messages: list[Message], emit_final: bool
    ) -> None:
        """强制无工具回复"""
        try:
            ctx = self._build_response_context(agent, result_messages)
            llm = self._llm_clients.get(agent.name, self.llm)
            response = llm.chat(
                messages=ctx,
                model=agent.model,
                temperature=agent.temperature,
                tools=None,
                on_chunk=self._emit_chunk if self._stream else None,
                on_reasoning_chunk=self._emit_reasoning if self._stream else None,
            )
            final_msg = self._create_final_message(agent, response, self._current_round())
            if emit_final:
                self._emit_message(final_msg)
            result_messages.append(final_msg)
        except Exception as e:
            logger.warning(f"强制无工具回复失败: {e}")

    def _handle_command(self, raw_input: str) -> str | None:
        """处理斜杠命令，返回 'quit' 表示退出"""
        parts = raw_input.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit"):
            self._save_session()
            return "quit"

        if cmd == "/help":
            self._show_help()
            return None

        if cmd == "/history":
            n = 10
            if args:
                try:
                    n = int(args)
                except ValueError:
                    n = 10
            self._show_recent_history(n)
            return None

        if cmd == "/agents":
            self._show_agents()
            return None

        if cmd == "/topic":
            if args:
                self.current_topic = args
                self._emit_system(f"话题已切换为: {args}")
            else:
                topic_str = self.current_topic or "（未设置）"
                self._emit_system(f"当前话题: {topic_str}")
            return None

        if cmd == "/clear":
            self.history = []
            if self.session_id:
                self._session_store.delete_session(self.session_id)
            self.session_id = self._session_store.create_session()
            self._emit_system("会话历史已清空")
            return None

        try:
            from rich.console import Console

            console = Console()
            console.print(f"[yellow]未知命令: {cmd}[/yellow]  输入 /help 查看帮助")
        except ImportError:
            print(f"未知命令: {cmd}  输入 /help 查看帮助")
        return None

    def _show_help(self) -> None:
        try:
            from rich.console import Console

            console = Console()
            console.print("\n[bold]可用命令:[/bold]")
            for k, v in SLASH_COMMANDS.items():
                console.print(f"  {k:12s} {v}")
        except ImportError:
            print("\n可用命令:")
            for k, v in SLASH_COMMANDS.items():
                print(f"  {k:12s} {v}")

    def _show_recent_history(self, n: int = 10) -> None:
        """显示最近n条消息"""
        recent = self.history[-n:]
        if not recent:
            print("（暂无历史消息）")
            return
        try:
            from rich.console import Console

            console = Console()
            for msg in recent:
                if msg.msg_type == MessageType.system:
                    console.print(f"[dim]── {msg.content} ──[/dim]")
                elif msg.msg_type == MessageType.human_input:
                    console.print(f"[bold]👤 {msg.sender}:[/bold] {msg.content}")
                elif msg.msg_type in (MessageType.chat, MessageType.mention):
                    console.print(f"{msg.sender}: {msg.content}")
        except ImportError:
            for msg in recent:
                print(msg.format_display())

    def _show_agents(self) -> None:
        """显示群中的agent列表"""
        try:
            from rich.console import Console

            console = Console()
            console.print("\n[bold]群聊参与者:[/bold]")
            for a in self.agents:
                console.print(f"  @{a.name} · {a.role} · {a.goal}")
        except ImportError:
            print("\n群聊参与者:")
            for a in self.agents:
                print(f"  @{a.name} · {a.role}")

    def _try_name_session(self, user_input: str) -> None:
        """尝试用LLM给会话命名"""
        try:
            name = self._generate_session_name(user_input)
            if name:
                new_id = f"{self.session_id}_{name}"
                self.session_id = self._session_store.rename_session(self.session_id, new_id)
                self._named = True
        except Exception as e:
            logger.debug(f"会话命名失败: {e}")

    def _generate_session_name(self, first_message: str) -> str:
        """用LLM生成会话名称"""
        try:
            response = self.llm.chat(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "根据消息内容生成5-10字的会话标题。只输出标题，不要任何其他文字。\n\n"
                            "消息：今天天气怎么样\n标题：天气查询\n\n"
                            "消息：帮我写个Python脚本\n标题：Python编程求助\n\n"
                            f"消息：{first_message}\n标题："
                        ),
                    }
                ],
                temperature=0.0,
            )
            name = (response.content or response.reasoning_content or "").strip()
            name = re.sub(r'["""\n\r]', "", name)
            return name[:20]
        except Exception:
            return ""

    def _save_session(self) -> None:
        """保存会话（在退出时调用）"""
        if self.session_id and self.history:
            unsaved = [m for m in self.history if not getattr(m, "_saved", False)]
            if unsaved:
                self._session_store.append(self.session_id, unsaved)
                for m in unsaved:
                    m.metadata["_saved"] = True

    def load_session(self, session_id: str) -> None:
        """加载历史会话"""
        self.history = self._session_store.load_session(session_id)
        self.session_id = session_id
        for msg in self.history:
            msg.metadata["_saved"] = True
        if self.history:
            recent = self.history[-10:]
            for msg in recent:
                if msg.msg_type in (MessageType.tool_call, MessageType.tool_result):
                    continue
                for cb in self._on_message_callbacks:
                    cb(msg)
            self._emit_system(f"已恢复会话，共 {len(self.history)} 条历史消息")
