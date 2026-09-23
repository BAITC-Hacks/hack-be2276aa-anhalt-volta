#!/usr/bin/env python3
"""Run the six-turn backend demo dialog on Windows, macOS, or Linux."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def wait_for_backend(base_url: str, process: subprocess.Popen | None) -> None:
    for _ in range(40):
        try:
            requests.get(f"{base_url}/openapi.json", timeout=0.5).raise_for_status()
            return
        except requests.RequestException:
            if process and process.poll() is not None:
                break
            time.sleep(0.25)
    raise RuntimeError("Backend не запустился. Проверьте run.py или логи uvicorn.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    server = None
    log = None
    try:
        try:
            requests.get(f"{base_url}/openapi.json", timeout=0.5).raise_for_status()
        except requests.RequestException:
            log_path = Path(tempfile.gettempdir()) / "voice-router-demo.log"
            log = log_path.open("w", encoding="utf-8")
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            )
        wait_for_backend(base_url, server)

        data = json.loads((ROOT / "voice_router_dataset" / "mock_backend.json").read_text(encoding="utf-8"))
        phone = data["clients"][0]["phone"]
        session_id = requests.post(f"{base_url}/session", timeout=5).json()["session_id"]
        turns = [
            "Я переехала, новый адрес Almaty, Abai Ave 150. И ещё деньги списались дважды",
            phone, "да", "да", "Төлем екі рет алынды, тексеріп беріңізші", "соедините с оператором",
        ]
        for text in turns:
            response = requests.post(
                f"{base_url}/turn", json={"session_id": session_id, "text": text}, timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            answer = payload.get("answer_text", "").replace("\n", " ")
            timings = payload.get("timings_ms") or {}
            print(" | ".join([
                str(payload.get("router_mode", "—")), str(payload.get("scenario_id", "—")),
                str(payload.get("confidence", "—")), str(payload.get("action", "—")),
                answer, str(timings.get("llm_ms", "—")),
            ]), flush=True)
            if text == phone and not payload.get("pending_topics"):
                raise RuntimeError("pending_topics пропал после реплики с телефоном")
            if text == phone and any(word in answer.lower() for word in ("телефон", "номер телефона", "нөмір")):
                raise RuntimeError("телефон был запрошен повторно")
        return 0
    finally:
        if server and server.poll() is None:
            server.terminate()
            server.wait(timeout=5)
        if log:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
