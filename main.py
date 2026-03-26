"""
Медицинский голосовой AI-ассистент
Стек: Voximplant + ElevenLabs + Supabase + FastAPI

Запуск:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from api.call_handler import router as call_router
from api.twilio_handler import router as twilio_router
from scheduler.reminder_scheduler import start_scheduler
from services.elevenlabs_service import cleanup_old_audio

load_dotenv()

# ── Логирование ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ── Жизненный цикл приложения ─────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Создать папку для аудио
    Path("audio_cache").mkdir(exist_ok=True)

    # Запустить планировщик напоминаний
    scheduler = start_scheduler()

    logger.info("=" * 60)
    logger.info("  Medical Clinic AI Assistant — started")
    logger.info(f"  SERVER_URL : {os.getenv('SERVER_URL', 'http://localhost:8000')}")
    logger.info("=" * 60)

    yield

    # Очистить старые аудиофайлы при остановке
    await cleanup_old_audio()
    scheduler.shutdown()
    logger.info("Server stopped.")


# ── FastAPI приложение ────────────────────────────────────────────────────────
app = FastAPI(
    title="Medical Clinic AI Assistant",
    description="Голосовой ИИ-ассистент для медицинской клиники",
    version="1.0.0",
    lifespan=lifespan,
)

# Статические файлы — аудио для Voximplant
app.mount("/audio", StaticFiles(directory="audio_cache"), name="audio")

# API маршруты
app.include_router(call_router, prefix="/api")
app.include_router(twilio_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "medical-clinic-ai"}


# ── Точка входа ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("SERVER_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVER_PORT", "8000")),
        reload=True,
    )
