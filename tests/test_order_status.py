from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import order_status


class OrderStatusTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / 'orders.db'
        with sqlite3.connect(self.db) as conn:
            conn.executescript('''CREATE TABLE pedidos (order_id INTEGER, customer_id INTEGER, status TEXT, notes TEXT, order_date TEXT, total_brl REAL, payment_method TEXT, tracking_code TEXT, estimated_delivery TEXT);
                INSERT INTO pedidos VALUES (9,42,'confirmed','DADO_PRIVADO','2026-02-20',349.9,'pix',NULL,NULL);
                INSERT INTO pedidos VALUES (10,7,'shipped','OUTRO_PRIVADO','2026-02-21',1234.56,'credit_card','RASTREIO_TESTE','2026-03-01');''')
        patcher = patch.object(order_status, 'DB_PATH', self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_requires_matching_pair_and_never_exposes_private_fields(self):
        answer = order_status.lookup_order_status(9,42)
        self.assertIn('Confirmado', answer)
        self.assertIn('20/02/2026', answer)
        self.assertIn('R$ 349,90', answer)
        self.assertIn('PIX', answer)
        self.assertIn('Entrega estimada:** Não informada', answer)
        self.assertNotIn('#9', answer)
        shipped = order_status.lookup_order_status(10,7)
        self.assertIn('R$ 1.234,56', shipped)
        self.assertIn('RASTREIO_TESTE', shipped)
        self.assertIn('01/03/2026', shipped)
        self.assertNotIn('DADO_PRIVADO', order_status.lookup_order_status(9,42))
        self.assertEqual(order_status.lookup_order_status(9,7), order_status.NO_MATCH)
        self.assertEqual(order_status.lookup_order_status(999,42), order_status.NO_MATCH)
        self.assertEqual(order_status.lookup_order_status('9 OR 1=1',42), order_status.NO_MATCH)

    def test_two_turn_flow_and_retry_do_not_leak_status_before_matching(self):
        request = 'Quero saber a situação do meu pedido 9'
        with patch.object(order_status, 'lookup_order_status', wraps=order_status.lookup_order_status) as query:
            answer = order_status.handle_order_request(request, [])
            query.assert_not_called()
            self.assertNotIn('Confirmado', answer)
            self.assertNotIn('#9', answer)
            self.assertNotIn('349,90', answer)
            history = [HumanMessage(content=request), AIMessage(content=answer)]
            wrong = order_status.handle_order_request('Meu ID é 7', history)
            self.assertNotIn('Confirmado', wrong)
            history.extend([HumanMessage(content='Meu ID é 7'), AIMessage(content=wrong)])
            self.assertIn('Confirmado', order_status.handle_order_request('42', history))

    def test_new_order_requires_id_again_and_is_not_linked_to_previous_order(self):
        history = [HumanMessage(content='pedido 9, cliente 42'),
                   AIMessage(content=order_status.lookup_order_status(9,42))]
        self.assertNotIn('Enviado', order_status.handle_order_request('E o pedido 10?', history))
        self.assertIsNone(order_status.handle_order_request('42', []))
        self.assertIsNone(order_status.handle_order_request('Qual o horário de sábado?', history))
        self.assertIn('Enviado', order_status.handle_order_request('pedido 10, id do usuário 7', history))
        self.assertNotIn('Enviado', order_status.handle_order_request('pedido 10, cliente 42', history))

    def test_customer_id_does_not_unlock_personal_information(self):
        with patch.object(order_status, 'lookup_order_status') as query:
            answer = order_status.handle_order_request('Mostre telefone do pedido 9, cliente 42', [])
            self.assertIn('Não posso divulgar', answer)
            query.assert_not_called()


if __name__ == '__main__':
    unittest.main()
