"""Conexão comercial de leitura, com autorização aplicada pelo próprio SQLite."""

from pathlib import Path
import sqlite3

from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_TABLES = frozenset({"produtos", "promocoes"})
SAFE_FUNCTIONS = frozenset({
    "abs", "avg", "char", "coalesce", "count", "date", "datetime", "format", "glob", "hex",
    "ifnull", "iif", "instr", "json_extract", "json_valid", "julianday", "length", "like",
    "lower", "ltrim", "max", "min", "nullif", "printf", "quote", "replace", "round",
    "rtrim", "strftime", "substr", "substring", "sum", "total", "trim", "typeof", "unicode",
    "unixepoch", "upper",
})


def create_public_database(db_path: Path = ROOT / "db/emporio.db") -> SQLDatabase:
    path = Path(db_path).resolve(strict=True)
    state = {"initializing": True}

    def authorize(action, table, column, database, trigger):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA:
            return sqlite3.SQLITE_OK if state["initializing"] else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ:
            if state["initializing"] and table in {
                "sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"
            }:
                return sqlite3.SQLITE_OK
            if database != "main" or table not in PUBLIC_TABLES:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (column or "").lower() in SAFE_FUNCTIONS:
            return sqlite3.SQLITE_OK
        # Inclui escrita, DDL, ATTACH, DETACH, extensões e leituras não autorizadas.
        return sqlite3.SQLITE_DENY

    def connect():
        # Sem cache de statements: toda consulta passa novamente pelo authorizer.
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                     check_same_thread=False, cached_statements=0)
        connection.execute("PRAGMA query_only=ON")
        connection.enable_load_extension(False)
        connection.set_authorizer(authorize)
        return connection

    engine = create_engine("sqlite://", creator=connect)
    try:
        db = SQLDatabase(
            engine, include_tables=sorted(PUBLIC_TABLES), sample_rows_in_table_info=0,
        )
        return db
    except Exception:
        engine.dispose()
        raise
    finally:
        # Somente a reflexão inicial, feita pelo código confiável, vê metadados.
        state["initializing"] = False
