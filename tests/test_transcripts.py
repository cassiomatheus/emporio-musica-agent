import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from conversation_logs import TranscriptStore, ConversationTrace, USER_ERROR_MESSAGE


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = TranscriptStore(Path(directory.name) / 'conversas')
        self.session = uuid4().hex

    def test_full_turns_and_refusals_are_appended_and_session_code_is_omitted(self):
        trace = ConversationTrace()
        trace.guardrail = 'permitiu'
        run = uuid4()
        trace.on_tool_start({'name': 'sql_db_query'}, 'SELECT name FROM produtos', run_id=run)
        trace.on_tool_end('Crafter D-8', run_id=run)
        ticket = self.store.begin(self.session, 'Meu código é ' + self.session, 'modelo')
        self.store.finish(self.session, ticket, 'O produto está disponível.', 'respondida', trace)
        folder = self.store.directory(self.session)
        before = (folder / 'eventos.jsonl').read_bytes()
        ticket = self.store.begin(self.session, 'Escreva Python.', 'modelo')
        self.store.finish(self.session, ticket, 'Solicitação bloqueada.', 'bloqueada', ConversationTrace())
        self.assertTrue((folder / 'eventos.jsonl').read_bytes().startswith(before))
        for path in folder.iterdir():
            self.assertNotIn(self.session, str(path))
            self.assertNotIn(self.session, path.read_text())
        text = (folder / 'transcricao.md').read_text()
        self.assertIn('CODIGO_DE_RETOMADA_OMITIDO', text)
        self.assertIn('Solicitação bloqueada.', text)
        self.assertIn('SELECT name FROM produtos', text)
        self.assertIn('Crafter D-8', text)
        self.assertEqual(os.stat(folder).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(folder / 'eventos.jsonl').st_mode & 0o777, 0o600)

    def test_error_and_interrupted_turn_remain_visible(self):
        ticket = self.store.begin(self.session, 'Pergunta que falhou', 'modelo')
        self.store.finish(self.session, ticket, USER_ERROR_MESSAGE, 'erro', ConversationTrace(), 'TimeoutError')
        self.store.begin(self.session, 'Pergunta interrompida', 'modelo')
        folder = self.store.directory(self.session)
        text = (folder / 'transcricao.md').read_text()
        self.assertIn('**erro**', text)
        self.assertIn('sem conclusão registrada', text)
        events = [json.loads(line) for line in (folder / 'eventos.jsonl').read_text().splitlines()]
        self.assertEqual(events[1]['error_type'], 'TimeoutError')

    def test_previous_evaluation_file_is_not_overwritten(self):
        self.store.artifact(self.session, 'avaliacao.md', 'PENDENTE')
        with self.assertRaises(FileExistsError):
            self.store.artifact(self.session, 'avaliacao.md', 'PASS')
        self.assertEqual((self.store.directory(self.session) / 'avaliacao.md').read_text(), 'PENDENTE')

    def test_concurrent_turns_keep_valid_journal_and_distinct_numbers(self):
        def record(number):
            ticket = self.store.begin(self.session, str(number), 'modelo')
            self.store.finish(self.session, ticket, 'Resposta ' + str(number), 'respondida', ConversationTrace())
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(record, range(8)))
        events = [json.loads(line) for line in (self.store.directory(self.session) / 'eventos.jsonl').read_text().splitlines()]
        self.assertEqual(len(events), 16)
        self.assertEqual({item['turn'] for item in events if item['event']=='turn_start'}, set(range(1,9)))


if __name__ == '__main__':
    unittest.main()
