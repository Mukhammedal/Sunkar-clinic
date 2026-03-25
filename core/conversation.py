"""
Конечный автомат разговора.

Входящие данные от Voximplant:
    call_id   — уникальный ID звонка
    phone     — номер звонящего
    state     — текущее состояние (из прошлого ответа)
    user_text — распознанная речь пациента

Исходящие данные для Voximplant:
    audio_url — URL MP3-файла для воспроизведения
    action    — "play" | "hangup" | "transfer"
    state     — новое состояние (сохранить и прислать обратно)
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Any

from core import nlu
from scripts.conversation_scripts import get_script, spec_display
from services import supabase_service as db
from services.elevenlabs_service import text_to_speech

logger = logging.getLogger(__name__)

# Максимальное число попыток переспросить перед переключением на оператора
MAX_RETRIES = 2


async def process(call_id: str, phone: str, state: str, user_text: str) -> dict:
    """
    Основная точка входа. Возвращает словарь для Voximplant:
    {audio_url, action, state}
    """
    session = db.get_call_session(call_id)

    # ── Первый вызов: создать сессию ──────────────────────────────────────────
    if not session:
        session = db.create_call_session(call_id, phone)

    ctx: dict[str, Any] = session.get("context") or {}
    lang: str = session.get("language") or ctx.get("language") or "ru"

    try:
        text, action, new_state, ctx = await _dispatch(
            state=state,
            user_text=user_text,
            ctx=ctx,
            phone=phone,
            lang=lang,
            session=session,
        )
        lang = ctx.get("language", lang)

    except Exception as exc:
        logger.exception(f"Error in conversation [{call_id}]: {exc}")
        text     = get_script(lang, "error_fallback")
        action   = "hangup"
        new_state = "error"

    audio_url = await text_to_speech(text, lang)

    db.update_call_session(
        call_id,
        state=new_state,
        language=lang,
        context=ctx,
        patient_id=ctx.get("patient_id"),
    )

    if action in ("hangup", "transfer"):
        db.end_call_session(call_id, status=action)

    return {"audio_url": audio_url, "action": action, "state": new_state}


# ── Диспетчер состояний ───────────────────────────────────────────────────────

async def _dispatch(
    state: str,
    user_text: str,
    ctx: dict,
    phone: str,
    lang: str,
    session: dict,
) -> tuple[str, str, str, dict]:
    """
    Возвращает (text, action, new_state, ctx).
    action: "play" | "hangup" | "transfer"
    """

    # ─ Приветствие ───────────────────────────────────────────────────────────
    if state == "start" or state == "greeting":
        text = get_script("ru", "greeting")     # Всегда двуязычное приветствие
        ctx["retries"] = 0
        return text, "play", "language_select", ctx

    # ─ Определение языка ─────────────────────────────────────────────────────
    if state == "language_select":
        detected = nlu.detect_language(user_text)
        if detected:
            ctx["language"] = detected
            lang = detected
            text = get_script(lang, "language_confirm") + " " + get_script(lang, "ask_name")
            return text, "play", "ask_name", ctx
        # Казахское слово «қазақша» или русское молчание → по умолчанию русский
        ctx["language"] = "ru"
        lang = "ru"
        text = get_script("ru", "ask_name")
        return text, "play", "ask_name", ctx

    # ─ Имя пациента ──────────────────────────────────────────────────────────
    if state == "ask_name":
        name = user_text.strip().title() if user_text.strip() else ""
        if not name:
            return _retry(ctx, lang, "ask_name", "repeat_please")

        patient = db.upsert_patient(phone, full_name=name, language=lang)
        ctx["patient_id"] = patient["id"]
        ctx["patient_name"] = name
        ctx["retries"] = 0

        greeting = "patient_found" if patient.get("full_name") else "patient_new"
        text = (
            get_script(lang, greeting, name=name)
            + " "
            + get_script(lang, "ask_purpose")
        )
        return text, "play", "ask_purpose", ctx

    # ─ Цель обращения ────────────────────────────────────────────────────────
    if state == "ask_purpose":
        intent = nlu.detect_intent(user_text)

        if intent == "appointment":
            text = get_script(lang, "ask_specialization")
            ctx["retries"] = 0
            return text, "play", "ask_specialization", ctx

        if intent in ("question", "transfer"):
            text = get_script(lang, "complex_question")
            return text, "transfer", "transfer", ctx

        return _retry(ctx, lang, "ask_purpose", "purpose_unknown")

    # ─ Специальность ─────────────────────────────────────────────────────────
    if state == "ask_specialization":
        spec = nlu.detect_specialization(user_text)
        if not spec:
            return _retry(ctx, lang, "ask_specialization", "spec_unknown")

        doctors = db.get_doctors_by_specialization(spec)
        if not doctors:
            text = get_script(lang, "no_doctors", spec=spec_display(spec, lang))
            ctx["retries"] = 0
            return text, "play", "ask_purpose", ctx

        ctx["specialization"] = spec
        ctx["doctors"] = [d["id"] for d in doctors]
        ctx["doctor_index"] = 0
        ctx["retries"] = 0
        return _offer_doctor(ctx, lang, doctors[0])

    # ─ Выбор врача ───────────────────────────────────────────────────────────
    if state == "select_doctor":
        answer = nlu.detect_yes_no(user_text)

        if answer is True:
            ctx["retries"] = 0
            text = get_script(lang, "ask_date")
            return text, "play", "ask_date", ctx

        if answer is False:
            idx = ctx.get("doctor_index", 0) + 1
            ctx["doctor_index"] = idx
            doctor_ids: list = ctx.get("doctors", [])

            if idx >= len(doctor_ids):
                text = get_script(
                    lang, "no_doctors",
                    spec=spec_display(ctx.get("specialization", ""), lang)
                )
                return text, "play", "ask_purpose", ctx

            # Загрузить следующего врача
            next_doc_res = db.get_doctors_by_specialization(ctx["specialization"])
            next_doc = next((d for d in next_doc_res if d["id"] == doctor_ids[idx]), None)
            if not next_doc:
                text = get_script(lang, "no_doctors", spec=spec_display(ctx["specialization"], lang))
                return text, "play", "ask_purpose", ctx

            ctx["doctor_id"] = next_doc["id"]
            ctx["doctor_name"] = next_doc["full_name"]
            text = get_script(
                lang, "doctor_next",
                doctor_name=next_doc["full_name"],
            )
            return text, "play", "select_doctor", ctx

        return _retry(ctx, lang, "select_doctor", "repeat_please")

    # ─ Дата ──────────────────────────────────────────────────────────────────
    if state == "ask_date":
        date_str = nlu.detect_date(user_text)
        if not date_str:
            return _retry(ctx, lang, "ask_date", "date_unknown")

        ctx["date"] = date_str
        ctx["retries"] = 0

        doctor_id = ctx.get("doctor_id", "")
        slots = db.get_free_slots(doctor_id, date_str)
        if not slots:
            doctor_name = ctx.get("doctor_name", "")
            text = get_script(lang, "no_slots", doctor_name=doctor_name)
            return text, "play", "ask_date", ctx

        ctx["available_slots"] = slots
        slots_str = ", ".join(slots[:6])  # Показываем первые 6 слотов
        text = get_script(
            lang, "ask_time",
            doctor_name=ctx.get("doctor_name", ""),
            slots=slots_str,
        )
        return text, "play", "ask_time", ctx

    # ─ Время ─────────────────────────────────────────────────────────────────
    if state == "ask_time":
        time_str = nlu.detect_time(user_text)
        available = ctx.get("available_slots", [])

        if not time_str or time_str not in available:
            return _retry(ctx, lang, "ask_time", "time_unknown")

        ctx["time"] = time_str
        ctx["retries"] = 0

        date_str = ctx.get("date", "")
        appointment_dt = f"{date_str}T{time_str}:00"
        ctx["appointment_datetime"] = appointment_dt

        formatted_dt = _format_datetime(date_str, time_str, lang)
        text = get_script(
            lang, "confirm_booking",
            doctor_name=ctx.get("doctor_name", ""),
            spec=spec_display(ctx.get("specialization", ""), lang),
            datetime=formatted_dt,
        )
        return text, "play", "confirm_booking", ctx

    # ─ Подтверждение записи ──────────────────────────────────────────────────
    if state == "confirm_booking":
        answer = nlu.detect_yes_no(user_text)

        if answer is True:
            appointment = db.create_appointment(
                patient_id=ctx["patient_id"],
                doctor_id=ctx["doctor_id"],
                appointment_datetime=ctx["appointment_datetime"],
            )
            ctx["appointment_id"] = appointment["id"]
            text = get_script(lang, "booking_saved")
            return text, "hangup", "booking_saved", ctx

        if answer is False:
            text = get_script(lang, "booking_cancelled") + " " + get_script(lang, "ask_date")
            return text, "play", "ask_date", ctx

        return _retry(ctx, lang, "confirm_booking", "repeat_please")

    # ─ Напоминание (исходящий звонок) ────────────────────────────────────────
    if state == "reminder":
        import json as _json
        try:
            data = _json.loads(user_text)
        except Exception:
            data = {}

        reminder_lang = data.get("language", "ru")
        ctx["language"] = reminder_lang

        text = get_script(
            reminder_lang,
            "reminder_greeting",
            patient_name=data.get("patient_name", ""),
            doctor_name=data.get("doctor_name", ""),
            spec=data.get("spec", ""),
            date=data.get("date", ""),
            time=data.get("time", ""),
        )
        return text, "hangup", "reminder_done", ctx

    # ─ Неизвестное состояние ─────────────────────────────────────────────────
    logger.warning(f"Unknown state: {state!r}")
    text = get_script(lang, "ask_purpose")
    return text, "play", "ask_purpose", ctx


# ── Вспомогательные ───────────────────────────────────────────────────────────

def _offer_doctor(ctx: dict, lang: str, doctor: dict) -> tuple[str, str, str, dict]:
    ctx["doctor_id"]   = doctor["id"]
    ctx["doctor_name"] = doctor["full_name"]
    spec = spec_display(ctx.get("specialization", ""), lang)
    text = get_script(lang, "doctor_available", doctor_name=doctor["full_name"], spec=spec)
    return text, "play", "select_doctor", ctx


def _retry(ctx: dict, lang: str, return_state: str, script_key: str) -> tuple[str, str, str, dict]:
    """Переспросить или передать оператору после MAX_RETRIES неудач."""
    retries = ctx.get("retries", 0) + 1
    ctx["retries"] = retries

    if retries > MAX_RETRIES:
        text = get_script(lang, "transfer_operator")
        return text, "transfer", "transfer", ctx

    text = get_script(lang, script_key)
    return text, "play", return_state, ctx


def _format_datetime(date_str: str, time_str: str, lang: str) -> str:
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        months_ru = [
            "", "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря",
        ]
        months_kz = [
            "", "қаңтарда", "ақпанда", "наурызда", "сәуірде", "мамырда",
            "маусымда", "шілдеде", "тамызда", "қыркүйекте", "қазанда",
            "қарашада", "желтоқсанда",
        ]
        months = months_kz if lang == "kz" else months_ru
        return f"{dt.day} {months[dt.month]} в {time_str}"
    except ValueError:
        return f"{date_str} {time_str}"
