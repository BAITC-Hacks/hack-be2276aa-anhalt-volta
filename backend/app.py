import os
import time
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .executor import execute_turn
from .router_client import route_safely
from .speech import router as speech_router


load_dotenv()

# Keys are loaded from .env without exposing or modifying them.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ROUTER_API_KEY = os.getenv("ROUTER_API_KEY")

app = FastAPI(title="Contact Center Voice Bot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(speech_router)

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
        "pending_action": None,
        "pending_return": None,
        "params": {},
        "clarification_count": 0,
        "trace": [],
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

    executor_started_at = time.perf_counter()
    execution = execute_turn(result, request.text, session)
    executor_ms = (time.perf_counter() - executor_started_at) * 1000
    result.update(execution)

    save_started_at = time.perf_counter()
    history.append({"role": "user", "text": request.text})
    history.append({"role": "assistant", "text": result["answer_text"]})
    session["current_scenario"] = result.get("scenario_id", session["current_scenario"])
    session["pending_topics"] = result.get("pending_topics", session["pending_topics"])
    save_ms = (time.perf_counter() - save_started_at) * 1000

    llm_ms = result.pop("llm_ms", 0.0)
    total_ms = (time.perf_counter() - started_at) * 1000
    timings_ms = {
        "session_lookup": round(lookup_ms, 3),
        "routing": round(routing_ms, 3),
        "llm_ms": llm_ms,
        "executor_ms": round(executor_ms, 3),
        "save": round(save_ms, 3),
        "total": round(total_ms, 3),
    }
    session["trace"].append({
        "turn": len(session["trace"]) + 1,
        "scenario_id": result.get("scenario_id"),
        "confidence": result.get("confidence", 0.0),
        "reasoning": result.get("reasoning", ""),
        "router_mode": result.get("router_mode", "unknown"),
        "action": result.get("action"),
        "timings": timings_ms,
    })
    return {
        **result,
        "pending_topics": session["pending_topics"],
        "timings_ms": timings_ms,
    }


@app.get("/session/{session_id}/trace")
def get_session_trace(session_id: str) -> dict[str, Any]:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "trace": session["trace"]}
