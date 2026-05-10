import json
import tempfile
from pathlib import Path

import pytest

from agc.core.message import Message, MessageType
from agc.core.session import SessionStore


def _make_msg(sender: str, content: str, msg_type: MessageType = MessageType.chat) -> Message:
    return Message(sender=sender, content=content, msg_type=msg_type)


def test_create_session():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(base_dir=Path(tmp))
        session_id = store.create_session()
        assert session_id  # non-empty
        path = Path(tmp) / f"{session_id}.jsonl"
        assert path.exists()


def test_append_and_load():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(base_dir=Path(tmp))
        session_id = store.create_session()
        msgs = [
            _make_msg("human", "hello", MessageType.human_input),
            _make_msg("researcher", "hi there", MessageType.chat),
        ]
        store.append(session_id, msgs)
        loaded = store.load_session(session_id)
        assert len(loaded) == 2
        assert loaded[0].sender == "human"
        assert loaded[1].content == "hi there"


def test_list_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(base_dir=Path(tmp))
        id1 = store.create_session()
        id2 = store.create_session()
        sessions = store.list_sessions()
        assert len(sessions) == 2


def test_rename_session():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(base_dir=Path(tmp))
        old_id = store.create_session()
        store.append(old_id, [_make_msg("human", "test", MessageType.human_input)])
        new_id = store.rename_session(old_id, "我的群聊")
        loaded = store.load_session(new_id)
        assert len(loaded) == 1
        assert old_id not in store.list_sessions()


def test_delete_session():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(base_dir=Path(tmp))
        session_id = store.create_session()
        store.delete_session(session_id)
        assert session_id not in store.list_sessions()


def test_load_nonexistent_raises():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(base_dir=Path(tmp))
        with pytest.raises(FileNotFoundError):
            store.load_session("nonexistent")