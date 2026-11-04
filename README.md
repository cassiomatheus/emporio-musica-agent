# Empório da Música — Assistente de atendimento

Assistente em português para consultar produtos, estoque, pedidos e políticas da loja, com interface Streamlit, ferramentas SQL e retrieval do PDF. O projeto oferece atendimento consultivo; não efetua pagamentos nem registra compras.

## 1. Como executar

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

## 2. Decisões técnicas

| Escolha | Justificativa |
| --- | --- |
| **LangChain + `langchain-classic`** | Integram modelo, ferramentas SQL, retriever e histórico. `AgentExecutor` coordena as consultas com a API utilizada no projeto. |
| **Qwen 3.5 9B via Ollama** | Permite inferência local e chamadas de ferramentas. Temperatura zero e `reasoning=False` priorizam respostas diretas; contexto de 8.192 tokens e saída de até 4.096 tokens acomodam consultas e listas. Não foi realizado benchmark comparativo de modelos. |
| **SQLite para CSVs** | Mantém preços, estoque e pedidos estruturados, permitindo filtros e contagens por SQL. Evita usar similaridade textual para calcular totais. |
| **ChromaDB + MiniLM para o PDF** | Índice vetorial persistente e embeddings locais com `all-MiniLM-L6-v2`. Trechos de 1.000 caracteres, sobreposição de 100 e recuperação dos três mais próximos são parâmetros iniciais para preservar continuidade e limitar o contexto. |
| **Prompt com regras de domínio** | Orienta consultas SQL para dados e retrieval para políticas, resposta em português, distinção entre ativo e disponível, listagens completas e solicitação de dados ausentes. O histórico e os resultados das ferramentas entram no contexto do agente. |
| **Guardião e memória por sessão** | O guardião classifica o escopo antes das ferramentas, usando contexto recente em JSON. A memória guarda a resposta final por UUID; o Streamlit mantém a apresentação e oferece reinício da conversa. |

Fluxo: **pergunta → guardião → agente com histórico → SQL/retrieval → resposta**. Para listagens SQL simples de categoria reconhecidas por `src/catalog.py`, o código calcula os totais e monta a tabela diretamente do banco, reduzindo erros de contagem do modelo. A interface trata moeda e separação entre subtítulos e listas.

## 3. Limitações e próximos passos

**Limitações conhecidas:**

- A ingestão carrega apenas produtos, pedidos e clientes. Categorias, itens de pedidos e promoções ainda não são importados. Reexecutá-la substitui essas tabelas e pode duplicar trechos no ChromaDB.
- O modelo pode errar SQL, classificação de escopo ou interpretação das políticas. A correção determinística de catálogo cobre apenas consultas simples reconhecidas; não valida toda resposta gerada. A qualidade do retrieval em português ainda não foi avaliada sistematicamente.
- A memória existe apenas em RAM e se perde ao reiniciar o servidor. Não há autenticação por cliente, autorização de acesso a pedidos ou restrição dedicada das ferramentas SQL a consultas de leitura.
- O desempenho depende do hardware; o guardião acrescenta uma chamada por pergunta, com nova tentativa se o formato for inválido. As dependências não estão integralmente fixadas, e as APIs de memória utilizadas têm avisos de descontinuação na versão instalada.

**Com mais tempo:** integrar as fontes restantes e tornar a ingestão idempotente; avaliar embeddings multilíngues e reranking com perguntas de referência; ampliar testes de fluxo e precisão das respostas; persistir memória, implementar controles de acesso e SQL somente leitura; fixar versões e migrar as APIs de memória legadas.

## 4. Uso de assistente de código

Foi utilizado o **OpenAI Codex**, com acesso ao repositório e ao terminal, como apoio à implementação, diagnóstico e documentação. O workflow foi iterativo:

1. Os testes manuais do chat forneceram erros de execução, respostas incorretas e exemplos de quebra do fluxo de compra.
2. O Codex inspecionou código, dados e logs, propôs e aplicou ajustes de compatibilidade do LangChain, catálogo, formatação, memória e guardião.
3. As alterações foram verificadas com testes automatizados, testes da interface via Streamlit AppTest e chamadas ao Ollama local; novos testes manuais orientaram as correções seguintes.

A IA também auxiliou na redação deste README. As verificações cobrem os casos exercitados e não representam garantia de acerto em todos os cenários de atendimento.

Detalhes de arquitetura, módulos, solução de problemas e operação estão no [guia completo](README_full.md).
