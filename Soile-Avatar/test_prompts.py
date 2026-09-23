"""Offline regression checks; no credentials or paid requests required."""
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError
import agent
from agent import Decision, route


@pytest.mark.parametrize('text,expected', [
    ('Я потерял карту, хочу её заблокировать.', 'card_block'),
    ('Картамды жоғалттым, бұғаттау керек.', 'card_block'),
    ('Хочу поменять адрес доставки.', 'change_address'),
    ('Сәлем! Хочу поменять адрес, мекенжайым өзгерді.', 'change_address'),
    ('Какой остаток на счете?', 'check_balance'),
    ('Хочу заблокировать карту. Передумал, лучше проверить баланс.', 'check_balance'),
    ('Покажи баланс и поменяй адрес.', 'clarify'),
    ('Карта заблокировалась.', 'clarify'),
    ('Не нужно блокировать карту.', 'clarify'),
    ('Привет!', 'clarify'),
])
def test_demo_routing(text, expected):
    result = route(text)
    assert result['scenario_id'] == expected
    assert result['confidence'] is None
    assert result['routing_ms'] >= 0


@pytest.mark.parametrize('text', ['', '   ', 'x' * 4001])
def test_invalid_input(text):
    with pytest.raises(ValueError):
        route(text)


def test_demo_never_calls_api(monkeypatch):
    monkeypatch.setattr(agent, 'get_client', lambda: pytest.fail('Unexpected API call'))
    route('Проверить баланс')


def test_live_validates_response_and_passes_history(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.models.generate_content.return_value = SimpleNamespace(text=Decision(
        scenario_id='check_balance', explanation='Запрос остатка', reply='Выбран сценарий',
        confidence=0.8, alternatives=['check_balance', 'clarify', 'clarify']).model_dump_json())
    monkeypatch.setattr(agent, 'get_client', lambda: client)
    result = route('Да', [{'role': 'user', 'content': 'Проверить баланс'}], mode='live')
    assert result['alternatives'] == ['clarify']
    assert 'Проверить баланс' in client.models.generate_content.call_args.kwargs['contents']
    client.models.generate_content.return_value = SimpleNamespace(text='{"scenario_id":"invented"}')
    with pytest.raises(ValidationError):
        route('Да', mode='live')


def test_ui_demo():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file('app.py', default_timeout=20).run()
    assert not app.exception
    app.chat_input[0].set_value('Я потерял карту').run()
    assert not app.exception
    assert app.session_state['traces'][-1]['scenario_id'] == 'card_block'
    app.chat_input[0].set_value('Лучше проверить баланс').run()
    assert app.session_state['traces'][-1]['scenario_id'] == 'check_balance'
    next(b for b in app.button if b.label == 'Очистить диалог').click().run()
    assert app.session_state['messages'] == []
    assert not app.exception
