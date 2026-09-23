#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  if [[ ! -f .env.example ]]; then
    echo "Ошибка: отсутствуют и .env, и .env.example." >&2
    exit 1
  fi
  cp .env.example .env
  echo "Создан .env из .env.example. Впишите OPENAI_API_KEY и снова запустите: bash run.sh" >&2
  exit 1
fi

VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if command -v uv >/dev/null 2>&1; then
  if [[ ! -x "$VENV_PYTHON" ]] || ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
    echo "Создаю .venv через uv с Python 3.12..."
    uv venv --python 3.12 --clear --force "$VENV_DIR"
  fi
else
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Ошибка: нужен Python 3.10+ или установленный uv." >&2
    exit 1
  fi
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Ошибка: найден Python ниже 3.10. Установите Python 3.10+ или uv и повторите bash run.sh." >&2
    exit 1
  fi
  if [[ ! -x "$VENV_PYTHON" ]] || ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "Создаю .venv через python3..."
    python3 -m venv --clear "$VENV_DIR"
  fi
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Ошибка: не удалось создать $VENV_DIR." >&2
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$VENV_PYTHON" -r requirements.txt
else
  "$VENV_PYTHON" -m pip install -r requirements.txt
fi

PORT="${PORT:-8000}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"
check_port() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Ошибка: порт $port уже занят." >&2
    echo "Проверьте процесс: lsof -nP -iTCP:$port -sTCP:LISTEN" >&2
    return 1
  fi
}
check_port "$PORT" || { echo "Освободите порт или запустите API на другом: PORT=8001 bash run.sh" >&2; exit 1; }
check_port "$STREAMLIT_PORT" || { echo "Освободите порт или запустите UI на другом: STREAMLIT_PORT=8502 bash run.sh" >&2; exit 1; }

cleanup() { [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
echo "FastAPI:   http://127.0.0.1:$PORT"
echo "Streamlit: http://127.0.0.1:$STREAMLIT_PORT"
"$VENV_PYTHON" -m uvicorn backend.app:app --reload --port "$PORT" &
BACKEND_PID=$!
"$VENV_PYTHON" -m streamlit run Soile-Voice-Router/app.py --server.address 127.0.0.1 --server.port "$STREAMLIT_PORT"
