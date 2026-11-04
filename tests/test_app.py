from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from contextlib import ExitStack

from langchain_core.messages import HumanMessage, AIMessage
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import memory


class AppPersistenceTests(unittest.TestCase):
    def test_resume_uses_saved_history_and_new_conversation_clears_only_that_session(self):
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
            self.assertEqual(manager.get_session_history(saved_id).messages, [])
            self.assertEqual(len(manager.get_session_history(other_id).messages), 1)


if __name__ == '__main__':
    unittest.main()
