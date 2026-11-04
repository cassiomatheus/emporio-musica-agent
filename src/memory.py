"""Histórico persistente e isolado por sessão, separado do banco comercial."""

from pathlib import Path
import re
from uuid import UUID, RFC_4122

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def normalize_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", session_id.strip()):
        raise ValueError("Código de conversa inválido.")
    value = UUID(hex=session_id.strip())
    if value.version != 4 or value.variant != RFC_4122:
        raise ValueError("Código de conversa inválido.")
    return value.hex


class MemoryManager:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or f"sqlite:///{Path(__file__).resolve().parents[1] / 'db/chat_history.db'}"
        url = make_url(self.db_path)
        if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(self.db_path)

    def get_session_history(self, session_id: str) -> BaseChatMessageHistory:
        session_id = normalize_session_id(session_id)
        return SQLChatMessageHistory(session_id=session_id, connection=self.engine)

    def clear_memory(self, session_id: str):
        self.get_session_history(session_id).clear()

    def close(self):
        self.engine.dispose()


memory_manager = MemoryManager()
