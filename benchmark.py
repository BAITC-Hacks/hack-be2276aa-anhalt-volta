"""Local benchmark wrapper, NOT the official evaluate.py. Never edits evaluation data."""
import argparse
import json
import logging
import math
from pathlib import Path
from statistics import median
from agent import get_repository, get_client
from config import MODEL_NAME, KNOWLEDGE_PATH, MOCK_BACKEND_PATH
from routing_models import ConversationState
from scenario_repository import ScenarioRepository, read_json
from scenario_executor import ScenarioExecutor
from router import route_request


def load_cases(path):
    data = read_json(path)
    source = data.get('source', 'external_unverified') if isinstance(data, dict) else 'external_unverified'
    if isinstance(data, dict) and 'dialogs' in data:
        dialogs = data['dialogs']
    else:
        rows = data.get('utterances') if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError('Dataset adapter expects utterances or dialogs; see ROUTING.md')
        dialogs = [{'turns': [row]} for row in rows]
    if not isinstance(dialogs, list) or not dialogs:
        raise ValueError('Empty or invalid dataset')
    for dialog in dialogs:
        if not isinstance(dialog, dict) or not isinstance(dialog.get('turns'), list) or not dialog['turns']:
            raise ValueError('Each dialog must contain turns')
        for turn in dialog['turns']:
            if not isinstance(turn, dict) or not isinstance(turn.get('text'), str) or not isinstance(turn.get('expected_scenario'), str):
                raise ValueError('Turn requires text and expected_scenario')
    return source, dialogs


def evaluate(path, repository, mode='demo', client_factory=get_client, executor=None):
    source, dialogs = load_cases(path)
    rows = []
    allowed = set(repository.by_id) | {'clarify'}
    for dialog in dialogs:
        state, history = ConversationState().model_dump(), []
        for turn in dialog['turns']:
            if turn['expected_scenario'] not in allowed:
                raise ValueError('Dataset/catalog mismatch: unknown expected_scenario')
            result = route_request(turn['text'], history, mode, repository, client_factory,
                                   MODEL_NAME, state, executor)
            state = result['conversation_state']
            history.extend([{'role': 'user', 'content': turn['text']}, {'role': 'assistant', 'content': result['reply']}])
            rows.append({'expected': turn['expected_scenario'], 'actual': result['scenario_id'],
                         'correct': result['scenario_id'] == turn['expected_scenario'],
                         'topic_correct': result['topic'] == turn['expected_topic'] if 'expected_topic' in turn else None,
                         'secondary_correct': set(result['secondary_intents']) == set(turn['secondary_intents']) if 'secondary_intents' in turn else None,
                         'candidate_hit': turn['expected_scenario'] in {c['scenario'] for c in result['candidates']} if turn['expected_scenario'] != 'clarify' else None,
                         'fallback': result['fallback_reason'], 'latency_ms': result['routing_ms']})
    times = sorted(row['latency_ms'] for row in rows)
    def rate(key):
        values = [row[key] for row in rows if row[key] is not None]
        return sum(values) / len(values) if values else None
    return {'dataset': str(path), 'dataset_source': source, 'catalog_id': repository.catalog_id,
            'catalog_source': 'demo_fixture' if repository.demo else 'external',
            'mode': mode, 'count': len(rows), 'accuracy': rate('correct'),
            'wrong_scenario_count': sum(not row['correct'] for row in rows),
            'fallback_count': sum(row['fallback'] is not None for row in rows),
            'topic_accuracy': rate('topic_correct'), 'secondary_intent_accuracy': rate('secondary_correct'),
            'candidate_recall': rate('candidate_hit'),
            'routing_latency_ms': {'p50': median(times), 'p95': times[math.ceil(len(times) * .95) - 1]},
            'results': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default='data/demo/dev_utterances.json')
    parser.add_argument('--scenarios')
    parser.add_argument('--mode', choices=['demo', 'live'], default='demo')
    parser.add_argument('--output', help='JSON metrics; excludes raw transcripts')
    parser.add_argument('--log-jsonl', help='Optional sanitized routing metadata log')
    args = parser.parse_args()
    if args.log_jsonl:
        logger = logging.getLogger('seile.routing')
        handler = logging.FileHandler(args.log_jsonl, encoding='utf-8')
        logger.addHandler(handler); logger.setLevel(logging.INFO)
    repository = ScenarioRepository(args.scenarios) if args.scenarios else get_repository()
    report = evaluate(args.dataset, repository, args.mode,
                      executor=ScenarioExecutor(KNOWLEDGE_PATH, MOCK_BACKEND_PATH))
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        Path(args.output).write_text(encoded + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
