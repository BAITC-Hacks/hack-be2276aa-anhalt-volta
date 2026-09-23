"""Insurance Voice Router adapter used by the Streamlit interface."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field
from config import OPENAI_API_KEY, OPENAI_MODEL

ROOT = Path(__file__).resolve().parents[1]
ROUTER_DIR = ROOT / "router"
DATASET_DIR = ROOT / "voice_router_dataset"
sys.path.insert(0, str(ROUTER_DIR))

from router import route_dialogue  # noqa: E402


def _load_titles() -> dict[str, str]:
    titles = {"SYS_UNCLEAR": "Уточнение запроса", "SYS_OUT_OF_SCOPE": "Вне области страхования"}
    path = DATASET_DIR / "scenarios.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        titles.update({item["scenario_id"]: item["name"] for item in data["scenarios"]})
    return titles


EN_TITLES = _load_titles()
EN_TITLES.update(SYS_UNCLEAR="Clarify request", SYS_OUT_OF_SCOPE="Outside supported services", SYS_GOODBYE="Goodbye")
TITLES = dict(EN_TITLES)
TITLES.update(SYS_UNCLEAR="Уточнение запроса", SYS_OUT_OF_SCOPE="Вне области страхования", SYS_GOODBYE="Завершение диалога")
# The source catalog keeps English machine-readable names. The UI uses this
# Russian label map so the supervisor panel is readable for the demo audience.
TITLES.update({
    "SC01": "Расчёт стоимости ОГПО",
    "SC02": "Оформление ОГПО",
    "SC03": "Консультация и расчёт КАСКО",
    "SC04": "Добавление водителя в полис",
    "SC05": "Изменение автомобиля или номера",
    "SC06": "Покупка туристической страховки",
    "SC07": "Страхование квартиры или дома",
    "SC08": "Страхование от несчастного случая",
    "SC09": "Индивидуальное медицинское страхование",
    "SC10": "Корпоративное страхование",
    "SC11": "ДТП произошло сейчас",
    "SC12": "Обращение потерпевшего по ОГПО",
    "SC13": "Ущерб автомобилю по КАСКО",
    "SC14": "Ущерб квартире или дому",
    "SC15": "Медицинская помощь за границей",
    "SC16": "Страховой случай по несчастному случаю",
    "SC17": "Статус страховой выплаты",
    "SC18": "Документы по страховому случаю",
    "SC19": "Несогласие с решением по выплате",
    "SC20": "Осмотр автомобиля",
    "SC21": "Запись к врачу по ДМС",
    "SC22": "Проверка покрытия по ДМС",
    "SC23": "Список партнёрских клиник",
    "SC24": "Электронная страховая карта",
    "SC25": "Срок действия полиса",
    "SC26": "Повторная отправка документов",
    "SC27": "Продление полиса",
    "SC28": "Расторжение полиса и возврат",
    "SC29": "Изменение контактных данных",
    "SC30": "Деньги списаны, полис не оформлен",
    "SC31": "Способы оплаты и рассрочка",
    "SC32": "Бонус-малус и изменение цены",
    "SC33": "Адреса и часы работы офисов",
    "SC34": "Помощь с приложением и личным кабинетом",
    "SC35": "Жалоба на обслуживание",
    "SC36": "Обратный звонок",
    "SC37": "Соединение с оператором",
    "SC38": "Сообщение о мошенничестве",
    "SC39": "Справка или копия документа",
    "SC40": "Объяснение условий полиса",
})
TITLES_KK = {
    "SYS_UNCLEAR": "Сұрауды нақтылау", "SYS_OUT_OF_SCOPE": "Қызмет аясынан тыс", "SYS_GOODBYE": "Диалогты аяқтау",
    "SC01": "ОГПО құнын есептеу", "SC02": "ОГПО рәсімдеу",
    "SC03": "КАСКО бойынша кеңес және есептеу", "SC04": "Полиске жүргізуші қосу",
    "SC05": "Көлікті немесе нөмірді өзгерту", "SC06": "Саяхат сақтандыруын сатып алу",
    "SC07": "Пәтерді немесе үйді сақтандыру", "SC08": "Жазатайым оқиғадан сақтандыру",
    "SC09": "Жеке медициналық сақтандыру", "SC10": "Корпоративтік сақтандыру",
    "SC11": "Жол-көлік оқиғасы қазір болды", "SC12": "ОГПО бойынша зардап шегушінің өтініші",
    "SC13": "КАСКО бойынша көлікке келген залал", "SC14": "Пәтерге немесе үйге келген залал",
    "SC15": "Шетелдегі медициналық көмек", "SC16": "Жазатайым оқиға бойынша сақтандыру жағдайы",
    "SC17": "Сақтандыру төлемінің мәртебесі", "SC18": "Сақтандыру жағдайы бойынша құжаттар",
    "SC19": "Төлем шешімімен келіспеу", "SC20": "Көлікті тексеру",
    "SC21": "ДМС бойынша дәрігерге жазылу", "SC22": "ДМС бойынша өтімділікті тексеру",
    "SC23": "Серіктес емханалар тізімі", "SC24": "Электрондық сақтандыру картасы",
    "SC25": "Полистің жарамдылық мерзімі", "SC26": "Құжаттарды қайта жіберу",
    "SC27": "Полисті ұзарту", "SC28": "Полисті бұзу және ақшаны қайтару",
    "SC29": "Байланыс деректерін өзгерту", "SC30": "Ақша алынды, полис рәсімделмеді",
    "SC31": "Төлем тәсілдері және бөліп төлеу", "SC32": "Бонус-малус және бағаның өзгеруі",
    "SC33": "Кеңселердің мекенжайы мен жұмыс уақыты", "SC34": "Қосымша мен жеке кабинет бойынша көмек",
    "SC35": "Қызмет көрсетуге шағым", "SC36": "Кері қоңырау",
    "SC37": "Операторға қосылу", "SC38": "Алаяқтық туралы хабарлама",
    "SC39": "Анықтама немесе құжат көшірмесі", "SC40": "Полис шарттарын түсіндіру",
}


def localized_title(scenario_id: str, language: str) -> str:
    ru = TITLES.get(scenario_id, scenario_id)
    kk = TITLES_KK.get(scenario_id, ru)
    en = EN_TITLES.get(scenario_id, scenario_id)
    if language == "en":
        return en
    if language == "kk":
        return kk
    if language == "mixed":
        return f"{ru} / {kk}"
    return ru


FOLLOWUP_RU = {
    "SC01": "Для расчёта ОГПО уточните город регистрации, тип автомобиля и ИИН водителей.",
    "SC02": "Для оформления ОГПО нужны город регистрации, данные автомобиля и данные водителя. Подготовьте их, пожалуйста.",
    "SC03": "Для расчёта КАСКО уточните марку, модель, год выпуска и желаемую франшизу.",
    "SC04": "Чтобы добавить водителя, нужны его ИИН и данные действующего полиса.",
    "SC05": "Для изменения автомобиля или номера назовите номер полиса и новые данные машины.",
    "SC06": "Для туристической страховки уточните страну, даты поездки и количество путешественников.",
    "SC07": "Для страхования жилья уточните город, тип объекта и риски: пожар, затопление или повреждение имущества?",
    "SC08": "Для страховки от несчастного случая уточните возраст, вид занятий и желаемую сумму покрытия.",
    "SC09": "Для расчёта индивидуального ДМС уточните возраст, город и нужные медицинские услуги.",
    "SC10": "Для корпоративного страхования уточните количество сотрудников, вид страхования и контакт компании.",
    "SC11": "Если ДТП произошло сейчас, сначала убедитесь в безопасности. Уточните город и есть ли пострадавшие.",
    "SC12": "Для обращения как потерпевшего назовите дату ДТП, госномер виновника и ваши контактные данные.",
    "SC13": "Для заявления по КАСКО уточните дату, место и обстоятельства повреждения автомобиля.",
    "SC14": "Для заявления по ущербу жилью уточните дату, причину повреждения и адрес объекта.",
    "SC15": "Если вы за границей, назовите страну, город и опишите медицинскую ситуацию. Помощь доступна круглосуточно.",
    "SC16": "Для заявления по несчастному случаю уточните дату происшествия и характер травмы.",
    "SC17": "Для проверки статуса выплаты назовите номер заявления, полиса или телефон клиента.",
    "SC18": "Уточните, по какому страховому случаю нужны документы. Я подскажу список и способ отправки.",
    "SC19": "Опишите, с каким решением или суммой выплаты вы не согласны. Подготовим обращение на пересмотр.",
    "SC20": "Для записи на осмотр назовите город и удобную дату.",
    "SC21": "Для записи к врачу уточните специальность, город и удобное время.",
    "SC22": "Назовите медицинскую услугу или лекарство, которое нужно проверить по покрытию ДМС.",
    "SC23": "Назовите город, чтобы я показал доступные партнёрские клиники.",
    "SC24": "Электронная страховая карта доступна в приложении. Назовите телефон клиента, если она не отображается.",
    "SC25": "Для проверки срока действия назовите номер полиса или телефон клиента.",
    "SC26": "Назовите телефон или email, на который нужно повторно отправить документы.",
    "SC27": "Для продления назовите номер полиса и подтвердите, что хотите продлить его на следующий период.",
    "SC28": "Для расторжения назовите номер полиса и причину расторжения. Возврат рассчитаем по условиям договора.",
    "SC29": "Уточните, какие контактные данные нужно изменить: телефон, email или адрес.",
    "SC30": "Назовите дату и сумму списания, а также телефон, указанный при оплате.",
    "SC31": "Могу подсказать доступные способы оплаты и рассрочку. Какой способ вам удобнее?",
    "SC32": "Для проверки бонус-малус назовите ИИН или данные действующего полиса.",
    "SC33": "Назовите город, чтобы я показал адрес и часы работы ближайшего офиса.",
    "SC34": "Опишите ошибку в приложении или личном кабинете. Не передавайте пароль и SMS-код.",
    "SC35": "Опишите ситуацию, укажите дату обращения и удобный контакт для обратной связи.",
    "SC36": "Укажите номер телефона и удобное время для обратного звонка.",
    "SC37": "Соединю с оператором. Кратко передам ему контекст вашего обращения.",
    "SC38": "Не сообщайте коды из SMS и не переводите деньги. Опишите номер и содержание подозрительного звонка.",
    "SC39": "Уточните, какая справка нужна, на каком языке и для какой цели.",
    "SC40": "Назовите пункт или условие полиса, которое нужно объяснить.",
}


FOLLOWUP_KK = {
    "SC01": "ОГПО есептеу үшін тіркеу қаласын, көлік түрін және жүргізушілердің ЖСН-ін айтыңыз.",
    "SC02": "ОГПО рәсімдеу үшін көлік пен жүргізуші деректері қажет.",
    "SC03": "КАСКО есептеу үшін көліктің маркасын, моделін, жылын және франшизаны айтыңыз.",
    "SC04": "Жүргізушіні қосу үшін оның ЖСН-і мен полис деректері қажет.",
    "SC05": "Көлік немесе нөмірді өзгерту үшін полис нөмірі мен жаңа деректерді айтыңыз.",
    "SC06": "Саяхат сақтандыруы үшін елді, сапар күндерін және саяхатшылар санын айтыңыз.",
    "SC07": "Үйді сақтандыру үшін қалаңызды, нысан түрін және қандай тәуекелдерді жабу керегін айтыңыз.",
    "SC08": "Жазатайым оқиғадан сақтандыру үшін жасыңызды, қызмет түрін және сақтандыру сомасын айтыңыз.",
    "SC09": "Жеке ДМС үшін жасыңызды, қалаңызды және қажет медициналық қызметтерді айтыңыз.",
    "SC10": "Корпоративтік сақтандыру үшін қызметкерлер санын және сақтандыру түрін айтыңыз.",
    "SC11": "Қауіпсіздікке көз жеткізіңіз. Қаланы және зардап шеккендер бар-жоғын айтыңыз.",
    "SC12": "Оқиға күнін, кінәлі көліктің нөмірін және байланыс деректеріңізді айтыңыз.",
    "SC13": "КАСКО өтініші үшін зақымның күнін, орнын және жағдайын сипаттаңыз.",
    "SC14": "Мүлік залалы үшін мекенжайды, күнін және залал себебін айтыңыз.",
    "SC15": "Шетелде болсаңыз, елді, қаланы және медициналық жағдайды сипаттаңыз.",
    "SC16": "Оқиға күнін және жарақат түрін айтыңыз.",
    "SC17": "Төлем мәртебесін тексеру үшін өтініш немесе полис нөмірін айтыңыз.",
    "SC18": "Қай сақтандыру жағдайына құжат керек екенін айтыңыз.",
    "SC19": "Қай шешіммен немесе төлем сомасымен келіспейтініңізді сипаттаңыз.",
    "SC20": "Тексеру үшін қаланы және ыңғайлы күнді айтыңыз.",
    "SC21": "Мамандықты, қаланы және ыңғайлы уақытты айтыңыз.",
    "SC22": "Қандай медициналық қызметті тексеру керегін айтыңыз.",
    "SC23": "Қаланы айтыңыз, серіктес емханаларды көрсетемін.",
    "SC24": "Карта көрінбесе, клиенттің телефон нөмірін айтыңыз.",
    "SC25": "Полис нөмірін немесе телефон нөмірін айтыңыз.",
    "SC26": "Құжаттарды жіберетін телефонды немесе email-ды айтыңыз.",
    "SC27": "Ұзартқыңыз келетін полис нөмірін айтыңыз.",
    "SC28": "Полис нөмірін және бұзу себебін айтыңыз.",
    "SC29": "Телефон, email немесе мекенжайдың қайсысын өзгерту керегін айтыңыз.",
    "SC30": "Ақша алынған күнін, сомасын және телефон нөмірін айтыңыз.",
    "SC31": "Сізге ыңғайлы төлем тәсілін айтыңыз.",
    "SC32": "Бонус-малусты тексеру үшін ЖСН немесе полис деректерін айтыңыз.",
    "SC33": "Қаланы айтыңыз, жақын кеңсенің мекенжайы мен уақытын көрсетемін.",
    "SC34": "Қосымшадағы қатені сипаттаңыз. Құпия сөз бен SMS кодын айтпаңыз.",
    "SC35": "Жағдайды, өтініш күнін және байланыс нөмірін айтыңыз.",
    "SC36": "Телефон нөмірін және қоңырауға ыңғайлы уақытты айтыңыз.",
    "SC37": "Операторға қосамын және өтініш контекстін беремін.",
    "SC38": "SMS кодтарын айтпаңыз және ақша аудармаңыз. Қоңырау жағдайын сипаттаңыз.",
    "SC39": "Қандай анықтама және қай тілде керек екенін айтыңыз.",
    "SC40": "Полистің қай тармағын түсіндіру керегін айтыңыз.",
}
MODEL_NAME = "local-context-router"
GEMINI_API_KEY = ""


class Decision(BaseModel):
    scenario_id: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=2000)
    alternatives: list[str] = Field(default_factory=list, max_length=5)
    reply: str = Field(min_length=1, max_length=2000)
    language: str = "ru"
    pending_topics: list[str] = Field(default_factory=list)


def _reply(result: dict[str, Any], utterance: str) -> str:
    scenario = result["scenario_id"]
    lang = result.get("reply_language", "ru")
    title = localized_title(scenario, lang)
    queued = result.get("queued_scenarios", [])
    normalized = utterance.strip().lower()
    if lang == "en":
        if re.fullmatch(r"(hello|hi|hey|good morning|good afternoon|good evening)\s*[!.]?", normalized):
            return "Hello! I can help you buy insurance, check a policy, or report an insurance claim. What do you need?"
        if scenario == "SYS_UNCLEAR":
            return "Please clarify what you want to do: buy insurance, check an existing policy, or report an insurance claim?"
        if scenario == "SYS_OUT_OF_SCOPE":
            return "This request is outside the insurance services we provide."
        text = f'Selected scenario: "{title}". Please provide the details needed to continue.'
        if queued:
            text += " The next request has been saved."
        return text
    if re.fullmatch(r"(алло|здравствуйте|добрый день|добрый вечер|доброе утро|сәлеметсіз бе|сәлем|салам)(\s+бро)?\s*[!.]?", normalized):
        return "Здравствуйте! Я помогу оформить страховку, проверить полис или разобраться со страховым случаем. Что нужно сделать?"
    if scenario == "SYS_UNCLEAR" and re.search(r"^оформить[!. ]*$|^купить[!. ]*$|^сақтандыру керек", normalized):
        return "Какую страховку вы хотите оформить: ОГПО, КАСКО, туристическую, медицинскую или страхование имущества?"
    if scenario == "SYS_UNCLEAR" and re.fullmatch(r"проверить\s*[!.]?", normalized):
        return "Что проверить: срок действия полиса, статус страховой выплаты или факт оплаты?"
    if scenario == "SYS_UNCLEAR":
        return "Подскажите, пожалуйста, что нужно сделать со страховкой: оформить, проверить действующий полис или сообщить о страховом случае?"
    if scenario == "SYS_OUT_OF_SCOPE" and re.search(r"жизн|өмір|life|роскошн", normalized):
        return "Страхование жизни не входит в услуги Saqta Insurance. Мы предлагаем ОГПО, КАСКО, туристическое, медицинское и имущественное страхование."
    if scenario == "SYS_OUT_OF_SCOPE":
        return "Этот запрос не относится к услугам страховой компании."
    if scenario == "SC07":
        if lang == "kk":
            return "Үйді сақтандыру үшін қалаңызды, нысан түрін (пәтер немесе үй) және қандай тәуекелдерді жабу керегін айтыңыз: өрт, су басу немесе мүлік зақымы?"
        if lang == "mixed":
            return "Для страхования жилья уточним город и тип объекта. Қандай тәуекелдерді жабу керек: пожар, су басу или повреждение имущества?"
        return "Для страхования жилья уточните город, тип объекта (квартира или дом) и риски: пожар, затопление или повреждение имущества?"
    if lang == "kk":
        text = f"Сценарий таңдалды: «{title}». Қажетті деректерді нақтылаймын."
    else:
        text = f"Выбран сценарий «{title}». Уточню необходимые данные."
    if queued:
        names = ", ".join(localized_title(item, lang) for item in queued)
        text += f" Следующая задача сохранена: {names}."
    return text


def _openai_route(text, history, state=None, on_decision=None):
    from llm_routing import route_openai
    return route_openai(text, history, state, OPENAI_API_KEY, OPENAI_MODEL, on_decision=on_decision)


def route(text: str, history: list[dict] | None = None, mode: str = "demo",
          state: dict | None = None, on_decision=None) -> dict[str, Any]:
    """State is session-owned; callers should persist returned dialogue_state."""
    from copy import deepcopy
    from llm_routing import clean_history
    text = text.strip()
    if not text or len(text) > 4000:
        raise ValueError("Введите от 1 до 4000 символов.")
    if mode not in ("demo", "openai", "live"):
        raise ValueError("Неизвестный режим")
    mode = "openai" if mode == "live" else mode
    history = clean_history(history)
    state = deepcopy(state or {})
    current = state.get("current_scenario")
    current = current if current in TITLES and current.startswith("SC") else None
    started = perf_counter()
    fallback = False
    fallback_reason = ""
    if mode == "openai":
        try:
            result = _openai_route(text, history, state, on_decision=on_decision)
        except Exception as exc:
            # Model formatting failures are visible, not presented as LLM decisions.
            fallback = True
            fallback_reason = type(exc).__name__
            result = route_dialogue(text, history, current)
    else:
        result = route_dialogue(text, history, current)
    next_state = result.get("dialogue_state")
    if next_state is None:
        # Preserve known facts even when the provider is temporarily unavailable.
        next_state = deepcopy(state)
        next_state["current_scenario"] = result["scenario_id"]
        next_state["pending_topics"] = list(dict.fromkeys(
            state.get("pending_topics", []) + result.get("queued_scenarios", [])
        ))
    output = Decision(
        scenario_id=result["scenario_id"],
        confidence=result.get("confidence"),
        explanation=result.get("reason", ""),
        alternatives=result.get("alternatives", []),
        reply=(result.get("reply_text") or _reply(result, text)),
        language=result.get("reply_language", "ru"),
        pending_topics=next_state.get("pending_topics", []),
    ).model_dump()
    response_ms = round((perf_counter() - started) * 1000, 1)
    output.update(
        mode="router-fallback" if fallback else ("openai" if mode == "openai" else "router"),
        model=OPENAI_MODEL if mode == "openai" and not fallback else MODEL_NAME,
        fallback=fallback, fallback_reason=fallback_reason,
        dialogue_state=next_state, api_attempts=result.get("api_attempts", 1 if mode == "openai" else 0),
        api_ms=result.get("api_ms"), tokens=result.get("tokens"),
        validation_notes=result.get("validation_notes", []),
        routing_ms=result.get("decision_ms") or response_ms,
        response_ms=response_ms,
        input=text,
        scenario_title=localized_title(output["scenario_id"], output["language"]),
        alternative_titles=[localized_title(item, output["language"]) for item in output["alternatives"]],
        pending_topic_titles=[localized_title(item, output["language"]) for item in output["pending_topics"]],
    )
    return output


def transcribe(audio: bytes) -> str:
    raise ValueError("Для голосового ввода подключите STT. Пока используйте текстовый канал.")


def run_agent(user_prompt: str) -> str:
    return route(user_prompt)["reply"]
