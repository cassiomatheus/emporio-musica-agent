"""Listagens de catálogo com totais e preços obtidos diretamente do SQLite."""

import sqlite3
import re
from contextlib import closing
from pathlib import Path


def render_catalog_query(query: str, db_path: str = "db/emporio.db") -> str | None:
    """Formata apenas consultas completas de categoria, sem outros filtros.

    A correspondência restrita evita descartar filtros de marca, preço, LIMIT,
    joins ou agregações quando o agente usa SQL em vez da ferramenta de catálogo.
    """
    match = re.fullmatch(
        r"\s*SELECT\s+(?P<columns>[\w\s,*]+)\s+FROM\s+produtos\s+WHERE\s+"
        r"(?P<where>.+?)(?:\s+ORDER\s+BY\s+(?:product_id|price_brl|name)"
        r"(?:\s+(?:ASC|DESC))?(?:\s*,\s*(?:product_id|price_brl|name)"
        r"(?:\s+(?:ASC|DESC))?)*)?\s*;?\s*",
        query, flags=re.IGNORECASE,
    )
    if not match:
        return None
    columns = {column.strip().lower() for column in match['columns'].split(',')}
    allowed = {'product_id', 'name', 'price_brl', 'stock_quantity', 'status', '*'}
    if not columns <= allowed or not ('name' in columns or '*' in columns):
        return None
    category_id = None
    active = False
    only_in_stock = False
    for condition in re.split(r'\s+AND\s+', match['where'].strip(), flags=re.IGNORECASE):
        category = re.fullmatch(r'category_id\s*=\s*(\d+)', condition, flags=re.IGNORECASE)
        if category and category_id is None:
            category_id = int(category[1])
        elif re.fullmatch(r"status\s*=\s*'active'", condition, flags=re.IGNORECASE) and not active:
            active = True
        elif re.fullmatch(r'stock_quantity\s*>\s*0', condition, flags=re.IGNORECASE) and not only_in_stock:
            only_in_stock = True
        else:
            return None
    if category_id is None or not active:
        return None
    return list_products(category_id, only_in_stock=only_in_stock, db_path=db_path)


def list_products(
    category_id: int,
    only_in_stock: bool = False,
    limit: int | None = None,
    db_path: str = "db/emporio.db",
) -> str:
    if limit is not None and limit < 1:
        raise ValueError("A quantidade solicitada deve ser maior que zero.")

    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        total, available = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(stock_quantity > 0), 0) "
            "FROM produtos WHERE category_id = ? AND status = 'active'",
            (category_id,),
        ).fetchone()
        query = (
            "SELECT product_id, name, price_brl, stock_quantity FROM produtos "
            "WHERE category_id = ? AND status = 'active'"
        )
        parameters = [category_id]
        if only_in_stock:
            query += " AND stock_quantity > 0"
        query += " ORDER BY price_brl, product_id"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        rows = connection.execute(query, parameters).fetchall()

    lines = [
        f"Nesta categoria há **{total} modelos ativos no catálogo**, "
        f"dos quais **{available} estão disponíveis em estoque**.",
        "",
    ]
    if not rows:
        lines.append("Não há produtos que atendam aos filtros solicitados.")
        return "\n".join(lines)
    matching = available if only_in_stock else total
    lines.extend([
        f"Exibindo **{len(rows)} de {matching} modelos** que atendem aos filtros solicitados, em ordem de preço.",
        "",
        "| Código | Modelo | Preço | Unidades em estoque | Disponibilidade |",
        "| --- | --- | --- | --- | --- |",
    ])
    for product_id, name, price, stock in rows:
        name = name.replace("|", "\\|").replace("\n", " ")
        price = f"{price:,.2f}".translate(str.maketrans({",": ".", ".": ","}))
        availability = "Disponível" if stock > 0 else "Temporariamente indisponível"
        lines.append(f"| {product_id} | {name} | R$ {price} | {stock} | {availability} |")
    return "\n".join(lines)
