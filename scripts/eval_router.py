#!/usr/bin/env python3
"""Live evaluation of the backend router against dev_utterances.json."""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.llm_router import MODEL, route  # noqa: E402

logging.getLogger("backend.llm_router").disabled = True


DATASET = ROOT / "voice_router_dataset" / "dev_utterances.json"
REPORT = ROOT / "docs" / "eval_results.md"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def evaluate_one(item: dict) -> dict:
    started = time.perf_counter()
    result = route(item["text"], [], None)
    elapsed_ms = (time.perf_counter() - started) * 1000
    expected = item.get("expected", [])
    return {
        "id": item["id"],
        "text": item["text"],
        "expected": expected[0] if expected else "",
        "selected": result.get("scenario_id"),
        "correct": bool(expected) and result.get("scenario_id") == expected[0],
        "mode": result.get("router_mode", "unknown"),
        "elapsed_ms": elapsed_ms,
        "llm_ms": float(result.get("llm_ms") or 0),
        "error": result.get("llm_error"),
    }


def summarize(rows: list[dict], mode: str) -> dict:
    selected = [row for row in rows if row["mode"] == mode]
    elapsed = [row["elapsed_ms"] for row in selected]
    llm_ms = [row["llm_ms"] for row in selected]
    return {
        "mode": mode,
        "count": len(selected),
        "accuracy": (sum(row["correct"] for row in selected) / len(selected) * 100) if selected else 0.0,
        "mean_elapsed": statistics.mean(elapsed) if elapsed else 0.0,
        "p95_elapsed": percentile(elapsed, 0.95),
        "mean_llm_ms": statistics.mean(llm_ms) if llm_ms else 0.0,
        "errors": [row for row in selected if not row["correct"]],
    }


def append_report(rows: list[dict], workers: int) -> str:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    summaries = [summarize(rows, "fast_path"), summarize(rows, "llm"), summarize(rows, "rules_fallback")]
    live_rows = [row for row in rows if row["mode"] in {"fast_path", "llm"}]
    total_accuracy = sum(row["correct"] for row in live_rows) / len(live_rows) * 100 if live_rows else 0.0

    lines = [
        "\n## Live, с fast path\n",
        f"Дата прогона: {timestamp}",
        f"Модель: `{MODEL}`",
        f"Датасет: `voice_router_dataset/dev_utterances.json`, реплик: {len(rows)}, worker-ов: {workers}",
        "Источник ключа: `.env` через `python-dotenv`.\n",
        f"Итоговая primary accuracy для `fast_path` + `llm`: **{total_accuracy:.1f}%**.\n",
        "Время ниже — wall-clock одного вызова `route`; `llm_ms` — внутреннее время роутера.\n",
        "| Режим | Реплик | Accuracy | Среднее wall-clock | P95 wall-clock | Среднее llm_ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        if summary["mode"] in {"fast_path", "llm"} or summary["count"]:
            lines.append(
                f"| `{summary['mode']}` | {summary['count']} | {summary['accuracy']:.1f}% | "
                f"{summary['mean_elapsed']:.1f} мс | {summary['p95_elapsed']:.1f} мс | "
                f"{summary['mean_llm_ms']:.1f} мс |"
            )

    errors = [row for row in live_rows if not row["correct"]]
    lines.append("\nОшибки fast path/LLM:")
    if errors:
        lines.extend(f"- {row['id']} — {row['text']} → ожидалось `{row['expected']}`, выбрано `{row['selected']}`" for row in errors)
    else:
        lines.append("- Нет.")

    fallback_rows = [row for row in rows if row["mode"] == "rules_fallback"]
    if fallback_rows:
        lines.append(f"\nFallback во время прогона: {len(fallback_rows)}; live accuracy выше считается без fallback.")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8, help="Количество параллельных запросов")
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY не найден в окружении/.env; live-прогон остановлен.", file=sys.stderr)
        return 2

    items = json.loads(DATASET.read_text(encoding="utf-8"))["utterances"]
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(evaluate_one, item): item for item in items}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(
                f"{row['id']} | {row['mode']} | {row['selected']} | "
                f"{row['elapsed_ms']:.1f} ms | correct={row['correct']}",
                flush=True,
            )
    rows.sort(key=lambda row: row["id"])
    report = append_report(rows, max(1, args.workers))
    print("\n" + report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
