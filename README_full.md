# Empório da Música — Assistente de atendimento

Assistente em português para consultar instrumentos, preços, estoque, pedidos e políticas da loja. A aplicação usa Streamlit, LangChain e um modelo local executado pelo Ollama.

## Como funciona

- **Dados estruturados:** os CSVs de produtos, pedidos, clientes e promoções são carregados no SQLite por upsert com staging e chaves primárias. O agente usa ferramentas SQL para consultar essas informações.
- **Políticas da loja:** o PDF é dividido em trechos, convertido em embeddings com `sentence-transformers/all-MiniLM-L6-v2` e indexado no ChromaDB. A ferramenta de consulta de políticas recupera os três trechos mais próximos da pergunta.
- **Modelo:** o `qwen3.5:9b`, via `ChatOllama`, decide quais ferramentas consultar e prepara a resposta. O código usa `langchain-classic` para `AgentExecutor` e `create_tool_calling_agent`.
- **Memória e guardião:** `process_user_message` verifica o escopo antes de executar as ferramentas. `RunnableWithMessageHistory` mantém as mensagens aceitas e as respostas finais por ID de sessão.
- **Interface:** o Streamlit gera um ID exclusivo por sessão, mantém as mensagens para exibição, protege os símbolos de moeda da interpretação como fórmulas LaTeX e separa subtítulos de itens numerados que tenham vindo na mesma linha.

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
| `data/desafio_tecnico_ai_eng - promotions.csv` | Tabela `promocoes` |
| `data/políticas_da_loja.pdf` | Coleção de documentos no ChromaDB |

Com a `.venv` ativa, execute:

```bash
python src/data_ingestion.py
```

Isso cria as tabelas em `db/emporio.db` e persiste os embeddings do PDF em `vectorstore/`. O modelo de embeddings é baixado na primeira execução. Confira no terminal as mensagens de sucesso das duas etapas. Uma falha interrompe o comando com erro; uma falha no PDF não desfaz a etapa SQL já concluída.

Execute a ingestão com o Streamlit parado. As quatro tabelas comerciais recebem **upsert por chave primária**: registros novos são inseridos e campos fornecidos são atualizados, sem remover linhas ausentes do CSV ou outras tabelas. Não use a ausência de uma promoção no CSV para desativá-la: envie is_active=0. O banco chat_history.db não é alterado.

A carga usa staging temporário, INSERT ON CONFLICT DO UPDATE e uma transação SQL. Esquemas legados sem PK são migrados preservando dados, índices e triggers; chaves nulas/duplicadas provocam erro e rollback. Colunas novas do CSV são acrescentadas e colunas existentes não fornecidas são preservadas. Uma falha em qualquer tabela reverte a carga SQL inteira.

No ChromaDB, IDs SHA-256 combinam fonte e conteúdo. Trechos inalterados não são regravados; trechos novos/alterados são inseridos por upsert. Depois, versões obsoletas apenas daquele PDF são removidas, incluindo os IDs aleatórios da versão anterior. O diretório e as outras fontes não são apagados. Uma falha de embeddings não remove os trechos anteriores; operações entre SQLite e ChromaDB não formam uma transação única.

Os arquivos `categories.csv` e `order_items.csv` também estão em `data/`, com o prefixo `desafio_tecnico_ai_eng - `, mas **não são importados pela ingestão atual**. Os arquivos de `data/processado/` também não participam desse fluxo. Consultas a essas fontes exigem ampliar a ingestão.

### Adicionar um CSV novo

Registre a fonte e sua chave em `src/data_ingestion.py`, por exemplo:

```python
SOURCES["categorias"] = "desafio_tecnico_ai_eng - categories.csv"
PRIMARY_KEYS["categorias"] = "category_id"
```

Depois execute a ingestão e reinicie o Streamlit. A tabela categorias será adicionada sem substituir as tabelas anteriores. Para o agente utilizá-la corretamente, explique no prompt a relação produtos.category_id = categorias.category_id. Não é preciso substituir price_brl por price nem category_id por category: o pipeline conserva o esquema real das fontes.

Cada fonte cadastrada deve existir e conter sua chave sem valores nulos ou repetidos. Fontes não cadastradas não são importadas automaticamente. Não remova a chave de uma tabela existente nem altere seu tipo sem uma migração específica.

## 4. Executar o chat

Depois da ingestão, com o Ollama em execução:

```bash
source .venv/bin/activate
python -m streamlit run src/app.py
```

Abra o endereço exibido no terminal, normalmente `http://localhost:8501`. Para encerrar, pressione `Ctrl+C`. Para reiniciar após alterações, execute o mesmo comando novamente.

Após modificar `agent.py`, `guardrails.py` ou `memory.py`, pare o servidor com `Ctrl+C` e inicie-o novamente para recarregar os módulos e a configuração do classificador. O histórico permanece em db/chat_history.db. Guarde o código da conversa exibido na barra lateral e use **Retomar conversa** depois de reiniciar para recuperar as mensagens e o contexto. Não é necessário repetir a ingestão quando apenas o código de conversa mudar.

Exemplos de perguntas:

- “Liste todos os violões ativos no catálogo, com preço e disponibilidade.”
- “Quais são os três violões mais baratos em estoque?”
- “Qual é a política de trocas por defeito?”
- “Quais são as condições de frete para Campo Grande?”

## Teste manual do fluxo de compra

Use **Nova conversa** e envie as mensagens na mesma sessão, selecionando um produto encontrado na consulta inicial:

| Etapa | Exemplo de mensagem | Comportamento esperado |
| --- | --- | --- |
| Consultar produtos | “Quais violões estão disponíveis?” | Consultar o SQLite e informar preço e estoque. |
| Selecionar um produto | “Tenho interesse no [nome do produto].” | Manter o produto no contexto da conversa. |
| Perguntar sobre parcelamento | “Posso parcelar ele até quantas vezes?” | O guardião permite a pergunta; o agente consulta as políticas de pagamento. |
| Reformular a pergunta | “Posso parcelar ele de quantas vezes?” | A reformulação continua no escopo e preserva o contexto. |
| Consultar entrega | “Qual é o valor do frete?” | O guardião permite a pergunta; o agente consulta as políticas de frete e pede o destino se necessário. |

Perguntas sobre pagamento, parcelas e frete também estão no escopo sem um produto previamente selecionado. Nesse caso, o agente deve solicitar os dados que faltarem para responder às condições específicas. As respostas comerciais devem se basear no PDF, em vez de inventar valores ou condições.

Como verificação de bloqueio, uma pergunta como “Escreva código Python para calcular o frete” continua fora do escopo. Mencionar “frete” ou “parcelamento” não libera automaticamente qualquer pedido.

## Regras de catálogo e resposta

Um produto **ativo no catálogo** tem `status = 'active'`. Para estar **disponível em estoque**, ele também precisa ter `stock_quantity > 0`. A quantidade de modelos é diferente da soma de unidades em estoque.

O prompt orienta o agente a listar todos os resultados solicitados, sem um limite padrão de cinco opções. Um limite deve ser usado quando o cliente pedir uma seleção, como “os três mais baratos”.

Para consultas SQL completas de categoria reconhecidas por `src/catalog.py`, a tabela final e os totais são gerados diretamente do SQLite. Isso evita depender do modelo para contar ou reescrever todos os itens. Esse tratamento aceita consultas simples com categoria, status ativo e filtro opcional de estoque; consultas com outros filtros, agregações, joins ou `LIMIT` seguem o fluxo normal do agente.

Se o agente retornar texto vazio, o código tenta gerar uma resposta novamente a partir dos resultados das ferramentas. Se a segunda tentativa também vier vazia, o chat exibe um erro.

Na exibição, `chat_markdown` em `src/app.py` escapa símbolos `$` que ainda não estejam escapados e separa subtítulos em negrito terminados em dois-pontos do primeiro produto numerado na mesma linha. Essa formatação também é aplicada ao reexibir o histórico, preservando o texto original armazenado. O prompt orienta o uso de subtítulos em linhas próprias e descrições indentadas; a interface não completa nomes ou informações que o modelo tenha deixado incompletos.

## Memória e guardião

A entrada principal do chat é `process_user_message(user_input, session_id)`, definida em `src/agent.py` e chamada por `src/app.py`:

1. A interface gera UUID4 por sessão e reutiliza esse código nas mensagens seguintes. A retomada exige 32 caracteres hexadecimais e versão UUID4, validados no backend antes de buscar o histórico. O campo de retomada é mascarado; o código deve ser tratado como uma credencial privada.
2. `src/guardrails.py` classifica apenas a pergunta atual, usando até quatro mensagens anteriores como contexto, com até 1.200 caracteres por mensagem. A entrada e o histórico são enviados como dados JSON, separados das instruções do classificador. O guardião usa o mesmo `model_name` do agente, com `reasoning=False`, `num_ctx=8192` e `num_predict=64`.
3. Para entradas aceitas, `RunnableWithMessageHistory` fornece o histórico a `get_agent_response`, que mantém as correções de catálogo e a recuperação de respostas vazias.
4. A memória registra uma única vez a pergunta e a resposta final efetivamente exibida, incluindo a tabela corrigida do catálogo. Perguntas bloqueadas e turnos com falha não são gravados na memória do agente; as mensagens exibidas continuam no histórico visual da interface.
5. O botão **Nova conversa** apaga a memória persistida da sessão atual, reinicia o histórico visual e gera outro ID. Para continuar uma conversa anterior, informe seu código em **Retomar conversa** na barra lateral.

`src/memory.py` usa SQLChatMessageHistory com SQLite em db/chat_history.db, separado do banco comercial. Os históricos persistem após reiniciar, mas a interface precisa do mesmo código para recuperar uma sessão. A ingestão não apaga esse banco. A classificação do guardião depende do modelo; o código bearer não representa autenticação de identidade nem autorização por titularidade de pedidos. Quem possui o código válido pode retomar a conversa; não há expiração ou revogação específica.

O retorno do guardião é tratado da seguinte forma, após remover espaços externos e converter para maiúsculas:

| Classificação | Ação |
| --- | --- |
| `PERMITIDA` | Executar o agente com o histórico da sessão. |
| `BLOQUEADA` | Exibir a recusa de escopo, sem executar o agente nem gravar o turno em sua memória. |
| Saída vazia ou ambígua | Repetir uma vez. Se continuar inválida, registrar PARSE_ERROR com fallback=false, decision=BLOCKED e não executar o agente. |
| Exceção na chamada do classificador | Registrar EXCEPTION com decision=BLOCKED e não executar o agente. |

As falhas não são apresentadas como recusa por assunto fora de escopo. O arquivo guardrail_metrics.log registra eventos SAFE, BLOCKED, PARSE_ERROR e EXCEPTION com request_id, latency_ms, attempt e fallback, sem o texto das conversas. Há rotação de até 1 MB por arquivo e dois backups. A falha do classificador não libera o agente. Uma classificação PERMITIDA incorreta ainda é possível; as restrições SQL são independentes do modelo. Os eventos medem formato e disponibilidade; não medem acerto semântico sem dados de referência.

O guardião adiciona uma chamada ao modelo por pergunta, ou duas se a primeira classificação vier em formato inválido. Para manter essa validação, novas interfaces devem chamar `process_user_message`; chamadas diretas a `get_agent_response` não passam pelo guardião.

## Restrições SQL

A conexão de leitura do agente está em src/sql_access.py. O arquivo comercial é aberto com mode=ro, query_only e um authorizer SQLite. As únicas tabelas permitidas são produtos, pedidos e promocoes; clientes e outros bancos/tabelas não podem ser lidos nem por consultas diretas. Pedidos expõe apenas order_id, order_date, status, total_brl e estimated_delivery. Não são enviados exemplos de registros ao modelo. Escrita, DDL, ATTACH, PRAGMA e funções fora da lista permitida são negados.

include_tables limita o esquema mostrado pelo LangChain; não é, sozinho, autorização de SQL. A restrição efetiva fica na conexão. A ingestão continua usando sua conexão de escrita separada, e o histórico usa chat_history.db; essas permissões não são concedidas ao LLM.

## Promoções e monitoramento

A tabela promocoes relaciona product_id, discount_percent e is_active. Consulte apenas as ativas. A tabela de catálogo calcula o preço final por produto com o maior desconto ativo, sem acumular promoções; mostra preço original, percentual e preço final. Produtos sem promoção são preservados. O CSV não fornece datas de vigência: is_active é o indicador disponível.

Os logs ficam na raiz em guardrail_metrics.log e são ignorados pelo Git, assim como db/chat_history.db. Um mesmo request_id pode ter dois PARSE_ERROR ou um PARSE_ERROR seguido de SAFE/BLOCKED; agrupe por request_id para contar perguntas, sem confundir tentativas com atendimentos. Uma decisão SAFE representa a classificação do modelo, não uma confirmação externa de que a decisão estava correta.

## Testes

Na raiz do projeto, com a `.venv` ativa:

```bash
python -m unittest discover -s tests -v
```

Os testes de catálogo usam um SQLite temporário e cobrem listagem completa, estoque zero, limites explícitos, ordenação por preço, categoria vazia e preservação de filtros SQL.

Os testes de conversa cobrem isolamento de sessões, gravação única da resposta final, contexto entre turnos, bloqueio antes de executar o agente e continuidade do fluxo de compra com as perguntas de parcelamento e frete. Também verificam o envio limitado do histórico em JSON, a nova tentativa após uma classificação inválida e a distinção entre recusa explícita e bloqueio fail-closed. Testes adicionais verificam promoções ativas sem acúmulo, persistência e retomada na interface e sincronização real do ChromaDB em processos separados, usando embeddings de teste sem downloads. A cobertura da ingestão inclui inclusão/atualização sem duplicatas, preservação de linhas ausentes e de outras tabelas, adição de colunas, migração de PK com índices/triggers, rollback em conflitos e preservação de outras fontes e do diretório vetorial.

Os recursos externos são substituídos nos testes: não é necessário ter o Ollama ativo nem baixar os modelos. Esses testes verificam a orquestração; o teste manual do fluxo de compra verifica as respostas produzidas pelo modelo e a consulta às políticas.

As dez interações reais do modelo estão documentadas em [AVALIACAO_QWEN.md](AVALIACAO_QWEN.md), gerado por `python scripts/evaluate_qwen.py`. O relatório registra respostas e ferramentas observadas, sem simular resultados do Ollama.

## Problemas comuns

| Sintoma | Verificação |
| --- | --- |
| `externally-managed-environment` | Ative `.venv` e use `python -m pip install -r requirements.txt`. |
| `No module named ...` | Confira o Python ativo com `which python` e reinstale as dependências na `.venv`. Os imports de agentes legados usam `langchain_classic`. |
| Falha de conexão com Ollama ou modelo não encontrado | Confira se o servidor está ativo e se `ollama list` mostra o mesmo modelo configurado em `src/agent.py`. |
| Perguntas de parcelamento ou frete recusadas como fora de escopo | Essas perguntas fazem parte do atendimento. Reinicie o servidor para recarregar o guardião atualizado e repita o fluxo na mesma sessão após selecionar o produto. |
| PARSE_ERROR ou EXCEPTION em guardrail_metrics.log | O guardião aplicou bloqueio fail-closed. Verifique o Ollama e a contagem de eventos; uma falha do modelo principal ainda pode impedir a resposta. |
| Histórico não aparece após reiniciar | Informe o código salvo em **Retomar conversa**. Uma nova sessão recebe outro código; o arquivo SQLite preserva os históricos existentes. |
| Arquivo de dados não encontrado | Execute na raiz e confira os nomes completos, incluindo espaços e o acento em `políticas_da_loja.pdf`. |
| Banco ou políticas sem resultados | Confira os logs da ingestão e os arquivos gerados em `db/` e `vectorstore/`. |
| Aviso de requisições sem `HF_TOKEN` | O modelo público pode ser baixado sem token, sujeito aos limites do Hugging Face. O aviso não indica, por si só, falha na execução. |
| Símbolos de moeda e negrito desformatados | A interface escapa `$` ao renderizar mensagens novas e o histórico. Reinicie a aplicação para carregar a versão atualizada. |
| Subtítulo e primeiro produto na mesma linha | A interface separa o padrão de subtítulo em negrito seguido de item numerado. Reinicie a aplicação para carregar a correção. |

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
│   ├── emporio.db             # Dados comerciais e promoções
│   └── chat_history.db        # Histórico persistente por sessão
├── vectorstore/              # Índice persistente do ChromaDB
├── src/
│   ├── data_ingestion.py      # CSVs → upsert SQL; PDF → sincronização por hashes
│   ├── agent.py               # Modelo, ferramentas, prompt e recuperação de resposta
│   ├── guardrails.py          # Classificação de escopo antes das ferramentas
│   ├── memory.py              # Histórico persistente e validação UUID4
│   ├── sql_access.py          # SQL de leitura e autorização de tabelas/colunas
│   ├── catalog.py             # Tabelas e totais de catálogo calculados no SQLite
│   └── app.py                 # Chat Streamlit e formatação de moeda
├── tests/
│   ├── test_catalog.py
│   ├── test_conversation.py
│   ├── test_ingestion.py
│   ├── test_app.py
│   └── test_sql_access.py
├── scripts/
│   └── evaluate_qwen.py
├── AVALIACAO_QWEN.md
├── requirements.txt
└── README.md
```
