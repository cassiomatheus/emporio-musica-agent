# emporio-musica-agent

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
