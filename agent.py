"""Compatibility facade for UI/CLI; routing itself has no speech or UI dependency."""
from functools import lru_cache
from pathlib import Path
from config import GEMINI_API_KEY, MODEL_NAME, SCENARIOS_PATH, KNOWLEDGE_PATH, MOCK_BACKEND_PATH
from routing_models import Decision, ConversationState
from scenario_repository import ScenarioRepository
from scenario_executor import ScenarioExecutor
from router import route_request, demo_decision


@lru_cache(maxsize=4)
def _repository(path, modified):
    return ScenarioRepository(path)


def get_repository():
    path = Path(SCENARIOS_PATH)
    return _repository(str(path), path.stat().st_mtime_ns)


TITLES = get_repository().titles


def get_client():
    if not GEMINI_API_KEY:
        raise ValueError('Добавьте GEMINI_API_KEY в .env и перезапустите приложение.')
    from google import genai
    from google.genai import types
    return genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=30000))


def demo_route(text: str) -> Decision:
    repository = get_repository()
    state = ConversationState()
    return demo_decision(text, state, repository, repository.retrieve(text, state))


def route(text: str, history: list[dict] | None = None, mode: str = 'demo',
          state: dict | None = None) -> dict:
    return route_request(text, history, mode, get_repository(), get_client, MODEL_NAME,
                         state=state, executor=ScenarioExecutor(KNOWLEDGE_PATH, MOCK_BACKEND_PATH))


def transcribe(audio: bytes) -> str:
    if not audio or len(audio) > 5 * 1024 * 1024:
        raise ValueError('Запись должна быть непустой и не больше 5 МБ.')
    from google.genai import types
    with get_client() as client:
        response = client.models.generate_content(model=MODEL_NAME, contents=[
            'Точно расшифруй речь на русском и/или казахском. Только текст речи, без комментариев. Если речи нет, верни пустую строку.',
            types.Part.from_bytes(data=audio, mime_type='audio/wav')])
    text = (response.text or '').strip()
    if not text:
        raise ValueError('Речь не распознана. Попробуйте ещё раз или введите текст.')
    return text


def run_agent(user_prompt: str) -> str:
    return route(user_prompt, mode='live')['reply']
