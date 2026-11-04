import re
from uuid import uuid4

import streamlit as st
from agent import process_user_message
from memory import memory_manager


def chat_markdown(text: str) -> str:
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

if st.button("Nova conversa"):
    memory_manager.clear_memory(st.session_state.session_id)
    st.session_state.session_id = uuid4().hex
    st.session_state.pop("messages", None)
    st.session_state.pop("chat_history", None)

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Olá! Sou o assistente da Empório da Música. Como posso te ajudar hoje?"}]

# Renderiza as mensagens anteriores na tela
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(chat_markdown(msg["content"]))

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
                st.markdown(chat_markdown(resposta_agente))
            except Exception as e:
                resposta_agente = f"Desculpe, ocorreu um erro interno ao processar sua requisição. Detalhe técnico: {e}"
                st.error(resposta_agente)
                
    # O RunnableWithMessageHistory já salva os turnos aceitos na memória do agente.
    st.session_state.messages.append({"role": "assistant", "content": resposta_agente})
