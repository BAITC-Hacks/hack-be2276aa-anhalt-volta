"""Streamlit UI: streamlit run app.py."""
import json
from pathlib import Path
from uuid import uuid4
from time import perf_counter
import streamlit as st
from agent import route, transcribe, get_repository
from routing_models import ConversationState
from router import failure_trace
from avatar import render_avatar
from lip_sync import prepare_audio
from config import GEMINI_API_KEY, MODEL_NAME
from theme import render_theme_switch

st.set_page_config(page_title='Sөile • Voice Router', page_icon='🎙️', layout='wide')
render_theme_switch()

DEMOS = {
    'Русский · потеря карты': ['Я потерял карту, хочу её заблокировать.'],
    'Қазақша · карта': ['Сәлеметсіз бе! Картамды жоғалттым, бұғаттау керек.'],
    'Смешанный · доставка': ['Сәлеметсіз бе! Хочу поменять адрес доставки карты, мекенжайым өзгерді.'],
    'Смена темы': ['Хочу заблокировать карту.', 'Передумал, лучше проверить баланс.'],
    'Две задачи': ['Заблокируйте карту и поменяйте адрес доставки.', 'Следующий'],
    'Контекст': ['Хочу проверить баланс.', 'Да'],
}


def reset():
    st.session_state.messages = []
    st.session_state.traces = []
    st.session_state.demo_step = 0
    st.session_state.audio_version = st.session_state.get('audio_version', 0) + 1
    st.session_state.avatar_reset = st.session_state.get('avatar_reset', 0) + 1
    st.session_state.avatar_reply_id = ''
    st.session_state.avatar_audio = None
    st.session_state.pending_request = None
    st.session_state.avatar_reaction = None
    st.session_state.avatar_reaction_id = ''
    st.session_state.routing_context = ConversationState().model_dump()


if 'messages' not in st.session_state:
    reset()
# Preserve an existing chat when Streamlit hot-reloads the new avatar code.
for name, default in {'avatar_reset': 0, 'avatar_reply_id': '', 'avatar_audio': None,
                      'pending_request': None}.items():
    st.session_state.setdefault(name, default)
st.session_state.setdefault('routing_context', ConversationState().model_dump())


def submit(text, mode, stt_ms=None):
    started = perf_counter()
    try:
        with st.spinner('Обрабатываем обращение…'):
            result = route(text, st.session_state.messages, mode, state=st.session_state.routing_context)
    except Exception:
        result = failure_trace(text, st.session_state.routing_context, 'ROUTER_ERROR', mode,
                               (perf_counter() - started) * 1000)
    st.session_state.routing_context = result['conversation_state']
    result.update(stt_ms=stt_ms, processing_ms=round((perf_counter() - started) * 1000 + (stt_ms or 0), 1),
                  tts_ms=None, input=text)
    result['timing']['stt_ms'] = stt_ms
    result['timing']['server_response_ms'] = result['processing_ms']
    if result.get('fallback_reason') in ('ROUTER_ERROR', 'BACKEND_ERROR', 'INVALID_ROUTER_OUTPUT'):
        st.session_state.avatar_error = result['reply']
    st.session_state.messages.extend([{'role': 'user', 'content': text}, {'role': 'assistant', 'content': result['reply']}])
    st.session_state.traces.append(result)
    st.session_state.messages = st.session_state.messages[-40:]
    st.session_state.traces = st.session_state.traces[-20:]
    st.session_state.avatar_reply_id = uuid4().hex
    return True


st.caption('HACKATHON PROTOTYPE  /  RU + KK')
st.title('Sөile • Voice Router')
st.write('Пространство для разговора. Sөile рядом, чтобы помочь.')
with st.expander('Режим и информация', expanded=False):
    mode_label = st.radio('Режим работы', ['Демо · без API', 'Gemini · онлайн'], horizontal=True, on_change=reset)
    mode = 'demo' if mode_label.startswith('Демо') else 'live'
    if mode == 'demo':
        st.info('Демо: локальные правила, контекст и очередь задач. Без LLM и распознавания голоса; точность ограничена ключевыми словами.')
    else:
        st.caption(f'Модель: {MODEL_NAME}. Текст, последние 20 сообщений, состояние диалога и отправленная запись обрабатываются Gemini.')
        if not GEMINI_API_KEY:
            st.warning('Для онлайн-режима добавьте GEMINI_API_KEY в .env и перезапустите приложение.')
    st.caption('Прототип не подключён к банковским системам и не выполняет операции. Используйте тестовые данные.')
    catalog = get_repository()
    st.caption(f'Каталог: {len(catalog.scenarios)} сценария · ' + ('демоданные, не официальный набор' if catalog.demo else 'внешний JSON'))

# One stable component, mounted before any blocking model/STT call.
pending = st.session_state.pending_request
last = st.session_state.traces[-1] if st.session_state.traces else {}

with st.container(key='conversation_scene'):
    presence, conversation = st.columns([.48, .52], gap='large')
    with presence:
        render_avatar(reply=last.get('reply', ''), language=last.get('language', 'ru'),
                      reply_id=st.session_state.avatar_reply_id,
                      state=('listening' if pending and pending.get('audio') else 'thinking') if pending else 'idle',
                      audio=st.session_state.avatar_audio, reset_id=st.session_state.avatar_reset,
                      reaction=st.session_state.get('avatar_reaction') if not pending else None,
                      reaction_id=st.session_state.get('avatar_reaction_id', '') if not pending else '')
        with st.expander('Точный lip-sync файла · Rhubarb / JSON'):
            st.caption('WAV/MP3 до 20 МБ. Rhubarb анализирует фонемы один раз на CPU. Без него доступен упрощённый режим по громкости; можно загрузить готовый JSON mouthCues.')
            voice_file = st.file_uploader('Аудио для анализа', type=['wav', 'mp3'])
            cue_file = st.file_uploader('Таймкоды visemes (необязательно)', type=['json'])
            if st.button('Подготовить аудио для головы', disabled=voice_file is None):
                try:
                    with st.spinner('Подготавливаем артикуляцию…'):
                        st.session_state.avatar_audio = prepare_audio(voice_file.getvalue(), Path(voice_file.name).suffix,
                                                                      cue_file.getvalue() if cue_file else None)
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
                except Exception:
                    st.error('Анализ не завершён. Проверьте Rhubarb/FFmpeg, длину и формат записи или загрузите готовый JSON.')
    with conversation:
        with st.container(key='conversation_zone'):
            if error := st.session_state.pop('avatar_error', None):
                st.error(error)
            st.subheader('Conversation')
            st.caption('Вы и Sөile · один разговор')
            with st.container(height=365, border=False, key='conversation_messages'):
                if not st.session_state.messages:
                    with st.chat_message('assistant'):
                        st.caption('Sөile')
                        st.write('Привет. Чем могу помочь?')
                    st.caption('Например: «Хочу поменять адрес доставки карты».')
                for message in st.session_state.messages:
                    with st.chat_message(message['role']):
                        st.caption('Sөile' if message['role'] == 'assistant' else 'Вы')
                        st.write(message['content'])
            prompt = st.chat_input('Спросите Sөile…', max_chars=4000, disabled=mode == 'live' and not GEMINI_API_KEY)
            if prompt:
                st.session_state.pending_request = dict(text=prompt)
                st.rerun()
            with st.expander('Попробовать демо-диалог'):
                selection = st.selectbox('Сценарий демонстрации', list(DEMOS), on_change=lambda: st.session_state.update(demo_step=0))
                steps = DEMOS[selection]
                step = st.session_state.demo_step
                st.caption(steps[min(step, len(steps)-1)])
                if st.button('Отправить следующую реплику', disabled=step >= len(steps)):
                    st.session_state.pending_request = dict(text=steps[step], demo=True)
                    st.rerun()
            with st.expander('🎙 Голосовое сообщение'):
                st.caption('Запишите короткую фразу, затем нажмите «Распознать и отправить». Нужны онлайн-режим и доступ к микрофону.')
                audio = st.audio_input('Запись', key=f'audio_{st.session_state.audio_version}', disabled=mode == 'demo' or not GEMINI_API_KEY)
                if st.button('Распознать и отправить', disabled=audio is None or mode == 'demo' or not GEMINI_API_KEY):
                    st.session_state.pending_request = dict(audio=audio.getvalue())
                    st.rerun()
            if st.button('Очистить диалог'):
                reset()
                st.rerun()
            with st.expander('Панель супервизора', expanded=False):
                if not st.session_state.traces:
                    with st.container(border=True):
                        st.write('Ожидаем первое обращение')
                        st.caption('Здесь появятся сценарий, обоснование и время обработки.')
                else:
                    traces = st.session_state.traces
                    index = st.selectbox('Обращение', range(len(traces)), index=len(traces)-1,
                                         format_func=lambda i: f'{i+1}. {traces[i]["input"][:55]}')
                    result = traces[index]
                    with st.container(border=True):
                        st.caption('ВЫБРАННЫЙ СЦЕНАРИЙ')
                        st.subheader(result.get('scenario_name', result['scenario_id']))
                        st.code(result['scenario_id'], language=None)
                        confidence = result['confidence']
                        st.metric('Оценка уверенности модели', '—' if confidence is None else f'{confidence:.0%}')
                        st.caption('Самооценка модели, не измеренная точность. В демо отсутствует.')
                        st.write(result['explanation'])
                        st.write('Альтернативы: ' + (', '.join(result.get('alternative_names', {}).get(a, a) for a in result['alternatives']) or 'нет'))
                        st.write('Transcript:', result['input'])
                        st.write('Язык:', result['language'])
                        st.write('Тема:', result.get('topic', '—'))
                        st.write('Fallback:', result.get('fallback_reason') or 'нет')
                        st.write('Обработка:', result.get('execution_status', '—'))
                        st.write('Ожидаемые параметры:', ', '.join(result.get('missing_parameters', [])) or 'нет')
                        st.write('В очереди:', ', '.join(result.get('conversation_state', {}).get('pending_intents', [])) or 'нет')
                    with st.expander('Кандидаты и контекст решения'):
                        st.caption('Оценки поиска — не вероятности. Confidence — самооценка модели.')
                        st.json({'candidates': result.get('candidates', []),
                                 'previous_context': result.get('context_used', {}),
                                 'alternative_confidences': result.get('alternative_confidences', {})})
                    st.write('**Время обработки**')
                    timing = result.get('timing', {})
                    stages = {'STT': 'stt_ms', 'Поиск кандидатов': 'retrieval_ms',
                              'Решение router (demo/LLM)': 'decision_ms', 'LLM': 'llm_routing_ms',
                              'Обработчик сценария': 'execution_ms', 'Сервер: до текста': 'server_response_ms',
                              'TTS first byte': 'tts_first_byte_ms', 'End-to-end': 'end_to_end_ms'}
                    st.table({'Этап': list(stages), 'Время': [
                        'не измерено / не применимо' if timing.get(key) is None else f'{timing[key]:.2f} мс'
                        for key in stages.values()]})
                    st.caption('STT отсутствует для текстового ввода. Браузерный TTS не предоставляет first-byte; end-to-end до звука не измеряется. Серверное время не включает запись, сеть браузера и воспроизведение.')
                    with st.expander('JSON результата'):
                        st.json(result)
                    st.download_button('Скачать трассировку JSON', json.dumps(traces, ensure_ascii=False, indent=2),
                                       file_name='trace.json', mime='application/json')

# Process after both sides render; the persistent avatar keeps animating.
if pending:
    # Consume before processing: reruns cannot replay a paid request.
    st.session_state.pending_request = None
    text, stt_ms = pending.get('text'), None
    try:
        if pending.get('audio'):
            started = perf_counter()
            with st.spinner('Распознаём речь…'):
                text = transcribe(pending['audio'])
            stt_ms = round((perf_counter() - started) * 1000, 1)
        if submit(text, mode, stt_ms):
            if pending.get('demo'):
                st.session_state.demo_step += 1
            if pending.get('audio'):
                st.session_state.audio_version += 1
        else:
            st.session_state.avatar_error = 'Не удалось получить ответ. Проверьте настройки API или используйте демо.'
    except Exception:
        st.session_state.avatar_error = 'Не удалось распознать запись. Проверьте API или введите текст.'
        st.session_state.traces.append(failure_trace(text, st.session_state.routing_context,
            'STT_ERROR', mode, (perf_counter() - started) * 1000 if pending.get('audio') else 0))
    # UI-only reaction metadata; routing and audio continue to own their existing lifecycle.
    result = st.session_state.traces[-1] if st.session_state.traces else {}
    st.session_state.avatar_reaction = (
        'fallback' if st.session_state.get('avatar_error') else
        'unsure' if result.get('requires_clarification') else 'success'
    )
    st.session_state.avatar_reaction_id = uuid4().hex
    st.rerun()
