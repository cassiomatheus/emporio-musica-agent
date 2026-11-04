# Empório da Música — Assistente de atendimento

Assistente em português para consultar instrumentos, preços, estoque, pedidos e políticas da loja. A aplicação usa Streamlit, LangChain e um modelo local executado pelo Ollama.

## Como funciona

- **Dados estruturados:** os CSVs de produtos, pedidos e clientes são importados para SQLite. O agente usa ferramentas SQL para consultar essas informações.
- **Políticas da loja:** o PDF é dividido em trechos, convertido em embeddings com `sentence-transformers/all-MiniLM-L6-v2` e indexado no ChromaDB. A ferramenta de consulta de políticas recupera os três trechos mais próximos da pergunta.
- **Modelo:** o `qwen3.5:9b`, via `ChatOllama`, decide quais ferramentas consultar e prepara a resposta. O código usa `langchain-classic` para `AgentExecutor` e `create_tool_calling_agent`.
- **Memória e guardião:** `process_user_message` verifica o escopo antes de executar as ferramentas. `RunnableWithMessageHistory` mantém as mensagens aceitas e as respostas finais por ID de sessão.
- **Interface:** o Streamlit gera um ID exclusivo por sessão, mantém as mensagens para exibição e protege os símbolos de moeda da interpretação como fórmulas LaTeX.

SQLite e ChromaDB mantêm os dados no diretório do projeto. Os modelos são baixados inicialmente; a inferência do Qwen é feita pelo Ollama local.

## Pré-requisitos

- Python com suporte às dependências de `requirements.txt`. O ambiente utilizado neste projeto foi validado com **Python 3.14.6**.
- [Ollama instalado](https://docs.ollama.com/linux), em execução e com o modelo `qwen3.5:9b` disponível.
- Acesso à internet para instalar os pacotes e baixar os modelos na primeira utilização.
- Memória e espaço em disco para o modelo e as dependências. A instalação padrão do PyTorch também pode baixar bibliotecas CUDA/NVIDIA.

Os comandos abaixo são para Linux/Bash. Execute os comandos Python **na raiz do projeto**, pois os caminhos de `data/`, `db/` e `vectorstore/` são relativos a ela.

## 1. Instalar as dependências

Na pasta `emporio-musica-agent`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

Em cada novo terminal, ative novamente o ambiente com `source .venv/bin/activate`. Use `python -m pip` para instalar os pacotes no mesmo Python que executa a aplicação. A pasta `.venv/` está no `.gitignore`.

## 2. Preparar o Ollama

Se o servidor ainda não estiver em execução, abra outro terminal e mantenha este comando ativo:

```bash
ollama serve
```

No terminal do projeto, baixe e confira o modelo:

```bash
ollama pull qwen3.5:9b
ollama list
```

Se o Ollama já estiver funcionando como serviço, não é necessário iniciar outro servidor. Consulte o [guia oficial do Ollama](https://docs.ollama.com/quickstart) para detalhes de execução local.

A configuração atual em `src/agent.py` é:

```python
model_name = "qwen3.5:9b"
llm = ChatOllama(
    model=model_name, temperature=0, reasoning=False,
    num_ctx=8192, num_predict=4096,
)
```

Para trocar o modelo, baixe a nova versão e ajuste `model_name` nesse arquivo para o nome exato exibido por `ollama list`. O agente e o guardião usam esse mesmo nome. O modelo deve suportar chamadas de ferramentas; confira também a compatibilidade com `reasoning=False`.

## 3. Preparar os dados

O script de ingestão espera estes arquivos, com os nomes e acentos abaixo:

| Arquivo | Destino |
| --- | --- |
| `data/desafio_tecnico_ai_eng - products.csv` | Tabela `produtos` |
| `data/desafio_tecnico_ai_eng - orders.csv` | Tabela `pedidos` |
| `data/desafio_tecnico_ai_eng - customers.csv` | Tabela `clientes` |
| `data/políticas_da_loja.pdf` | Coleção de documentos no ChromaDB |

Com a `.venv` ativa, execute:

```bash
python src/data_ingestion.py
```

Isso cria as tabelas em `db/emporio.db` e persiste os embeddings do PDF em `vectorstore/`. O modelo de embeddings é baixado na primeira execução. Confira no terminal as mensagens de sucesso das duas etapas: o script captura os erros, portanto terminar a execução não garante que ambas tenham sido concluídas.

Ao repetir a ingestão, as três tabelas SQLite são **substituídas** pelos CSVs. A etapa do ChromaDB adiciona documentos à coleção existente, podendo duplicar trechos em execuções repetidas; o script ainda não implementa uma reconstrução idempotente do índice.

Os arquivos `categories.csv`, `order_items.csv` e `promotions.csv` também estão em `data/`, com o prefixo `desafio_tecnico_ai_eng - `, mas **não são importados pela ingestão atual**. Os arquivos de `data/processado/` também não participam desse fluxo. Consultas a essas fontes exigem ampliar a ingestão.

## 4. Executar o chat

Depois da ingestão, com o Ollama em execução:

```bash
source .venv/bin/activate
python -m streamlit run src/app.py
```

Abra o endereço exibido no terminal, normalmente `http://localhost:8501`. Para encerrar, pressione `Ctrl+C`. Para reiniciar após alterações, execute o mesmo comando novamente.

Exemplos de perguntas:

- “Liste todos os violões ativos no catálogo, com preço e disponibilidade.”
- “Quais são os três violões mais baratos em estoque?”
- “Qual é a política de trocas por defeito?”
- “Quais são as condições de frete para Campo Grande?”

## Regras de catálogo e resposta

Um produto **ativo no catálogo** tem `status = 'active'`. Para estar **disponível em estoque**, ele também precisa ter `stock_quantity > 0`. A quantidade de modelos é diferente da soma de unidades em estoque.

O prompt orienta o agente a listar todos os resultados solicitados, sem um limite padrão de cinco opções. Um limite deve ser usado quando o cliente pedir uma seleção, como “os três mais baratos”.

Para consultas SQL completas de categoria reconhecidas por `src/catalog.py`, a tabela final e os totais são gerados diretamente do SQLite. Isso evita depender do modelo para contar ou reescrever todos os itens. Esse tratamento aceita consultas simples com categoria, status ativo e filtro opcional de estoque; consultas com outros filtros, agregações, joins ou `LIMIT` seguem o fluxo normal do agente.

Se o agente retornar texto vazio, o código tenta gerar uma resposta novamente a partir dos resultados das ferramentas. Se a segunda tentativa também vier vazia, o chat exibe um erro.

## Memória e guardião

A entrada principal do chat é `process_user_message(user_input, session_id)`, definida em `src/agent.py` e chamada por `src/app.py`:

1. A interface cria um UUID por sessão e reutiliza esse ID nas mensagens seguintes. IDs fixos compartilhariam a memória entre usuários.
2. `src/guardrails.py` classifica a pergunta com o mesmo modelo do agente, considerando até quatro mensagens anteriores, com até 1.200 caracteres por mensagem. Esse contexto é enviado como dados JSON, separado das instruções do classificador. Parcelamento, pagamentos, frete, políticas da loja e continuações de conversa estão no escopo permitido, mesmo quando o cliente usa “ele” ou “esse”. Só a classificação exata `PERMITIDA` libera o agente. Uma saída inválida é tentada novamente; se a falha persistir, a interface informa o erro de validação, em vez de recusar a pergunta como fora de escopo.
3. Para entradas aceitas, `RunnableWithMessageHistory` fornece o histórico a `get_agent_response`, que mantém as correções de catálogo e a recuperação de respostas vazias.
4. A memória registra uma única vez a pergunta e a resposta final efetivamente exibida, incluindo a tabela corrigida do catálogo. Perguntas bloqueadas e turnos com falha não são gravados na memória do agente; as mensagens exibidas continuam no histórico visual da interface.
5. O botão **Nova conversa** limpa a memória da sessão atual, reinicia o histórico visual e gera outro ID.

`src/memory.py` mantém os históricos em um dicionário no processo Python. Reiniciar o servidor perde essa memória, e uma nova sessão do Streamlit recebe outro ID. Não há persistência em Redis ou banco de dados. A classificação do guardião depende do modelo; a configuração atual não representa autenticação de clientes nem autorização de acesso a pedidos.

O guardião adiciona uma chamada ao modelo antes de cada turno aceito. Para manter essa validação, novas interfaces devem chamar `process_user_message`; chamadas diretas a `get_agent_response` não passam pelo guardião.

## Testes

Na raiz do projeto, com a `.venv` ativa:

```bash
python -m unittest discover -s tests -v
```

Os testes de catálogo usam um SQLite temporário e cobrem listagem completa, estoque zero, limites explícitos, ordenação por preço, categoria vazia e preservação de filtros SQL. Os testes de conversa verificam isolamento de sessões, gravação única da resposta final, contexto entre turnos e bloqueio antes de executar o agente. Os recursos externos são substituídos nos testes: não é necessário ter o Ollama ativo nem baixar os modelos.

## Problemas comuns

| Sintoma | Verificação |
| --- | --- |
| `externally-managed-environment` | Ative `.venv` e use `python -m pip install -r requirements.txt`. |
| `No module named ...` | Confira o Python ativo com `which python` e reinstale as dependências na `.venv`. Os imports de agentes legados usam `langchain_classic`. |
| Falha de conexão com Ollama ou modelo não encontrado | Confira se o servidor está ativo e se `ollama list` mostra o mesmo modelo configurado em `src/agent.py`. |
| Arquivo de dados não encontrado | Execute na raiz e confira os nomes completos, incluindo espaços e o acento em `políticas_da_loja.pdf`. |
| Banco ou políticas sem resultados | Confira os logs da ingestão e os arquivos gerados em `db/` e `vectorstore/`. |
| Aviso de requisições sem `HF_TOKEN` | O modelo público pode ser baixado sem token, sujeito aos limites do Hugging Face. O aviso não indica, por si só, falha na execução. |
| Símbolos de moeda e negrito desformatados | A interface escapa `$` ao renderizar mensagens novas e o histórico. Reinicie a aplicação para carregar a versão atualizada. |

## Estrutura

```text
emporio-musica-agent/
├── data/
│   ├── desafio_tecnico_ai_eng - products.csv
│   ├── desafio_tecnico_ai_eng - orders.csv
│   ├── desafio_tecnico_ai_eng - customers.csv
│   ├── desafio_tecnico_ai_eng - categories.csv
│   ├── desafio_tecnico_ai_eng - order_items.csv
│   ├── desafio_tecnico_ai_eng - promotions.csv
│   ├── políticas_da_loja.pdf
│   └── processado/            # Arquivos auxiliares fora do fluxo de ingestão
├── db/
│   └── emporio.db             # SQLite gerado pela ingestão
├── vectorstore/              # Índice persistente do ChromaDB
├── src/
│   ├── data_ingestion.py      # CSVs → SQLite; PDF → ChromaDB
│   ├── agent.py               # Modelo, ferramentas, prompt e recuperação de resposta
│   ├── guardrails.py          # Classificação de escopo antes das ferramentas
│   ├── memory.py              # Histórico do agente em memória, por sessão
│   ├── catalog.py             # Tabelas e totais de catálogo calculados no SQLite
│   └── app.py                 # Chat Streamlit e formatação de moeda
├── tests/
│   ├── test_catalog.py
│   └── test_conversation.py
├── requirements.txt
└── README.md
```
