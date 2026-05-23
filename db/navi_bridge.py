import logging
import time
from pathlib import Path

import aiosqlite

from game_engine.constants import NAVI_DB_PATH

logger = logging.getLogger(__name__)


async def ensure_navi_tables() -> None:
    """Create Bamboozled-owned tables in the Navi DB if they don't already exist.

    Called once at bot startup. Safe to call when NAVI_DB_PATH is unset or the
    DB file doesn't exist yet — logs a warning and returns.
    """
    if not NAVI_DB_PATH:
        logger.warning("ensure_navi_tables: NAVI_DB_PATH not set — skipping.")
        return
    if not Path(NAVI_DB_PATH).exists():
        logger.warning("ensure_navi_tables: DB not found at %s — skipping.", NAVI_DB_PATH)
        return
    try:
        async with aiosqlite.connect(NAVI_DB_PATH) as db:
            # Queue table: Navi bot reads this to credit points.
            # INSERT OR IGNORE on game_id prevents double-awarding on bot restart.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS external_boli_points (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    username    TEXT    NOT NULL,
                    points      INTEGER NOT NULL,
                    source_game TEXT    NOT NULL,
                    game_id     TEXT    NOT NULL UNIQUE,
                    awarded_at  TEXT    DEFAULT (datetime('now'))
                )
            """)
            # Survival leaderboard / personal-best tracking.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS survival_scores (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id      TEXT    NOT NULL UNIQUE,
                    user_id      INTEGER NOT NULL,
                    guild_id     INTEGER NOT NULL,
                    username     TEXT    NOT NULL,
                    streak       INTEGER NOT NULL,
                    difficulty   TEXT    NOT NULL,
                    category     TEXT,
                    boli_awarded INTEGER NOT NULL,
                    played_at    TEXT    DEFAULT (datetime('now'))
                )
            """)
            await db.commit()
        logger.info("ensure_navi_tables: Navi DB tables verified/created.")
    except Exception as exc:
        logger.error("ensure_navi_tables: failed — %s", exc)


async def award_boli(
    user_id: int,
    username: str,
    amount: int,
    reason: str,
    game_id: str | None = None,
    source_game: str = "bamboozled",
) -> bool:
    """Award Boli Points via the external_boli_points queue in Navi's database.

    Strategy:
    1. Try a direct UPDATE on user_stats (works if the user already exists in Navi).
       Tries both int and str forms of user_id to handle TEXT-affinity columns.
    2. If the UPDATE matched 0 rows (user not in Navi yet), fall back to inserting
       into the external_boli_points queue so Navi can process it later.

    Returns True if the award was queued or directly applied, False on failure.
    """
    if not NAVI_DB_PATH:
        logger.warning("Boli bridge: NAVI_DB_PATH not configured — skipping.")
        return False
    if not Path(NAVI_DB_PATH).exists():
        logger.warning("Boli bridge: DB not found at %s — skipping.", NAVI_DB_PATH)
        return False

    gid = game_id or f"{source_game}_{user_id}_{int(time.time())}"

    try:
        async with aiosqlite.connect(NAVI_DB_PATH) as db:
            # Try direct UPDATE — attempt int first, then str, to handle type affinity mismatches.
            for uid_val in (user_id, str(user_id)):
                cursor = await db.execute(
                    "UPDATE user_stats SET boli_points = boli_points + ? WHERE user_id = ?",
                    (amount, uid_val),
                )
                if cursor.rowcount > 0:
                    await db.commit()
                    logger.info(
                        "Boli bridge: +%d directly credited to user %d (%s)", amount, user_id, reason
                    )
                    return True

            # User not found in user_stats — insert into the processing queue.
            await db.execute(
                "INSERT OR IGNORE INTO external_boli_points "
                "    (user_id, username, points, source_game, game_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, username, amount, source_game, gid),
            )
            await db.commit()
            logger.info(
                "Boli bridge: +%d queued for user %d (%s) — user not in user_stats yet.",
                amount, user_id, reason,
            )
            return True

    except Exception as exc:
        logger.warning("Boli bridge: failed — %s", exc)
        return False
