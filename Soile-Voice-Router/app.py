"""Streamlit UI for the FastAPI voice router."""
import base64
import json
import os
from time import perf_counter
from pathlib import Path
from uuid import uuid4

import requests
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")

from agent import route as local_route, transcribe

st.set_page_config(page_title="Sөile • Voice Router", page_icon="🎙️", layout="wide")

SYSTEM_TITLES = {
    "SYS_UNCLEAR": "Нужно уточнение",
    "SYS_OUT_OF_SCOPE": "Вне тематики",
    "SYS_GOODBYE": "Прощание",
}
SCENARIO_TITLES_RU = {
    "SC01": "Цена ОГПО", "SC02": "Оформление ОГПО", "SC03": "Консультация по КАСКО",
    "SC04": "Добавление водителя", "SC05": "Изменение автомобиля или номера",
    "SC06": "Страховка для поездки", "SC07": "Страхование жилья", "SC08": "Страхование от несчастного случая",
    "SC09": "Индивидуальная медицинская страховка", "SC10": "Корпоративное страхование",
    "SC11": "Срочное ДТП", "SC12": "Ущерб по ОГПО виновника", "SC13": "Ущерб по КАСКО",
    "SC14": "Ущерб имуществу", "SC15": "Медицинская помощь за границей", "SC16": "Травма и выплата",
    "SC17": "Статус выплаты", "SC18": "Документы по страховому случаю", "SC19": "Спор по решению о выплате",
    "SC20": "Осмотр автомобиля", "SC21": "Запись к врачу", "SC22": "Покрытие ДМС",
    "SC23": "Партнёрские клиники", "SC24": "Электронная страховая карта", "SC25": "Срок действия полиса",
    "SC26": "Повторная отправка полиса", "SC27": "Продление полиса", "SC28": "Расторжение и возврат",
    "SC29": "Изменение контактных данных", "SC30": "Деньги списали, полиса нет", "SC31": "Способы оплаты",
    "SC32": "Бонус-малус и изменение цены", "SC33": "Офис и часы работы", "SC34": "Приложение и личный кабинет",
    "SC35": "Жалоба на обслуживание", "SC36": "Обратный звонок", "SC37": "Оператор",
    "SC38": "Подозрительный звонок или мошенничество", "SC39": "Справка или копия документа",
    "SC40": "Условия полиса",
}
ACTION_LABELS = {
    "answer": ("Ответ", "✅", "success"), "clarify": ("Уточнение", "❓", "warning"),
    "confirm": ("Нужно подтверждение", "🔐", "warning"), "handoff": ("Передача оператору", "☎️", "error"),
}
MODE_LABELS = {
    "llm": "LLM", "fast_path": "Быстрый путь (правила)",
    "rules_fallback": "Резерв: LLM недоступна",
}


@st.cache_data
def scenario_names():
    try:
        data = json.loads((ROOT / "voice_router_dataset" / "scenarios.json").read_text(encoding="utf-8"))
        return {item["scenario_id"]: item.get("name", item["scenario_id"]) for item in data.get("scenarios", [])}
    except (OSError, json.JSONDecodeError):
        return {}


def scenario_title(scenario_id):
    return SYSTEM_TITLES.get(scenario_id) or SCENARIO_TITLES_RU.get(scenario_id) or scenario_names().get(scenario_id, "Неизвестный сценарий")


def confidence_value(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def reset_state():
    st.session_state.messages = []
    st.session_state.traces = []
    st.session_state.session_id = None
    st.session_state.audio_key = st.session_state.get("audio_key", 0) + 1
    st.session_state.last_audio = None


def create_session():
    try:
        response = requests.post(f"{API_URL}/session", timeout=5)
        response.raise_for_status()
        st.session_state.session_id = response.json()["session_id"]
        return True
    except requests.RequestException as exc:
        st.error(f"Backend недоступен: {exc}")
        return False


def ensure_session():
    if not st.session_state.get("session_id"):
        create_session()


def browser_fallback(text, language="ru"):
    lang = "kk-KZ" if language in ("kk", "kz", "kazakh") else "ru-RU"
    st.html(
        f"<script>const u=new SpeechSynthesisUtterance({json.dumps(text, ensure_ascii=False)});"
        f"u.lang={json.dumps(lang)};speechSynthesis.cancel();speechSynthesis.speak(u);</script>",
        unsafe_allow_javascript=True,
    )


def play_tts(text, language="ru"):
    if not text:
        return None
    try:
        response = requests.post(f"{API_URL}/tts", json={"text": text}, timeout=20)
        response.raise_for_status()
        encoded = base64.b64encode(response.content).decode("ascii")
        audio_id = uuid4().hex
        payload = json.dumps(text, ensure_ascii=False)
        lang = "kk-KZ" if language in ("kk", "kz", "kazakh") else "ru-RU"
        st.html(
            f"""<audio id="a-{audio_id}" controls autoplay style="width:100%"
                src="data:audio/mpeg;base64,{encoded}"></audio>
                <script>
                const audio=document.getElementById('a-{audio_id}');
                audio.onerror=()=>{{const u=new SpeechSynthesisUtterance({payload});
                u.lang={json.dumps(lang)};speechSynthesis.speak(u);}};
                audio.play().catch(()=>{{}});
                </script>""",
            unsafe_allow_javascript=True,
        )
        return float(response.headers.get("tts_ms", 0) or 0)
    except (requests.RequestException, ValueError):
        browser_fallback(text, language)
        return None


def backend_turn(text):
    response = requests.post(
        f"{API_URL}/turn",
        json={"session_id": st.session_state.session_id, "text": text},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    return {
        **result,
        "reply": result.get("answer_text", ""),
        "explanation": result.get("reasoning", ""),
        "routing_ms": (result.get("timings_ms") or {}).get("llm_ms", 0),
        "language": result.get("language", "ru"),
        "mode": result.get("router_mode", "llm"),
    }


def submit(text, mode="openai", stt_ms=None):
    if not st.session_state.get("session_id") and not create_session():
        return
    try:
        with st.spinner("Обрабатываем обращение…"):
            if mode == "local":
                result = local_route(text, st.session_state.messages, "demo")
            else:
                result = backend_turn(text)
        tts_ms = play_tts(result.get("reply", ""), result.get("language", "ru"))
        timings = dict(result.get("timings_ms") or {})
        timings["stt_ms"] = stt_ms
        timings["tts_ms"] = tts_ms
        result.update(input=text, stt_ms=stt_ms, tts_ms=tts_ms, timings_ms=timings)
        st.session_state.messages.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": result.get("reply", "")},
        ])
        st.session_state.messages = st.session_state.messages[-40:]
        st.session_state.traces.append(result)
        st.session_state.traces = st.session_state.traces[-20:]
    except requests.RequestException as exc:
        st.error(f"Backend не обработал запрос: {exc}")
    except Exception as exc:
        st.error(f"Не удалось обработать запрос: {exc}")


if "messages" not in st.session_state:
    reset_state()
ensure_session()

st.caption("HACKATHON PROTOTYPE  /  RU + KK")
st.title("Sөile • Voice Router")
st.caption(f"API: {API_URL} · Сессия: {st.session_state.get('session_id') or 'не создана'}")

mode_label = st.segmented_control("Режим маршрутизации", ["OpenAI · backend", "Локальный роутер · fallback"], default="OpenAI · backend")
mode = "local" if mode_label.startswith("Локальный") else "openai"
if mode == "local":
    st.warning("Включён локальный резервный роутер. Для рабочего режима выберите OpenAI · backend.")
else:
    st.caption("По умолчанию запросы идут в FastAPI и далее в OpenAI-роутер.")

left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Чат клиента")
    input_col, mic_col, send_col = st.columns([5, 2.4, 1.2], vertical_alignment="bottom")
    with input_col:
        prompt = st.text_input("Ваш вопрос", placeholder="Напишите сообщение…", max_chars=4000)
    with mic_col:
        audio = st.audio_input("Нажмите и говорите (RU / KZ)", key=f"audio_{st.session_state.audio_key}")
    with send_col:
        send_text = st.button("Отправить", disabled=not prompt.strip())
    if send_text:
        submit(prompt.strip(), mode)
        st.rerun()
    if audio is not None and st.button("Распознать запись"):
        try:
            with st.spinner("Распознаём речь…"):
                started = perf_counter()
                text = transcribe(audio.getvalue())
            submit(text, mode, round((perf_counter() - started) * 1000, 1))
            st.session_state.audio_key += 1
            st.rerun()
        except Exception as exc:
            st.error(f"Не удалось распознать запись: {exc}. Переключитесь на текст.")
    with st.container(height=420, border=True):
        if not st.session_state.messages:
            st.markdown(
                "### Сәлеметсіз бе! Здравствуйте!\n\n"
                "Я голосовой помощник Saqta Insurance. Спросите про полис, выплату или ДТП — голосом или текстом."
            )
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

    if st.button("Новый диалог"):
        reset_state()
        create_session()
        st.rerun()

with right:
    st.subheader("Панель супервизора")
    if not st.session_state.traces:
        st.info("Ожидаем первое обращение")
    else:
        result = st.session_state.traces[-1]
        scenario_id = result.get("scenario_id", "—")
        st.caption("ВЫБРАННЫЙ СЦЕНАРИЙ")
        st.markdown(f"## {scenario_title(scenario_id)}")
        st.caption(scenario_id)

        confidence = confidence_value(result.get("confidence"))
        st.write("**Уверенность**")
        st.progress(confidence or 0.0, text="—" if confidence is None else f"{confidence:.0%}")
        if confidence is not None and confidence < 0.6:
            st.warning("Робот не уверен — задаёт уточняющий вопрос")

        st.write(f"**Путь решения:** {MODE_LABELS.get(result.get('router_mode', result.get('mode')), 'Неизвестный')}")
        action = result.get("action", "answer")
        action_title, action_icon, action_kind = ACTION_LABELS.get(action, (action, "•", "info"))
        if action_kind == "error":
            st.error(f"{action_icon} {action_title}")
        elif action_kind == "warning":
            st.warning(f"{action_icon} {action_title}")
        else:
            st.success(f"{action_icon} {action_title}")
        st.write(f"**Обоснование:** {result.get('explanation', result.get('reasoning', '—'))}")

        alternatives = result.get("alternatives") or []
        if alternatives:
            st.write("**Альтернативы**")
            for alternative in alternatives:
                if isinstance(alternative, dict):
                    alt_id = alternative.get("id", alternative.get("scenario_id", "—"))
                    alt_confidence = confidence_value(alternative.get("confidence"))
                    suffix = "—" if alt_confidence is None else f"{alt_confidence:.0%}"
                else:
                    alt_id, suffix = alternative, "—"
                st.markdown(f"- {scenario_title(alt_id)} `{alt_id}` — {suffix}")
        st.write(f"**Отложенные темы:** {', '.join(scenario_title(item) for item in (result.get('pending_topics') or [])) or 'нет'}")
        timings = result.get("timings_ms") or {}
        routing_ms = timings.get("routing", timings.get("llm_ms"))
        timing_rows = [
            ("STT", timings.get("stt_ms")), ("Маршрутизация", routing_ms),
            ("Исполнение", timings.get("executor_ms")), ("TTS", timings.get("tts_ms")),
            ("Всего", timings.get("total")),
        ]
        st.write("**Тайминги**")
        st.table({"Этап": [name for name, _ in timing_rows], "Время": [
            "—" if value is None else f"{float(value):.1f} мс" for _, value in timing_rows
        ]})
        if routing_ms is not None and float(routing_ms) <= 500:
            st.success("Маршрутизация уложилась в 500 мс")
        elif routing_ms is not None:
            st.caption("Маршрутизация заняла больше 500 мс")
        st.json(result)
