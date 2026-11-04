import pandas as pd
from sqlalchemy import create_engine
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
import os

# Criar pastas se não existirem
os.makedirs("db", exist_ok=True)
os.makedirs("vectorstore", exist_ok=True)

# 1. Ingestão de CSVs para SQLite
print("Criando banco de dados SQLite...")
engine = create_engine("sqlite:///db/emporio.db")

try:
    # Ajuste os nomes dos arquivos conforme o seu diretório data/
    df_produtos = pd.read_csv("data/desafio_tecnico_ai_eng - products.csv")
    df_produtos.to_sql("produtos", engine, if_exists="replace", index=False)
    
    df_pedidos = pd.read_csv("data/desafio_tecnico_ai_eng - orders.csv")
    df_pedidos.to_sql("pedidos", engine, if_exists="replace", index=False)
    
    df_clientes = pd.read_csv("data/desafio_tecnico_ai_eng - customers.csv")
    df_clientes.to_sql("clientes", engine, if_exists="replace", index=False)
    print("Banco de dados SQLite criado com sucesso!")
except Exception as e:
    print(f"Erro ao processar CSVs: {e}")

# 2. Ingestão do PDF para ChromaDB
print("Processando PDF de Políticas...")
try:
    loader = PyPDFLoader("data/políticas_da_loja.pdf")
    docs = loader.load()
    
    # Quebrar o texto em pedaços menores (chunks) para facilitar a busca
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    splits = text_splitter.split_documents(docs)
    
    # Embeddings locais super leves que rodam na CPU
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    
    vectorstore = Chroma.from_documents(
        documents=splits, 
        embedding=embeddings, 
        persist_directory="vectorstore"
    )
    print("Vectorstore ChromaDB criado com sucesso!")
except Exception as e:
    print(f"Erro ao processar PDF: {e}")