"""SessionStore — 会话持久化（JSONL）"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from agc.core.message import Message

logger = logging.getLogger(__name__)


class SessionStore:
    """JSONL文件存储的会话持久化"""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path("data/sessions")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> str:
        base = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        session_id = base
        path = self._session_path(session_id)
        counter = 1
        while path.exists():
            session_id = f"{base}_{counter}"
            path = self._session_path(session_id)
            counter += 1
        path.touch()
        logger.info(f"创建会话: {session_id}")
        return session_id

    def append(self, session_id: str, messages: list[Message]) -> None:
        path = self._resolve_path(session_id)
        with open(path, "a", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg.to_json(), ensure_ascii=False) + "\n")

    def load_session(self, session_id: str) -> list[Message]:
        path = self._resolve_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"会话不存在: {session_id}")
        messages = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                messages.append(Message.from_json(data))
        return messages

    def list_sessions(self) -> list[str]:
        sessions = []
        for f in sorted(self.base_dir.glob("*.jsonl")):
            sessions.append(f.stem)
        return sessions

    def rename_session(self, old_id: str, new_name: str) -> str:
        old_path = self._resolve_path(old_id)
        new_id = new_name
        new_path = self._session_path(new_id)
        old_path.rename(new_path)
        logger.info(f"会话重命名: {old_id} -> {new_id}")
        return new_id

    def delete_session(self, session_id: str) -> None:
        path = self._resolve_path(session_id)
        if path.exists():
            path.unlink()
            logger.info(f"删除会话: {session_id}")

    def _session_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.jsonl"

    def _resolve_path(self, session_id: str) -> Path:
        exact = self._session_path(session_id)
        if exact.exists():
            return exact
        matches = list(self.base_dir.glob(f"{session_id}*.jsonl"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"会话前缀 '{session_id}' 匹配到多个文件: {[m.stem for m in matches]}")
        return exact