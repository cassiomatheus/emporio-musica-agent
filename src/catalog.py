"""Listagens de catálogo com totais e preços obtidos diretamente do SQLite."""

import sqlite3
import re
import csv
import unicodedata
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATEGORY_SOURCE = ROOT / "data/desafio_tecnico_ai_eng - categories.csv"


def load_categories(path: Path = CATEGORY_SOURCE) -> dict[int, str]:
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    categories = {int(row["category_id"]): row["name"].strip() for row in rows}
    if len(categories) != len(rows) or not all(categories.values()):
        raise ValueError("Categorias devem ter IDs únicos e nomes preenchidos.")
    return categories


def _fold(text: str) -> str:
    text = ''.join(character for character in unicodedata.normalize('NFKD', text.lower())
                   if not unicodedata.combining(character))
    return ' '.join(re.sub(r'[^a-z0-9\s]', ' ', text).split())


def _singular(word: str) -> str:
    if word.endswith('oes'):
        return word[:-3] + 'ao'
    if word in {'metais', 'orquestrais'}:
        return {'metais': 'metal', 'orquestrais': 'orquestral'}[word]
    return word[:-1] if word.endswith('s') and len(word) > 3 else word


def render_availability_question(question: str, db_path: str = "db/emporio.db",
                                 categories: dict[int, str] | None = None) -> str | None:
    """Responde consultas curtas de categoria; filtros adicionais ficam no agente."""
    normalized = _fold(question)
    match = re.fullmatch(
        r'(?:tem(?: um| uma| uns| umas)?|voces tem|ha|quais(?: sao)?(?: os| as)?|'
        r'(?:estou procurando|procuro|busco)(?: um| uma| uns| umas)?|'
        r'(?:liste|mostre)(?: todos os| todas as| os| as)?)\s+(.+?)'
        r'(?:\s+(?:disponivel|disponiveis|em estoque|no estoque|na loja|no catalogo))?',
        normalized,
    )
    target = match[1] if match else normalized
    target = ' '.join(_singular(word) for word in target.split())
    matches = []
    for category_id, name in (load_categories() if categories is None else categories).items():
        words = [_singular(word) for word in _fold(name).split()]
        aliases = {' '.join(words)} | (set(words) - {'e', 'de', 'instrumento', 'corda'})
        if target in aliases:
            matches.append(category_id)
    if len(matches) != 1:
        return None
    return list_products(matches[0], only_in_stock=True, db_path=db_path)


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
        has_promotions = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='promocoes'"
        ).fetchone()
        promotion_join = (
            " LEFT JOIN (SELECT product_id, MAX(discount_percent) AS discount_percent "
            "FROM promocoes WHERE is_active = 1 AND discount_percent BETWEEN 0 AND 100 "
            "GROUP BY product_id) AS promotion ON promotion.product_id = p.product_id "
            if has_promotions else ""
        )
        discount = "COALESCE(promotion.discount_percent, 0)" if has_promotions else "0"
        query = (
            f"SELECT p.product_id, p.name, p.price_brl, p.stock_quantity, {discount}, "
            f"ROUND(p.price_brl * (1 - ({discount}) / 100.0), 2) AS final_price "
            f"FROM produtos AS p {promotion_join} WHERE p.category_id = ? AND p.status = 'active'"
        )
        parameters = [category_id]
        if only_in_stock:
            query += " AND p.stock_quantity > 0"
        query += " ORDER BY final_price, p.product_id"
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
    show_promotions = any(row[4] > 0 for row in rows)
    lines.extend([
        f"Exibindo **{len(rows)} de {matching} modelos** que atendem aos filtros solicitados, em ordem de preço.",
        "",
        ("| Código | Modelo | Preço original | Desconto | Preço final | Unidades em estoque | Disponibilidade |"
         if show_promotions else "| Código | Modelo | Preço | Unidades em estoque | Disponibilidade |"),
        "| --- | --- | --- | --- | --- | --- | --- |" if show_promotions else "| --- | --- | --- | --- | --- |",
    ])
    for product_id, name, price, stock, discount, final_price in rows:
        name = name.replace("|", "\\|").replace("\n", " ")
        price = f"{price:,.2f}".translate(str.maketrans({",": ".", ".": ","}))
        availability = "Disponível" if stock > 0 else "Temporariamente indisponível"
        if show_promotions:
            final_price = f"{final_price:,.2f}".translate(str.maketrans({",": ".", ".": ","}))
            lines.append(f"| {product_id} | {name} | R$ {price} | {discount:g}% | R$ {final_price} | {stock} | {availability} |")
        else:
            lines.append(f"| {product_id} | {name} | R$ {price} | {stock} | {availability} |")
    return "\n".join(lines)
