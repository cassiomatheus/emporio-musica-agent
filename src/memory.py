from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory

class MemoryManager:
    def __init__(self):
        # Dicionário em memória para armazenar históricos por ID de sessão.
        # Em produção, isso seria substituído por Redis ou banco de dados.
        self.store = {}

    def get_session_history(self, session_id: str) -> BaseChatMessageHistory:
        """Recupera ou cria o histórico de uma sessão específica."""
        if session_id not in self.store:
            self.store[session_id] = ChatMessageHistory()
        return self.store[session_id]

    def clear_memory(self, session_id: str):
        """Limpa o histórico de uma sessão."""
        if session_id in self.store:
            self.store[session_id].clear()

# Instância global para ser importada e utilizada
memory_manager = MemoryManager()