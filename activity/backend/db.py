from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from config import settings

logger = logging.getLogger("bamboozled.activity.db")

_CREATE_TABLES = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS game_sessions (
    session_id  TEXT PRIMARY KEY,
    guild_id    TEXT NOT NULL,
    channel_id  TEXT NOT NULL,
    host_id     TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    total_rounds INTEGER NOT NULL,
    difficulty  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES game_sessions(session_id),
    discord_id  TEXT NOT NULL,
    username    TEXT NOT NULL,
    final_score INTEGER NOT NULL,
    rank        INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_results_session ON game_results(session_id);
CREATE INDEX IF NOT EXISTS idx_results_user ON game_results(discord_id);
"""


async def init_db() -> None:
    db_path = Path(settings.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_CREATE_TABLES)
        await db.commit()
    logger.info("Activity DB initialised at %s", db_path)


async def record_session(
    session_id: str,
    guild_id: str,
    channel_id: str,
    host_id: str,
    total_rounds: int,
    difficulty: str,
) -> None:
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO game_sessions
                (session_id, guild_id, channel_id, host_id, started_at, total_rounds, difficulty)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                guild_id,
                channel_id,
                host_id,
                datetime.now(timezone.utc).isoformat(),
                total_rounds,
                difficulty,
            ),
        )
        await db.commit()


async def close_session(session_id: str) -> None:
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute(
            "UPDATE game_sessions SET ended_at = ? WHERE session_id = ?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )
        await db.commit()


async def record_results(
    session_id: str,
    results: list[dict],  # {discord_id, username, final_score, rank}
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.executemany(
            """
            INSERT INTO game_results
                (session_id, discord_id, username, final_score, rank, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    session_id,
                    r["discord_id"],
                    r["username"],
                    r["final_score"],
                    r["rank"],
                    now,
                )
                for r in results
            ],
        )
        await db.commit()
