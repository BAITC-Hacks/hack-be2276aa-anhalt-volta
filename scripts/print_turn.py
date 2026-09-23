#!/usr/bin/env python3

import json
import sys


payload = json.load(sys.stdin)
timings = payload.get("timings_ms", {})


def clean(value):
    return str(value if value is not None else "").replace("\n", " ").replace("|", "/")


print(" | ".join([
    clean(payload.get("router_mode")),
    clean(payload.get("scenario_id")),
    clean(payload.get("confidence")),
    clean(payload.get("action")),
    clean(payload.get("answer_text")),
    clean(timings.get("llm_ms")),
]))
