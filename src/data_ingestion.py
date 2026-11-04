"""Ingestão incremental: upsert dos CSVs e sincronização do PDF por hashes."""

from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "produtos": "desafio_tecnico_ai_eng - products.csv",
    "pedidos": "desafio_tecnico_ai_eng - orders.csv",
    "clientes": "desafio_tecnico_ai_eng - customers.csv",
    "promocoes": "desafio_tecnico_ai_eng - promotions.csv",
}
PRIMARY_KEYS = {
    "produtos": "product_id", "pedidos": "order_id",
    "clientes": "customer_id", "promocoes": "promotion_id",
}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _column_type(series: pd.Series) -> str:
    if pd.api.types.is_integer_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype):
        return "INTEGER"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "REAL"
    return "TEXT"


def _validate_frame(frame: pd.DataFrame, table: str, pk: str):
    if pk not in frame or frame[pk].isna().any():
        raise ValueError(f"{table}: chave {pk} ausente ou nula.")
    if frame[pk].duplicated().any():
        raise ValueError(f"{table}: valores duplicados na chave {pk} do CSV.")
    if table == "promocoes":
        for column in ("product_id", "discount_percent", "is_active"):
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not frame.is_active.isin([0, 1]).all():
            raise ValueError("is_active das promoções deve ser 0 ou 1.")
        if not frame.discount_percent.between(0, 100).all():
            raise ValueError("Percentual de desconto fora do intervalo de 0 a 100.")


def _ensure_table(connection, frame, table, pk):
    quoted, key = _quote(table), _quote(pk)
    existing = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if existing is None:
        columns = [
            f"{_quote(column)} {_column_type(frame[column])}" +
            (" NOT NULL PRIMARY KEY" if column == pk else "")
            for column in frame.columns
        ]
        connection.execute(f"CREATE TABLE {quoted} ({', '.join(columns)})")
        return

    info = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
    names = {column[1] for column in info}
    if pk not in names:
        raise ValueError(f"{table}: a tabela existente não contém a chave {pk}.")
    for column in frame.columns:
        if column not in names:
            connection.execute(
                f"ALTER TABLE {quoted} ADD COLUMN {_quote(column)} {_column_type(frame[column])}"
            )
    info = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
    current_keys = [column[1] for column in sorted(info, key=lambda row: row[5]) if column[5]]
    if current_keys == [pk]:
        return
    if current_keys:
        raise ValueError(f"{table}: chave primária existente incompatível: {current_keys}.")
    invalid = connection.execute(
        f"SELECT 1 FROM {quoted} GROUP BY {key} HAVING {key} IS NULL OR COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if invalid:
        raise ValueError(f"{table}: corrija chaves nulas/duplicadas do banco antes da migração.")

    # Migração das tabelas antigas criadas pelo Pandas, na mesma transação.
    # Conservar a definição SQL original, índices e triggers explícitos.
    original_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]
    objects = connection.execute(
        "SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    definition = original_sql[original_sql.index('('):].rstrip()
    if not definition.endswith(')'):
        raise ValueError(f"{table}: formato de esquema não suportado para migração automática.")
    temporary = _quote(f"_migrate_{table}_{uuid4().hex}")
    definition = definition[:-1] + f", PRIMARY KEY ({key}), CHECK ({key} IS NOT NULL))"
    connection.execute(f"CREATE TABLE {temporary} {definition}")
    columns = ', '.join(_quote(column[1]) for column in info)
    connection.execute(f"INSERT INTO {temporary} ({columns}) SELECT {columns} FROM {quoted}")
    connection.execute(f"DROP TABLE {quoted}")
    connection.execute(f"ALTER TABLE {temporary} RENAME TO {quoted}")
    for (sql,) in objects:
        connection.execute(sql)


def _upsert_frame(connection, frame, table, pk):
    _ensure_table(connection, frame, table, pk)
    staging = _quote(f"stg_{table}_{uuid4().hex}")
    columns = ', '.join(_quote(column) for column in frame.columns)
    definitions = ', '.join(f"{_quote(column)} {_column_type(frame[column])}" for column in frame.columns)
    connection.execute(f"CREATE TEMP TABLE {staging} ({definitions})")
    values = frame.astype(object).where(frame.notna(), None).itertuples(index=False, name=None)
    connection.executemany(
        f"INSERT INTO temp.{staging} ({columns}) VALUES ({', '.join('?' for _ in frame.columns)})", values
    )
    updated = [column for column in frame.columns if column != pk]
    action = "DO NOTHING"
    if updated:
        assignments = ', '.join(f"{_quote(column)} = excluded.{_quote(column)}" for column in updated)
        changed = ' OR '.join(f"{_quote(table)}.{_quote(column)} IS NOT excluded.{_quote(column)}" for column in updated)
        action = f"DO UPDATE SET {assignments} WHERE {changed}"
    connection.execute(
        f"INSERT INTO {_quote(table)} ({columns}) SELECT {columns} FROM temp.{staging} WHERE true "
        f"ON CONFLICT ({_quote(pk)}) {action}"
    )
    connection.execute(f"DROP TABLE temp.{staging}")


def ingest_sql(data_dir: Path = ROOT / "data", db_path: Path = ROOT / "db/emporio.db",
               sources: dict | None = None, primary_keys: dict | None = None):
    sources = SOURCES if sources is None else sources
    keys = PRIMARY_KEYS if primary_keys is None else primary_keys
    frames = {table: pd.read_csv(Path(data_dir) / filename) for table, filename in sources.items()}
    for table, frame in frames.items():
        _validate_frame(frame, table, keys[table])
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path, isolation_level=None)) as connection:
        # SQLite exige desativar FKs antes da migração de esquema. A integridade
        # é verificada antes do commit; uma falha reverte toda a carga SQL.
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table, frame in frames.items():
                _upsert_frame(connection, frame, table, keys[table])
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("A carga viola relacionamentos de chave estrangeira.")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys=ON")
    print("Upsert SQLite concluído: " + ', '.join(frames) + ".")


def update_vectorstore(pdf_path: Path = ROOT / "data/políticas_da_loja.pdf",
                       index_dir: Path = ROOT / "vectorstore", embeddings=None):
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_chroma import Chroma

    pdf_path, index_dir = Path(pdf_path), Path(index_dir)
    docs = PyPDFLoader(str(pdf_path)).load()
    splits = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100).split_documents(docs)
    if not splits:
        raise ValueError("O PDF não contém texto para indexação.")
    if index_dir.is_symlink():
        raise ValueError("O diretório do índice não pode ser um link simbólico.")
    source = str(pdf_path.resolve())
    by_id = {}
    for document in splits:
        identifier = sha256((source + '\0' + document.page_content).encode('utf-8')).hexdigest()
        document.metadata.update(source=source, ingestion_source=source)
        by_id.setdefault(identifier, document)
    if embeddings is None:
        from langchain_huggingface import HuggingFaceEmbeddings
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    store = Chroma(persist_directory=str(index_dir), embedding_function=embeddings)
    aliases = {source, str(pdf_path)}
    if pdf_path.resolve().is_relative_to(ROOT):
        aliases.add(str(pdf_path.resolve().relative_to(ROOT)))
    old = store.get(where={"$or": [{"ingestion_source": source}] + [{"source": alias} for alias in sorted(aliases)]},
                    include=["documents", "metadatas"])
    previous = {identifier: (text, metadata) for identifier, text, metadata
                in zip(old['ids'], old['documents'], old['metadatas'])}
    changed = [identifier for identifier, document in by_id.items()
               if previous.get(identifier) != (document.page_content, document.metadata)]
    if changed:
        store.add_documents(documents=[by_id[identifier] for identifier in changed], ids=changed)
    # Só retirar versões obsoletas deste PDF depois de gravar os trechos atuais.
    obsolete = sorted(set(old['ids']) - by_id.keys())
    if obsolete:
        store.delete(ids=obsolete)
    print(f"ChromaDB sincronizado: {len(by_id)} trechos atuais, {len(changed)} gravados, {len(obsolete)} obsoletos removidos.")
    return store


def main():
    ingest_sql()
    update_vectorstore()


if __name__ == "__main__":
    main()
