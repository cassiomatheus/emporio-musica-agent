"""Conferência simplificada de pedido/cliente para a demonstração local."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
import re
import sqlite3
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'db/emporio.db'
ORDER = re.compile(r'\bpedido\s*(?:(?:numero|n[º°.]?)\s*)?#?\s*([0-9]{1,18})\b')
CUSTOMER = re.compile(
    r'\b(?:id\s+(?:do\s+)?(?:cliente|usuario)|(?:meu\s+)?id|cliente|usuario)'
    r'\s*(?:e\s+|:|=|#)?\s*([0-9]{1,18})\b'
)
PENDING = re.compile(r'^Para consultar o status do pedido #([0-9]+), informe seu ID de cliente\.$')
LEGACY_REQUEST_CUSTOMER_ID = 'Para consultar o status do seu pedido, informe seu ID de cliente.'
REQUEST_CUSTOMER_ID = 'Para consultar as informações do seu pedido, informe seu ID de cliente.'
NO_MATCH = 'Não foi possível consultar o pedido com os dados informados. Confira o número do pedido e seu ID de cliente.'


def _normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))


def lookup_order_status(order_id: int, customer_id: int, db_path: Path | None = None) -> str:
    """Retorna detalhes comerciais se os dois IDs coincidirem; nunca informa o titular."""
    if type(order_id) is not int or type(customer_id) is not int or not 0 < order_id < 10**18 or not 0 < customer_id < 10**18:
        return NO_MATCH
    path = Path(db_path or DB_PATH).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        row = connection.execute(
            'SELECT status, order_date, total_brl, payment_method, tracking_code, estimated_delivery '
            'FROM pedidos WHERE order_id = ? AND customer_id = ?',
            (order_id, customer_id),
        ).fetchone()
    if row is None:
        return NO_MATCH
    labels = {'confirmed': 'Confirmado', 'pending': 'Pendente', 'paid': 'Pago',
              'shipped': 'Enviado', 'delivered': 'Entregue', 'cancelled': 'Cancelado',
              'canceled': 'Cancelado', 'processing': 'Em processamento'}
    status = labels.get(row[0], row[0]) if row[0] else 'Não informado'
    def display_date(value):
        if not value:
            return 'Não informada'
        try:
            return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
        except ValueError:
            return str(value)

    total = 'Não informado'
    if row[2] is not None:
        amount = format(Decimal(str(row[2])), ',.2f').translate(str.maketrans({',': '.', '.': ','}))
        total = f'R$ {amount}'
    payment_labels = {'pix': 'PIX', 'credit_card': 'Cartão de crédito',
                      'debit_card': 'Cartão de débito', 'boleto': 'Boleto', 'cash': 'Dinheiro'}
    payment = payment_labels.get(row[3], row[3]) if row[3] else 'Não informada'
    return '\n'.join([
        'Conferência concluída! O pedido está vinculado ao ID de cliente informado.', '',
        'Aqui estão as informações do seu pedido:', '',
        f'- **Data do pedido:** {display_date(row[1])}',
        f'- **Status:** {status}',
        f'- **Valor total:** {total}',
        f'- **Forma de pagamento:** {payment}',
        f'- **Código de rastreamento:** {row[4] or "Não informado"}',
        f'- **Entrega estimada:** {display_date(row[5])}',
    ])


def handle_order_request(user_input: str, history: list) -> str | None:
    """Fluxo restrito: pedido → ID explícito → consulta parametrizada, sem LLM."""
    text = _normalized(user_input)
    order = ORDER.search(text)
    pending_order_id = None
    if history and history[-1].type == 'ai':
        last_answer = history[-1].content.split('\n\n')[-1]
        legacy_pending = PENDING.fullmatch(last_answer)
        if legacy_pending:
            pending_order_id = int(legacy_pending.group(1))
        elif last_answer in (REQUEST_CUSTOMER_ID, LEGACY_REQUEST_CUSTOMER_ID):
            # O número fica no contexto do cliente, sem reaparecer na resposta.
            for message in reversed(history[:-1]):
                if message.type == 'human':
                    previous_order = ORDER.search(_normalized(message.content))
                    if previous_order:
                        pending_order_id = int(previous_order.group(1))
                        break
    customer = CUSTOMER.search(text)
    # Um ID isolado só é interpretado como cliente após a solicitação do sistema.
    bare_id = re.fullmatch(r'\s*([0-9]{1,18})\s*[.!]?\s*', text) if pending_order_id is not None else None
    if order is None and not (pending_order_id is not None and (customer or bare_id)):
        if 'pedido' in text and re.search(r'\b(status|situacao|acompanhar|rastrear)\b', text):
            return 'Informe o número do pedido e seu ID de cliente para consultar o status.'
        return None
    # Mensagens compostas não dão acesso a dados pessoais nem a outras ações.
    if re.search(r'\b(nome|telefone|endereco|email|e-mail|cpf|titular)\b', text):
        return 'Não posso divulgar dados pessoais associados a pedidos. Posso consultar os detalhes comerciais com o número do pedido e seu ID de cliente.'
    order_id = int(order.group(1)) if order else pending_order_id
    if customer is None and bare_id is None:
        return REQUEST_CUSTOMER_ID
    customer_id = int((customer or bare_id).group(1))
    result = lookup_order_status(order_id, customer_id)
    if result == NO_MATCH:
        # Mantém a possibilidade de corrigir o ID sem revelar se o pedido existe.
        return result + '\n\n' + REQUEST_CUSTOMER_ID
    return result
