"""Explicit normalized starter-kit adapter; never silently replaces malformed real data."""
import hashlib
import json
import re
from pathlib import Path
from pydantic import Field
from routing_models import Contract


class Parameter(Contract):
    name: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,63}$')
    description: str
    required: bool = True


class Scenario(Contract):
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,99}$')
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    boundaries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    examples: dict[str, list[str]] = Field(default_factory=dict)
    parameters: list[Parameter] = Field(default_factory=list)
    # Only code-registered handlers can execute. A catalog cannot name arbitrary functions.
    handler: str = 'respond'
    responses: dict[str, str] = Field(default_factory=dict)
    knowledge_keys: list[str] = Field(default_factory=list)
    mock_key: str | None = None
    priority: int = Field(default=0, ge=0, le=100)


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError(f'JSON слишком большой: {path.name}')
    return json.loads(path.read_text(encoding='utf-8-sig'))


class ScenarioRepository:
    def __init__(self, path):
        self.path = Path(path)
        raw = read_json(self.path)
        rows = raw.get('scenarios') if isinstance(raw, dict) else raw
        if not isinstance(rows, list) or not rows:
            raise ValueError('Нужен список сценариев или объект {"scenarios": [...]}: см. ROUTING.md')
        self.scenarios = [Scenario.model_validate(row) for row in rows]
        self.by_id = {s.id: s for s in self.scenarios}
        if len(self.by_id) != len(rows) or 'clarify' in self.by_id:
            raise ValueError('ID сценариев должны быть уникальными; clarify зарезервирован для уточнения')
        for s in self.scenarios:
            if len({p.name for p in s.parameters}) != len(s.parameters):
                raise ValueError(f'Повтор параметра: {s.id}')
        self.catalog_id = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        self.demo = isinstance(raw, dict) and raw.get('source') == 'demo_fixture'
        self.titles = {s.id: s.name for s in self.scenarios} | {'clarify': 'Уточнение запроса'}

    def retrieve(self, text, state, limit=8):
        """High-recall CPU lexical shortlist. Scores are not probabilities."""
        query = text.casefold()
        tokens = set(re.findall(r'\w{3,}', query))
        ranked = []
        for s in self.scenarios:
            corpus = ' '.join([s.name, s.description, *s.boundaries,
                               *(ex for values in s.examples.values() for ex in values)]).casefold()
            hits = [k for k in s.keywords if k.casefold() in query]
            score = len(hits) * 4 + sum(token in corpus for token in tokens)
            excluded = any(k.casefold() in query for k in s.exclude_keywords)
            if excluded:
                score = 0
            ranked.append({'scenario': s.id, 'score': score, 'keyword_hits': hits,
                           'excluded': excluded, 'context': s.id == state.current_scenario})
        ranked.sort(key=lambda c: (-c['score'], c['scenario']))
        positive = [c for c in ranked if c['score'] > 0]
        # No lexical evidence: let the LLM see the catalog rather than force a wrong top-k.
        selected = positive[:limit] if positive else ranked[:]
        mandatory = {state.current_scenario, *state.pending_intents}
        # Include all direct keyword hits: a shortlist must not erase secondary intents.
        for c in ranked:
            if (c['scenario'] in mandatory or (c['keyword_hits'] and not c['excluded'])) and c not in selected:
                selected.append(c)
        return selected
