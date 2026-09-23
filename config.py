import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
MODEL_NAME = os.getenv('GEMINI_MODEL', 'gemini-3.6-flash')
_bundled_rhubarb = Path(__file__).parent / '.tools' / 'Rhubarb-Lip-Sync-1.14.0-Windows' / 'rhubarb.exe'
RHUBARB_PATH = os.getenv('RHUBARB_PATH') or (str(_bundled_rhubarb) if _bundled_rhubarb.is_file() else 'rhubarb')
FFMPEG_PATH = os.getenv('FFMPEG_PATH', 'ffmpeg')

# Data paths are relative to the project, not the shell working directory.
_root = Path(__file__).parent
def _data_path(variable, default):
    value = Path(os.getenv(variable) or default)
    return value if value.is_absolute() else _root / value

SCENARIOS_PATH = _data_path('SCENARIOS_PATH', 'data/scenarios.json' if (_root / 'data/scenarios.json').exists() else 'data/demo/scenarios.json')
KNOWLEDGE_PATH = _data_path('KNOWLEDGE_PATH', 'data/knowledge_base.json')
MOCK_BACKEND_PATH = _data_path('MOCK_BACKEND_PATH', 'data/mock_backend.json')
