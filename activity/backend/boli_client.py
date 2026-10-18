from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger("bamboozled.activity.boli_client")


async def award_boli(session_id: str, awards: dict[str, int]) -> bool:
    """POST boli awards to the bot's internal API.

    awards: { discord_id: boli_amount }
    Returns True on success.
    """
    if not settings.BOT_INTERNAL_SECRET:
        logger.warning("BOT_INTERNAL_SECRET not set — skipping Boli award.")
        return False

    url = f"{settings.BOT_INTERNAL_API_URL}/internal/boli/award"
    payload = {
        "game_id": session_id,
        "source_game": "bamboozled_activity",
        "awards": awards,
    }
    headers = {"X-Internal-Secret": settings.BOT_INTERNAL_SECRET}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                logger.info("Boli awards submitted for session %s: %s", session_id, awards)
                return True
            logger.warning(
                "Boli award failed: HTTP %d — %s", resp.status_code, resp.text[:200]
            )
            return False
    except Exception as exc:
        logger.warning("Boli award request failed: %s", exc)
        return False
