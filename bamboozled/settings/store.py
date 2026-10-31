"""Settings overrides live in the `settings` table as JSON; every change records who made it."""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..db.connection import connect
from . import BY_KEY, Settings, SettingError

log = logging.getLogger("bamboozled.settings")


async def load(settings: Settings) -> int:
    """Apply stored overrides. An unknown key or an invalid value stops start-up: a typo must not go unnoticed."""
    async with connect() as db:
        rows = await (await db.execute("SELECT key, value FROM settings")).fetchall()
    unknown = [r["key"] for r in rows if r["key"] not in BY_KEY]
    if unknown:
        raise SettingError(f"The database holds unknown setting(s): {', '.join(unknown)}. Remove them or upgrade the bot.")
    settings.update({r["key"]: json.loads(r["value"]) for r in rows})
    return len(rows)


async def save(key: str, value, user_id: Optional[int]) -> None:
    async with connect() as db:
        await db.execute(
            "INSERT INTO settings (key, value, updated_by, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, "
            "updated_at = CURRENT_TIMESTAMP",
            (key, json.dumps(value), user_id),
        )
        await db.commit()


async def delete(key: str) -> None:
    async with connect() as db:
        await db.execute("DELETE FROM settings WHERE key = ?", (key,))
        await db.commit()


async def who_changed(key: str) -> Optional[tuple[Optional[int], str]]:
    async with connect() as db:
        row = await (await db.execute("SELECT updated_by, updated_at FROM settings WHERE key = ?", (key,))).fetchone()
    return (row["updated_by"], row["updated_at"]) if row else None
