# emporio-musica-agent

## Instalação

Na raiz do projeto, crie e ative um ambiente virtual para instalar as dependências:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Em novos terminais, execute `source .venv/bin/activate` antes de usar o projeto.
Use `python -m pip` para garantir que a instalação use o Python do ambiente ativo.

## Estrutura

```text
emporio-musica-agent/
├── data/
│   ├── politicas_da_loja.pdf
│   ├── produtos.csv
│   ├── pedidos.csv
│   └── clientes.csv
├── vectorstore/               # ChromaDB salvo localmente
├── db/
│   └── emporio.db             # Banco SQLite gerado a partir dos CSVs
├── src/
│   ├── data_ingestion.py      # Script para ler CSVs para SQLite e PDF para ChromaDB
│   ├── agent.py               # Lógica do LangChain, prompt e tools
│   └── app.py                 # Interface Streamlit
├── requirements.txt
├── conversas_exemplos/        # Exemplos salvos em .md
└── README.md                  # Justificativas e setup
```
