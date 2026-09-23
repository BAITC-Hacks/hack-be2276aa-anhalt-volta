"""Provider-free validation, analysis and UI lifecycle regressions."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import lip_sync


@pytest.mark.parametrize('cues', [
    [{'start': -1, 'end': 1, 'value': 'A'}],
    [{'start': 0, 'end': 0, 'value': 'A'}],
    [{'start': 0, 'end': 1, 'value': 'unknown'}],
    [{'start': 0, 'end': float('nan'), 'value': 'A'}],
    [{'start': 0, 'end': 2, 'value': 'A'}, {'start': 1, 'end': 3, 'value': 'B'}],
    [{'start': True, 'end': 2, 'value': 'A'}],
])
def test_invalid_cues(cues):
    with pytest.raises(ValueError):
        lip_sync.validate_cues(cues)


def test_uploaded_timeline_skips_recognizer(monkeypatch):
    monkeypatch.setattr(lip_sync.subprocess, 'run', lambda *a, **k: pytest.fail('Unexpected process'))
    cues = [{'start': 0, 'end': .5, 'value': 'D'}]
    result = lip_sync.prepare_audio(b'fixture', '.wav', json.dumps({'mouthCues': cues}).encode())
    assert result['cues'] == cues
    assert result['mode'] == 'visemes'


def test_missing_recognizer_explicit_fallback(monkeypatch):
    monkeypatch.setattr(lip_sync.shutil, 'which', lambda _: None)
    result = lip_sync.prepare_audio(b'fixture', '.mp3')
    assert result['mode'] == 'amplitude'
    assert result['src'].startswith('data:audio/mpeg;base64,')


def test_phonetic_analysis_once(monkeypatch):
    monkeypatch.setattr(lip_sync.shutil, 'which', lambda _: 'found')
    run = Mock(return_value=SimpleNamespace(stdout=b'{"mouthCues":[{"start":0,"end":1,"value":"B"}]}'))
    monkeypatch.setattr(lip_sync.subprocess, 'run', run)
    result = lip_sync.prepare_audio(b'fixture', '.wav')
    assert result['mode'] == 'visemes'
    assert run.call_count == 1
    assert run.call_args.args[0][1:5] == ['-r', 'phonetic', '-f', 'json']
    assert run.call_args.kwargs['timeout'] == 120


def test_request_error_returns_to_idle(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import agent
    monkeypatch.setattr(agent, 'route', Mock(side_effect=RuntimeError('offline')))
    app = AppTest.from_file('app.py', default_timeout=20).run()
    app.chat_input[0].set_value('Привет').run()
    assert not app.exception
    assert app.session_state['pending_request'] is None
    assert app.session_state['traces'][-1]['fallback_reason'] == 'ROUTER_ERROR'
    assert app.error
