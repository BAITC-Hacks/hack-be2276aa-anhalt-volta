"""Run the baseline router against the supplied dataset.

Usage:
  python test_router.py --dataset C:\\Users\\...\\voice_router_dataset
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from router import route_dialogue


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="Directory containing dev_utterances.json")
    ap.add_argument("--complex-only", action="store_true")
    args = ap.parse_args()
    root = Path(args.dataset)
    data = json.loads((root / "dev_utterances.json").read_text(encoding="utf-8"))
    expected_complex = json.loads(Path("complex_routes.json").read_text(encoding="utf-8"))
    predictions = {}
    passed = total = 0
    timings = []
    for item in data["utterances"]:
        if args.complex_only and item["id"] not in expected_complex:
            continue
        total += 1
        started = time.perf_counter()
        result = route_dialogue(item["text"])
        timings.append((time.perf_counter() - started) * 1000)
        got = [result["scenario_id"], *result.get("queued_scenarios", [])]
        predictions[item["id"]] = got
        expected = item["expected"]
        ok = got == expected
        passed += ok
        if not ok:
            print(f"FAIL {item['id']}: expected={expected} got={got} | {item['text']}")
    out = Path("predictions.json")
    out.write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Passed {passed}/{total}; p95 local routing time={sorted(timings)[max(0, int(len(timings)*.95)-1)]:.2f} ms")
    print(f"Wrote {out.resolve()}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
