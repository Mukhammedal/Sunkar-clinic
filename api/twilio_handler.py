"""
Twilio Voice webhook — обработка входящих звонков через TwiML.
Twilio сам распознаёт речь и передаёт текст нам.
"""

from __future__ import annotations
import logging

from fastapi import APIRouter, Form, Response
from typing import Optional

from core.conversation import process_text
from services import supabase_service as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/twilio", tags=["twilio"])


def twiml(content: str) -> Response:
    """Вернуть TwiML ответ."""
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{content}</Response>',
        media_type="application/xml"
    )


def say(text: str, lang: str = "ru") -> str:
    """TwiML <Say> с нужным языком."""
    voice = "Polly.Tatyana" if lang == "ru" else "Polly.Tatyana"
    return f'<Say voice="{voice}" language="ru-RU">{text}</Say>'


def gather(action: str, text: str, lang: str = "ru") -> str:
    """TwiML <Gather> — говорим текст и слушаем ответ."""
    voice = "Polly.Tatyana"
    return (
        f'<Gather input="speech" language="ru-RU" speechTimeout="3" '
        f'action="{action}" method="POST">'
        f'<Say voice="{voice}" language="ru-RU">{text}</Say>'
        f'</Gather>'
        f'<Redirect method="POST">{action}?timeout=1</Redirect>'
    )


# ── Входящий звонок ───────────────────────────────────────────────────────────

@router.post("/voice")
async def voice_incoming(
    CallSid: str = Form(...),
    From: str = Form(...),
):
    """Первый webhook — звонок поступил."""
    logger.info(f"[{CallSid}] Incoming call from {From}")

    session = db.get_call_session(CallSid)
    if not session:
        db.create_call_session(CallSid, From)

    greeting = (
        "Здравствуйте! Добро пожаловать в медицинскую клинику. "
        "Для продолжения на русском скажите русский. "
        "Для казахского языка скажите казахский."
    )

    return twiml(gather(
        action=f"/twilio/gather?call_id={CallSid}&phone={From}&state=language_select",
        text=greeting
    ))


# ── Обработка речи ────────────────────────────────────────────────────────────

@router.post("/gather")
async def voice_gather(
    CallSid: str = Form(...),
    SpeechResult: Optional[str] = Form(default=""),
    call_id: str = "",
    phone: str = "",
    state: str = "start",
    timeout: str = "0",
):
    """Twilio прислал распознанную речь."""
    user_text = SpeechResult or ""
    cid = call_id or CallSid

    logger.info(f"[{cid}] state={state!r} speech={user_text!r}")

    result = await process_text(
        call_id=cid,
        phone=phone,
        state=state,
        user_text=user_text,
    )

    text   = result["text"]
    action = result["action"]
    new_state = result["state"]
    lang   = result.get("lang", "ru")

    if action == "transfer":
        operator = "+77071234567"  # заменить на реальный номер оператора
        xml = (
            say("Соединяю со специалистом. Пожалуйста, подождите.") +
            f'<Dial>{operator}</Dial>'
        )
        return twiml(xml)

    if action == "hangup":
        return twiml(say(text) + "<Hangup/>")

    # action == "play" — продолжаем разговор
    return twiml(gather(
        action=f"/twilio/gather?call_id={cid}&phone={phone}&state={new_state}",
        text=text,
        lang=lang,
    ))
