"""Temporary client for the conversation router.

Replace ``route`` with a real LLM/router integration later.
"""

from typing import Any


def route(text: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """Return a fixed routing result for now."""
    # Keep the arguments in the public interface for the future real router.
    _ = (text, history)
    return {
        "scenario_id": "general_support",
        "confidence": 0.92,
        "reasoning": "Запрос направлен в общий сценарий поддержки.",
        "alternatives": ["billing", "technical_support"],
        "params": {"topic": "general_support"},
        "action": "answer",
        "pending_topics": [],
        "answer_text": "Здравствуйте! Чем могу помочь?",
    }
