"""Testes da memória e da orquestração sem carregar modelos ou acessar serviços."""

import importlib
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4, uuid1

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import guardrails
from memory import MemoryManager, normalize_session_id


class MemoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = f"sqlite:///{Path(directory.name) / 'history.db'}"
        self.first_id, self.second_id = uuid4().hex, uuid4().hex

    def test_sessions_are_isolated_and_can_be_cleared(self):
        manager = MemoryManager(self.database)
        self.addCleanup(manager.close)
        first = manager.get_session_history(self.first_id)
        first.add_user_message("Procuro um violão")
        second = manager.get_session_history(self.second_id)
        second.add_user_message("Procuro uma guitarra")
        self.assertEqual(first.messages, manager.get_session_history(self.first_id).messages)
        manager.clear_memory(self.first_id)
        self.assertEqual(first.messages, [])
        self.assertEqual(second.messages[0].content, "Procuro uma guitarra")

    def test_history_survives_a_new_manager(self):
        manager = MemoryManager(self.database)
        manager.get_session_history(self.first_id).add_messages([
            HumanMessage(content='Procuro um violão'), AIMessage(content='Qual modelo?')
        ])
        manager.close()
        restored = MemoryManager(self.database)
        self.addCleanup(restored.close)
        self.assertEqual([m.content for m in restored.get_session_history(self.first_id).messages],
                         ['Procuro um violão', 'Qual modelo?'])

    def test_session_codes_require_uuid4_and_normalize_hex(self):
        code = uuid4().hex
        self.assertEqual(normalize_session_id(code.upper()), code)
        for invalid in ('user_123', '1', '0' * 32, uuid1().hex, '', ' '):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_session_id(invalid)


class GuardrailTests(unittest.TestCase):
    def setUp(self):
        self.metrics_patch = patch.object(guardrails, '_metrics_logger')
        self.metrics = self.metrics_patch.start()
        self.addCleanup(self.metrics_patch.stop)

    def test_only_explicit_permission_is_accepted(self):
        for content, allowed in [
            ("PERMITIDA", True), (" permitida\n", True),
            ("BLOQUEADA", False),
        ]:
            with self.subTest(content=content), patch.object(guardrails, "_guardrail_chain") as chain:
                chain.return_value.invoke.return_value = AIMessage(content=content)
                self.assertEqual(guardrails.check_input_guardrail("pergunta"), allowed)

    def test_recent_context_is_sent_with_the_same_model(self):
        history = [HumanMessage(content=str(i)) for i in range(6)]
        with patch.object(guardrails, "_guardrail_chain") as chain:
            chain.return_value.invoke.return_value = AIMessage(content="PERMITIDA")
            self.assertTrue(guardrails.check_input_guardrail("E esse?", "modelo", history))
            chain.assert_called_with("modelo")
            payload = json.loads(chain.return_value.invoke.call_args.args[0]["payload"])
            self.assertEqual([m['texto'] for m in payload['historico']], [m.content for m in history[-4:]])
            self.assertEqual(payload['entrada'], 'E esse?')

    def test_invalid_classification_is_retried(self):
        with patch.object(guardrails, '_guardrail_chain') as chain:
            chain.return_value.invoke.side_effect = [
                AIMessage(content='Não consigo classificar.'), AIMessage(content='PERMITIDA')
            ]
            self.assertTrue(guardrails.check_input_guardrail('Qual é o frete?'))
            self.assertEqual(chain.return_value.invoke.call_count, 2)

    def test_ambiguous_classification_fails_closed_after_two_attempts(self):
        for content in ['NÃO PERMITIDA', 'PERMITIDA ou BLOQUEADA', '']:
            with self.subTest(content=content), patch.object(guardrails, '_guardrail_chain') as chain:
                chain.return_value.invoke.return_value = AIMessage(content=content)
                self.assertFalse(guardrails.check_input_guardrail('Posso parcelar?'))
                self.assertEqual(chain.return_value.invoke.call_count, 2)
                event = json.loads(self.metrics.return_value.log.call_args.args[1])
                self.assertEqual(event['event'], 'PARSE_ERROR')
                self.assertFalse(event['fallback'])

    def test_connection_error_fails_closed_and_is_logged(self):
        with patch.object(guardrails, '_guardrail_chain', side_effect=ConnectionError('local')):
            self.assertFalse(guardrails.check_input_guardrail('Olá'))
        event = json.loads(self.metrics.return_value.log.call_args.args[1])
        self.assertEqual(event['event'], 'EXCEPTION')
        self.assertFalse(event['fallback'])
        self.assertEqual(event['error_type'], 'ConnectionError')

    def test_explicit_block_is_logged_without_fallback_or_input_text(self):
        with patch.object(guardrails, '_guardrail_chain') as chain:
            chain.return_value.invoke.return_value = AIMessage(content='BLOQUEADA')
            self.assertFalse(guardrails.check_input_guardrail('conteúdo privado'))
        event = json.loads(self.metrics.return_value.log.call_args.args[1])
        self.assertEqual(event['event'], 'BLOCKED')
        self.assertFalse(event['fallback'])
        self.assertNotIn('conteúdo privado', str(self.metrics.return_value.log.call_args))
        self.assertIn('latency_ms', event)

    def test_long_catalog_is_bounded_and_not_inserted_as_chat_instructions(self):
        history = [AIMessage(content='Catálogo: ' + 'produto ' * 3000)]
        with patch.object(guardrails, '_guardrail_chain') as chain:
            chain.return_value.invoke.return_value = AIMessage(content='PERMITIDA')
            guardrails.check_input_guardrail('Qual é o frete?', chat_history=history)
            payload = json.loads(chain.return_value.invoke.call_args.args[0]['payload'])
            self.assertEqual(len(payload['historico'][0]['texto']), 1200)
            self.assertEqual(payload['entrada'], 'Qual é o frete?')


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A orquestração e o RunnableWithMessageHistory são reais. Só a criação
        # de recursos externos é substituída para não ler o banco nem os modelos.
        with ExitStack() as stack:
            for target in [
                "sql_access.create_public_database",
                "langchain_chroma.Chroma",
                "langchain_huggingface.HuggingFaceEmbeddings",
                "langchain_core.tools.create_retriever_tool",
                "langchain_classic.agents.create_tool_calling_agent",
                "langchain_classic.agents.AgentExecutor",
            ]:
                stack.enter_context(patch(target))
            toolkit = stack.enter_context(patch("langchain_community.agent_toolkits.SQLDatabaseToolkit"))
            toolkit.return_value.get_tools.return_value = []
            cls.agent = importlib.import_module("agent")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        manager = MemoryManager(f"sqlite:///{Path(directory.name) / 'history.db'}")
        self.addCleanup(manager.close)
        self.ids = {name: uuid4().hex for name in ("a", "b", "purchase")}
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(self.agent, 'memory_manager', manager))
        self.patches.enter_context(patch.object(self.agent.agent_with_history, 'get_session_history', manager.get_session_history))
        self.patches.enter_context(patch.object(guardrails, '_metrics_logger'))
        self.guard = self.patches.enter_context(
            patch.object(self.agent, "check_input_guardrail", return_value=True)
        )
        self.respond = self.patches.enter_context(
            patch.object(self.agent, "get_agent_response", return_value="Resposta final corrigida")
        )

    def test_history_saves_final_text_once_and_reaches_the_next_turn(self):
        self.assertEqual(self.agent.process_user_message("Quero um violão", self.ids["a"]), "Resposta final corrigida")
        history = self.agent.memory_manager.get_session_history(self.ids["a"]).messages
        self.assertEqual([m.content for m in history], ["Quero um violão", "Resposta final corrigida"])
        self.agent.process_user_message("E o preço dele?", self.ids["a"])
        self.assertEqual(len(self.agent.memory_manager.get_session_history(self.ids["a"]).messages), 4)
        self.assertEqual(len(self.respond.call_args.args[1]), 2)
        self.assertEqual(self.respond.call_args.args[1][1].content, "Resposta final corrigida")
        self.assertEqual(self.guard.call_args.args[1], self.agent.model_name)

    def test_another_session_does_not_receive_the_first_history(self):
        self.agent.process_user_message("Quero um violão", self.ids["a"])
        self.agent.process_user_message("Quero uma guitarra", self.ids["b"])
        self.assertEqual(self.respond.call_args.args[1], [])

    def test_blocked_input_does_not_reach_tools_or_enter_memory(self):
        self.guard.return_value = False
        answer = self.agent.process_user_message("Escreva código", self.ids["a"])
        self.assertIn("Empório da Música", answer)
        self.respond.assert_not_called()
        self.assertEqual(self.agent.memory_manager.get_session_history(self.ids["a"]).messages, [])

    def test_guardrail_failure_does_not_release_the_agent(self):
        self.guard.side_effect = RuntimeError("Ollama indisponível")
        with self.assertRaises(RuntimeError):
            self.agent.process_user_message("Olá", self.ids["a"])
        self.respond.assert_not_called()

    def test_real_guardrail_connection_failure_returns_friendly_refusal_without_agent(self):
        with patch.object(self.agent, 'check_input_guardrail', guardrails.check_input_guardrail), \
                patch.object(guardrails, '_guardrail_chain', side_effect=ConnectionError('indisponível')):
            answer = self.agent.process_user_message('Qual é o frete?', self.ids['a'])
        self.assertEqual(answer, self.agent.VALIDATION_REFUSAL)
        self.respond.assert_not_called()
        self.assertEqual(self.agent.memory_manager.get_session_history(self.ids['a']).messages, [])

    def test_failed_agent_turn_is_not_saved(self):
        self.respond.side_effect = RuntimeError("Falha no agente")
        with self.assertRaises(RuntimeError):
            self.agent.process_user_message("Olá", self.ids["a"])
        self.assertEqual(self.agent.memory_manager.get_session_history(self.ids["a"]).messages, [])

    def test_empty_session_is_rejected(self):
        with self.assertRaises(ValueError):
            self.agent.process_user_message("Olá", " ")
        self.guard.assert_not_called()

    def test_purchase_followups_pass_guardrail_and_keep_product_context(self):
        history = self.agent.memory_manager.get_session_history(self.ids["purchase"])
        history.add_user_message('Quero comprar o Yamaha C70.')
        history.add_ai_message('O Yamaha C70 está disponível por R$ 849,00.')
        questions = [
            'Posso parcelar ele até quantas vezes?',
            'Posso parcelar ele de quantas vezes?',
            'Qual é o valor do frete?',
        ]
        with patch.object(self.agent, 'check_input_guardrail', guardrails.check_input_guardrail), \
                patch.object(guardrails, '_guardrail_chain') as chain:
            chain.return_value.invoke.return_value = AIMessage(content='PERMITIDA')
            for question in questions:
                answer = self.agent.process_user_message(question, self.ids["purchase"])
                self.assertEqual(answer, 'Resposta final corrigida')
                self.assertEqual(self.respond.call_args.args[0], question)
                self.assertIn('Yamaha C70', self.respond.call_args.args[1][0].content)
                payload = json.loads(chain.return_value.invoke.call_args.args[0]['payload'])
                self.assertEqual(payload['entrada'], question)
        self.assertEqual(len(history.messages), 8)


if __name__ == "__main__":
    unittest.main()
