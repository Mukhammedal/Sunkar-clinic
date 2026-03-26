"""
API эндпоинты для веб-портала клиники.
"""

from __future__ import annotations
import logging
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services import supabase_service as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portal", tags=["portal"])


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_dashboard():
    """Статистика для главной страницы."""
    try:
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        supabase = db._supabase

        # Звонки сегодня
        calls_today = supabase.table("call_sessions") \
            .select("*", count="exact") \
            .gte("started_at", f"{today}T00:00:00") \
            .execute()

        # Записи сегодня
        appointments_today = supabase.table("appointments") \
            .select("*", count="exact") \
            .gte("created_at", f"{today}T00:00:00") \
            .execute()

        # Переводы на оператора сегодня
        transfers_today = supabase.table("call_sessions") \
            .select("*", count="exact") \
            .eq("status", "transfer") \
            .gte("started_at", f"{today}T00:00:00") \
            .execute()

        # Всего пациентов
        total_patients = supabase.table("patients") \
            .select("*", count="exact") \
            .execute()

        # Последние 10 звонков
        recent_calls = supabase.table("call_sessions") \
            .select("*") \
            .order("started_at", desc=True) \
            .limit(10) \
            .execute()

        # Звонки по часам за сегодня
        calls_by_hour_raw = supabase.table("call_sessions") \
            .select("started_at") \
            .gte("started_at", f"{today}T00:00:00") \
            .execute()

        calls_by_hour = [0] * 24
        for row in (calls_by_hour_raw.data or []):
            try:
                dt = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
                calls_by_hour[dt.hour] += 1
            except Exception:
                pass

        # Предстоящие записи на сегодня
        upcoming = supabase.table("appointments") \
            .select("*, patients(full_name, phone), doctors(full_name, specialization_ru)") \
            .gte("appointment_datetime", f"{today}T00:00:00") \
            .lte("appointment_datetime", f"{today}T23:59:59") \
            .eq("status", "scheduled") \
            .order("appointment_datetime") \
            .execute()

        return {
            "stats": {
                "calls_today": calls_today.count or 0,
                "appointments_today": appointments_today.count or 0,
                "transfers_today": transfers_today.count or 0,
                "total_patients": total_patients.count or 0,
            },
            "calls_by_hour": calls_by_hour,
            "recent_calls": recent_calls.data or [],
            "upcoming_appointments": upcoming.data or [],
        }
    except Exception as e:
        logger.exception(f"Dashboard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Пациенты ──────────────────────────────────────────────────────────────────

@router.get("/patients")
async def get_patients(
    search: str = Query(default=""),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
):
    try:
        supabase = db._supabase
        query = supabase.table("patients").select("*", count="exact")

        if search:
            query = query.or_(f"full_name.ilike.%{search}%,phone.ilike.%{search}%")

        result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        return {"patients": result.data or [], "total": result.count or 0}
    except Exception as e:
        logger.exception(f"Get patients error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/patients/{patient_id}")
async def get_patient(patient_id: str):
    try:
        supabase = db._supabase
        patient = supabase.table("patients").select("*").eq("id", patient_id).execute()
        if not patient.data:
            raise HTTPException(status_code=404, detail="Patient not found")

        appointments = supabase.table("appointments") \
            .select("*, doctors(full_name, specialization_ru)") \
            .eq("patient_id", patient_id) \
            .order("appointment_datetime", desc=True) \
            .execute()

        return {
            "patient": patient.data[0],
            "appointments": appointments.data or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Записи на приём ───────────────────────────────────────────────────────────

@router.get("/appointments")
async def get_appointments(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    doctor_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
):
    try:
        supabase = db._supabase
        query = supabase.table("appointments") \
            .select("*, patients(full_name, phone, language), doctors(full_name, specialization_ru)", count="exact")

        if date_from:
            query = query.gte("appointment_datetime", f"{date_from}T00:00:00")
        if date_to:
            query = query.lte("appointment_datetime", f"{date_to}T23:59:59")
        if doctor_id:
            query = query.eq("doctor_id", doctor_id)
        if status:
            query = query.eq("status", status)

        result = query.order("appointment_datetime", desc=True).range(offset, offset + limit - 1).execute()
        return {"appointments": result.data or [], "total": result.count or 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UpdateStatusRequest(BaseModel):
    status: str  # scheduled | confirmed | cancelled | completed


@router.put("/appointments/{appointment_id}/status")
async def update_appointment_status(appointment_id: str, req: UpdateStatusRequest):
    try:
        supabase = db._supabase
        result = supabase.table("appointments") \
            .update({"status": req.status}) \
            .eq("id", appointment_id) \
            .execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Appointment not found")
        return {"ok": True, "appointment": result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Врачи ─────────────────────────────────────────────────────────────────────

@router.get("/doctors")
async def get_doctors():
    try:
        supabase = db._supabase
        result = supabase.table("doctors").select("*").order("full_name").execute()
        return {"doctors": result.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class DoctorRequest(BaseModel):
    full_name: str
    specialization: str
    specialization_ru: str = ""
    specialization_kz: str = ""
    phone: str = ""
    work_start: str = "09:00"
    work_end: str = "18:00"
    slot_minutes: int = 30
    is_active: bool = True


@router.post("/doctors")
async def create_doctor(req: DoctorRequest):
    try:
        supabase = db._supabase
        result = supabase.table("doctors").insert(req.dict()).execute()
        return {"ok": True, "doctor": result.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/doctors/{doctor_id}")
async def update_doctor(doctor_id: str, req: DoctorRequest):
    try:
        supabase = db._supabase
        result = supabase.table("doctors").update(req.dict()).eq("id", doctor_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Doctor not found")
        return {"ok": True, "doctor": result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/doctors/{doctor_id}")
async def delete_doctor(doctor_id: str):
    try:
        supabase = db._supabase
        supabase.table("doctors").update({"is_active": False}).eq("id", doctor_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Звонки ────────────────────────────────────────────────────────────────────

@router.get("/calls")
async def get_calls(
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    status: Optional[str] = Query(default=None),
):
    try:
        supabase = db._supabase
        query = supabase.table("call_sessions") \
            .select("*, patients(full_name)", count="exact")

        if status:
            query = query.eq("status", status)

        result = query.order("started_at", desc=True).range(offset, offset + limit - 1).execute()
        return {"calls": result.data or [], "total": result.count or 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calls/{call_id}")
async def get_call(call_id: str):
    try:
        supabase = db._supabase
        result = supabase.table("call_sessions") \
            .select("*, patients(full_name, phone)") \
            .eq("call_id", call_id) \
            .execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Call not found")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
