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


def _gpt5_reasoning_effort(model: str) -> str | None:
    if not model.lower().startswith("gpt-5"):
        return None
    if re.match(r"^gpt-5\.(?:4|2|1)(?:$|[-])", model.lower()):
        return "none"
    return "minimal"


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
    for intent in data.get("system_intents", []):
        catalog.append({
            "id": intent["id"],
            "purpose": intent.get("description", "")[:120],
            "boundaries": [],
            "example": "",
        })
    return catalog


SCENARIO_CATALOG = _load_catalog()
SCENARIO_IDS = {item["id"] for item in SCENARIO_CATALOG}

with DATASET_PATH.open(encoding="utf-8") as _scenario_file:
    _SCENARIO_DATA = json.load(_scenario_file)
SCENARIO_META = {
    item["scenario_id"]: item
    for item in _SCENARIO_DATA["scenarios"]
}
SCENARIO_META.update({
    item["id"]: item for item in _SCENARIO_DATA.get("system_intents", [])
})

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
    r"(?:соедин(?:ите|ить)?\s+с\s+(?:оператором|человеком)|"
    r"позовите\s+оператора|оператормен\s+байланыстырыңыз)",
    re.IGNORECASE,
)


def _operator_requested(text: str) -> bool:
    return bool(OPERATOR_PATTERN.search(text))


try:
    _OPENAI_CLIENT = OpenAI(timeout=6.0, max_retries=0)
except Exception:
    _OPENAI_CLIENT = None


def _prioritize_topics(result: dict[str, Any]) -> dict[str, Any]:
    """Promote an urgent rule match and retain the other detected topics."""
    primary = result.get("scenario_id")
    candidates = [primary]
    candidates.extend(result.get("queued_scenarios") or [])
    candidates.extend(result.get("alternatives") or [])
    candidates = [item for item in candidates if item in SCENARIO_IDS]
    urgent = next(
        (item for item in candidates if SCENARIO_META.get(item, {}).get("priority") == "urgent"),
        None,
    )
    if urgent and urgent != primary:
        result["scenario_id"] = urgent
        result["reason"] = f"Срочный сценарий имеет приоритет: {SCENARIO_META[urgent].get('name', urgent)}."
        candidates = [urgent] + [item for item in candidates if item != urgent]
    pending = []
    for item in candidates[1:]:
        if item not in pending:
            pending.append(item)
    result["queued_scenarios"] = pending
    return result


def _rules_result(
    utterance: str,
    history: list[dict[str, Any]],
    current_scenario: str | None,
) -> dict[str, Any]:
    result = route_dialogue(utterance, history, current_scenario)
    # Let the unchanged baseline router inspect independent clauses too. This
    # exposes secondary topics that its single-pass rule may otherwise hide.
    clauses = [part.strip() for part in re.split(
        r"\s+(?:и|ещё|заодно|және|әрі|тағы)\s+|[;!?]\s*", utterance,
        flags=re.IGNORECASE,
    ) if len(part.strip().split()) >= 2]
    detected = []
    for clause in clauses:
        clause_result = route_dialogue(clause, history, current_scenario)
        scenario_id = clause_result.get("scenario_id")
        if scenario_id in SCENARIO_IDS and scenario_id not in detected:
            detected.append(scenario_id)
    if len(detected) > 1:
        existing = result.get("queued_scenarios") or []
        result["queued_scenarios"] = existing + [item for item in detected if item != result.get("scenario_id")]
        result["decision"] = "multi_intent"
    return _prioritize_topics(result)


STATIC_PROMPT = (
    "Ты роутер диалогов контакт-центра страховой компании.\n"
    "Каталог сценариев (id, назначение, границы и один пример):\n"
    f"{json.dumps(SCENARIO_CATALOG, ensure_ascii=False, separators=(',', ':'))}\n\n"
    "Выбирай сценарий с учётом смены темы, истории и смешения русского с казахским. "
    "Сначала отдели ясность потребности от соответствия услугам компании. "
    "SYS_UNCLEAR используй только когда непонятно, чего хочет клиент: названа лишь общая тема "
    "или есть только приветствие без конкретного запроса. Если желание клиента можно сформулировать, "
    "не используй SYS_UNCLEAR, даже если услуга не относится к компании. "
    "SYS_OUT_OF_SCOPE используй, когда потребность ясна, но Saqta Insurance её не предлагает: "
    "страхование жизни, пенсионные аннуитеты, кредиты, а также любую тему вне страхования. "
    "Для SYS_UNCLEAR ставь action=clarify, для SYS_OUT_OF_SCOPE — action=handoff. "
    "Если в реплике несколько тем, сценарий с priority=urgent ставь основным, "
    "а остальные темы сохраняй в pending_topics. "
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


def _clean_pending_topics(result: dict[str, Any]) -> list[str]:
    primary = result.get("scenario_id")
    pending = result.get("pending_topics") or []
    if not isinstance(pending, list):
        return []
    cleaned = []
    for item in pending:
        if item in SCENARIO_IDS and item != primary and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _promote_urgent_pending(result: dict[str, Any]) -> dict[str, Any]:
    primary = result.get("scenario_id")
    pending = _clean_pending_topics(result)
    primary_priority = SCENARIO_META.get(primary, {}).get("priority")
    urgent = next(
        (item for item in pending if SCENARIO_META.get(item, {}).get("priority") == "urgent"),
        None,
    )
    if urgent and primary_priority != "urgent":
        result["scenario_id"] = urgent
        pending = [primary] + [item for item in pending if item != urgent and item != primary]
        note = f"Срочный сценарий поставлен первым: {SCENARIO_META[urgent].get('name', urgent)}."
        reasoning = str(result.get("reasoning", "")).strip()
        result["reasoning"] = f"{reasoning} {note}".strip()[:180]
    result["pending_topics"] = [
        item for item in pending
        if item in SCENARIO_IDS and item != result.get("scenario_id")
    ]
    return result


def _fallback(
    utterance: str,
    history: list[dict[str, Any]],
    current_scenario: str | None,
    started_at: float,
    llm_error: str | None = None,
) -> dict[str, Any]:
    result = _rules_result(utterance, history, current_scenario)
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

    # Fast path is deliberately limited to simple, high-confidence scenarios
    # explicitly marked as eligible in scenarios.json. Multi-intent matches
    # stay on the LLM path so topic ordering and pending topics are preserved.
    rules = _rules_result(utterance, history[-10:], current_scenario)
    rules_scenario = rules.get("scenario_id")
    rules_meta = SCENARIO_META.get(rules_scenario, {})
    if (
        rules_scenario in SCENARIO_IDS
        and rules_meta.get("fast_path_eligible") is True
        and float(rules.get("confidence", 0.0)) >= 0.80
        and rules.get("decision") not in {"clarify", "multi_intent"}
        and not rules.get("queued_scenarios")
    ):
        return {
            "scenario_id": rules_scenario,
            "confidence": rules.get("confidence", 0.0),
            "reasoning": rules.get("reason", ""),
            "alternatives": [
                {"id": item, "confidence": 0.0}
                for item in (rules.get("alternatives") or [])[:3]
                if item in SCENARIO_IDS
            ],
            "params": _params_list(rules.get("entities", {})),
            "action": "answer",
            "pending_topics": rules.get("queued_scenarios", []),
            "router_mode": "fast_path",
            "llm_ms": 0.0,
        }

    try:
        if _OPENAI_CLIENT is None:
            raise RuntimeError("OpenAI client is unavailable")
        request = {
            "model": MODEL,
            "input": _prompt(utterance, history, current_scenario),
            "max_output_tokens": 600 if MODEL.lower().startswith("gpt-5") else 300,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "voice_router_result",
                    "strict": True,
                    "schema": ROUTER_SCHEMA,
                }
            },
        }
        reasoning_effort = _gpt5_reasoning_effort(MODEL)
        if reasoning_effort is not None:
            request["reasoning"] = {"effort": reasoning_effort}
        response = _OPENAI_CLIENT.responses.create(**request)
        result = json.loads(response.output_text)

        if result.get("scenario_id") not in SCENARIO_IDS:
            result["action"] = "clarify"
            result["reasoning"] = "Не удалось уверенно определить сценарий из каталога."
        result["alternatives"] = result.get("alternatives", [])[:3]
        result["params"] = _params_list(result.get("params", []))
        _promote_urgent_pending(result)
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
