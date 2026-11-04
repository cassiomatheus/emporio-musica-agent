import re

import streamlit as st
from agent import get_agent_response
from langchain_core.messages import HumanMessage, AIMessage


def chat_markdown(text: str) -> str:
    # Valores monetários não devem ser interpretados como fórmulas LaTeX.
    return re.sub(r"(?<!\\)\$", r"\\$", text)


st.set_page_config(page_title="Empório da Música - Atendimento", page_icon="🎸", layout="centered")

st.title("🎸 Empório da Música")
st.caption("Assistente Virtual de Atendimento ao Cliente")

# Inicializa o histórico na memória da sessão do Streamlit
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
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
        with st.spinner("Buscando informações..."):
            try:
                resposta_agente = get_agent_response(user_input, st.session_state.chat_history)
                st.markdown(chat_markdown(resposta_agente))
            except Exception as e:
                resposta_agente = f"Desculpe, ocorreu um erro interno ao processar sua requisição. Detalhe técnico: {e}"
                st.error(resposta_agente)
                
    # Salva a resposta na UI e no histórico do LangChain para manter o contexto
    st.session_state.messages.append({"role": "assistant", "content": resposta_agente})
    st.session_state.chat_history.extend([
        HumanMessage(content=user_input),
        AIMessage(content=resposta_agente)
    ])
