import os
import time
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .router_client import route_safely


load_dotenv()

# Keys are loaded from .env without exposing or modifying them.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ROUTER_API_KEY = os.getenv("ROUTER_API_KEY")

app = FastAPI(title="Contact Center Voice Bot")

sessions: dict[str, dict[str, Any]] = {}


class TurnRequest(BaseModel):
    session_id: str
    text: str


@app.post("/session")
def create_session() -> dict[str, str]:
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "history": [],
        "current_scenario": None,
        "pending_topics": [],
    }
    return {"session_id": session_id}


@app.post("/turn")
def process_turn(request: TurnRequest) -> dict[str, Any]:
    started_at = time.perf_counter()

    session = sessions.get(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    history = session["history"]
    lookup_ms = (time.perf_counter() - started_at) * 1000

    routing_started_at = time.perf_counter()
    result = route_safely(request.text, history, session["current_scenario"])
    routing_ms = (time.perf_counter() - routing_started_at) * 1000

    save_started_at = time.perf_counter()
    history.append({"role": "user", "text": request.text})
    history.append({"role": "assistant", "text": result["answer_text"]})
    session["current_scenario"] = result["scenario_id"]
    session["pending_topics"] = result["pending_topics"]
    save_ms = (time.perf_counter() - save_started_at) * 1000

    llm_ms = result.pop("llm_ms", 0.0)
    total_ms = (time.perf_counter() - started_at) * 1000
    return {
        **result,
        "pending_topics": session["pending_topics"],
        "timings_ms": {
            "session_lookup": round(lookup_ms, 3),
            "routing": round(routing_ms, 3),
            "llm_ms": llm_ms,
            "save": round(save_ms, 3),
            "total": round(total_ms, 3),
        },
    }
