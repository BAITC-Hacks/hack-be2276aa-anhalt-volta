"""Regression tests for structured routing and mixed-language session memory."""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import agent
from llm_routing import parse_reply, merge_state, route_openai, clean_history, _client, EN_QUESTIONS, SLOTS, streamed_header


def reply(**changes):
    value = dict(scenario_id="SC11", confidence=.9, reason="Accident reported",
                 alternatives=["SC13"], queued_scenarios=[], reply_language="en",
                 reply_text="Did the accident just happen?", new_facts=[],
                 question_field="incident_date")
    value.update(changes)
    return value


def completion(value):
    content = json.dumps(value)
    stream = MagicMock()
    stream.__enter__.return_value = stream
    chunks = [SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason=None,
        delta=SimpleNamespace(content=content[i:i+10], refusal=None))])
        for i in range(0, len(content), 10)]
    chunks.append(SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason='stop',
        delta=SimpleNamespace(content=None, refusal=None))]))
    stream.__iter__.return_value = iter(chunks)
    return stream


class RoutingTests(unittest.TestCase):
    def test_dictionary_references_no_longer_crash(self):
        value = reply(scenario_id={"id": "SC11"}, alternatives=[
            {"scenario_id": "SC13", "reason": "CASCO"}, "SC13", "SC11"],
            queued_scenarios=[{"id": "SC25"}])
        result = parse_reply(json.dumps(value))
        self.assertEqual(result["alternatives"], ["SC13"])
        self.assertEqual(result["queued_scenarios"], ["SC25"])

    def test_malformed_values_are_validation_errors(self):
        for changes in ({"scenario_id": []}, {"alternatives": [{}]},
                        {"alternatives": "SC13"}, {"reply_language": "other"},
                        {"scenario_id": "SC99"}, {"confidence": 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_reply(json.dumps(reply(**changes)))

    def test_multilingual_facts_persist_and_corrections_replace(self):
        previous = {"current_scenario": "SC11", "facts": [{
            "name": "city", "scope": "SC11", "value": "Almaty", "evidence": "Almaty"}]}
        original = deepcopy(previous)
        text = "Нет, Астана. Жедел жәрдем келді, I am at the scene."
        facts = [
            dict(name="city", scope="SC11", value="Astana", evidence="Астана"),
            dict(name="emergency_help", scope="SC11", value="arrived", evidence="Жедел жәрдем келді"),
            dict(name="at_scene", scope="SC11", value="yes", evidence="I am at the scene"),
        ]
        state = merge_state(previous, reply(new_facts=facts, question_field="policy_number"), text)
        self.assertEqual(previous, original)
        self.assertEqual(len(state["facts"]), 3)
        self.assertEqual(state["facts"][0]["value"], "Astana")
        state2 = merge_state(state, reply(scenario_id="SC25", question_field="phone"), "Check my policy")
        self.assertEqual(state2["facts"], state["facts"])

    def test_repeated_question_repaired_and_invented_evidence_discarded(self):
        fact = dict(name="city", scope="SC11", value="Astana", evidence="Астана")
        value = reply(question_field="city")
        state = merge_state({"facts": [fact]}, value, "Yes")
        self.assertEqual(state['question_field'], 'injured')
        self.assertEqual(value['reply_text'], 'Was anyone injured?')
        self.assertEqual(merge_state({}, reply(new_facts=[fact]), "Yes")['facts'], [])

    def test_full_dialogue_history_and_backend_format(self):
        history = [{"role": "client", "text": "I crashed my car"}]
        history += [{"role": "assistant", "content": "Уточните"}] * 18
        history += [{"role": "user", "content": "Жедел жәрдем келді"}]
        self.assertEqual(len(clean_history(history)), 20)
        self.assertEqual(clean_history(history)[0]["content"], "I crashed my car")

    def test_strict_schema_and_single_request(self):
        import openai
        _client.cache_clear()
        client = MagicMock()
        client.chat.completions.create.return_value = completion(reply(question_field="city"))
        state = {"facts": [dict(name="city", scope="SC11", value="Astana", evidence="Astana")]}
        with patch.object(openai, "OpenAI", return_value=client):
            result = route_openai("Да, I am here", [], state, "test-key", "gpt-5.4-mini")
        request = client.chat.completions.create.call_args.kwargs
        self.assertTrue(request["response_format"]["json_schema"]["strict"])
        self.assertEqual(result["api_attempts"], 1)
        client.chat.completions.create.assert_called_once()
        self.assertEqual(request['reasoning_effort'], 'none')
        self.assertEqual(json.loads(request["messages"][1]["content"])["conversation_state"], state)
        self.assertLessEqual(result['decision_ms'], result['api_ms'])
        _client.cache_clear()

    def test_all_slots_have_english_repair_questions(self):
        self.assertEqual({s['name'] for s in SLOTS}, set(EN_QUESTIONS))

    def test_stream_header_only_when_complete(self):
        data = reply(reason='Quoted text: "reply_text": not a JSON property')
        wire = json.dumps(data)
        start = wire.index(', "reply_text":')
        self.assertEqual(streamed_header(wire[:start + 1])['scenario_id'], 'SC11')
        self.assertIsNone(streamed_header('{"scenario_id":"SC'))
        self.assertIsNone(streamed_header('{"scenario_id":"SC11","queued_scenarios":['))
        self.assertEqual(streamed_header('{"scenario_id":"SC11","queued_scenarios":[],')['scenario_id'], 'SC11')

    def test_openai_is_not_bypassed_by_keyword_guard(self):
        result = reply(scenario_id="SYS_UNCLEAR", question_field="product_type",
                       reply_text="What would you like to insure?")
        result["dialogue_state"] = merge_state({}, result, "A luxurious life")
        with patch.object(agent, "_openai_route", return_value=result) as call:
            output = agent.route("I want insurance for a luxurious life", mode="openai")
        call.assert_called_once()
        self.assertFalse(output["fallback"])

    def test_fallback_preserves_memory_and_reports_source(self):
        state = {"current_scenario": "SC11", "facts": [dict(
            name="city", scope="SC11", value="Astana", evidence="Astana")]}
        with patch.object(agent, "_openai_route", side_effect=TimeoutError("do not expose raw error")):
            output = agent.route("Yes", mode="openai", state=state)
        self.assertTrue(output["fallback"])
        self.assertEqual(output["model"], agent.MODEL_NAME)
        self.assertEqual(output["dialogue_state"]["facts"], state["facts"])
        self.assertEqual(output["fallback_reason"], "TimeoutError")


if __name__ == "__main__":
    unittest.main()
