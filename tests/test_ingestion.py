import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

import pandas as pd

from src.data_ingestion import SOURCES, PRIMARY_KEYS, ingest_sql, update_vectorstore


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for table, filename in SOURCES.items():
            frame = pd.DataFrame([{PRIMARY_KEYS[table]: 1}])
            if table == 'produtos':
                frame = pd.DataFrame([{'product_id': 1, 'name': 'Violão 1', 'price_brl': 100.0, 'stock_quantity': 2}])
            if table == 'promocoes':
                frame = pd.DataFrame([{'promotion_id': 1, 'product_id': 1, 'discount_percent': 10, 'is_active': 1}])
            frame.to_csv(self.root / filename, index=False)
        self.database = self.root / 'db/store.db'

    def test_csv_ingestion_can_run_twice_without_duplicates(self):
        for _ in range(2):
            ingest_sql(self.root, self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            for table in SOURCES:
                self.assertEqual(connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT discount_percent FROM promocoes').fetchone()[0], 10)

    def test_missing_source_does_not_replace_existing_data(self):
        ingest_sql(self.root, self.database)
        pd.DataFrame([{'product_id': 99}]).to_csv(self.root / SOURCES['produtos'], index=False)
        (self.root / SOURCES['promocoes']).unlink()
        with self.assertRaises(FileNotFoundError):
            ingest_sql(self.root, self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT product_id FROM produtos').fetchone()[0], 1)

    def test_missing_pdf_does_not_delete_existing_index(self):
        index = self.root / 'index'
        index.mkdir()
        marker = index / 'old.txt'
        marker.write_text('index anterior')
        with self.assertRaises((ValueError, FileNotFoundError)):
            update_vectorstore(self.root / 'missing.pdf', index)
        self.assertEqual(marker.read_text(), 'index anterior')

    def test_upsert_inserts_updates_and_preserves_absent_rows_and_other_tables(self):
        ingest_sql(self.root, self.database)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO produtos VALUES (99, 'Histórico preservado', 50, 1)")
            connection.execute('CREATE TABLE metricas (valor INTEGER)')
            connection.execute('INSERT INTO metricas VALUES (42)')
        pd.DataFrame([
            {'product_id': 1, 'name': 'Violão atualizado', 'price_brl': 120, 'stock_quantity': 7},
            {'product_id': 2, 'name': 'Produto novo', 'price_brl': 200, 'stock_quantity': 3},
        ]).to_csv(self.root / SOURCES['produtos'], index=False)
        ingest_sql(self.root, self.database)
        ingest_sql(self.root, self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM produtos').fetchone()[0], 3)
            self.assertEqual(connection.execute('SELECT price_brl,stock_quantity FROM produtos WHERE product_id=1').fetchone(), (120, 7))
            self.assertEqual(connection.execute('SELECT name FROM produtos WHERE product_id=99').fetchone()[0], 'Histórico preservado')
            self.assertEqual(connection.execute('SELECT valor FROM metricas').fetchone()[0], 42)
            self.assertEqual(connection.execute('PRAGMA temp.table_list').fetchall()[0][1], 'sqlite_temp_schema')

    def test_migration_adds_primary_key_and_preserves_index_trigger_and_old_rows(self):
        self.database.parent.mkdir()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('CREATE TABLE produtos (product_id BIGINT, name TEXT, price_brl REAL, stock_quantity INTEGER)')
            connection.execute("INSERT INTO produtos VALUES (1,'Antigo',90,1),(99,'Preservado',50,1)")
            connection.execute('CREATE INDEX idx_product_name ON produtos(name)')
            connection.execute('CREATE TABLE auditoria (product_id INTEGER)')
            connection.execute('CREATE TRIGGER audit_update AFTER UPDATE ON produtos BEGIN INSERT INTO auditoria VALUES (new.product_id); END')
        ingest_sql(self.root, self.database)
        ingest_sql(self.root, self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('PRAGMA table_info(produtos)').fetchall()[0][5], 1)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM produtos').fetchone()[0], 2)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='idx_product_name'").fetchone())
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM auditoria').fetchone()[0], 1)

    def test_duplicate_existing_keys_roll_back_schema_and_other_table_updates(self):
        self.database.parent.mkdir()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('CREATE TABLE produtos (product_id BIGINT, name TEXT, price_brl REAL, stock_quantity INTEGER)')
            connection.execute("INSERT INTO produtos VALUES (1,'Antigo',90,1)")
            connection.execute('CREATE TABLE pedidos (order_id INTEGER)')
            connection.execute('INSERT INTO pedidos VALUES (1),(1)')
        with self.assertRaisesRegex(ValueError, 'nulas/duplicadas'):
            ingest_sql(self.root, self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT price_brl FROM produtos').fetchone()[0], 90)
            self.assertEqual(connection.execute('PRAGMA table_info(produtos)').fetchall()[0][5], 0)

    def test_duplicate_csv_keys_are_rejected_before_changes(self):
        ingest_sql(self.root, self.database)
        pd.DataFrame([{'product_id': 1}, {'product_id': 1}]).to_csv(self.root / SOURCES['produtos'], index=False)
        with self.assertRaisesRegex(ValueError, 'duplicados'):
            ingest_sql(self.root, self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT name FROM produtos').fetchone()[0], 'Violão 1')

    def test_new_registered_csv_adds_a_table_without_touching_existing_ones(self):
        ingest_sql(self.root, self.database)
        pd.DataFrame([{'category_id': 5, 'name': 'Violões'}]).to_csv(self.root / 'categories.csv', index=False)
        ingest_sql(self.root, self.database, sources={'categorias': 'categories.csv'}, primary_keys={'categorias': 'category_id'})
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT name FROM categorias').fetchone()[0], 'Violões')
            self.assertEqual(connection.execute('SELECT name FROM produtos').fetchone()[0], 'Violão 1')

    def test_partial_csv_updates_preserve_other_columns_and_allow_new_columns(self):
        ingest_sql(self.root, self.database)
        pd.DataFrame([{'product_id': 1, 'price_brl': 175, 'brand': 'Marca nova'}]).to_csv(
            self.root / SOURCES['produtos'], index=False)
        ingest_sql(self.root, self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT name,stock_quantity,price_brl,brand FROM produtos').fetchone(),
                             ('Violão 1', 2, 175, 'Marca nova'))

    def test_legacy_migration_preserves_references_from_other_tables(self):
        self.database.parent.mkdir()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('CREATE TABLE produtos (product_id INTEGER, name TEXT)')
            connection.execute("INSERT INTO produtos VALUES (99,'Produto antigo')")
            connection.execute('CREATE UNIQUE INDEX unique_product ON produtos(product_id)')
            connection.execute('CREATE TABLE historico (product_id INTEGER REFERENCES produtos(product_id))')
            connection.execute('INSERT INTO historico VALUES (99)')
        ingest_sql(self.root, self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(connection.execute('SELECT product_id FROM historico').fetchone()[0], 99)

    def test_embedding_failure_does_not_delete_old_chunks(self):
        from langchain_core.documents import Document
        with patch('langchain_community.document_loaders.PyPDFLoader') as loader, \
                patch('langchain_chroma.Chroma') as chroma:
            loader.return_value.load.return_value = [Document(page_content='Política nova')]
            store = chroma.return_value
            store.get.return_value = {'ids': ['old'], 'documents': ['Política antiga'], 'metadatas': [{}]}
            store.add_documents.side_effect = RuntimeError('Embedding indisponível')
            with self.assertRaisesRegex(RuntimeError, 'Embedding indisponível'):
                update_vectorstore(self.root / 'policy.pdf', self.root / 'index', embeddings=object())
            store.delete.assert_not_called()

    def test_real_chroma_hash_upsert_preserves_directory_and_other_sources(self):
        # Processos separados reproduzem duas execuções do comando de ingestão.
        code = '''
import json, sys
from pathlib import Path
from unittest.mock import patch
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_chroma import Chroma
from data_ingestion import update_vectorstore
embed = DeterministicFakeEmbedding(size=8)
if sys.argv[2] == 'initial':
    legacy = Chroma(persist_directory=sys.argv[1], embedding_function=embed)
    legacy.add_documents([Document(page_content='Política antiga', metadata={'source': 'fixture.pdf'})], ids=['legacy'])
    legacy.add_documents([Document(page_content='Documento independente', metadata={'source': 'other.pdf'})], ids=['other-source'])
with patch('langchain_community.document_loaders.PyPDFLoader') as loader:
    text = ('Política revisada sobre entregas. ' if sys.argv[2] == 'changed' else 'Política de frete e devolução. ') * 100
    loader.return_value.load.return_value = [Document(page_content=text)]
    store = update_vectorstore(Path('fixture.pdf'), Path(sys.argv[1]), embed)
    print(json.dumps({'ids': sorted(store.get(include=[])['ids'])}))
'''
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'),
                           PYTHONDONTWRITEBYTECODE='1', ANONYMIZED_TELEMETRY='False')
        snapshots = []
        for mode in ('initial', 'unchanged', 'changed'):
            run = subprocess.run([sys.executable, '-c', code, str(self.root / 'index'), mode],
                                 env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            snapshots.append(json.loads(run.stdout.strip().splitlines()[-1])['ids'])
            marker = self.root / 'index' / 'sentinel.txt'
            if mode == 'initial':
                marker.write_text('não apagar')
            self.assertEqual(marker.read_text(), 'não apagar')
        self.assertGreater(len(snapshots[0]), 1)
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertNotIn('legacy', snapshots[0])
        self.assertEqual(set(snapshots[0]) & set(snapshots[2]), {'other-source'})


if __name__ == '__main__':
    unittest.main()
