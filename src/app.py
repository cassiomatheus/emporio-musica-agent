import re
from uuid import uuid4
import logging

import streamlit as st
from agent import process_user_message
from memory import memory_manager, normalize_session_id


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


st.set_page_config(page_title="Empório da Música - Atendimento", page_icon="🎸", layout="centered")

st.title("🎸 Empório da Música")
st.caption("Assistente Virtual de Atendimento ao Cliente")

# A memória do agente é isolada por sessão; messages guarda apenas a exibição.
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid4().hex

with st.sidebar:
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
    try:
        memory_manager.clear_memory(st.session_state.session_id)
    except Exception as error:
        logging.getLogger(__name__).error("Falha ao limpar conversa: %s", type(error).__name__)
        st.error("Não foi possível iniciar uma nova conversa neste momento.")
        st.stop()
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
                resposta_agente = "Não foi possível concluir o atendimento neste momento. Tente novamente."
                st.error(resposta_agente)
                
    # O RunnableWithMessageHistory já salva os turnos aceitos na memória do agente.
    st.session_state.messages.append({"role": "assistant", "content": resposta_agente})
