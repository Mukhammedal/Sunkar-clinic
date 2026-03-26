"""
Генерация голоса через ElevenLabs TTS API.
Аудио кэшируется в папке audio_cache/ и отдаётся по HTTP.
"""

from __future__ import annotations
import os
import uuid
import asyncio
import logging
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_API_KEY      = os.getenv("ELEVENLABS_API_KEY", "")
_VOICE_RU     = os.getenv("ELEVENLABS_VOICE_ID_RU", "EXAVITQu4vr4xnSDxMaL")
_VOICE_KZ     = os.getenv("ELEVENLABS_VOICE_ID_KZ", "EXAVITQu4vr4xnSDxMaL")
_MODEL        = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
_SERVER_URL   = os.getenv("SERVER_URL", "http://localhost:8000")

AUDIO_DIR = Path("audio_cache")
AUDIO_DIR.mkdir(exist_ok=True)

_BASE_URL = "https://api.elevenlabs.io/v1"


def _get_voice_id(lang: str) -> str:
    return _VOICE_KZ if lang == "kz" else _VOICE_RU


async def text_to_speech(text: str, lang: str = "ru") -> str:
    """
    Конвертирует текст в MP3 через ElevenLabs.
    Возвращает публичный URL аудиофайла.
    """
    voice_id = _get_voice_id(lang)
    filename = f"{uuid.uuid4().hex}.mp3"
    filepath = AUDIO_DIR / filename

    headers = {
        "xi-api-key": _API_KEY,
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": _MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }

    logger.info(f"ElevenLabs key (first 10): {_API_KEY[:10]!r}, len={len(_API_KEY)}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_BASE_URL}/text-to-speech/{voice_id}",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        filepath.write_bytes(resp.content)

    audio_url = f"{_SERVER_URL}/audio/{filename}"
    logger.info(f"ElevenLabs TTS generated: {audio_url}")
    return audio_url


async def cleanup_old_audio(max_age_hours: int = 24) -> None:
    """Удаляет аудиофайлы старше max_age_hours часов."""
    import time
    now = time.time()
    deleted = 0
    for f in AUDIO_DIR.glob("*.mp3"):
        if now - f.stat().st_mtime > max_age_hours * 3600:
            f.unlink(missing_ok=True)
            deleted += 1
    if deleted:
        logger.info(f"Cleaned up {deleted} old audio files")
