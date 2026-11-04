from langchain_ollama import ChatOllama
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.tools.retriever import create_retriever_tool
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# 1. Configurar o LLM (Qwen no Ollama)
# Substitua "qwen2.5" pelo nome exato que aparece no seu `ollama list` (ex: "qwen2.5:7b")
llm = ChatOllama(model="qwen2.5", temperature=0)

# 2. Configurar Ferramentas do SQL (Estoque, Pedidos, Clientes)
db = SQLDatabase.from_uri("sqlite:///db/emporio.db")
sql_toolkit = SQLDatabaseToolkit(db=db, llm=llm)
sql_tools = sql_toolkit.get_tools() 

# 3. Configurar Ferramenta RAG (Políticas em PDF)
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
vectorstore = Chroma(persist_directory="vectorstore", embedding_function=embeddings)
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

rag_tool = create_retriever_tool(
    retriever,
    "consulta_politicas_loja",
    "Use esta ferramenta para consultar regras de devolução, trocas, horários de funcionamento, meios de pagamento e garantias."
)

# Agrupamos todas as ferramentas que o agente tem permissão para usar
tools = sql_tools + [rag_tool]

# 4. Prompt Base do Agente
system_prompt = """Você é um assistente virtual amigável da Empório da Música, uma loja de instrumentos musicais em Campo Grande/MS.
Sua missão é ajudar os clientes usando as ferramentas disponíveis.

Regras:
1. Se a pergunta for sobre disponibilidade de produtos, preços ou status de pedido, use as ferramentas SQL.
2. Se a pergunta for sobre regras da loja (troca, horário, etc), use a ferramenta 'consulta_politicas_loja'.
3. Responda de forma clara, natural e sempre em Português.
4. Se o usuário perguntar algo totalmente fora do escopo da loja de música, recuse educadamente.
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

# 5. Criação do Executor do Agente
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

def get_agent_response(user_input: str, chat_history: list) -> str:
    response = agent_executor.invoke({
        "input": user_input,
        "chat_history": chat_history
    })
    return response["output"]