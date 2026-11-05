"""Transcrições privadas: journal append-only e projeção Markdown por conversa."""

from contextvars import ContextVar
from datetime import datetime
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
import re
from secrets import token_hex
from threading import Lock
from time import perf_counter
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.callbacks import BaseCallbackHandler
from memory import normalize_session_id

ROOT = Path(__file__).resolve().parents[1]
USER_ERROR_MESSAGE = "Não foi possível concluir o atendimento neste momento. Tente novamente."
CURRENT_TRACE = ContextVar('conversation_trace', default=None)


def _now():
    return datetime.now(ZoneInfo('America/Belem')).isoformat(timespec='milliseconds')


def _fenced(text):
    length = max([2] + [len(value) for value in re.findall(r'`+', text)]) + 1
    fence = '`' * length
    return f'{fence}text\n{text}\n{fence}'


class ConversationTrace(BaseCallbackHandler):
    def __init__(self):
        self.tools = []
        self.evidence = []
        self.guardrail = 'nao_concluido'
        self._runs = {}
        self._lock = Lock()

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        with self._lock:
            self._runs[str(run_id)] = len(self.tools)
            self.tools.append({'name': (serialized or {}).get('name', 'desconhecida'),
                               'input': str(input_str), 'status': 'iniciada'})

    def on_tool_end(self, output, *, run_id, **kwargs):
        with self._lock:
            if str(run_id) in self._runs:
                self.tools[self._runs[str(run_id)]].update(output=str(output), status='concluida')

    def on_tool_error(self, error, *, run_id, **kwargs):
        with self._lock:
            if str(run_id) in self._runs:
                self.tools[self._runs[str(run_id)]].update(error_type=type(error).__name__, status='erro')

    def export(self):
        with self._lock:
            return {'guardrail': self.guardrail, 'tools': list(self.tools), 'evidence': list(self.evidence)}


def record_catalog_evidence(handler, answer):
    trace = CURRENT_TRACE.get()
    if trace is not None:
        trace.evidence.append({'type': 'consulta_sql_estruturada', 'handler': handler,
                               'source': 'db/emporio.db', 'output': answer})


class TranscriptStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or os.environ.get('EMPORIO_TRANSCRIPT_DIR') or ROOT / 'conversas')

    def directory(self, session_id):
        session_id = normalize_session_id(session_id)
        fingerprint = sha256(('transcript-v1:' + session_id).encode()).hexdigest()
        return self.root / f'conversa_{fingerprint}'

    def _sanitize(self, value, session_id):
        if isinstance(value, str):
            for secret in (session_id, str(UUID(hex=session_id))):
                value = re.sub(re.escape(secret), '[CODIGO_DE_RETOMADA_OMITIDO]', value, flags=re.IGNORECASE)
            return value
        if isinstance(value, list):
            return [self._sanitize(item, session_id) for item in value]
        if isinstance(value, dict):
            return {key: self._sanitize(item, session_id) for key, item in value.items()}
        return value

    @staticmethod
    def _read(data):
        events = []
        for number, line in enumerate(data.splitlines(), 1):
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({'event': 'journal_error', 'line': number})
        return events

    @staticmethod
    def _write(path, text):
        temporary = path.with_name(f'.{path.name}.{token_hex(8)}.tmp')
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                output.write(text)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _append(self, session_id, event):
        session_id = normalize_session_id(session_id)
        folder = self.directory(session_id)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.mkdir(exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        os.chmod(folder, 0o700)
        event = self._sanitize(event, session_id)
        path = folder / 'eventos.jsonl'
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, 'a+', encoding='utf-8') as output:
            fcntl.flock(output, fcntl.LOCK_EX)
            output.seek(0)
            content = output.read()
            events = self._read(content)
            if event['event'] == 'turn_start':
                event['turn'] = 1 + sum(item.get('event') == 'turn_start' for item in events)
            output.seek(0, os.SEEK_END)
            if content and not content.endswith('\n'):
                output.write('\n')
            output.write(json.dumps(event, ensure_ascii=False) + '\n')
            output.flush()
            os.fsync(output.fileno())
            self._write(folder / 'transcricao.md', self._markdown(events + [event]))
            fcntl.flock(output, fcntl.LOCK_UN)
        return event

    def _markdown(self, events):
        lines = ['# Transcrição integral da conversa', '',
                 'Arquivo privado. O código de retomada não é incluído. Revise dados pessoais antes de compartilhar.', '',
                 'Origem: eventos.jsonl. Recusas, erros e turnos interrompidos também são mantidos. A memória do agente pode conter apenas os turnos aceitos.', '']
        ends = {item['turn_id']: item for item in events if item.get('event') == 'turn_end'}
        for item in events:
            if item.get('event') == 'journal_error':
                lines.extend([f'**Aviso:** linha {item["line"]} incompleta/inválida no journal original; ela não foi apagada.', ''])
            elif item.get('event') == 'note':
                lines.extend(['## Evento de execução', '', item['text'], ''])
            elif item.get('event') == 'turn_start':
                end = ends.get(item['turn_id'])
                lines.extend([f'## Turno {item["turn"]}', '', f'Início: {item["at"]}. Modelo: {item["model"]}.', '',
                              '**Cliente**', '', _fenced(item['question']), '', '**Assistente**', '',
                              _fenced(end['answer']) if end else '*Turno iniciado sem conclusão registrada.*', ''])
                if end:
                    trace = end.get('trace', {})
                    lines.extend([f'Estado: **{end["status"]}**. Tempo: {end["elapsed_ms"]:.2f} ms. Guardião: {trace.get("guardrail", "nao_concluido")}.', ''])
                    for tool in trace.get('tools', []):
                        lines.extend([f'### Ferramenta: {tool["name"]} ({tool["status"]})', '',
                                      '**Entrada:**', '', _fenced(tool['input']), '', '**Retorno:**', '',
                                      _fenced(tool.get('output', tool.get('error_type', 'Sem conclusão registrada.'))), ''])
                    for evidence in trace.get('evidence', []):
                        lines.extend([f'### Evidência: {evidence["type"]}', '',
                                      f'Fonte: {evidence["source"]}. Função: {evidence["handler"]}.', '',
                                      _fenced(evidence['output']), ''])
        return '\n'.join(lines) + '\n'

    def begin(self, session_id, question, model):
        turn_id = token_hex(12)
        self._append(session_id, {'event': 'turn_start', 'turn_id': turn_id, 'at': _now(),
                                  'question': question, 'model': model})
        return {'turn_id': turn_id, 'start': perf_counter()}

    def finish(self, session_id, ticket, answer, status, trace, error_type=None):
        self._append(session_id, {'event': 'turn_end', 'turn_id': ticket['turn_id'], 'at': _now(),
                                  'answer': answer, 'status': status, 'error_type': error_type,
                                  'elapsed_ms': round((perf_counter() - ticket['start']) * 1000, 2),
                                  'trace': trace.export()})

    def note(self, session_id, text):
        self._append(session_id, {'event': 'note', 'at': _now(), 'text': text})

    def artifact(self, session_id, name, text):
        if name not in {'avaliacao.md', 'referencias.json', 'execucao.json', 'roteiro.json'}:
            raise ValueError('Nome de artefato não permitido.')
        folder = self.directory(session_id)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.mkdir(exist_ok=True, mode=0o700)
        path = folder / name
        if path.exists():
            raise FileExistsError('Artefato já existe; preserve a execução anterior.')
        self._write(path, self._sanitize(text, normalize_session_id(session_id)))
        return path


transcript_store = TranscriptStore()
