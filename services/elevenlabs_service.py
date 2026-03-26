"""
Генерация голоса через Google Cloud Text-to-Speech API.
Аудио кэшируется в папке audio_cache/ и отдаётся по HTTP.
"""

from __future__ import annotations
import os
import uuid
import base64
import logging
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_API_KEY    = os.getenv("GOOGLE_TTS_API_KEY", "")
_SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")

AUDIO_DIR = Path("audio_cache")
AUDIO_DIR.mkdir(exist_ok=True)

_BASE_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"

_VOICE_MAP = {
    "ru": {"languageCode": "ru-RU", "name": "ru-RU-Wavenet-C", "ssmlGender": "FEMALE"},
    "kz": {"languageCode": "kk-KZ", "ssmlGender": "FEMALE"},
}


async def text_to_speech(text: str, lang: str = "ru") -> str:
    """
    Конвертирует текст в MP3 через Google Cloud TTS.
    Возвращает публичный URL аудиофайла.
    """
    voice = _VOICE_MAP.get(lang, _VOICE_MAP["ru"])
    filename = f"{uuid.uuid4().hex}.mp3"
    filepath = AUDIO_DIR / filename

    payload = {
        "input": {"text": text},
        "voice": voice,
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.0},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _BASE_URL,
            params={"key": _API_KEY},
            json=payload,
        )
        if resp.status_code != 200:
            logger.error(f"Google TTS error {resp.status_code}: {resp.text}")
        resp.raise_for_status()

        audio_content = resp.json()["audioContent"]
        filepath.write_bytes(base64.b64decode(audio_content))

    audio_url = f"{_SERVER_URL}/audio/{filename}"
    logger.info(f"Google TTS generated: {audio_url}")
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
