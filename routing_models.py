"""Provider-neutral contracts. Scenario IDs are validated against the loaded catalog."""
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field

Topic = Literal['SAME_TOPIC', 'TOPIC_REFINEMENT', 'TOPIC_SWITCH', 'MULTI_INTENT']
Fallback = Literal['LOW_CONFIDENCE', 'NO_MATCH', 'AMBIGUOUS', 'MISSING_CONTEXT',
                   'INVALID_ROUTER_OUTPUT', 'BACKEND_ERROR', 'ROUTER_ERROR', 'STT_ERROR']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Decision(Contract):
    scenario_id: str = Field(min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=1000)
    alternatives: list[str] = Field(default_factory=list, max_length=3)
    alternative_confidences: dict[str, float] = Field(default_factory=dict)
    reply: str = Field(default='', max_length=2000)
    language: Literal['ru', 'kk', 'mixed'] = 'ru'
    topic: Topic = 'SAME_TOPIC'
    secondary_intents: list[str] = Field(default_factory=list, max_length=10)
    parameters: dict[str, str] = Field(default_factory=dict)
    requires_clarification: bool = False
    fallback_reason: Fallback | None = None


class ConversationState(Contract):
    conversation_id: str = Field(default_factory=lambda: uuid4().hex)
    catalog_id: str = ''
    current_scenario: str | None = None
    previous_scenarios: list[str] = Field(default_factory=list)
    collected_parameters: dict[str, dict[str, str]] = Field(default_factory=dict)
    unresolved_questions: list[str] = Field(default_factory=list)
    language: Literal['ru', 'kk', 'mixed'] = 'ru'
    topic_history: list[dict[str, str]] = Field(default_factory=list)
    relevant_user_facts: dict[str, str] = Field(default_factory=dict)
    pending_intents: list[str] = Field(default_factory=list)
    pending_action: str | None = None
    turn: int = 0
