"""Streamlit UI for the FastAPI voice router."""
import base64
import json
import os
from time import perf_counter
from pathlib import Path
from uuid import uuid4

import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from agent import route as local_route, transcribe

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="Sөile • Voice Router", page_icon="🎙️", layout="wide")


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
    components.html(
        f"<script>const u=new SpeechSynthesisUtterance({json.dumps(text, ensure_ascii=False)});"
        f"u.lang={json.dumps(lang)};speechSynthesis.cancel();speechSynthesis.speak(u);</script>",
        height=0,
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
        components.html(
            f"""<audio id="a-{audio_id}" controls autoplay style="width:100%"
                src="data:audio/mpeg;base64,{encoded}"></audio>
                <script>
                const audio=document.getElementById('a-{audio_id}');
                audio.onerror=()=>{{const u=new SpeechSynthesisUtterance({payload});
                u.lang={json.dumps(lang)};speechSynthesis.speak(u);}};
                audio.play().catch(()=>{{}});
                </script>""",
            height=55,
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

mode_label = st.radio("Режим маршрутизации", ["OpenAI · backend", "Локальный роутер · fallback"], horizontal=True)
mode = "local" if mode_label.startswith("Локальный") else "openai"
if mode == "local":
    st.warning("Включён локальный резервный роутер. Для рабочего режима выберите OpenAI · backend.")
else:
    st.caption("По умолчанию запросы идут в FastAPI и далее в OpenAI-роутер.")

left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Чат клиента")
    prompt = st.chat_input("Напишите сообщение…", max_chars=4000)
    if prompt:
        submit(prompt, mode)
        st.rerun()
    with st.container(height=420, border=True):
        if not st.session_state.messages:
            st.write("👋 Здравствуйте! Опишите, с чем нужна помощь.")
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

    with st.expander("🎙 Голосовое сообщение"):
        st.caption("STT выполняется backend через OpenAI; поддерживаются webm/ogg/wav.")
        audio = st.audio_input("Запись", key=f"audio_{st.session_state.audio_key}")
        if st.button("Распознать и отправить", disabled=audio is None):
            try:
                with st.spinner("Распознаём речь…"):
                    started = perf_counter()
                    text = transcribe(audio.getvalue())
                stt_ms = round((perf_counter() - started) * 1000, 1)
                submit(text, mode, stt_ms)
                st.session_state.audio_key += 1
                st.rerun()
            except Exception as exc:
                st.error(f"Не удалось распознать запись: {exc}. Переключитесь на текст.")

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
        st.markdown(f"**Сценарий:** `{result.get('scenario_id', '—')}`")
        st.write(f"**Confidence:** {result.get('confidence', '—')}")
        st.write(f"**Reasoning:** {result.get('explanation', '—')}")
        st.write(f"**Action:** `{result.get('action', '—')}`")
        st.write(f"**Router mode:** `{result.get('router_mode', result.get('mode', '—'))}`")
        st.write(f"**Pending topics:** {result.get('pending_topics') or 'нет'}")
        timings = result.get("timings_ms") or {}
        st.table({"Этап": ["STT", "LLM", "TTS", "Total"], "Время": [
            f"{timings.get('stt_ms', '—')} мс", f"{timings.get('llm_ms', '—')} мс",
            f"{timings.get('tts_ms', '—')} мс", f"{timings.get('total', '—')} мс",
        ]})
        st.json(result)
