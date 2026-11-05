import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src.catalog import list_products, render_catalog_query, render_availability_question


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "catalog.db")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "CREATE TABLE produtos (product_id INTEGER, name TEXT, price_brl REAL, "
                "stock_quantity INTEGER, category_id INTEGER, status TEXT)"
            )
            connection.executemany(
                "INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?)",
                [(i, f"Violão {i}", i * 100.5, 0 if i == 34 else 2, 5, "active")
                 for i in range(1, 35)]
                + [(35, "Descontinuado", 10, 4, 5, "discontinued"),
                   (36, "Outra categoria", 10, 4, 6, "active")],
            )

    def test_all_active_products_are_listed_without_default_limit(self):
        result = list_products(5, db_path=self.database)
        self.assertIn("**34 modelos ativos no catálogo**", result)
        self.assertIn("**33 estão disponíveis em estoque**", result)
        self.assertIn("**34 de 34 modelos**", result)
        self.assertEqual(sum(line.startswith("| ") for line in result.splitlines()), 36)
        self.assertIn("| 34 | Violão 34 | R$ 3.417,00 | 0 | Temporariamente indisponível |", result)
        self.assertNotIn("Descontinuado", result)
        self.assertNotIn("Outra categoria", result)

    def test_available_products_exclude_zero_stock(self):
        result = list_products(5, only_in_stock=True, db_path=self.database)
        self.assertIn("**33 de 33 modelos**", result)
        self.assertNotIn("Violão 34", result)

    def test_explicit_limit_preserves_the_total_and_price_order(self):
        result = list_products(5, only_in_stock=True, limit=3, db_path=self.database)
        self.assertIn("**3 de 33 modelos**", result)
        self.assertLess(result.index("Violão 1"), result.index("Violão 3"))
        self.assertNotIn("Violão 4", result)

    def test_empty_category(self):
        result = list_products(999, db_path=self.database)
        self.assertIn("**0 modelos ativos no catálogo**", result)
        self.assertIn("Não há produtos", result)

    def test_invalid_limit(self):
        with self.assertRaises(ValueError):
            list_products(5, limit=0, db_path=self.database)

    def test_complete_sql_listing_gets_exact_table(self):
        result = render_catalog_query(
            "SELECT product_id, name, price_brl, stock_quantity, status FROM produtos "
            "WHERE category_id = 5 AND status = 'active' ORDER BY product_id", self.database,
        )
        self.assertIn("**34 de 34 modelos**", result)

    def test_complete_sql_available_listing(self):
        result = render_catalog_query(
            "SELECT name, price_brl FROM produtos WHERE status = 'active' "
            "AND stock_quantity > 0 AND category_id = 5 ORDER BY price_brl ASC;", self.database,
        )
        self.assertIn("**33 de 33 modelos**", result)
        self.assertNotIn("Violão 34", result)

    def test_sql_with_other_filters_or_limits_is_not_replaced(self):
        for suffix in (" AND price_brl < 500", " LIMIT 5", " OR status = 'discontinued'", " AND name LIKE '%Yamaha%'"):
            with self.subTest(suffix=suffix):
                self.assertIsNone(render_catalog_query(
                    "SELECT name FROM produtos WHERE category_id = 5 AND status = 'active'" + suffix,
                    self.database,
                ))

    def test_only_active_promotions_apply_without_accumulating_discounts(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('CREATE TABLE promocoes (product_id INTEGER, discount_percent REAL, is_active INTEGER)')
            connection.executemany('INSERT INTO promocoes VALUES (?, ?, ?)',
                                   [(1, 10, 1), (1, 20, 1), (1, 95, 0), (2, 99, 0), (3, 90, 1)])
        result = list_products(5, db_path=self.database)
        self.assertIn('| 1 | Violão 1 | R$ 100,50 | 20% | R$ 80,40 |', result)
        self.assertIn('| 2 | Violão 2 | R$ 201,00 | 0% | R$ 201,00 |', result)
        self.assertLess(result.index('| 3 |'), result.index('| 1 |'))
        self.assertIn('**34 de 34 modelos**', result)
        self.assertEqual(result.count('| 1 | Violão 1 |'), 1)

    def test_drum_availability_uses_real_category_and_preserves_stock_counts(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executemany('INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?)', [
                (139, 'Bateria Acústica Yamaha Kit 1 Studio', 4439, 8, 3, 'active'),
                (140, 'Bateria Acústica Pearl Kit 2 Studio', 13285, 7, 3, 'active'),
                (141, 'Bateria Acústica Yamaha Kit 3 Studio', 14922, 8, 3, 'active'),
                (142, 'Bateria sem estoque', 1000, 0, 3, 'active'),
                (143, 'Bateria descontinuada', 1000, 5, 3, 'discontinued'),
            ])
        for question in ('Tem baterias?', 'Tem bateria?', 'Vocês têm baterias?', 'Estou procurando uma bateria', 'Mostre as baterias em estoque'):
            with self.subTest(question=question):
                result = render_availability_question(question, self.database, {3: 'Baterias e Percussão'})
                self.assertIn('**3 de 3 modelos**', result)
                self.assertIn('Bateria Acústica Yamaha Kit 1 Studio', result)
                self.assertIn('Bateria Acústica Pearl Kit 2 Studio', result)
                self.assertIn('Bateria Acústica Yamaha Kit 3 Studio', result)
                self.assertNotIn('Bateria sem estoque', result)
                self.assertNotIn('Bateria descontinuada', result)

    def test_category_ids_are_resolved_from_names_not_assumed(self):
        result = render_availability_question('Tem violões?', self.database, {5: 'Violões', 1: 'Guitarras'})
        self.assertIn('**33 de 33 modelos**', result)
        self.assertIn('Violão 1', result)

    def test_additional_filters_or_ambiguous_requests_are_not_overridden(self):
        categories = {3: 'Baterias e Percussão', 6: 'Instrumentos de Sopro (Madeiras)', 7: 'Instrumentos de Sopro (Metais)'}
        for question in ('Tem baterias até 500 reais?', 'Tem baterias da Yamaha?', 'Tem sopro?', 'Não mostre baterias', 'Qual é o frete?', 'Tem banjos?'):
            with self.subTest(question=question):
                self.assertIsNone(render_availability_question(question, self.database, categories))


if __name__ == "__main__":
    unittest.main()
