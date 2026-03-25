"""
FastAPI маршруты для обработки звонков.
Voximplant VoxEngine вызывает эти эндпоинты через HTTP.
"""

from __future__ import annotations
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.conversation import process
from services import supabase_service as db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["calls"])


# ── Модели запросов ───────────────────────────────────────────────────────────

class CallProcessRequest(BaseModel):
    call_id:   str
    phone:     str
    state:     str = "start"
    user_text: str = ""


class CallEndRequest(BaseModel):
    call_id: str
    status:  str = "completed"   # completed | transferred | failed


# ── Эндпоинты ────────────────────────────────────────────────────────────────

@router.post("/call/process")
async def call_process(req: CallProcessRequest) -> dict:
    """
    Основной эндпоинт разговора.
    Вызывается Voximplant на каждом шаге диалога.

    Ответ:
        audio_url  — URL MP3 для воспроизведения
        action     — "play" | "hangup" | "transfer"
        state      — новое состояние (вернуть на следующем запросе)
    """
    logger.info(
        f"[{req.call_id}] state={req.state!r} phone={req.phone} text={req.user_text!r}"
    )

    try:
        result = await process(
            call_id=req.call_id,
            phone=req.phone,
            state=req.state,
            user_text=req.user_text,
        )
    except Exception as exc:
        logger.exception(f"[{req.call_id}] Unhandled error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info(f"[{req.call_id}] → action={result['action']} new_state={result['state']}")
    return result


@router.post("/call/end")
async def call_end(req: CallEndRequest) -> dict:
    """
    Завершить сессию звонка (вызывается при разрыве соединения).
    """
    db.end_call_session(req.call_id, status=req.status)
    logger.info(f"[{req.call_id}] Session ended with status={req.status}")
    return {"ok": True}


@router.get("/call/session/{call_id}")
async def get_session(call_id: str) -> dict:
    """Получить текущее состояние сессии (для отладки)."""
    session = db.get_call_session(call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
