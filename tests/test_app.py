from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from contextlib import ExitStack
from uuid import uuid1

from langchain_core.messages import HumanMessage, AIMessage
from streamlit.testing.v1 import AppTest
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import memory


class AppPersistenceTests(unittest.TestCase):
    def test_download_includes_latest_messages_and_omits_private_code(self):
        fake = types.ModuleType('agent')
        fake.process_user_message = lambda question, session_id: f'Preço: R$ 100,00. Código: {session_id}'
        with patch.dict(sys.modules, {'agent': fake}), \
                patch.object(st, 'download_button', wraps=st.download_button) as download:
            app_path = str(Path(__file__).resolve().parents[1] / 'src/app.py')
            app = AppTest.from_file(app_path).run(timeout=15)
            app.chat_input[0].set_value('Qual é o preço?').run(timeout=15)
            self.assertFalse(app.exception)
            payload = download.call_args.kwargs
            self.assertIn('Qual é o preço?', payload['data'])
            self.assertIn(r'Preço: R\$ 100,00.', payload['data'])
            self.assertIn('[CÓDIGO PRIVADO OMITIDO]', payload['data'])
            self.assertNotIn(app.session_state['session_id'], payload['data'])
            self.assertNotIn(app.session_state['session_id'], payload['file_name'])
            self.assertTrue(payload['file_name'].endswith('.md'))
            self.assertEqual(payload['on_click'], 'ignore')

    def test_internal_error_details_are_not_exposed_in_chat(self):
        fake = types.ModuleType('agent')

        def fail(*args, **kwargs):
            raise RuntimeError('DETALHE_INTERNO_PRIVADO')

        fake.process_user_message = fail
        with patch.dict(sys.modules, {'agent': fake}):
            app_path = str(Path(__file__).resolve().parents[1] / 'src/app.py')
            app = AppTest.from_file(app_path).run(timeout=15)
            app.chat_input[0].set_value('Qual é o frete?').run(timeout=15)
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertNotIn('DETALHE_INTERNO_PRIVADO', app.error[0].value)
            self.assertNotIn('DETALHE_INTERNO_PRIVADO', app.session_state['messages'][-1]['content'])

    def test_weak_session_codes_are_rejected_before_history_lookup(self):
        fake = types.ModuleType('agent')
        fake.process_user_message = lambda question, session_id: 'Resposta'
        with patch.dict(sys.modules, {'agent': fake}), patch.object(memory.memory_manager, 'get_session_history') as lookup:
            app_path = str(Path(__file__).resolve().parents[1] / 'src/app.py')
            app = AppTest.from_file(app_path).run(timeout=15)
            original_id = app.session_state['session_id']
            for invalid in ('user_123', '1', uuid1().hex):
                app.text_input(key='restore_id').set_value(invalid).run(timeout=15)
                app.button(key='restore_conversation').click().run(timeout=15)
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state['session_id'], original_id)
            lookup.assert_not_called()

    def test_new_conversation_preserves_history_and_allows_resuming_again(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            manager = memory.MemoryManager(f"sqlite:///{Path(directory) / 'history.db'}")
            patches.callback(manager.close)
            patches.enter_context(patch.object(memory, 'memory_manager', manager))
            fake = types.ModuleType('agent')

            def respond(question, session_id):
                manager.get_session_history(session_id).add_messages([
                    HumanMessage(content=question), AIMessage(content='Frete: **R$ 35,00**')
                ])
                return 'Frete: **R$ 35,00**'

            fake.process_user_message = respond
            patches.enter_context(patch.dict(sys.modules, {'agent': fake}))
            app_path = str(Path(__file__).resolve().parents[1] / 'src/app.py')
            first = AppTest.from_file(app_path).run(timeout=15)
            saved_id = first.session_state['session_id']
            first.chat_input[0].set_value('Qual é o frete?').run(timeout=15)
            self.assertFalse(first.exception)
            second = AppTest.from_file(app_path).run(timeout=15)
            other_id = second.session_state['session_id']
            self.assertNotEqual(saved_id, other_id)
            manager.get_session_history(other_id).add_user_message('Outra conversa')
            second.text_input(key='restore_id').set_value(saved_id).run(timeout=15)
            second.button(key='restore_conversation').click().run(timeout=15)
            self.assertFalse(second.exception)
            self.assertEqual(second.session_state['session_id'], saved_id)
            self.assertTrue(any(m.value == r'Frete: **R\$ 35,00**' for m in second.markdown))
            self.assertEqual(len(manager.get_session_history(saved_id).messages), 2)
            second.button(key='new_conversation').click().run(timeout=15)
            self.assertFalse(second.exception)
            self.assertNotEqual(second.session_state['session_id'], saved_id)
            self.assertEqual(len(manager.get_session_history(saved_id).messages), 2)
            self.assertEqual(len(manager.get_session_history(other_id).messages), 1)
            self.assertEqual(len(second.session_state['messages']), 1)
            second.text_input(key='restore_id').set_value(saved_id).run(timeout=15)
            second.button(key='restore_conversation').click().run(timeout=15)
            self.assertFalse(second.exception)
            self.assertEqual(second.session_state['session_id'], saved_id)
            self.assertTrue(any(m.value == r'Frete: **R\$ 35,00**' for m in second.markdown))


if __name__ == '__main__':
    unittest.main()
