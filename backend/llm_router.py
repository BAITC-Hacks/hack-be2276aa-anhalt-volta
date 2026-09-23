"""LLM-backed dialogue router with a deterministic rules fallback."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from router.router import route_dialogue


logger = logging.getLogger(__name__)

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
DATASET_PATH = Path(__file__).resolve().parent.parent / "voice_router_dataset" / "scenarios.json"


def _load_catalog() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as file:
        data = json.load(file)

    catalog = []
    for scenario in data["scenarios"]:
        examples = scenario.get("examples", {})
        example = (examples.get("ru") or examples.get("kk") or [""])[0]
        catalog.append({
            "id": scenario["scenario_id"],
            "purpose": scenario.get("name", "")[:80],
            "boundaries": [
                f"{boundary.get('condition', '')[:100]} -> {boundary.get('use_instead', '')}"
                for boundary in scenario.get("not_this_if", [])
            ],
            "example": example[:100],
        })
    return catalog


SCENARIO_CATALOG = _load_catalog()
SCENARIO_IDS = {item["id"] for item in SCENARIO_CATALOG}

ROUTER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scenario_id": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string", "maxLength": 180},
        "alternatives": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["id", "confidence"],
            },
        },
        "params": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["name", "value"],
            },
        },
        "action": {"type": "string", "enum": ["answer", "clarify", "handoff"]},
        "pending_topics": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "scenario_id",
        "confidence",
        "reasoning",
        "alternatives",
        "params",
        "action",
        "pending_topics",
    ],
}

OPERATOR_PATTERN = re.compile(
    r"оператор|соедин.*челов|человеком|жив.*челов|адаммен|тірі оператор",
    re.IGNORECASE,
)


def _operator_requested(text: str) -> bool:
    return bool(OPERATOR_PATTERN.search(text))


STATIC_PROMPT = (
    "Ты роутер диалогов контакт-центра страховой компании.\n"
    "Каталог сценариев (id, назначение, границы и один пример):\n"
    f"{json.dumps(SCENARIO_CATALOG, ensure_ascii=False, separators=(',', ':'))}\n\n"
    "Выбирай сценарий с учётом смены темы, истории и смешения русского с казахским. "
    "pending_topics — список ID дополнительных сценариев из каталога, только из текущей реплики. "
    "Если клиент просит оператора, action должен быть handoff. "
    "reasoning — одно короткое предложение на русском."
)


def _params_list(value: Any) -> list[dict[str, str]]:
    if isinstance(value, list):
        return [
            {"name": str(item["name"]), "value": str(item["value"])}
            for item in value
            if isinstance(item, dict) and "name" in item and "value" in item
        ]
    if isinstance(value, dict):
        return [
            {"name": str(name), "value": str(item_value)}
            for name, item_value in value.items()
        ]
    return []


def _fallback(
    utterance: str,
    history: list[dict[str, Any]],
    current_scenario: str | None,
    started_at: float,
    llm_error: str | None = None,
) -> dict[str, Any]:
    result = route_dialogue(utterance, history, current_scenario)
    action = "handoff" if _operator_requested(utterance) else {
        "clarify": "clarify",
        "escalate": "handoff",
    }.get(result.get("decision"), "answer")
    scenario_id = result.get("scenario_id")
    if scenario_id not in SCENARIO_IDS:
        action = "clarify"

    return {
        "scenario_id": scenario_id,
        "confidence": result.get("confidence", 0.0),
        "reasoning": result.get("reason", ""),
        "alternatives": [
            {"id": item, "confidence": 0.0}
            for item in result.get("alternatives", [])[:3]
        ],
        "params": _params_list(result.get("entities", {})),
        "action": action,
        "pending_topics": result.get("queued_scenarios", []),
        "router_mode": "rules_fallback",
        "llm_ms": round((time.perf_counter() - started_at) * 1000, 3),
        **({"llm_error": llm_error} if llm_error else {}),
    }


def _prompt(utterance: str, history: list[dict[str, Any]], current_scenario: str | None) -> str:
    recent_history = history[-10:]
    return (
        f"{STATIC_PROMPT}\n\n"
        "Контекст диалога (последние 10 реплик):\n"
        f"{json.dumps(recent_history, ensure_ascii=False)}\n\n"
        f"Текущий сценарий: {current_scenario or 'нет'}\n"
        f"Новая реплика клиента: {utterance}\n\n"
        "Верни только JSON по заданной схеме."
    )


def _input_tokens(response: Any) -> int | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get("input_tokens") or usage.get("prompt_tokens")
    return getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)


def route(
    utterance: str,
    history: list[dict[str, Any]],
    current_scenario: str | None,
) -> dict[str, Any]:
    """Route through OpenAI, falling back to the deterministic router on failure."""
    started_at = time.perf_counter()
    if _operator_requested(utterance):
        # Do not let an LLM response override the explicit operator request.
        fallback = _fallback(utterance, history[-10:], current_scenario, started_at)
        fallback["action"] = "handoff"
        fallback["router_mode"] = "fast_path"
        fallback.pop("llm_error", None)
        return fallback

    try:
        client = OpenAI(timeout=6.0, max_retries=0)
        response = client.responses.create(
            model=MODEL,
            input=_prompt(utterance, history, current_scenario),
            max_output_tokens=300,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "voice_router_result",
                    "strict": True,
                    "schema": ROUTER_SCHEMA,
                }
            },
        )
        result = json.loads(response.output_text)

        if result.get("scenario_id") not in SCENARIO_IDS:
            result["action"] = "clarify"
            result["reasoning"] = "Не удалось уверенно определить сценарий из каталога."
        if _operator_requested(utterance):
            result["action"] = "handoff"
        result["alternatives"] = result.get("alternatives", [])[:3]
        result["params"] = _params_list(result.get("params", []))
        result["router_mode"] = "llm"
        result["llm_ms"] = round((time.perf_counter() - started_at) * 1000, 3)
        logger.info(
            "LLM router success: model=%s prompt_tokens=%s llm_ms=%.3f",
            MODEL,
            _input_tokens(response),
            result["llm_ms"],
        )
        return result
    except Exception as exc:
        llm_ms = round((time.perf_counter() - started_at) * 1000, 3)
        logger.exception("LLM router failed: prompt_tokens=unknown llm_ms=%.3f: %s", llm_ms, exc)
        return _fallback(
            utterance,
            history[-10:],
            current_scenario,
            started_at,
            llm_error=str(exc)[:500],
        )
