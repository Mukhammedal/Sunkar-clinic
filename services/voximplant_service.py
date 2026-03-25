"""
Интеграция с Voximplant Management API.
Используется для исходящих звонков-напоминаний.
"""

from __future__ import annotations
import os
import json
import logging

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_ACCOUNT_ID   = os.getenv("VOXIMPLANT_ACCOUNT_ID", "")
_API_KEY      = os.getenv("VOXIMPLANT_API_KEY", "")
_RULE_ID      = os.getenv("VOXIMPLANT_RULE_ID", "")       # ID правила для исходящих
_CALLER_ID    = os.getenv("VOXIMPLANT_CALLER_ID", "")

_VX_API = "https://api.voximplant.com/platform_api"


async def make_outbound_call(to_number: str, custom_data: dict) -> bool:
    """
    Инициировать исходящий звонок через Voximplant.
    custom_data передаётся в VoxEngine через VoxEngine.customData().
    """
    if not _RULE_ID:
        logger.warning("VOXIMPLANT_RULE_ID не задан — исходящий звонок пропущен")
        return False

    params = {
        "account_id": _ACCOUNT_ID,
        "api_key":    _API_KEY,
        "rule_id":    _RULE_ID,
        "script_custom_data": json.dumps(custom_data, ensure_ascii=False),
        "reference_to_call_id": "",
        # Номер получателя передаётся через customData, сам набор —
        # в сценарии VoxEngine через VoxEngine.callPSTN()
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_VX_API}/StartScenarios/",
            data=params,
        )
        data = resp.json()

    if data.get("error"):
        logger.error(f"Voximplant error: {data['error']}")
        return False

    logger.info(f"Outbound call started to {to_number}: {data}")
    return True
