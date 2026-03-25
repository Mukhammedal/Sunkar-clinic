"""
Все операции с базой данных Supabase.
"""

from __future__ import annotations
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_supabase: Client = create_client(
    os.getenv("SUPABASE_URL", ""),
    os.getenv("SUPABASE_SERVICE_KEY", ""),
)


# ── Пациенты ─────────────────────────────────────────────────────────────────

def get_patient_by_phone(phone: str) -> Optional[dict]:
    res = _supabase.table("patients").select("*").eq("phone", phone).execute()
    return res.data[0] if res.data else None


def create_patient(phone: str, full_name: str = "", language: str = "ru") -> dict:
    res = _supabase.table("patients").insert({
        "phone": phone,
        "full_name": full_name,
        "language": language,
    }).execute()
    return res.data[0]


def update_patient(patient_id: str, **fields) -> dict:
    res = _supabase.table("patients").update(fields).eq("id", patient_id).execute()
    return res.data[0]


def upsert_patient(phone: str, full_name: str = "", language: str = "ru") -> dict:
    existing = get_patient_by_phone(phone)
    if existing:
        updates: dict[str, Any] = {}
        if full_name and not existing.get("full_name"):
            updates["full_name"] = full_name
        if language:
            updates["language"] = language
        if updates:
            return update_patient(existing["id"], **updates)
        return existing
    return create_patient(phone, full_name, language)


# ── Врачи ─────────────────────────────────────────────────────────────────────

def get_doctors_by_specialization(specialization: str) -> list[dict]:
    res = (
        _supabase.table("doctors")
        .select("*")
        .eq("specialization", specialization)
        .eq("is_active", True)
        .execute()
    )
    return res.data or []


# ── Расписание / занятые слоты ────────────────────────────────────────────────

def get_busy_slots(doctor_id: str, date_str: str) -> list[str]:
    """Вернуть список занятых HH:MM слотов врача на дату."""
    day_start = f"{date_str}T00:00:00"
    day_end   = f"{date_str}T23:59:59"
    res = (
        _supabase.table("appointments")
        .select("appointment_datetime")
        .eq("doctor_id", doctor_id)
        .in_("status", ["scheduled", "confirmed"])
        .gte("appointment_datetime", day_start)
        .lte("appointment_datetime", day_end)
        .execute()
    )
    slots = []
    for row in (res.data or []):
        dt = datetime.fromisoformat(row["appointment_datetime"].replace("Z", "+00:00"))
        slots.append(dt.strftime("%H:%M"))
    return slots


def get_free_slots(doctor_id: str, date_str: str, slot_minutes: int = 30) -> list[str]:
    """
    Вернуть список свободных HH:MM слотов врача на дату.
    Учитывает рабочие часы и уже занятые слоты.
    """
    doctor_res = _supabase.table("doctors").select("work_start,work_end").eq("id", doctor_id).execute()
    if not doctor_res.data:
        return []

    doc = doctor_res.data[0]
    start_h, start_m = map(int, doc["work_start"].split(":"))
    end_h,   end_m   = map(int, doc["work_end"].split(":"))

    busy = set(get_busy_slots(doctor_id, date_str))

    slots = []
    current = datetime.strptime(f"{date_str} {start_h:02d}:{start_m:02d}", "%Y-%m-%d %H:%M")
    end_dt  = datetime.strptime(f"{date_str} {end_h:02d}:{end_m:02d}", "%Y-%m-%d %H:%M")

    while current < end_dt:
        slot_str = current.strftime("%H:%M")
        if slot_str not in busy:
            slots.append(slot_str)
        current += timedelta(minutes=slot_minutes)

    return slots


# ── Записи на приём ───────────────────────────────────────────────────────────

def create_appointment(
    patient_id: str,
    doctor_id: str,
    appointment_datetime: str,  # ISO string
    notes: str = "",
) -> dict:
    res = _supabase.table("appointments").insert({
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "appointment_datetime": appointment_datetime,
        "notes": notes,
        "status": "scheduled",
    }).execute()
    return res.data[0]


def get_tomorrow_reminders() -> list[dict]:
    """Записи на завтра без напоминания (из VIEW tomorrow_reminders)."""
    res = _supabase.table("tomorrow_reminders").select("*").execute()
    return res.data or []


def mark_reminder_sent(appointment_id: str) -> None:
    _supabase.table("appointments").update({"reminder_sent": True}).eq("id", appointment_id).execute()


# ── Сессии звонков ────────────────────────────────────────────────────────────

def create_call_session(call_id: str, phone: str) -> dict:
    res = _supabase.table("call_sessions").insert({
        "call_id": call_id,
        "phone": phone,
        "state": "greeting",
        "context": {},
    }).execute()
    return res.data[0]


def get_call_session(call_id: str) -> Optional[dict]:
    res = _supabase.table("call_sessions").select("*").eq("call_id", call_id).execute()
    return res.data[0] if res.data else None


def update_call_session(call_id: str, **fields) -> dict:
    res = _supabase.table("call_sessions").update(fields).eq("call_id", call_id).execute()
    return res.data[0]


def end_call_session(call_id: str, status: str = "completed") -> None:
    _supabase.table("call_sessions").update({
        "status": status,
        "ended_at": datetime.utcnow().isoformat(),
    }).eq("call_id", call_id).execute()
