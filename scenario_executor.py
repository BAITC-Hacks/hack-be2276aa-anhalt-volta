"""Allowlisted local, read-only handlers. Never dispatches model-supplied operation names."""
from scenario_repository import read_json


class ScenarioExecutor:
    def __init__(self, knowledge_path=None, mock_path=None):
        self.knowledge_path, self.mock_path = knowledge_path, mock_path

    def execute(self, scenario, parameters, language):
        missing = [p.name for p in scenario.parameters if p.required and not parameters.get(p.name, '').strip()]
        lang = 'kk' if language == 'kk' else 'ru'
        if missing:
            labels = [p.description for p in scenario.parameters if p.name in missing]
            return {'status': 'needs_parameters', 'missing_parameters': missing,
                    'reply': ('Нақтылаңызшы: ' if lang == 'kk' else 'Уточните, пожалуйста: ') + ', '.join(labels) + '?'}
        handlers = {'respond': self._respond, 'knowledge': self._knowledge, 'mock_lookup': self._mock}
        if scenario.handler not in handlers:
            raise ValueError('Unregistered scenario handler')
        return {'status': 'completed', 'missing_parameters': [],
                'reply': handlers[scenario.handler](scenario, lang)}

    @staticmethod
    def _respond(scenario, lang):
        return scenario.responses.get(lang) or scenario.responses.get('ru') or (
            f'«{scenario.name}» сценарийі таңдалды. Бұл демонстрация.' if lang == 'kk' else
            f'Выбран сценарий «{scenario.name}». Это демонстрация, реальные операции не выполняются.')

    def _knowledge(self, scenario, lang):
        if not self.knowledge_path or not scenario.knowledge_keys:
            raise ValueError('Missing knowledge data')
        data = read_json(self.knowledge_path)
        return '\n'.join(self._text(data[key], lang) for key in scenario.knowledge_keys)

    def _mock(self, scenario, lang):
        if not self.mock_path or not scenario.mock_key:
            raise ValueError('Missing mock data')
        value = read_json(self.mock_path)[scenario.mock_key]
        return ('Тест деректері: ' if lang == 'kk' else 'Тестовые данные: ') + self._text(value, lang)

    @staticmethod
    def _text(value, lang):
        if isinstance(value, dict):
            value = value.get(lang) or value.get('ru')
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError('Expected bounded localized text in data adapter')
        return value
