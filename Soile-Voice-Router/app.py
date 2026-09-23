"""Streamlit UI: streamlit run app.py."""
import json
from time import perf_counter
import streamlit as st
import streamlit.components.v1 as components
from agent import TITLES, route, transcribe
from config import OPENAI_API_KEY, OPENAI_MODEL

st.set_page_config(page_title='Sөile • Voice Router', page_icon='🎙️', layout='wide')

DEMOS = {
    'Русский · платёж и полис': ['Деньги списали, но полис не оформился.'],
    'Қазақша · срок полиса': ['Полисімнің мерзімі қашан бітеді?'],
    'Смешанный · КАСКО и осмотр': ['Кеше көлігімді біреу соғып кетті, КАСКО бар, и ещё где пройти осмотр?'],
    'Несколько задач': ['Не пришёл полис на почту, и ещё хочу поменять почту на новую.'],
}


def reset():
    st.session_state.messages = []
    st.session_state.traces = []
    st.session_state.dialogue_state = {}
    st.session_state.demo_step = 0
    st.session_state.audio_version = st.session_state.get('audio_version', 0) + 1


if 'messages' not in st.session_state:
    reset()
if 'dialogue_state' not in st.session_state:
    st.session_state.dialogue_state = {}


def submit(text, mode, stt_ms=None):
    started = perf_counter()
    progress = st.empty()
    def show_decision(decision, elapsed_ms):
        progress.info(f'Сценарий: {decision["scenario_id"]} · {elapsed_ms:.0f} мс. Готовим ответ…')
    try:
        with st.spinner('Обрабатываем обращение…'):
            result = route(text, st.session_state.messages, mode,
                           state=st.session_state.dialogue_state, on_decision=show_decision)
    except ValueError:
        st.error('Запрос или ответ модели не прошёл проверку. Проверьте длину текста, ключ и настройки модели.')
        return False
    except Exception:
        st.error('Сервис недоступен. Проверьте соединение, ключ, доступ к модели и квоту. Можно переключиться в деморежим.')
        return False
    finally:
        progress.empty()
    result.update(stt_ms=stt_ms, processing_ms=round((perf_counter() - started) * 1000 + (stt_ms or 0), 1),
                  tts_ms=None, input=text)
    st.session_state.messages.extend([{'role': 'user', 'content': text}, {'role': 'assistant', 'content': result['reply']}])
    st.session_state.traces.append(result)
    st.session_state.dialogue_state = result['dialogue_state']
    st.session_state.messages = st.session_state.messages[-40:]
    st.session_state.traces = st.session_state.traces[-20:]
    return True


def speech_button(text, language):
    # JSON escaping also prevents a generated response from closing the script tag.
    payload = json.dumps(text, ensure_ascii=True).replace('<', '\\u003c')
    lang = {'kk': 'kk-KZ', 'en': 'en-US'}.get(language, 'ru-RU')
    components.html('''
        <style>body{font:14px sans-serif;color:#cbd5e1}button{padding:10px 16px;
        border:1px solid #38d9a9;border-radius:9px;background:#152c29;color:#d9fff4;cursor:pointer}</style>
        <button id="play">▶ Озвучить ответ</button> <span id="status"></span>
        <script>
        const status = document.getElementById('status');
        document.getElementById('play').onclick = () => {
          if (!('speechSynthesis' in window)) {status.textContent='Браузер не поддерживает озвучку'; return;}
          const lang = ''' + json.dumps(lang) + ''';
          const voices = speechSynthesis.getVoices();
          const voice = voices.find(v => v.lang.toLowerCase().startsWith(lang.slice(0,2)));
          if (!voice) {status.textContent='Нет голоса для этого языка в браузере / ОС'; return;}
          speechSynthesis.cancel();
          const utterance = new SpeechSynthesisUtterance(''' + payload + ''');
          utterance.lang = lang; utterance.voice = voice;
          const started = performance.now();
          utterance.onstart = () => { status.textContent='Старт озвучки: ' + Math.round(performance.now()-started) + ' мс'; };
          utterance.onerror = () => { status.textContent='Озвучка недоступна'; };
          speechSynthesis.speak(utterance);
        };
        if ('speechSynthesis' in window) speechSynthesis.getVoices();
        </script>''', height=75)


st.caption('HACKATHON PROTOTYPE  /  RU + KK + EN  /  40 INSURANCE SCENARIOS')
st.title('Voice Router • Saqta Insurance')
st.write('Свободная реплика клиента — к страховому сценарию с объяснимой трассировкой.')
mode_label = st.radio('Режим работы', ['Локальный страховой роутер', 'OpenAI онлайн'], horizontal=True, on_change=reset)
mode = 'openai' if mode_label.startswith('OpenAI') else 'demo'
if mode == 'demo':
    st.info('Локальный роутер подключён из ../router/router.py. API-ключ не нужен.')
elif not OPENAI_API_KEY:
    st.warning('Для OpenAI режима добавьте OPENAI_API_KEY в .env и перезапустите приложение.')
else:
    st.caption(f'Модель OpenAI: {OPENAI_MODEL}. Один запрос на реплику. При ошибке API используется локальный fallback.')
st.caption('Прототип использует синтетические данные Saqta Insurance и не выполняет реальные страховые операции.')

left, right = st.columns([3, 2], gap='large')
with left:
    st.subheader('Чат клиента')
    with st.expander('Попробовать демо-диалог'):
        selection = st.selectbox('Сценарий демонстрации', list(DEMOS), on_change=lambda: st.session_state.update(demo_step=0))
        steps = DEMOS[selection]
        step = st.session_state.demo_step
        st.caption(steps[min(step, len(steps)-1)])
        if st.button('Отправить следующую реплику', disabled=step >= len(steps)):
            if submit(steps[step], mode):
                st.session_state.demo_step += 1
                st.rerun()
    with st.container(height=400, border=True):
        if not st.session_state.messages:
            st.write('👋 Здравствуйте! Опишите, с чем нужна помощь.')
            st.caption('Например: «Деньги списали, но полис не оформился».')
        for message in st.session_state.messages:
            with st.chat_message(message['role']):
                st.write(message['content'])
    prompt = st.chat_input('Напишите сообщение…', max_chars=4000,
                           disabled=mode == 'openai' and not OPENAI_API_KEY)
    if prompt and submit(prompt, mode):
        st.rerun()
    with st.expander('🎙 Голосовое сообщение'):
        st.caption('Голосовой канал подключается отдельным STT-модулем. Пока используйте текстовый канал.')
        audio = st.audio_input('Запись', key=f'audio_{st.session_state.audio_version}', disabled=True)
        if st.button('Распознать и отправить', disabled=True):
            try:
                started = perf_counter()
                with st.spinner('Распознаём речь…'):
                    text = transcribe(audio.getvalue())
                stt_ms = round((perf_counter() - started) * 1000, 1)
            except Exception:
                st.error('Не удалось распознать запись. Проверьте ключ, модель и соединение или введите текст.')
            else:
                if submit(text, mode, stt_ms):
                    st.session_state.audio_version += 1
                    st.rerun()
    if st.session_state.traces:
        last = st.session_state.traces[-1]
        speech_button(last['reply'], last['language'])
    if st.button('Очистить диалог'):
        reset()
        st.rerun()

with right:
    st.subheader('Панель супервизора')
    if not st.session_state.traces:
        with st.container(border=True):
            st.write('Ожидаем первое обращение')
            st.caption('Здесь появятся сценарий, обоснование и время обработки.')
    else:
        traces = st.session_state.traces
        index = st.selectbox('Обращение', range(len(traces)), index=len(traces)-1,
                             format_func=lambda i: f'{i+1}. {traces[i]["input"][:55]}')
        result = traces[index]
        if result.get('fallback'):
            st.warning('OpenAI не обработал ответ. Использован локальный резервный роутер. Причина: '
                       + result.get('fallback_reason', 'неизвестна'))
        st.caption('Источник решения: ' + result.get('mode', 'router') + ' · ' + str(result.get('model', '')))
        with st.container(border=True):
            st.caption('ВЫБРАННЫЙ СЦЕНАРИЙ')
            st.subheader(result.get('scenario_title', TITLES.get(result['scenario_id'], result['scenario_id'])))
            st.code(result['scenario_id'], language=None)
            confidence = result['confidence']
            st.metric('Оценка уверенности модели', '—' if confidence is None else f'{confidence:.0%}')
            st.caption('Самооценка модели или оценка локальных правил; это не измеренная точность.')
            st.write(result['explanation'])
            st.write('Альтернативы: ' + (', '.join(result.get('alternative_titles', [])) or 'нет'))
            st.write('Следующие задачи: ' + (', '.join(result.get('pending_topic_titles', [])) or 'нет'))
        with st.expander('Известные факты и последний вопрос'):
            st.json(result.get('dialogue_state', {}))
        st.write('**Время обработки**')
        # Three text rows do not need dataframe/Arrow initialization on first turn.
        stt_time = '—' if result['stt_ms'] is None else f'{result["stt_ms"]:.1f} мс'
        st.markdown('| Этап | Время |\n|---|---:|\n'
                    f'| Распознавание (STT) | {stt_time} |\n'
                    f'| Выбор сценария | {result["routing_ms"]:.1f} мс |\n'
                    f'| Всего до текста ответа | {result["processing_ms"]:.1f} мс |')
        if result.get('api_ms') is not None:
            st.caption(f'В том числе API: {result["api_ms"]:.1f} мс · запросов: {result["api_attempts"]}')
        llm_times = sorted(t['routing_ms'] for t in traces if t.get('mode') == 'openai')
        if llm_times:
            import math
            p95 = llm_times[math.ceil(len(llm_times) * .95) - 1]
            st.caption(f'LLM за эту сессию: {len(llm_times)} ответов · p95 {p95:.1f} мс · '
                       f'переходов на fallback: {sum(bool(t.get("fallback")) for t in traces)}')
        st.caption('Без времени записи и озвучки. Задержка старта TTS показывается рядом с кнопкой озвучки; голоса зависят от браузера и ОС.')
        with st.expander('JSON результата'):
            st.json(result)
        st.download_button('Скачать трассировку JSON', json.dumps(traces, ensure_ascii=False, indent=2),
                           file_name='trace.json', mime='application/json')
