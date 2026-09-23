"""Adapter between the backend and the baseline dialogue router."""

from __future__ import annotations

from typing import Any

from .llm_router import route as llm_route


def _params_dict(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return value
    return {
        str(item["name"]): str(item["value"])
        for item in value or []
        if isinstance(item, dict) and "name" in item and "value" in item
    }


def route(
    text: str,
    history: list[dict[str, Any]],
    current_scenario: str | None = None,
) -> dict[str, Any]:
    """Call the LLM router and return its normalized result."""
    result = llm_route(text, history, current_scenario)
    action = result.get("action", "clarify")

    if action == "clarify":
        answer_text = result.get("clarifying_question") or "Уточните, пожалуйста, ваш вопрос."
    elif action == "handoff":
        answer_text = "Передаю ваш вопрос оператору."
    else:
        answer_text = "Ваш запрос принят и направлен в соответствующий сценарий."

    return {**result, "params": _params_dict(result.get("params")), "answer_text": answer_text}


def route_safely(
    text: str,
    history: list[dict[str, Any]],
    current_scenario: str | None = None,
) -> dict[str, Any]:
    """Return a handoff result if the router fails."""
    try:
        return route(text, history, current_scenario)
    except Exception as exc:
        return {
            "scenario_id": current_scenario or "SYS_ROUTER_ERROR",
            "confidence": 0.0,
            "reasoning": "Роутер временно недоступен; требуется оператор.",
            "alternatives": [],
            "params": {"error": str(exc), "dialogue_context": history},
            "action": "handoff",
            "pending_topics": [],
            "router_mode": "rules_fallback",
            "llm_ms": 0.0,
            "answer_text": "Не удалось автоматически обработать запрос. Передаю вас оператору.",
        }
