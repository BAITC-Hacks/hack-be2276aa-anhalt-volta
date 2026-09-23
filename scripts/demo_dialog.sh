#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SERVER_PID=""

PHONE="$(python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("voice_router_dataset/mock_backend.json").read_text(encoding="utf-8"))
print(data["clients"][0]["phone"])
PY
)"

if ! curl -fsS "$BASE_URL/openapi.json" >/dev/null 2>&1; then
  python3 -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 >"${TMPDIR:-/tmp}/voice-router-demo.log" 2>&1 &
  SERVER_PID="$!"
  trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
  for _ in $(seq 1 30); do
    if curl -fsS "$BASE_URL/openapi.json" >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
fi

SESSION_ID="$(curl -fsS -X POST "$BASE_URL/session" | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')"

print_turn() {
  local text="$1"
  local response
  response="$(curl -fsS -X POST "$BASE_URL/turn" \
    -H 'Content-Type: application/json' \
    --data "$(python3 -c 'import json,sys; print(json.dumps({"session_id": sys.argv[1], "text": sys.argv[2]}, ensure_ascii=False))' "$SESSION_ID" "$text")")"
  LAST_RESPONSE="$response"
  printf '%s' "$LAST_RESPONSE" | python3 scripts/print_turn.py
}

assert_pending_topics() {
  RESPONSE_JSON="$LAST_RESPONSE" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["RESPONSE_JSON"])
if not payload.get("pending_topics"):
    raise SystemExit("demo check failed: pending_topics was lost")
PY
}

assert_phone_not_asked_again() {
  RESPONSE_JSON="$LAST_RESPONSE" python3 - <<'PY'
import json
import os

answer = json.loads(os.environ["RESPONSE_JSON"]).get("answer_text", "").lower()
if "телефон" in answer or "нөмір" in answer or "номер телефона" in answer:
    raise SystemExit("demo check failed: phone was requested again")
PY
}

print_turn "Я переехала, новый адрес Almaty, Abai Ave 150. И ещё деньги списались дважды"
assert_pending_topics
print_turn "$PHONE"
assert_pending_topics
assert_phone_not_asked_again
print_turn "да"
print_turn "да"
print_turn "Төлем екі рет алынды, тексеріп беріңізші"
print_turn "соедините с оператором"
