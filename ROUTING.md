# Контекстный Voice Router

Это доработка существующего Streamlit-приложения. Официальных 40 сценариев,
`dialogs_sample.json`, `dev_utterances.json`, `evaluate.py`, KB и mock backend в
репозитории пока нет. `data/demo/` — **наши синтетические примеры**, не стартовый кит.
Три бизнес-сценария сохранены, `clarify` — служебное решение вне каталога.

## Запуск и ручная проверка

```powershell
.\.venv-avatar\Scripts\python.exe -m streamlit run app.py
```

В деморежиме отправьте:

1. «Заблокируйте карту и поменяйте адрес доставки» → card_block, MULTI_INTENT,
   change_address в очереди, предложение перейти к следующему вопросу.
2. «Следующий» → change_address, TOPIC_SWITCH, очередь очищается.
3. «Да» → TOPIC_REFINEMENT текущего сценария.
4. «Баланс или адрес?» → AMBIGUOUS, уточнение.
5. «Передумал, лучше проверить баланс» → check_balance.
6. «Сәлем! Хочу поменять адрес, мекенжайым өзгерді» → change_address, mixed.

Откройте существующую «Панель супервизора»: transcript, язык, решение, тема,
обоснование, кандидаты, предыдущий контекст, очередь, параметры, ошибки и времена.
«Очистить диалог» и смена режима сбрасывают также состояние маршрутизатора.

## Архитектура

`agent.py` сохраняет публичные `route`, `transcribe`, `run_agent`.
`route(text, history, mode, state=...)` возвращает результат и новое
`conversation_state`; входное состояние не мутируется. UI/CLI передают его в
следующую реплику. STT можно полностью исключить для benchmark.

- `scenario_repository.py`: строгий JSON loader, нормализованный каталог,
  словарный поиск кандидатов на CPU. Поиск учитывает описания, примеры, границы,
  keywords; удерживает текущий сценарий, pending и прямые совпадения намерений.
  Обычно top-8, при отсутствии лексических совпадений — весь каталог для LLM,
  чтобы принудительный shortlist не отбрасывал ответ. Это начальная эвристика;
  её recall надо измерять на реальных данных, embeddings пока не добавлены.
- `routing_models.py`: валидируемые Decision/ConversationState. Отдельно хранятся
  текущий и прошлые сценарии, параметры по сценариям, ожидаемые параметры,
  очередь, язык, topic history, conversation ID. `relevant_user_facts` — пока
  расширяемое поле для адаптера, автоматического извлечения свободных фактов нет.
- `router.py`: rules / scenario context / conversation context / utterance /
  output schema разделены. Temperature=0. ID ограничены текущими кандидатами
  в JSON Schema и повторно проверяются в коде. Параметры проверяются по выбранному
  сценарию, неизвестные поля и операции отвергаются. Ответ LLM о выполнении
  действия не используется; текст нормального ответа формирует handler.
- `scenario_executor.py`: allowlist `respond`, `knowledge`, `mock_lookup`.
  Только локальные read-only действия. Недостающий параметр вызывает вопрос;
  незавершённая задача сохраняется при смене темы. По окончании предлагается
  перейти к pending-задаче. Сбой обработчика не считается завершением.
- `app.py`: прежняя композиция, чат, темы, аватар и голос. Расширены только
  состояние диалога, диагностические поля и демопримеры.

Демоправила учитывают отрицания по фрагментам, явную смену намерения, порядок
«сначала», короткое подтверждение и несколько совпадений. Они не обеспечивают
понимание произвольной естественной речи. Демо определяет RU/KK/mixed эвристически;
в live это поле возвращает модель. Язык не используется как категория сценария.

## Подключение реального стартового кита

Сначала прочитать его README и JSON. Их реальная схема имеет приоритет.
Loader принимает массив либо объект `{"scenarios": [...]}` следующего формата:

```json
{
  "scenarios": [{
    "id": "claim_status",
    "name": "Статус заявления",
    "description": "Узнать состояние ранее поданного заявления",
    "boundaries": ["Не подача нового заявления"],
    "keywords": ["статус заявления"],
    "exclude_keywords": [],
    "examples": {"ru": ["Что с моим заявлением?"], "kk": []},
    "parameters": [{"name": "reference", "description": "тестовый номер заявления", "required": true}],
    "handler": "respond",
    "responses": {"ru": "Выбран сценарий проверки статуса. Это демонстрация."},
    "priority": 0
  }]
}
```

Это пример **контракта адаптера**, не предполагаемая схема официального файла.
Если официальный JSON отличается, преобразовать его в `Scenario` в loader,
не переписывая сценарии вручную и не меняя исходные файлы. Незнакомые поля,
повторные ID и некорректные данные сейчас приводят к явной ошибке, а не тихому
переключению на демо. Изменение каталога требует очистить текущий диалог.

Настройки `.env` (не меняйте ключи и существующие значения без необходимости):

```dotenv
SCENARIOS_PATH=data/scenarios.json
KNOWLEDGE_PATH=data/knowledge_base.json
MOCK_BACKEND_PATH=data/mock_backend.json
```

Без SCENARIOS_PATH автоматически выбирается `data/scenarios.json`, если он
существует, иначе `data/demo/scenarios.json`. После смены настроек перезапустить
Streamlit. Loader не ограничен тремя ID; тест отдельно проверяет 40 произвольных ID.

Минимальная KB: `{"hours":{"ru":"9–18","kk":"9–18"}}`.
Сценарий `handler="knowledge"`, `knowledge_keys=["hours"]` читает только выбранные
факты для ответа; KB не включается в routing prompt. Минимальный mock backend:
`{"demo_status":{"ru":"Активен"}}`; `handler="mock_lookup"`, `mock_key="demo_status"`.
Это проверяемые интерфейсы для тестовых данных, не реализация неизвестных будущих
бизнес-операций. Обработка реальных параметров/типов/операций добавляется только
после получения схемы стартового кита. Никакого eval, shell или свободного tool dispatch.

## Fallback и измерения

Причины: LOW_CONFIDENCE, NO_MATCH, AMBIGUOUS, MISSING_CONTEXT,
INVALID_ROUTER_OUTPUT, BACKEND_ERROR, ROUTER_ERROR, STT_ERROR.
Порог confidence 0.55 — начальный, **не откалиброван**; значение не является accuracy.
Причина и состояние ошибки видны в trace. Уточнение параметров существующего
сценария не заменяет его ID на clarify. Ошибки провайдера не выводят сырой ответ.

`perf_counter` измеряет retrieval, decision, LLM, execution и серверное время до
текста; UI добавляет STT при голосовом вводе. Недоступные метрики — null:
браузерный Web Speech API не даёт TTS first-byte, время от конца речи до звука
не измерено. Серверное время нельзя выдавать за end-to-end. Цели 500 мс/1.5 с
для онлайн-пути пока не подтверждены.

Полная trace и transcript живут в сессии и скачиваемом JSON. Используйте тестовые
данные. Диагностический logger `seile.routing` пишет метаданные в stderr:
timestamp, случайный conversation ID, кандидаты, решение, confidence, альтернативы,
тип смены темы, latency и код причины. Он **не пишет** transcript, параметры,
сырой prompt, ответ/исключение провайдера или секреты. Вместо utterance —
`[not persisted]`. Свободное объяснение решения доступно только в session trace.

## Evaluation

```powershell
.\.venv-avatar\Scripts\python.exe -m pytest -q
node --test avatar_frontend/core.test.js avatar_frontend/playback.test.js avatar_frontend/behavior.test.js theme_frontend/switch.test.js
.\.venv-avatar\Scripts\python.exe benchmark.py --output benchmark-report-demo.json
```

`benchmark.py` — наш wrapper, не официальный evaluate.py. Он выводит primary
accuracy, wrong scenario count, fallback count, topic/secondary accuracy,
candidate recall, p50/p95 routing latency. Время загрузки каталога и STT исключены.
Диалог сбрасывается между примерами и сохраняется между turns одного диалога.
Текущий набор: 17 синтетических реплик; его результат не подтверждает качество LLM.

Для внешнего набора ожидается список `{text, expected_scenario}` или
`{"utterances":[...]}`; для диалогов — `{"dialogs":[{"turns":[...]}]}`.
Необязательные labels: `expected_topic`, `secondary_intents`. Внешнюю разметку
не угадываем: при другой структуре адаптировать `load_cases` по README набора.

```powershell
.\.venv-avatar\Scripts\python.exe benchmark.py --dataset data/dev_utterances.json --scenarios data/scenarios.json --mode live --output benchmark-report-live.json
```

Live-команда вызывает API и требует настроенного ключа. В этой доработке
онлайн-оценка не запускалась. Для sanitized JSONL добавьте
`--log-jsonl routing.log` (raw transcript туда не попадает).

Когда появится официальный `evaluate.py`, запускать **его исходную команду из
README организаторов**, не менять scoring. При необходимости адаптировать
только точку вызова нашего `route`, сохранив их логику. Сейчас официального
скрипта нет, поэтому его интеграцию и официальный accuracy проверить невозможно.

JSON Schema сверена с [документацией Gemini](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en);
используется поддерживаемый установленным SDK `response_json_schema` с последующей
Pydantic-валидацией. Конкретная доступность модели и качество RU/KK требуют live-прогона.
