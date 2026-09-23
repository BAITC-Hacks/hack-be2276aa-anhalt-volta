#!/usr/bin/env python3
"""Small offline contract test for the LLM-router postprocessing."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import llm_router


RESPONSES = {
    "ваш оператор мне нагрубил": {
        "scenario_id": "SC35", "confidence": 0.9,
        "reasoning": "Клиент сообщает о жалобе на обслуживание.",
        "alternatives": [], "params": [], "action": "answer", "pending_topics": [],
    },
    "попал в аварию и ещё адрес поменять надо": {
        "scenario_id": "SC29", "confidence": 0.8,
        "reasoning": "Клиент назвал две темы.", "alternatives": [], "params": [],
        "action": "answer", "pending_topics": ["SC11", "SC29", "UNKNOWN"],
    },
    "какая погода завтра": {
        "scenario_id": "SYS_OUT_OF_SCOPE", "confidence": 0.99,
        "reasoning": "Запрос не относится к услугам страховой компании.",
        "alternatives": [], "params": [], "action": "handoff", "pending_topics": [],
    },
}


class FakeResponses:
    def create(self, *, input, **kwargs):
        utterance = input.rsplit("Новая реплика клиента: ", 1)[-1].split("\n", 1)[0]
        return SimpleNamespace(output_text=json.dumps(RESPONSES[utterance]), usage={"input_tokens": 1})


class FakeClient:
    responses = FakeResponses()


def main():
    previous = llm_router._OPENAI_CLIENT
    llm_router._OPENAI_CLIENT = FakeClient()
    try:
        complaint = llm_router.route("ваш оператор мне нагрубил", [], None)
        assert complaint["action"] != "handoff"

        urgent = llm_router.route("попал в аварию и ещё адрес поменять надо", [], None)
        assert urgent["scenario_id"] == "SC11"
        assert "SC29" in urgent["pending_topics"]
        assert "сроч" in urgent["reasoning"].lower()

        out_of_scope = llm_router.route("какая погода завтра", [], None)
        assert out_of_scope["scenario_id"] == "SYS_OUT_OF_SCOPE"
        assert out_of_scope["reasoning"] == RESPONSES["какая погода завтра"]["reasoning"]
        print("llm_router contract checks: ok")
    finally:
        llm_router._OPENAI_CLIENT = previous


if __name__ == "__main__":
    main()
