# Voice Router: участник 1

Файлы:

- `router.py` — baseline context-aware router и контракт ответа.
- `complex_routes.json` — эталонные маршруты сложных реплик U081–U104.
- `test_router.py` — прогон по `dev_utterances.json` и генерация `predictions.json`.

## Проверка сложных реплик

Из рабочей папки проекта:

```powershell
python test_router.py --dataset C:\Users\Амирхан\Downloads\case_2\voice_router_dataset --complex-only
```

## Проверка всех 104 реплик

```powershell
python test_router.py --dataset C:\Users\Амирхан\Downloads\case_2\voice_router_dataset
python C:\Users\Амирхан\Downloads\case_2\voice_router_dataset\evaluate.py predictions.json C:\Users\Амирхан\Downloads\case_2\voice_router_dataset\dev_utterances.json
```

Оценщик проверяет первый сценарий, полный набор сценариев в multi-intent и recall намерений.

## Контракт для backend

```python
result = route_dialogue(
    utterance="Не пришёл полис на почту, и ещё хочу поменять почту",
    history=[],
    current_scenario=None,
)
```

`scenario_id` — основной сценарий, `queued_scenarios` — дополнительные. Поля `reason`, `confidence` и `alternatives` можно напрямую показать в панели супервизора.

## Следующее улучшение

Заменить правила внутри `route_dialogue` на LLM с structured JSON output, сохранив тот же контракт. Срочные, out-of-scope и operator safeguards оставить перед вызовом LLM.
