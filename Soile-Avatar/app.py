"""Streamlit-клиент FastAPI voice router с аватаром."""
import base64
import json
import os
from pathlib import Path
from uuid import uuid4

import requests
import streamlit as st
from dotenv import load_dotenv

from avatar import render_avatar

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
SCENARIOS_PATH = ROOT / "voice_router_dataset" / "scenarios.json"
DIALOGS_PATH = ROOT / "voice_router_dataset" / "dialogs_sample.json"

st.set_page_config(page_title="Sөile • Voice Router", page_icon="🎙️", layout="wide")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


SCENARIO_NAMES = {
    item.get("scenario_id"): item.get("name", item.get("scenario_id"))
    for item in load_json(SCENARIOS_PATH, {}).get("scenarios", [])
    if item.get("scenario_id")
}


def build_examples():
    examples = []
    dialogs = load_json(DIALOGS_PATH, {}).get("dialogs", [])
    labels = {"ru": "Русский", "kazakh": "Қазақша", "mixed_language": "Смешанный", "topic_switch": "Смена темы"}
    for tag in labels:
        dialog = next((d for d in dialogs if tag in d.get("tags", [])), None)
        if dialog:
            client_turns = [t["text"] for t in dialog.get("turns", []) if t.get("role") == "client"]
            if client_turns:
                examples.append((labels[tag], client_turns[0]))
    return examples


EXAMPLES = build_examples()


def reset_state():
    for key, value in {
        "session_id": None, "messages": [], "traces": [], "avatar_audio": None,
        "avatar_reply_id": "", "avatar_reset": st.session_state.get("avatar_reset", 0) + 1,
        "pending_request": None, "last_error": None,
    }.items():
        st.session_state[key] = value


def create_session():
    try:
        response = requests.post(f"{API_URL}/session", timeout=5)
        response.raise_for_status()
        st.session_state.session_id = response.json()["session_id"]
        return True
    except requests.RequestException as exc:
        st.session_state.last_error = f"Не удалось создать сессию: {exc}"
        return False


def ensure_session():
    if not st.session_state.get("session_id"):
        create_session()


def browser_speech(text, language="ru"):
    lang = "kk-KZ" if language in ("kk", "kz", "kazakh") else "ru-RU"
    st.components.v1.html(
        f"<script>const u=new SpeechSynthesisUtterance({json.dumps(text, ensure_ascii=False)});"
        f"u.lang={json.dumps(lang)};window.speechSynthesis.cancel();window.speechSynthesis.speak(u);</script>",
        height=0,
    )


def set_avatar_audio(audio_bytes):
    if not audio_bytes:
        st.session_state.avatar_audio = None
        return
    encoded = base64.b64encode(audio_bytes).decode("ascii")
    st.session_state.avatar_audio = {
        "id": uuid4().hex, "src": f"data:audio/mpeg;base64,{encoded}",
        "cues": [], "mode": "amplitude",
    }


def speak_answer(answer, language="ru"):
    if not answer:
        return None
    try:
        response = requests.post(f"{API_URL}/tts", json={"text": answer}, timeout=15)
        response.raise_for_status()
        tts_ms = float(response.headers.get("tts_ms", response.headers.get("X-TTS-Ms", 0)) or 0)
        set_avatar_audio(response.content)
        return tts_ms
    except (requests.RequestException, ValueError) as exc:
        st.warning(f"Серверная озвучка недоступна, включён голос браузера: {exc}")
        browser_speech(answer, language)
        st.session_state.avatar_audio = None
        return None


def add_turn(result, transcript, tts_ms=None):
    result = dict(result)
    result["transcript"] = transcript
    timings = dict(result.get("timings_ms") or {})
    timings["tts_ms"] = tts_ms
    result["timings_ms"] = timings
    result["input"] = transcript
    st.session_state.messages.extend([
        {"role": "user", "content": transcript},
        {"role": "assistant", "content": result.get("answer_text", "")},
    ])
    st.session_state.messages = st.session_state.messages[-40:]
    st.session_state.traces.append(result)
    st.session_state.traces = st.session_state.traces[-20:]
    st.session_state.avatar_reply_id = uuid4().hex


def submit_text(text):
    if not st.session_state.session_id and not create_session():
        return
    try:
        with st.spinner("Обрабатываем обращение…"):
            response = requests.post(
                f"{API_URL}/turn", json={"session_id": st.session_state.session_id, "text": text}, timeout=30,
            )
            response.raise_for_status()
            result = response.json()
        tts_ms = speak_answer(result.get("answer_text", ""), result.get("language", "ru"))
        add_turn(result, text, tts_ms)
    except requests.RequestException as exc:
        st.error(f"Не удалось получить ответ бэкенда: {exc}")


def submit_audio(uploaded):
    if not st.session_state.session_id and not create_session():
        return
    try:
        files = {"audio": (uploaded.name, uploaded.getvalue(), uploaded.type or "audio/webm")}
        with st.spinner("Распознаём речь и обрабатываем обращение…"):
            response = requests.post(
                f"{API_URL}/voice_turn", files=files,
                data={"session_id": st.session_state.session_id}, timeout=45,
            )
            response.raise_for_status()
            result = response.json()
        transcript = result.get("transcript", "")
        tts_ms = speak_answer(result.get("answer_text", ""), result.get("language", "ru"))
        add_turn(result, transcript, tts_ms)
    except requests.RequestException as exc:
        st.error(f"Не удалось обработать голосовую запись: {exc}. Переключитесь на текст.")


def fetch_trace():
    if not st.session_state.get("session_id"):
        return []
    try:
        response = requests.get(f"{API_URL}/session/{st.session_state.session_id}/trace", timeout=5)
        response.raise_for_status()
        return response.json().get("trace", [])
    except requests.RequestException:
        return []


def fmt_ms(value):
    return "—" if value is None else f"{float(value):.1f} мс"


if "session_id" not in st.session_state:
    reset_state()
ensure_session()

st.caption("HACKATHON PROTOTYPE  /  RU + KZ")
st.title("Sөile • Voice Router")
st.caption(f"FastAPI: {API_URL} · Сессия: {st.session_state.get('session_id') or 'не создана'}")

last = st.session_state.traces[-1] if st.session_state.traces else {}
render_avatar(
    reply=last.get("answer_text", ""), language=last.get("language", "ru"),
    reply_id=st.session_state.avatar_reply_id, state="idle",
    audio=st.session_state.avatar_audio, reset_id=st.session_state.avatar_reset,
)

if st.session_state.last_error:
    st.error(st.session_state.last_error)
    st.session_state.last_error = None

left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Чат клиента")
    if EXAMPLES:
        labels = [f"{title}: {text[:70]}" for title, text in EXAMPLES]
        selected = st.selectbox("Быстрые примеры из dialogs_sample.json", labels)
        if st.button("Подставить пример"):
            st.session_state.example_text = EXAMPLES[labels.index(selected)][1]
    prompt = st.chat_input("Напишите сообщение…", max_chars=4000)
    prompt = prompt or st.session_state.pop("example_text", None)
    if prompt:
        submit_text(prompt)
        st.rerun()

    with st.container(height=400, border=True):
        if not st.session_state.messages:
            st.write("👋 Здравствуйте! Опишите, с чем нужна помощь.")
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

    with st.expander("🎙 Голосовое сообщение"):
        st.caption("Запишите webm/ogg/wav — запись уйдёт в FastAPI на STT и маршрутизацию.")
        audio = st.audio_input("Запись", key=f"audio_{st.session_state.avatar_reset}")
        if st.button("Распознать и отправить", disabled=audio is None):
            submit_audio(audio)
            st.rerun()

    if st.button("Новый диалог"):
        reset_state()
        create_session()
        st.rerun()

with right:
    st.subheader("Панель супервизора")
    if not st.session_state.traces:
        st.info("Ожидаем первое обращение")
    else:
        traces = st.session_state.traces
        index = st.selectbox(
            "Обращение", range(len(traces)), index=len(traces) - 1,
            format_func=lambda i: f"{i + 1}. {traces[i].get('transcript', '')[:55]}",
        )
        result = traces[index]
        scenario_id = result.get("scenario_id", "—")
        st.markdown(f"**Сценарий:** {scenario_id} — {SCENARIO_NAMES.get(scenario_id, 'неизвестен')}")
        st.write(f"**Transcript:** {result.get('transcript', '—')}")
        confidence = result.get("confidence")
        st.metric("Confidence", "—" if confidence is None else f"{float(confidence):.0%}")
        st.write(f"**Reasoning:** {result.get('reasoning', '—')}")
        alternatives = result.get("alternatives") or []
        alt_text = ", ".join(
            f"{a.get('id', '—')} ({float(a.get('confidence', 0)):.0%})" for a in alternatives
        ) or "нет"
        st.write(f"**Alternatives:** {alt_text}")
        st.write(f"**Action:** `{result.get('action', '—')}`")
        st.write(f"**Router mode:** `{result.get('router_mode', '—')}`")
        st.write(f"**Pending topics:** {result.get('pending_topics') or 'нет'}")
        timings = result.get("timings_ms") or {}
        st.table({
            "Этап": ["STT", "LLM", "Executor", "TTS", "Total"],
            "Время": [fmt_ms(timings.get(key)) for key in ("stt_ms", "llm_ms", "executor_ms", "tts_ms", "total")],
        })
        with st.expander("JSON результата"):
            st.json(result)

    trace = fetch_trace()
    if trace:
        st.subheader("Статистика сессии")
        totals = [float(t["timings"]["total"]) for t in trace if t.get("timings", {}).get("total") is not None]
        summary = f"Реплик: {len(trace)}"
        if totals:
            summary += f" · Среднее total: {sum(totals) / len(totals):.1f} мс"
        st.write(summary)
        st.caption("Режимы: " + ", ".join(
            f"{mode}={sum(t.get('router_mode') == mode for t in trace)}"
            for mode in ("llm", "fast_path", "rules_fallback")
        ))
