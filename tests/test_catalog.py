import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src.catalog import list_products, render_catalog_query


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


if __name__ == "__main__":
    unittest.main()
