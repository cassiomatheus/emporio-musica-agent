# Empório da Música — Assistente de atendimento

## Problema e objetivos

A Empório da Música é uma loja fictícia de instrumentos musicais cujo atendimento recebe perguntas recorrentes sobre catálogo, preços, estoque, pedidos e políticas comerciais. O desafio consiste em construir um protótipo de assistente capaz de responder a essas solicitações em linguagem natural, consultando as fontes apropriadas em vez de depender exclusivamente do conhecimento do modelo.

O objetivo foi integrar dois tipos de informação: dados estruturados, armazenados originalmente em CSVs, e regras de atendimento descritas em um manual PDF. Para isso, desenvolvi um agente em Python que identifica quando consultar o banco de dados e quando recuperar trechos das políticas, mantendo o contexto de uma conversa e respondendo em português com uma persona amigável e profissional. A interface permite realizar consultas sucessivas sobre o mesmo produto, como preço, disponibilidade, parcelamento e frete.

O escopo é **consultivo**: o agente não efetua compras, pagamentos, cancelamentos ou alterações de pedidos. A proposta é demonstrar a integração entre LLMs, ferramentas externas e dados de negócio, além de explicitar os limites do protótipo.

## Como executar

**Pré-requisitos:** Python com `venv` (ambiente validado com Python 3.14.6), [Ollama instalado](https://docs.ollama.com/linux), internet para os downloads iniciais e memória/espaço para os modelos. O provedor é o **Ollama local**, sem chave de API, no endereço padrão `http://localhost:11434`.

Execute os comandos na **raiz do projeto**, em Linux/Bash:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Se o Ollama ainda não estiver em execução como serviço, mantenha `ollama serve` ativo em outro terminal. No terminal do projeto:

```bash
ollama pull qwen3.5:9b
ollama list
```

O modelo configurado é `qwen3.5:9b`. Para trocá-lo, ajuste `model_name` em `src/agent.py`; ele deve suportar chamadas de ferramentas e a configuração de raciocínio utilizada. O guardião recebe o mesmo nome de modelo.

Confira os arquivos esperados pela ingestão:

```text
data/desafio_tecnico_ai_eng - products.csv
data/desafio_tecnico_ai_eng - orders.csv
data/desafio_tecnico_ai_eng - customers.csv
data/políticas_da_loja.pdf
```

Prepare os dados e inicie o chat:

```bash
python src/data_ingestion.py
python -m streamlit run src/app.py
```

A ingestão gera `db/emporio.db` e `vectorstore/`; o modelo de embeddings é baixado na primeira execução. Confira as mensagens de sucesso das etapas SQLite e PDF. Abra a URL exibida pelo Streamlit, normalmente `http://localhost:8501`.

Em novos terminais, reative `.venv`. Para recarregar alterações nos módulos, encerre com `Ctrl+C` e execute novamente o Streamlit. **Nova conversa** limpa a sessão atual. Não é necessário repetir a ingestão a cada execução do chat.

Para verificar dependências e executar os testes, sem exigir Ollama ativo:

```bash
python -m pip check
python -m unittest discover -s tests -v
```

Teste o contexto na mesma conversa: escolha um produto, pergunte “Posso parcelar ele até quantas vezes?” e depois “Qual é o valor do frete?”. Essas perguntas estão no escopo; as condições devem ser consultadas nas políticas da loja.

## Decisões arquiteturais

Optei por uma arquitetura em Python com um agente orientado a ferramentas. Os dados transacionais e as políticas documentais têm características diferentes e, por isso, são tratados por mecanismos distintos. O agente utiliza ferramentas SQL para informações estruturadas e uma ferramenta de recuperação semântica para o PDF. A interface, o histórico de mensagens e a classificação de escopo ficam separados dessas consultas.

**SQLite — dados estruturados.** Escolhi o SQLite por ser leve, relacional e suficiente para o volume dos arquivos fornecidos. Ele permite aplicar filtros, ordenações e contagens sobre produtos, estoque e pedidos sem depender de similaridade semântica ou da memória do LLM. A escolha também aproveitou minha experiência prévia com bancos de dados e processamento de informações no projeto de mestrado. Nesta versão, a ingestão importa produtos, pedidos e clientes; categorias, itens de pedidos e promoções ainda não integram o banco utilizado pelo agente.

**ChromaDB — base vetorial.** Para as políticas da loja, aproveitei minha experiência de pesquisa com representações vetoriais, embeddings e recuperação de informações. O ChromaDB fornece um índice persistente, permitindo reutilizar os embeddings do manual entre execuções. A busca semântica é empregada para localizar trechos pertinentes; ela não substitui consultas exatas ao banco de produtos.

**Streamlit — interface de demonstração.** Escolhi o Streamlit porque já tinha familiaridade com a construção de interfaces e visualizações em Python no contexto acadêmico. Como o objetivo da seleção é avaliar o agente funcionando, essa abordagem permitiu criar rapidamente um chat navegável sem desenvolver um frontend separado. O `session_state` mantém a apresentação da conversa e um identificador próprio para cada sessão.

**LangChain — integração e orquestração.** O LangChain foi a principal tecnologia nova incorporada neste desafio. Adotei-o por oferecer abstrações prontas para conectar `ChatOllama`, ferramentas SQL, o retriever do ChromaDB e o histórico de mensagens. `create_tool_calling_agent` e `AgentExecutor` coordenam a seleção e execução das ferramentas; `RunnableWithMessageHistory` reaproveita o contexto da sessão.

Isso reduziu a necessidade de implementar manualmente todo o protocolo de chamadas de ferramentas e permitiu concentrar o desenvolvimento nas regras de domínio e na experiência de atendimento. Como contrapartida, a solução depende de componentes de `langchain-classic` e de APIs de memória que exigirão acompanhamento de compatibilidade.

## Escolha do modelo: Qwen 3.5 9B com Ollama

Escolhi o `qwen3.5:9b` executado localmente pelo Ollama porque o desafio requer interpretação de mensagens em português e chamadas de ferramentas, e eu já tinha experiência prática com modelos locais e Ollama em atividades do mestrado. Reaproveitar esse ambiente reduziu o tempo de configuração e permitiu desenvolver e testar o agente sem depender de uma API paga a cada mensagem.

O modelo é integrado por `ChatOllama`, com temperatura `0`, `reasoning=False`, janela configurada de `8.192` tokens e limite de geração de `4.096` tokens. Esses parâmetros procuram favorecer respostas diretas e disponibilizar contexto suficiente para histórico, ferramentas e seus resultados; temperatura zero, entretanto, não garante respostas sempre idênticas ou corretas.

A escolha foi pragmática, considerando o hardware disponível e a experiência prévia com a ferramenta. **Não foi realizado um benchmark comparativo rigoroso entre diferentes modelos nesta implementação**, de modo que não afirmo que o Qwen 3.5 9B seja o melhor modelo possível para a tarefa.

Uma evolução seria comparar modelos sob os mesmos cenários, incluindo qualidade de tool calling, latência, consumo de memória e respostas em português.

## Estratégia de retrieval para as políticas da loja

As informações de produtos e pedidos são consultadas via SQL; as regras sobre devolução, troca, garantia, horário, frete e pagamento são recuperadas do PDF por busca semântica.

A ingestão divide o manual em **trechos de 1.000 caracteres, com sobreposição de 100 caracteres**, para reduzir a perda de contexto nas fronteiras entre fragmentos. Cada trecho é convertido em vetor pelo modelo `sentence-transformers/all-MiniLM-L6-v2` e armazenado no ChromaDB.

Quando o agente precisa consultar uma política, a ferramenta `consulta_politicas_loja` busca os **três fragmentos mais próximos da pergunta (`top-k = 3`)**. O Qwen recebe esses trechos e formula a resposta.

A utilização de embeddings e recuperação vetorial reaproveita conhecimentos e técnicas com os quais já trabalhava no mestrado, especialmente a representação semântica de textos. O tamanho dos trechos e o valor de `k` são parâmetros iniciais do protótipo, não resultados de uma otimização experimental.

Essa abordagem possui limitações. A semelhança vetorial não garante que o trecho recuperado contenha todas as condições necessárias para responder. O modelo de embeddings escolhido pode ter limitações para perguntas formuladas em português, e a qualidade da recuperação ainda não foi medida sistematicamente com um conjunto de perguntas e evidências de referência.

Além disso, a ingestão atual pode duplicar fragmentos se executada repetidamente no mesmo índice.

Como próximos passos, avaliaria modelos multilíngues, diferentes configurações de chunking e top-k, além da reconstrução idempotente do índice.

## Estratégia de prompt

O prompt define a persona de atendimento em português e orienta o uso de SQL para catálogo, preços, estoque e pedidos, e de `consulta_politicas_loja` para condições comerciais. As regras distinguem produtos ativos de produtos com estoque, exigem consultas antes de informar valores e orientam a solicitação de dados ausentes, como o destino da entrega. O histórico da sessão e os resultados das ferramentas entram no contexto para permitir perguntas de continuação.

As instruções também tratam a apresentação: listas completas quando solicitadas, nomes comerciais dos produtos em vez de códigos internos de categoria e alternativas com disponibilidade consultada. Para listagens simples reconhecidas por `src/catalog.py`, a tabela e os totais são calculados diretamente do SQLite. Essa verificação complementa o prompt, sem tornar todas as respostas determinísticas.

## Segurança e controle de escopo

Antes de chamar o agente, a função `process_user_message` executa um **guardião de escopo**. Esse componente utiliza o mesmo Qwen para classificar a mensagem como `PERMITIDA` ou `BLOQUEADA`, considerando a pergunta atual e um histórico recente limitado, transmitido como dados JSON.

Perguntas sobre instrumentos e atendimento da loja são encaminhadas; solicitações externas ao domínio, como produção de código ou assuntos sem relação com a loja, são recusadas educadamente.

Se o classificador devolver um formato inválido, o sistema tenta novamente uma vez. Persistindo a saída inválida, apresenta um erro de validação em vez de liberar automaticamente o agente.

O histórico do atendimento é separado por identificador de sessão e permanece apenas na memória do processo; a opção **Nova conversa** reinicia esse estado.

**Limite importante:** esse guardião controla assunto, não identidade nem permissões de acesso.

A versão atual não autentica clientes, não implementa autorização específica para visualizar pedidos e ainda não impõe uma restrição dedicada de somente leitura às ferramentas SQL. Portanto, não seria correto apresentar o sistema como preparado para consultar dados pessoais de clientes em produção.

Antes de qualquer uso real, seria necessário acrescentar autenticação, autorização por titularidade, privilégios mínimos no banco e revisão da exposição de detalhes técnicos nas mensagens de erro. O classificador por LLM também não constitui proteção comprovada contra todas as formas de prompt injection.

## Limitações e próximos passos

**Limitações conhecidas:**

- A ingestão carrega apenas produtos, pedidos e clientes. Categorias, itens de pedidos e promoções ainda não são importados. Reexecutá-la substitui essas tabelas e pode duplicar trechos no ChromaDB.
- O modelo pode errar SQL, classificação de escopo ou interpretação das políticas. A correção determinística de catálogo cobre apenas consultas simples reconhecidas; não valida toda resposta gerada. A qualidade do retrieval em português ainda não foi avaliada sistematicamente.
- A memória existe apenas em RAM e se perde ao reiniciar o servidor. Não há autenticação por cliente, autorização de acesso a pedidos ou restrição dedicada das ferramentas SQL a consultas de leitura.
- O desempenho depende do hardware; o guardião acrescenta uma chamada por pergunta, com nova tentativa se o formato for inválido. As dependências não estão integralmente fixadas, e as APIs de memória utilizadas têm avisos de descontinuação na versão instalada.

**Com mais tempo:** integrar as fontes restantes e tornar a ingestão idempotente; avaliar embeddings multilíngues e reranking com perguntas de referência; ampliar testes de fluxo e precisão das respostas; persistir memória, implementar controles de acesso e SQL somente leitura; fixar versões e migrar as APIs de memória legadas.

## Uso do OpenAI Codex no desenvolvimento

Utilizei o **OpenAI Codex** como assistente de programação durante a implementação, depuração e documentação do protótipo.

O uso da ferramenta foi organizado em ciclos: observar comportamentos do chat, identificar um problema ou necessidade, examinar os módulos relacionados, propor um ajuste e verificar seus efeitos por meio de testes e novas interações.

O Codex apoiou ajustes de compatibilidade do LangChain, consultas e apresentação do catálogo, formatação no Streamlit, gerenciamento da memória e classificação de escopo. Também auxiliou na criação e execução de testes automatizados e na redação da documentação.

As verificações documentadas incluem `unittest`, testes da interface com Streamlit AppTest e interações manuais com o Ollama; os testes com dependências simuladas não substituem a avaliação das respostas do modelo real.

O uso de IA acelerou tarefas repetitivas e a investigação de erros, mas o código gerado precisa ser compreendido e revisado antes da entrega.

Minha responsabilidade é conseguir explicar as decisões adotadas, reproduzir as funcionalidades essenciais, identificar limitações e distinguir comportamentos comprovados de hipóteses ainda não avaliadas. Não apresento a utilização do Codex, isoladamente, como garantia de qualidade da solução.

Detalhes de arquitetura, módulos, solução de problemas e operação estão no [guia completo](README_full.md).

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
├── vectorstore/               # Índice persistente do ChromaDB
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
