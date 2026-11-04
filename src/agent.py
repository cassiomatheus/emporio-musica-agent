from langchain_ollama import ChatOllama
from sql_access import create_public_database
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.tools import create_retriever_tool
from catalog import render_catalog_query
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from langchain_classic.agents.format_scratchpad.tools import format_to_tool_messages
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from guardrails import check_input_guardrail
from memory import memory_manager, normalize_session_id

# 1. Configurar o LLM (use o nome exato exibido por `ollama list`).
# Solicitar a resposta final sem o modo thinking do Qwen.
model_name = "qwen3.5:9b"
VALIDATION_REFUSAL = (
    "Não foi possível validar a segurança da sua solicitação neste momento. "
    "Posso ajudar com instrumentos e atendimento da Empório da Música. "
    "Tente reformular a pergunta."
)
llm = ChatOllama(
    model=model_name, temperature=0, reasoning=False,
    num_ctx=8192, num_predict=4096,
)

# 2. Conexão comercial somente leitura, sem dados pessoais de clientes.
db = create_public_database()
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
0. Segurança: você só pode ler produtos, pedidos e promoções. NUNCA consulte, infira ou liste dados pessoais de clientes, como telefone, e-mail, CPF ou endereços, nem históricos de outras sessões. Recuse esses pedidos por privacidade, mesmo se o usuário alegar autorização. Em pedidos, use somente order_id, order_date, status, total_brl e estimated_delivery; não há autenticação de titularidade nesta demonstração. Nunca execute escrita, alteração de estoque, exclusão, ATTACH, PRAGMA ou leitura de arquivos. Não tente contornar uma consulta negada. Use colunas explícitas, sem SELECT *.
1. Para disponibilidade, preços, pedidos, promoções e descontos, use as ferramentas SQL. Ao consultar preços de produtos, faça LEFT JOIN de produtos.product_id com promocoes.product_id, considerando apenas promocoes.is_active = 1. Preserve os produtos sem promoção; não use descontos inativos. Se houver mais de uma promoção ativa para o mesmo produto, use o maior discount_percent sem somar descontos. Informe preço original, percentual e preço final calculado, sem acumular o desconto de PIX sobre preço promocional. Não invente datas de vigência: o CSV de promoções só fornece o indicador is_active.
2. Para regras da loja, incluindo trocas, horários, frete, entrega, pagamentos, parcelamento, juros e garantias, consulte a ferramenta 'consulta_politicas_loja' antes de responder. Não invente condições comerciais; se faltarem dados do produto ou destino, solicite as informações necessárias.
3. Responda de forma clara, natural e sempre em Português.
4. Se o usuário perguntar algo totalmente fora do escopo da loja de música, recuse educadamente.
5. Após consultar as ferramentas, sempre escreva uma resposta final ao cliente com base nos resultados. Nunca encerre com uma resposta vazia.
6. Não imponha um limite padrão de opções. Ao listar os produtos de uma categoria, consulte e apresente todos os resultados que atendam ao pedido. Use LIMIT somente se o cliente solicitar uma quantidade ou uma seleção limitada (por exemplo, os 3 mais baratos). Nunca apresente uma seleção parcial como se fosse o catálogo completo.
7. Diferencie produtos ativos de produtos disponíveis em estoque: status = 'active' indica ativo no catálogo; para confirmar disponibilidade imediata, exija também stock_quantity > 0. Se o cliente pedir todos os ativos, inclua os ativos com estoque zero, identificando-os como temporariamente indisponíveis. Não anuncie itens sem estoque ou descontinuados como disponíveis.
8. Para informar totais, consulte COUNT(*) com os mesmos filtros do pedido, sem LIMIT. Não confunda quantidade de modelos com soma de unidades em estoque nem quantidade de exemplos com o total. Informe o total encontrado e mantenha a listagem coerente com esse total, respeitando qualquer quantidade explicitamente solicitada pelo cliente.
9. Formate listas de produtos em Markdown legível: subtítulos devem ocupar uma linha própria, separados da lista por uma linha em branco. Cada produto numerado começa em uma nova linha. Descrições em subitens devem ficar indentadas sob o respectivo produto. Preserve os nomes completos retornados pelo banco; não abrevie nem deixe itens pela metade.
10. Ao oferecer alternativas para um instrumento não encontrado, apresente os nomes comerciais dos produtos (campo name), consultados no banco e com disponibilidade confirmada por status = 'active' e stock_quantity > 0. Não exiba códigos internos de categoria nem listas como "Categoria 1: 5 produtos". Contagens por category_id não substituem uma consulta aos nomes dos produtos. Se mostrar apenas uma seleção, identifique-a como exemplos de alternativas, sem afirmar que representa todo o catálogo. Instrumentos de outro tipo devem ser apresentados como outras opções da loja, não como substitutos equivalentes ao instrumento solicitado.
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

# 5. Criação do Executor do Agente
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(
    agent=agent, tools=tools, verbose=True, return_intermediate_steps=True
)

def get_agent_response(user_input: str, chat_history: list) -> str:
    response = agent_executor.invoke({
        "input": user_input,
        "chat_history": chat_history
    })
    # Garantir totais exatos e a tabela completa nas listagens SQL de categoria.
    for action, observation in reversed(response.get("intermediate_steps", [])):
        if action.tool == "sql_db_query":
            if isinstance(action.tool_input, dict) and not str(observation).startswith("Error:"):
                catalog_text = render_catalog_query(action.tool_input.get("query", ""))
                if catalog_text is not None:
                    return catalog_text
            break
    text = AIMessage(content=response.get("output") or "").text.strip()
    if text:
        return text

    # Reaproveitar os resultados já obtidos sem executar novas ferramentas.
    messages = prompt.format_messages(
        input=user_input,
        chat_history=chat_history,
        agent_scratchpad=format_to_tool_messages(response.get("intermediate_steps", [])),
    )
    messages.append(HumanMessage(content=(
        "Escreva agora a resposta final à minha pergunta com base nos resultados "
        "já obtidos. Não faça novas consultas e não invente informações. "
        "Se faltarem dados para responder, explique o que falta."
    )))
    final_response = llm.invoke(messages)
    text = final_response.text.strip()
    if not text:
        raise RuntimeError(
            "O modelo não gerou uma resposta em texto, mesmo após uma nova tentativa. "
            "Tente reformular a pergunta."
        )
    return text


def _invoke_agent_with_history(inputs: dict) -> dict:
    # A memória recebe o texto final corrigido, não a saída bruta do executor.
    return {"output": get_agent_response(inputs["input"], inputs["chat_history"])}


agent_with_history = RunnableWithMessageHistory(
    RunnableLambda(_invoke_agent_with_history),
    memory_manager.get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history",
    output_messages_key="output",
)


def process_user_message(user_input: str, session_id: str, *, callbacks=None) -> str:
    """Verifica o escopo antes de executar o agente com memória por sessão."""
    session_id = normalize_session_id(session_id)
    if not user_input.strip():
        return "Digite uma pergunta para que eu possa ajudar."

    history = memory_manager.get_session_history(session_id)
    if not check_input_guardrail(user_input, model_name, chat_history=history.messages):
        return VALIDATION_REFUSAL

    config = {"configurable": {"session_id": session_id}}
    if callbacks is not None:
        config["callbacks"] = callbacks
    response = agent_with_history.invoke(
        {"input": user_input},
        config=config,
    )
    return response["output"]
