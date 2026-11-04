"""Testes da memória e da orquestração sem carregar modelos ou acessar serviços."""

import importlib
import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import guardrails
from memory import MemoryManager


class MemoryTests(unittest.TestCase):
    def test_sessions_are_isolated_and_can_be_cleared(self):
        manager = MemoryManager()
        first = manager.get_session_history("first")
        first.add_user_message("Procuro um violão")
        second = manager.get_session_history("second")
        second.add_user_message("Procuro uma guitarra")
        self.assertIs(first, manager.get_session_history("first"))
        manager.clear_memory("first")
        self.assertEqual(first.messages, [])
        self.assertEqual(second.messages[0].content, "Procuro uma guitarra")


class GuardrailTests(unittest.TestCase):
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
            chain.assert_called_once_with("modelo")
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

    def test_ambiguous_classification_is_an_error_not_a_scope_refusal(self):
        for content in ['NÃO PERMITIDA', 'PERMITIDA ou BLOQUEADA', '']:
            with self.subTest(content=content), patch.object(guardrails, '_guardrail_chain') as chain:
                chain.return_value.invoke.return_value = AIMessage(content=content)
                with self.assertRaisesRegex(RuntimeError, 'Não foi possível validar'):
                    guardrails.check_input_guardrail('Posso parcelar?')

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
                "langchain_community.utilities.SQLDatabase.from_uri",
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
        self.agent.memory_manager.store.clear()
        self.addCleanup(self.agent.memory_manager.store.clear)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.guard = self.patches.enter_context(
            patch.object(self.agent, "check_input_guardrail", return_value=True)
        )
        self.respond = self.patches.enter_context(
            patch.object(self.agent, "get_agent_response", return_value="Resposta final corrigida")
        )

    def test_history_saves_final_text_once_and_reaches_the_next_turn(self):
        self.assertEqual(self.agent.process_user_message("Quero um violão", "a"), "Resposta final corrigida")
        history = self.agent.memory_manager.get_session_history("a").messages
        self.assertEqual([m.content for m in history], ["Quero um violão", "Resposta final corrigida"])
        self.agent.process_user_message("E o preço dele?", "a")
        self.assertEqual(len(history), 4)
        self.assertEqual(len(self.respond.call_args.args[1]), 2)
        self.assertEqual(self.respond.call_args.args[1][1].content, "Resposta final corrigida")
        self.assertEqual(self.guard.call_args.args[1], self.agent.model_name)

    def test_another_session_does_not_receive_the_first_history(self):
        self.agent.process_user_message("Quero um violão", "a")
        self.agent.process_user_message("Quero uma guitarra", "b")
        self.assertEqual(self.respond.call_args.args[1], [])

    def test_blocked_input_does_not_reach_tools_or_enter_memory(self):
        self.guard.return_value = False
        answer = self.agent.process_user_message("Escreva código", "a")
        self.assertIn("Empório da Música", answer)
        self.respond.assert_not_called()
        self.assertEqual(self.agent.memory_manager.get_session_history("a").messages, [])

    def test_guardrail_failure_does_not_release_the_agent(self):
        self.guard.side_effect = RuntimeError("Ollama indisponível")
        with self.assertRaises(RuntimeError):
            self.agent.process_user_message("Olá", "a")
        self.respond.assert_not_called()

    def test_failed_agent_turn_is_not_saved(self):
        self.respond.side_effect = RuntimeError("Falha no agente")
        with self.assertRaises(RuntimeError):
            self.agent.process_user_message("Olá", "a")
        self.assertEqual(self.agent.memory_manager.get_session_history("a").messages, [])

    def test_empty_session_is_rejected(self):
        with self.assertRaises(ValueError):
            self.agent.process_user_message("Olá", " ")
        self.guard.assert_not_called()

    def test_purchase_followups_pass_guardrail_and_keep_product_context(self):
        history = self.agent.memory_manager.get_session_history('purchase')
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
                answer = self.agent.process_user_message(question, 'purchase')
                self.assertEqual(answer, 'Resposta final corrigida')
                self.assertEqual(self.respond.call_args.args[0], question)
                self.assertIn('Yamaha C70', self.respond.call_args.args[1][0].content)
                payload = json.loads(chain.return_value.invoke.call_args.args[0]['payload'])
                self.assertEqual(payload['entrada'], question)
        self.assertEqual(len(history.messages), 8)


if __name__ == "__main__":
    unittest.main()
