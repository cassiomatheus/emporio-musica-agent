import re
from uuid import uuid4
import logging
from datetime import datetime

import streamlit as st
from agent import process_user_message
from memory import memory_manager, normalize_session_id
from conversation_logs import USER_ERROR_MESSAGE


def chat_markdown(text: str, *, hide_category_codes: bool = False) -> str:
    if hide_category_codes:
        text = re.sub(
            r"[ \t]*\(\s*categorias?\s+\d+(?:\s*(?:,|e|/)\s*\d+)*\s*\)",
            "",
            text,
            flags=re.IGNORECASE,
        )
    # Separar subtítulos do primeiro produto, preservando a numeração original.
    text = re.sub(
        r"(?m)^(\*\*[^*\n]+:\*\*)[ \t]+(\d+[.)][ \t]+\*\*)",
        r"\1\n\n\2",
        text,
    )
    # Valores monetários não devem ser interpretados como fórmulas LaTeX.
    return re.sub(r"(?<!\\)\$", r"\\$", text)


def conversation_markdown(messages: list[dict], session_id: str) -> str:
    lines = ["# Conversa — Empório da Música", ""]
    for message in messages:
        role = "Cliente" if message["role"] == "user" else "Assistente"
        content = message["content"]
        # O código privado não deve acompanhar uma transcrição compartilhável.
        content = re.sub(re.escape(session_id), "[CÓDIGO PRIVADO OMITIDO]", content, flags=re.IGNORECASE)
        lines.extend([f"## {role}", "", chat_markdown(
            content, hide_category_codes=message["role"] == "assistant"
        ), ""])
    return "\n".join(lines)


st.set_page_config(page_title="Empório da Música - Atendimento", page_icon="🎸", layout="centered")

st.title("🎸 Empório da Música")
st.caption("Assistente Virtual de Atendimento ao Cliente")

# A memória do agente é isolada por sessão; messages guarda apenas a exibição.
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid4().hex

with st.sidebar:
    st.caption("Transcrições são salvas automaticamente em conversas/. Nova conversa preserva esses arquivos locais.")
    st.caption("Código privado: quem o possui pode retomar esta conversa. Guarde-o com cuidado.")
    st.code(st.session_state.session_id, language=None)
    restore_id = st.text_input("Código de uma conversa anterior", key="restore_id", type="password")
    if st.button("Retomar conversa", key="restore_conversation"):
        try:
            restored_id = normalize_session_id(restore_id)
            saved = memory_manager.get_session_history(restored_id).messages
            if saved:
                st.session_state.session_id = restored_id
                st.session_state.messages = [
                    {"role": "user" if message.type == "human" else "assistant", "content": message.text}
                    for message in saved if message.type in ("human", "ai")
                ]
                st.rerun()
            else:
                st.warning("Código inválido ou conversa indisponível.")
        except ValueError:
            st.warning("Código inválido ou conversa indisponível.")
        except Exception as error:
            logging.getLogger(__name__).error("Falha ao retomar conversa: %s", type(error).__name__)
            st.warning("Não foi possível retomar a conversa neste momento.")

if st.button("Nova conversa", key="new_conversation"):
    # Trocar de conversa preserva a anterior para retomada pelo código privado.
    st.session_state.session_id = uuid4().hex
    st.session_state.pop("messages", None)
    st.session_state.pop("chat_history", None)
    st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Olá! Sou o assistente da Empório da Música. Como posso te ajudar hoje?"}]

# Renderiza as mensagens anteriores na tela
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(chat_markdown(
            msg["content"], hide_category_codes=msg["role"] == "assistant"
        ))

# Caixa de input para o usuário
if user_input := st.chat_input("Digite sua pergunta..."):
    
    # Exibe a pergunta do usuário na UI
    st.chat_message("user").markdown(chat_markdown(user_input))
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # Processa a resposta do agente com um spinner visual
    with st.chat_message("assistant"):
        with st.spinner("Analisando sua pergunta..."):
            try:
                resposta_agente = process_user_message(
                    user_input, session_id=st.session_state.session_id
                )
                st.markdown(chat_markdown(resposta_agente, hide_category_codes=True))
            except Exception as e:
                logging.getLogger(__name__).error("Falha no atendimento: %s", type(e).__name__)
                resposta_agente = USER_ERROR_MESSAGE
                st.error(resposta_agente)
                
    # O RunnableWithMessageHistory já salva os turnos aceitos na memória do agente.
    st.session_state.messages.append({"role": "assistant", "content": resposta_agente})

# Preparar depois do atendimento inclui a última resposta no mesmo download.
with st.sidebar:
    st.download_button(
        "Salvar mensagens",
        data=conversation_markdown(st.session_state.messages, st.session_state.session_id),
        file_name=f"conversa_emporio_{datetime.now():%Y%m%d_%H%M%S}.md",
        mime="text/markdown; charset=utf-8",
        key="save_messages",
        on_click="ignore",
    )
    st.caption("Baixa as mensagens desta conversa em Markdown. Salve antes de iniciar uma nova conversa.")
