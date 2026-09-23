"""Small mock scenario executor backed by the dataset JSON files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "voice_router_dataset"


def _load(name: str) -> dict[str, Any]:
    with (DATA_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


# Loaded once when the backend starts.
KNOWLEDGE_BASE = _load("knowledge_base.json")
MOCK_BACKEND = _load("mock_backend.json")
ACTIONS_DATA = _load("actions.json")
SCENARIOS_DATA = _load("scenarios.json")

ACTION_BY_NAME = {item["name"]: item for item in ACTIONS_DATA["actions"]}
SCENARIO_BY_ID = {item["scenario_id"]: item for item in SCENARIOS_DATA["scenarios"]}
IRREVERSIBLE_ACTIONS = {
    name for name, item in ACTION_BY_NAME.items() if item.get("irreversible")
}


def _language(text: str, session: dict[str, Any]) -> str:
    if re.search(r"[әіңғүұқөһ]", text.lower()):
        return "kk"
    client = session.get("client")
    if client and client.get("preferred_language") in {"ru", "kk"}:
        return client["preferred_language"]
    return "ru"


def _is_yes(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(да|иә|ия|подтверждаю|подтверждаю да|yes)\s*[.!]?", text.lower()))


def _is_no(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(нет|жоқ|отмена|не надо|отменить)\s*[.!]?", text.lower()))


def _topic_id(topic: Any) -> str | None:
    value = str(topic).lower()
    if value in SCENARIO_BY_ID:
        return value.upper()
    if any(word in value for word in ("спис", "платеж", "оплат", "charged", "деньг")):
        return "SC30"
    if any(word in value for word in ("email", "почт", "контакт", "адрес")):
        return "SC29"
    if any(word in value for word in ("полис", "документ")):
        return "SC26"
    return None


def _param(params: dict[str, Any], *names: str) -> Any:
    for name in names:
        if params.get(name) not in (None, "", []):
            return params[name]
    return None


def _extract_params(text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    phone = re.search(r"\+?7\s*\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}", text)
    if phone:
        params["phone"] = re.sub(r"\D", "", phone.group(0))
        if not params["phone"].startswith("7"):
            params["phone"] = "7" + params["phone"]
        params["phone"] = "+" + params["phone"]
    if re.search(r"переех|переезд|мекенжай|көшіп", text.lower()):
        params["contact_field"] = "address"
    address = re.search(r"(?:адрес|мекенжай)[\s:]+(.+?)(?:\.|$)", text, re.IGNORECASE)
    if address:
        params["new_value"] = address.group(1).strip()
    return params


def _find_client(params: dict[str, Any], session: dict[str, Any]) -> dict[str, Any] | None:
    if session.get("client"):
        return session["client"]
    phone = _param(params, "phone", "telephone")
    iin = _param(params, "iin", "client_iin")
    for client in MOCK_BACKEND["clients"]:
        if (phone and client["phone"] == str(phone)) or (iin and client["iin"] == str(iin)):
            session["client"] = client
            return client
    return None


def _required_missing(action_name: str, params: dict[str, Any], session: dict[str, Any]) -> str | None:
    action = ACTION_BY_NAME[action_name]
    for raw_input in action.get("inputs", []):
        alternatives = raw_input.split("|")
        if any(_param(params, option) is not None for option in alternatives):
            continue
        if raw_input == "phone|iin" and session.get("client"):
            continue
        if raw_input == "client_id" and session.get("client"):
            continue
        return alternatives[0]
    return None


def _question(slot: str, language: str) -> str:
    questions = {
        "phone": ("Назовите номер телефона, на который оформлен полис.", "Полис тіркелген телефон нөмірін айтыңызшы."),
        "iin": ("Назовите ИИН клиента.", "Клиенттің ЖСН-ін айтыңызшы."),
        "contact_field": ("Что изменить: адрес, телефон или email?", "Нені өзгертеміз: мекенжайды, телефонды әлде email-ды?"),
        "new_value": ("Назовите новое значение.", "Жаңа мәнді айтыңызшы."),
        "policy_number": ("Назовите номер полиса.", "Полис нөмірін айтыңызшы."),
        "payment_date": ("Назовите дату платежа.", "Төлем күнін айтыңызшы."),
        "city": ("В каком городе вас обслужить?", "Қай қалада қызмет көрсетейік?"),
        "cancel_reason": ("Укажите причину отмены полиса.", "Полисті тоқтату себебін айтыңызшы."),
    }
    return questions.get(slot, (f"Уточните параметр: {slot}.", f"{slot} параметрін нақтылаңызшы."))[language == "kk"]


def _format_number(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.0f}".replace(",", " ")
    return str(value)


def _execute_action(name: str, params: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    client = session.get("client")
    if name == "find_client":
        found = _find_client(params, session)
        return {"client": found} if found else {"error": "Клиент не найден по указанному телефону или ИИН."}
    if name == "get_policies":
        policies = [p for p in MOCK_BACKEND["policies"] if p["client_id"] == client["client_id"]]
        return {"policies": policies}
    if name == "get_policy":
        number = _param(params, "policy_number")
        plate = _param(params, "vehicle_plate")
        policy = next((p for p in MOCK_BACKEND["policies"] if p["policy_number"] == number or p.get("details", {}).get("vehicle_plate") == plate), None)
        return {"policy": policy} if policy else {"error": "Полис не найден."}
    if name == "get_bm_class":
        iin = _param(params, "iin")
        found = next((c for c in MOCK_BACKEND["clients"] if c["iin"] == str(iin)), None)
        return {"bm_class": found["bm_class"] if found else MOCK_BACKEND["defaults"]["unknown_iin_bm_class"]}
    if name == "get_offices":
        city = str(_param(params, "city") or "").lower()
        office = next((o for o in KNOWLEDGE_BASE["offices"] if o["city"].lower() == city), None)
        return {"office": office} if office else {"error": "Офис в этом городе не найден."}
    if name == "list_clinics":
        city = str(_param(params, "city") or "").lower()
        clinics = [c for c in KNOWLEDGE_BASE["clinics"] if not city or c.get("city", "").lower() == city]
        return {"clinics": clinics}
    if name == "check_payment":
        payment_date = _param(params, "payment_date")
        payments = [p for p in MOCK_BACKEND["payments"] if p["client_id"] == client["client_id"]]
        if payment_date:
            payments = [p for p in payments if p["date"] == str(payment_date)]
        return {"payment": payments[0]} if payments else {"error": "Платёж за указанную дату не найден."}
    if name == "update_contact":
        field = str(_param(params, "contact_field") or "address")
        value = str(_param(params, "new_value"))
        old_value = client.get(field)
        client[field] = value
        return {"contact_field": field, "old_value": old_value, "new_value": value}
    if name == "resend_documents":
        return {"sent_to": client.get("email") if client else _param(params, "email")}
    if name == "cancel_policy":
        return {"refund_amount": 0, "refund_time": KNOWLEDGE_BASE["cancellation"]["refund_time"]}
    if name == "check_coverage":
        return {"covered": True, "note": "Проверка покрытия выполнена по данным полиса."}
    if name == "kb_lookup":
        topic = str(_param(params, "topic") or "payments").lower()
        return {"answer": KNOWLEDGE_BASE.get(topic, KNOWLEDGE_BASE["payments"])}
    if name == "transfer_to_operator":
        return {"handoff": True}
    if name in {"send_sms", "request_document", "create_callback", "create_complaint", "report_fraud"}:
        return {"done": True}
    return {"done": True}


def _answer(action_name: str, output: dict[str, Any], language: str) -> str:
    if "error" in output:
        return output["error"]
    if action_name == "update_contact":
        if language == "kk":
            return f"Деректер жаңартылды: {output['contact_field']} — {output['new_value']}."
        return f"Контактные данные обновлены: {output['contact_field']} — {output['new_value']}."
    if action_name == "check_payment":
        payment = output.get("payment", {})
        amount = _format_number(payment.get("amount", 0))
        if language == "kk":
            return f"Төлем тексерілді: {amount} теңге, мәртебесі — {payment.get('status', 'белгісіз')}."
        return f"Платёж проверен: {amount} тенге, статус — {payment.get('status', 'неизвестен')}."
    if action_name == "resend_documents":
        return f"Документы отправлены на {output.get('sent_to')}." if language == "ru" else f"Құжаттар {output.get('sent_to')} мекенжайына жіберілді."
    if action_name == "get_offices" and output.get("office"):
        office = output["office"]
        return f"Офис: {office['address']}, часы работы: {office['hours']}." if language == "ru" else f"Кеңсе: {office['address']}, жұмыс уақыты: {office['hours']}."
    if action_name == "kb_lookup":
        return json.dumps(output.get("answer"), ensure_ascii=False)
    if output.get("handoff"):
        return "Передаю вопрос оператору." if language == "ru" else "Сұрағыңызды операторға жіберемін."
    return "Готово." if language == "ru" else "Дайын."


def _pending_prompt(topic: str, language: str) -> str:
    labels = {"SC30": ("проверке списания", "төлемді тексеруге"), "SC29": ("контактным данным", "байланыс деректеріне"), "SC26": ("повторной отправке полиса", "полисті қайта жіберуге")}
    ru, kk = labels.get(topic, ("отложенной теме", "кейінге қалдырылған тақырыпқа"))
    return f"Вернёмся к {kk}?" if language == "kk" else f"Вернёмся к {ru}?"


def _topic_opening(topic: str, language: str) -> str:
    if topic == "SC30":
        return "Переходим к проверке списания. Назовите дату платежа." if language == "ru" else "Төлемді тексеруге көшейік. Төлем күнін айтыңызшы."
    if topic == "SC26":
        return "Переходим к повторной отправке полиса. Назовите номер полиса." if language == "ru" else "Полисті қайта жіберуге көшейік. Полис нөмірін айтыңызшы."
    return "Переходим к отложенной теме. Уточните, пожалуйста, детали." if language == "ru" else "Кейінге қалдырылған тақырыпқа көшейік. Толығырақ айтыңызшы."


def execute_turn(route_result: dict[str, Any], utterance: str, session: dict[str, Any]) -> dict[str, Any]:
    """Execute one routed turn and update the mutable session state."""
    language = _language(utterance, session)
    params = dict(session.get("params") or {})
    params.update(_extract_params(utterance))
    params.update(route_result.get("params") or {})
    session["params"] = params

    if route_result.get("action") == "handoff":
        return {
            "action": "handoff",
            "answer_text": route_result.get("answer_text") or "Передаю вас оператору.",
            "handoff_context": {"history": session.get("history", []), "route": dict(route_result)},
            "pending_topics": session.get("pending_topics", []),
        }

    slot_only_continuation = bool(_extract_params(utterance).get("phone")) and bool(session.get("current_scenario"))

    if session.get("pending_return") and _is_yes(utterance):
        topic = session.pop("pending_return")
        session["current_scenario"] = topic
        session["pending_topics"] = session.get("pending_topics", [])[1:]
        session["clarification_count"] = 0
        return {"scenario_id": topic, "action": "clarify", "answer_text": _topic_opening(topic, language), "pending_topics": session["pending_topics"]}

    pending = session.get("pending_action")
    if pending:
        if _is_no(utterance):
            session.pop("pending_action")
            return {"action": "answer", "answer_text": "Хорошо, действие отменено." if language == "ru" else "Жақсы, әрекет тоқтатылды.", "pending_topics": session.get("pending_topics", [])}
        if not _is_yes(utterance):
            return {"action": "confirm", "answer_text": pending["question"], "pending_topics": session.get("pending_topics", [])}
        output = _execute_action(pending["action"], pending["params"], session)
        session.pop("pending_action")
        answer = _answer(pending["action"], output, language)
        session["clarification_count"] = 0
        topics = session.get("pending_topics", [])
        if topics:
            topic = _topic_id(topics[0])
            if topic:
                session["pending_return"] = topic
                answer += " " + _pending_prompt(topic, language)
        return {"action": "answer", "answer_text": answer, "pending_topics": topics}

    if (route_result.get("confidence", 0.0) < 0.6 or route_result.get("action") == "clarify") and not slot_only_continuation:
        session["clarification_count"] = session.get("clarification_count", 0) + 1
        if session["clarification_count"] >= 2:
            return {"action": "handoff", "answer_text": "Не удалось уточнить вопрос. Передаю вас оператору.", "handoff_context": {"history": session.get("history", []), "last_route": dict(route_result)}, "pending_topics": session.get("pending_topics", [])}
        return {"action": "clarify", "answer_text": route_result.get("answer_text") or "Уточните, пожалуйста, ваш вопрос.", "pending_topics": session.get("pending_topics", [])}

    session["clarification_count"] = 0
    client = _find_client(params, session)
    if client:
        params.setdefault("client_id", client["client_id"])
    scenario_id = session.get("current_scenario") if slot_only_continuation else route_result.get("scenario_id")
    session["current_scenario"] = scenario_id
    session["pending_topics"] = route_result.get("pending_topics") or session.get("pending_topics", [])
    scenario = SCENARIO_BY_ID.get(scenario_id)
    if not scenario:
        return {"action": "clarify", "answer_text": "Уточните, пожалуйста, ваш запрос.", "pending_topics": session.get("pending_topics", [])}

    for action_name in scenario.get("actions", []):
        if action_name not in ACTION_BY_NAME:
            continue
        if action_name == "find_client" and not client:
            missing = _required_missing(action_name, params, session)
            if missing:
                session["clarification_count"] = session.get("clarification_count", 0) + 1
                return {"action": "clarify", "answer_text": _question(missing, language), "pending_topics": session.get("pending_topics", [])}
            output = _execute_action(action_name, params, session)
            client = output.get("client")
            if not client:
                return {"action": "clarify", "answer_text": output.get("error", "Клиент не найден."), "pending_topics": session.get("pending_topics", [])}
            params["client_id"] = client["client_id"]
            continue

        missing = _required_missing(action_name, params, session)
        if missing:
            session["clarification_count"] = session.get("clarification_count", 0) + 1
            if session["clarification_count"] >= 2:
                return {"action": "handoff", "answer_text": "Не хватает данных для выполнения операции. Передаю вас оператору.", "handoff_context": {"missing": missing, "scenario_id": scenario_id}, "pending_topics": session.get("pending_topics", [])}
            return {"action": "clarify", "answer_text": _question(missing, language), "pending_topics": session.get("pending_topics", [])}

        if action_name in IRREVERSIBLE_ACTIONS:
            question = "Подтвердите, пожалуйста, изменение данных: да или нет." if language == "ru" else "Деректерді өзгертуді растаңызшы: иә немесе жоқ."
            session["pending_action"] = {"action": action_name, "params": params.copy(), "question": question}
            return {"action": "confirm", "answer_text": question, "pending_topics": session.get("pending_topics", [])}

        output = _execute_action(action_name, params, session)
        if "error" in output:
            return {"action": "clarify", "answer_text": output["error"], "pending_topics": session.get("pending_topics", [])}
        if output.get("handoff"):
            return {"action": "handoff", "answer_text": _answer(action_name, output, language), "handoff_context": {"scenario_id": scenario_id}, "pending_topics": session.get("pending_topics", [])}

    session["pending_topics"] = route_result.get("pending_topics") or session.get("pending_topics", [])
    return {"action": "answer", "answer_text": _answer(scenario.get("actions", [""])[-1], output if 'output' in locals() else {}, language), "pending_topics": session["pending_topics"]}
