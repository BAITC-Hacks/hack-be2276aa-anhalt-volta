"""Context, catalog, fail-safe and evaluation contracts; no paid services."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from agent import route, get_repository
from routing_models import ConversationState, Decision
from scenario_repository import ScenarioRepository
from scenario_executor import ScenarioExecutor
from router import route_request
from benchmark import evaluate


def repository(tmp_path, rows):
    path = tmp_path / 'scenarios.json'
    path.write_text(json.dumps({'scenarios': rows}), encoding='utf-8')
    return ScenarioRepository(path)


def row(id='claim', **extra):
    return {'id': id, 'name': id, 'description': 'Страховой случай', 'keywords': [id], **extra}


def live(repo, payload, state=None, executor=None):
    client = MagicMock()
    client.__enter__.return_value = client
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(payload))
    return route_request('claim', [], 'live', repo, lambda: client, 'test', state, executor)


def test_external_catalog_supports_40_ids_and_rejects_malformed(tmp_path):
    repo = repository(tmp_path, [row(f'scenario_{i}', keywords=[f'label{i}:']) for i in range(40)])
    assert len(repo.scenarios) == 40 and not repo.demo
    result = route_request('label39:', [], 'demo', repo, None, 'unused')
    assert result['scenario_id'] == 'scenario_39'
    with pytest.raises(ValueError):
        repository(tmp_path, [row(), row()])
    with pytest.raises(ValueError):
        repository(tmp_path, [row('clarify')])
    with pytest.raises(ValueError):
        repository(tmp_path, [row(unrecognized_official_field='must adapt')])


def test_multi_intent_queue_topic_switch_and_context_are_not_mutated():
    ordered = route('Сначала баланс и потом заблокируйте карту')
    assert ordered['scenario_id'] == 'check_balance'
    assert ordered['secondary_intents'] == ['card_block']
    first = route('Заблокируйте карту и поменяйте адрес.')
    assert first['scenario_id'] == 'card_block'
    assert first['topic'] == 'MULTI_INTENT'
    state = first['conversation_state']
    snapshot = json.dumps(state)
    second = route('Следующий', state=state)
    assert second['scenario_id'] == 'change_address'
    assert second['topic'] == 'TOPIC_SWITCH'
    assert second['conversation_state']['pending_intents'] == []
    assert json.dumps(state) == snapshot
    third = route('Да', state=second['conversation_state'])
    assert third['scenario_id'] == 'change_address'
    assert third['topic'] == 'TOPIC_REFINEMENT'
    assert route('Несвязанный запрос', state=state)['fallback_reason'] == 'NO_MATCH'


def test_parameters_and_unfinished_task_survive_switch(tmp_path):
    repo = repository(tmp_path, [row(parameters=[{'name': 'city', 'description': 'город'}]), row('other')])
    first = live(repo, {'scenario_id': 'claim', 'explanation': 'match'})
    assert first['missing_parameters'] == ['city']
    assert first['execution_status'] == 'needs_parameters'
    second = route_request('other', [], 'demo', repo, None, 'test', first['conversation_state'])
    assert second['conversation_state']['pending_intents'] == ['claim']
    third = route_request('Следующий', [], 'demo', repo, None, 'test', second['conversation_state'])
    assert third['missing_parameters'] == ['city']
    fourth = live(repo, {'scenario_id': 'claim', 'explanation': 'city provided', 'parameters': {'city': 'Алматы'}}, third['conversation_state'])
    assert fourth['execution_status'] == 'completed'
    assert fourth['conversation_state']['collected_parameters']['claim']['city'] == 'Алматы'


@pytest.mark.parametrize('extra', [
    {'scenario_id': 'invented'}, {'secondary_intents': ['invented']},
    {'parameters': {'arbitrary_operation': 'delete'}}, {'execute': 'shell'},
    {'alternative_confidences': {'claim': 1.2}, 'alternatives': ['claim']},
    {'fallback_reason': 'NO_MATCH'},
])
def test_invalid_model_output_never_reaches_handler(tmp_path, extra):
    repo = repository(tmp_path, [row()])
    executor = MagicMock()
    result = live(repo, {'scenario_id': 'claim', 'explanation': 'x', **extra}, executor=executor)
    assert result['fallback_reason'] == 'INVALID_ROUTER_OUTPUT'
    executor.execute.assert_not_called()


def test_model_cannot_claim_operation_was_executed(tmp_path):
    repo = repository(tmp_path, [row(responses={'ru': 'Локальный ответ'})])
    result = live(repo, {'scenario_id': 'claim', 'explanation': 'x', 'reply': 'Выполнен перевод денег'})
    assert result['reply'] == 'Локальный ответ'


def test_low_confidence_and_provider_failure_are_controlled(tmp_path):
    repo = repository(tmp_path, [row()])
    assert live(repo, {'scenario_id': 'claim', 'explanation': 'x', 'confidence': .2})['fallback_reason'] == 'LOW_CONFIDENCE'
    def unavailable():
        raise RuntimeError('secret provider message')
    result = route_request('claim', [], 'live', repo, unavailable, 'test')
    assert result['fallback_reason'] == 'ROUTER_ERROR'
    assert 'secret provider message' not in json.dumps(result)


def test_handlers_are_allowlisted_and_backend_errors_keep_pending(tmp_path):
    repo = repository(tmp_path, [row(handler='shell')])
    result = live(repo, {'scenario_id': 'claim', 'explanation': 'x'})
    assert result['fallback_reason'] == 'BACKEND_ERROR'
    assert result['execution_status'] == 'error'
    assert result['conversation_state']['pending_intents'] == ['claim']


def test_knowledge_and_mock_are_only_read_by_selected_handler(tmp_path):
    kb = tmp_path / 'knowledge.json'
    mock = tmp_path / 'mock.json'
    kb.write_text(json.dumps({'hours': {'ru': '9–18', 'kk': '9–18'}, 'unused': 'not in reply'}), encoding='utf-8')
    mock.write_text(json.dumps({'demo_customer': {'ru': 'Тестовый статус: активен'}}), encoding='utf-8')
    repo = repository(tmp_path, [row(handler='knowledge', knowledge_keys=['hours']), row('status', handler='mock_lookup', mock_key='demo_customer')])
    executor = ScenarioExecutor(kb, mock)
    assert executor.execute(repo.by_id['claim'], {}, 'ru')['reply'] == '9–18'
    assert 'активен' in executor.execute(repo.by_id['status'], {}, 'ru')['reply']
    # The respond handler does not need either file.
    repo = repository(tmp_path, [row()])
    assert ScenarioExecutor('missing', 'missing').execute(repo.by_id['claim'], {}, 'ru')['status'] == 'completed'


def test_catalog_change_requires_new_conversation(tmp_path):
    repo = repository(tmp_path, [row()])
    with pytest.raises(ValueError, match='Каталог'):
        route_request('claim', [], 'demo', repo, None, 'test', {'catalog_id': 'old'})


def test_shortlist_retains_current_pending_and_has_no_match_broadening(tmp_path):
    repo = repository(tmp_path, [row(f'intent{i}') for i in range(40)])
    state = ConversationState(current_scenario='intent30', pending_intents=['intent31'])
    found = repo.retrieve('intent1', state, limit=2)
    assert {'intent1', 'intent30', 'intent31'} <= {c['scenario'] for c in found}
    assert len(repo.retrieve('unrecognized', state)) == 40


def test_sanitized_diagnostic_log_has_no_transcript(caplog):
    with caplog.at_level('INFO', logger='seile.routing'):
        route('Проверить баланс. email: private@example.com')
    assert 'private@example.com' not in caplog.text
    data = json.loads(caplog.records[-1].message)
    assert data['selected_scenario'] == 'check_balance'
    assert data['utterance'] == '[not persisted]'


def test_benchmark_is_explicitly_synthetic_and_keeps_dialog_context():
    result = evaluate('data/demo/dev_utterances.json', get_repository())
    assert result['dataset_source'] == 'synthetic_demo_not_official'
    assert result['accuracy'] == 1
    assert result['topic_accuracy'] == 1
    assert result['secondary_intent_accuracy'] == 1
    assert result['count'] == 17
    assert result['routing_latency_ms']['p95'] >= result['routing_latency_ms']['p50'] >= 0


def test_ui_keeps_queue_and_shows_trace():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file('app.py', default_timeout=20).run()
    app.chat_input[0].set_value('Заблокируйте карту и поменяйте адрес.').run()
    assert not app.exception
    assert app.session_state['routing_context']['pending_intents'] == ['change_address']
    app.chat_input[0].set_value('Следующий').run()
    assert not app.exception
    assert app.session_state['traces'][-1]['topic'] == 'TOPIC_SWITCH'


def test_real_sdk_serializes_dynamic_schema_without_network(monkeypatch):
    from google import genai
    from router import output_schema
    with genai.Client(api_key='offline-test-placeholder') as client:
        request = MagicMock(side_effect=RuntimeError('offline transport boundary'))
        monkeypatch.setattr(client._api_client, 'request', request)
        with pytest.raises(RuntimeError, match='offline transport boundary'):
            client.models.generate_content(model='test-model', contents='test', config={
                'temperature': 0, 'response_mime_type': 'application/json',
                'response_json_schema': output_schema([{'scenario': 'claim'}])})
        body = request.call_args.args[2]
        schema = body['generationConfig']['responseJsonSchema']
        assert schema['properties']['scenario_id']['enum'] == ['claim', 'clarify']
        assert schema['additionalProperties'] is False
