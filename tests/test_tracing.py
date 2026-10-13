import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from skala_rag.tracing import TraceRecorder


class Client:
    def __init__(self):
        self.created, self.updated = [], []
        self.flushed = False

    def create_run(self, name, **data):
        self.created.append((name, data))

    def update_run(self, run_id, **data):
        self.updated.append((run_id, data))

    def flush(self):
        self.flushed = True

    def read_run(self, run_id):
        return SimpleNamespace(dotted_order=self.created[0][1]['dotted_order'])


def test_redacted_local_and_remote_events_share_trace_and_timestamps(tmp_path):
    client, run_id = Client(), str(uuid4())
    path = tmp_path / 'events.jsonl'
    recorder = TraceRecorder(run_id, path, enabled=True, client=client)
    recorder.start()
    recorder.record('B', {'task_id': 'B:1', 'reason': 'token=sk-secret',
        'evidence_ids': ['id', 'lsv2_secret'], 'nested': {'api_key': 'private'},
        'authorization_reason': 'Authorization: Bearer privateJWT'})
    recorder.finish('incomplete')
    event = json.loads(path.read_text())
    child = client.created[1][1]
    assert event['run_id'] == child['trace_id'] == child['parent_run_id'] == run_id
    assert child['start_time'].tzinfo and child['end_time'] >= child['start_time']
    assert 'secret' not in json.dumps(event)
    assert 'private' not in json.dumps(event)
    assert child['inputs'] == {'run_id': run_id}
    assert client.flushed and recorder.delivery_status == 'submitted'


def test_remote_failure_is_visible_without_exposing_exception_body(tmp_path):
    class Broken(Client):
        def create_run(self, *args, **kwargs):
            raise ConnectionError('token=sk-private request payload')
    path = tmp_path / 'events.jsonl'
    recorder = TraceRecorder(str(uuid4()), path, enabled=True, client=Broken())
    recorder.start()
    recorder.record('supervisor', {'action': 'finish', 'status': 'incomplete'})
    recorder.finish('incomplete')
    assert recorder.delivery_status == 'failed'
    assert recorder.remote_errors == ['ConnectionError', 'ConnectionError']
    assert 'private' not in path.read_text()
    assert len(path.read_text().splitlines()) == 3


def test_enabled_tracing_requires_key_before_creating_run_directory(tmp_path, monkeypatch):
    monkeypatch.delenv('LANGSMITH_API_KEY', raising=False)
    with pytest.raises(ValueError, match='LANGSMITH_API_KEY'):
        TraceRecorder(str(uuid4()), tmp_path / 'new' / 'events.jsonl', enabled=True)
    assert not (tmp_path / 'new').exists()


def test_resume_reuses_existing_remote_root():
    client, run_id = Client(), str(uuid4())
    first = TraceRecorder(run_id, enabled=True, client=client)
    first.start()
    second = TraceRecorder(run_id, enabled=True, client=client)
    second.start(resume=True)
    second.record('C', {'attempt': 2})
    assert len(client.created) == 2
    assert client.created[1][1]['dotted_order'].startswith(first.root_order + '.')
