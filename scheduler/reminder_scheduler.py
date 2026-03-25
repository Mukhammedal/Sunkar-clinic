"""
Планировщик напоминаний.
Каждый день в заданное время проверяет завтрашние записи
и запускает исходящие звонки через Voximplant.
"""

from __future__ import annotations
import asyncio
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from services import supabase_service as db
from services.voximplant_service import make_outbound_call

load_dotenv()

logger = logging.getLogger(__name__)

_REMINDER_HOUR   = int(os.getenv("REMINDER_HOUR", "10"))
_REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "0"))


async def send_reminders() -> None:
    """
    Получить завтрашние записи без напоминания,
    позвонить каждому пациенту через Voximplant.
    """
    reminders = db.get_tomorrow_reminders()
    logger.info(f"Reminders job started: {len(reminders)} appointment(s) to notify")

    for row in reminders:
        phone        = row["phone"]
        patient_name = row.get("patient_name") or "Пациент"
        lang         = row.get("language", "ru")
        doctor_name  = row.get("doctor_name", "")
        spec_ru      = row.get("specialization_ru", "")
        spec_kz      = row.get("specialization_kz", "")
        spec         = spec_kz if lang == "kz" else spec_ru

        dt_str = row.get("appointment_datetime", "")
        try:
            from datetime import datetime
            dt     = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            date_f = dt.strftime("%d.%m.%Y")
            time_f = dt.strftime("%H:%M")
        except Exception:
            date_f = ""
            time_f = ""

        custom_data = {
            "type":         "reminder",
            "to_number":    phone,
            "patient_name": patient_name,
            "doctor_name":  doctor_name,
            "spec":         spec,
            "date":         date_f,
            "time":         time_f,
            "language":     lang,
            "appointment_id": row["id"],
        }

        success = await make_outbound_call(phone, custom_data)
        if success:
            db.mark_reminder_sent(row["id"])
            logger.info(f"Reminder call initiated → {phone} ({patient_name})")
        else:
            logger.warning(f"Failed to initiate reminder call → {phone}")

        # Небольшая пауза между звонками, чтобы не перегружать линию
        await asyncio.sleep(3)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_reminders,
        trigger="cron",
        hour=_REMINDER_HOUR,
        minute=_REMINDER_MINUTE,
        id="daily_reminders",
        replace_existing=True,
        misfire_grace_time=3600,  # Запустить с опозданием до 1 часа
    )
    scheduler.start()
    logger.info(
        f"Reminder scheduler started: runs daily at {_REMINDER_HOUR:02d}:{_REMINDER_MINUTE:02d} UTC"
    )
    return scheduler
