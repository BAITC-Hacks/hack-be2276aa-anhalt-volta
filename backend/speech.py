"""Speech endpoints backed by OpenAI audio APIs."""

from __future__ import annotations

import io
import os
import re
import time
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel


load_dotenv()

router = APIRouter()
SUPPORTED_AUDIO_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
}


class TTSRequest(BaseModel):
    text: str


def _client(timeout: float = 15.0) -> OpenAI:
    return OpenAI(timeout=timeout, max_retries=0)


def _language(text: str) -> str:
    lowered = text.lower()
    has_kk = bool(re.search(r"[әіңғүұқөһ]", lowered))
    has_ru = bool(re.search(r"[ыэёъюя]|\b(и|ещё|хочу|скажите|пожалуйста)\b", lowered))
    if has_kk and has_ru:
        return "mixed"
    return "kk" if has_kk else "ru"


def _transcribe(audio: bytes, filename: str, content_type: str | None) -> str:
    file_value = (filename or "audio.webm", audio, content_type or "application/octet-stream")
    try:
        response = _client().audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=file_value,
            response_format="json",
        )
        return response.text
    except Exception as first_error:
        try:
            response = _client().audio.transcriptions.create(
                model="whisper-1",
                file=file_value,
                response_format="json",
            )
            return response.text
        except Exception as second_error:
            raise RuntimeError(f"STT failed: {second_error}") from first_error


@router.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)) -> dict[str, Any]:
    started_at = time.perf_counter()
    content_type = (audio.content_type or "").lower()
    suffix = (audio.filename or "").lower().rsplit(".", 1)[-1] if audio.filename else ""
    if content_type not in SUPPORTED_AUDIO_TYPES and suffix not in {"webm", "ogg", "wav", "mp3"}:
        raise HTTPException(status_code=415, detail="Поддерживаются аудиофайлы webm, ogg и wav.")
    try:
        text = _transcribe(await audio.read(), audio.filename or "audio.webm", content_type)
        return {
            "text": text,
            "language": _language(text),
            "stt_ms": round((time.perf_counter() - started_at) * 1000, 3),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось распознать речь: {exc}") from exc


@router.post("/tts")
def text_to_speech(request: TTSRequest) -> StreamingResponse:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Текст для озвучивания не может быть пустым.")
    started_at = time.perf_counter()
    try:
        try:
            response = _client().audio.speech.create(
                model="gpt-4o-mini-tts",
                voice="nova",
                input=request.text,
                instructions="Speak calmly, warmly, and politely in the language of the input text.",
                response_format="mp3",
            )
        except Exception:
            response = _client().audio.speech.create(
                model="tts-1",
                voice="nova",
                input=request.text,
                response_format="mp3",
            )
        audio = response.content
        elapsed = round((time.perf_counter() - started_at) * 1000, 3)
        return StreamingResponse(
            io.BytesIO(audio),
            media_type="audio/mpeg",
            headers={"tts_ms": str(elapsed), "X-TTS-Ms": str(elapsed)},
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось синтезировать речь: {exc}") from exc


@router.post("/voice_turn")
async def voice_turn(session_id: str = Form(...), audio: UploadFile = File(...)) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        content_type = (audio.content_type or "").lower()
        suffix = (audio.filename or "").lower().rsplit(".", 1)[-1] if audio.filename else ""
        if content_type not in SUPPORTED_AUDIO_TYPES and suffix not in {"webm", "ogg", "wav", "mp3"}:
            raise HTTPException(status_code=415, detail="Поддерживаются аудиофайлы webm, ogg и wav.")
        stt_started_at = time.perf_counter()
        text = _transcribe(await audio.read(), audio.filename or "audio.webm", content_type)
        stt_ms = round((time.perf_counter() - stt_started_at) * 1000, 3)

        # Lazy import avoids a module cycle while reusing the exact /turn logic.
        from .app import TurnRequest, process_turn

        result = process_turn(TurnRequest(session_id=session_id, text=text))
        return {**result, "transcript": text, "language": _language(text), "stt_ms": stt_ms}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось обработать голосовой запрос: {exc}") from exc
