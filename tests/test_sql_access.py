from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from src.sql_access import create_public_database


class SQLAccessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'store.db'
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript('''
                CREATE TABLE produtos (product_id INTEGER PRIMARY KEY, name TEXT, price_brl REAL, stock_quantity INTEGER);
                INSERT INTO produtos VALUES (1,'Violão',100,4);
                CREATE TABLE promocoes (product_id INTEGER, discount_percent REAL, is_active INTEGER);
                INSERT INTO promocoes VALUES (1,10,1);
                CREATE TABLE clientes (customer_id INTEGER, phone TEXT, email TEXT);
                INSERT INTO clientes VALUES (1,'TELEFONE_PRIVADO','EMAIL_PRIVADO');
                CREATE TABLE pedidos (order_id INTEGER, status TEXT, total_brl REAL, customer_id INTEGER, notes TEXT);
                INSERT INTO pedidos VALUES (10,'shipped',90,1,'NOTA_PRIVADA');
            ''')
        self.db = create_public_database(self.path)
        self.addCleanup(self.db._engine.dispose)

    def test_only_public_schema_is_exposed_without_samples_or_private_order_columns(self):
        self.assertEqual(set(self.db.get_usable_table_names()), {'produtos','pedidos','promocoes'})
        schema = self.db.get_table_info()
        for private in ('clientes','customer_id','notes','TELEFONE_PRIVADO','NOTA_PRIVADA'):
            self.assertNotIn(private, schema)

    def test_reads_joins_and_counts_continue_working(self):
        result = self.db.run('SELECT p.name, ROUND(p.price_brl*(1-pr.discount_percent/100.0),2) FROM produtos p JOIN promocoes pr ON p.product_id=pr.product_id WHERE pr.is_active=1')
        self.assertIn('90.0', result)
        self.assertIn('shipped', self.db.run('SELECT status FROM pedidos WHERE order_id=10'))

    def test_new_physical_connection_keeps_authorization_after_initialization(self):
        self.db._engine.dispose()
        self.assertIn('Violão', self.db.run('SELECT name FROM produtos'))
        self.assertTrue(self.db.run_no_throw('SELECT phone FROM clientes').startswith('Error:'))
        self.assertTrue(self.db.run_no_throw('SELECT name FROM sqlite_master').startswith('Error:'))

    def test_private_reads_are_denied_even_without_the_llm(self):
        for query in [
            'SELECT phone FROM clientes', 'SELECT COUNT(*) FROM clientes',
            'SELECT p.name,c.email FROM produtos p JOIN clientes c ON c.customer_id=p.product_id',
            'WITH segredo AS (SELECT phone FROM clientes) SELECT * FROM segredo',
            'SELECT name FROM produtos UNION SELECT email FROM clientes',
            'SELECT notes FROM pedidos', 'SELECT customer_id FROM pedidos', 'SELECT * FROM pedidos',
            'SELECT name FROM sqlite_master',
        ]:
            with self.subTest(query=query):
                answer = self.db.run_no_throw(query)
                self.assertTrue(answer.startswith('Error:'), answer)
                for secret in ('TELEFONE_PRIVADO','EMAIL_PRIVADO','NOTA_PRIVADA'):
                    self.assertNotIn(secret, answer)

    def test_writes_ddl_attach_and_configuration_bypasses_are_denied(self):
        for query in [
            'UPDATE produtos SET stock_quantity=0', 'DELETE FROM produtos',
            "INSERT INTO produtos VALUES (2,'Novo',0,0)", 'DROP TABLE produtos',
            'CREATE TABLE ataque (id INTEGER)', 'PRAGMA query_only=OFF',
            'ATTACH DATABASE ":memory:" AS other', "SELECT load_extension('qualquer')",
        ]:
            with self.subTest(query=query):
                self.assertTrue(self.db.run_no_throw(query).startswith('Error:'))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT stock_quantity FROM produtos').fetchone()[0], 4)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM produtos').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
