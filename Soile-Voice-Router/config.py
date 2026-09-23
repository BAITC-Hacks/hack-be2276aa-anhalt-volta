import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-5-mini')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
MODEL_NAME = os.getenv('GEMINI_MODEL', 'gemini-3.6-flash')
