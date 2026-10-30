"""Recording finished games. Only ids and numbers are stored (never names or avatars)."""
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bamboozled.db.connection import connect

MODES = ("bamboozled", "fff", "survival")


@dataclass
class ResultRow:
    user_id: int
    rank: int
    score: int          # bamboozled: final points | fff: points | survival: streak
    correct: int = 0
    details: dict = field(default_factory=dict)


def ranked(scores: dict[int, int], winner: Optional[int] = None) -> list[tuple[int, int]]:
    """(user_id, rank) with a deterministic order: score high to low, then user_id. `winner` is forced to rank 1."""
    order = sorted(scores, key=lambda u: (u != winner, -scores[u], u))
    return [(u, i + 1) for i, u in enumerate(order)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def record_match(mode: str, guild_id: int, results: list[ResultRow], *, started_at: Optional[str] = None,
                       rounds: Optional[int] = None, difficulty: Optional[str] = None,
                       category: Optional[str] = None) -> str:
    """Write the match, its results and the stats updates in ONE transaction. Returns the match id."""
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    match_id = str(uuid.uuid4())
    ended = _now()
    async with connect() as db:
        await db.execute("BEGIN")
        try:
            await db.execute(
                "INSERT INTO matches (match_id, mode, guild_id, started_at, ended_at, rounds, difficulty, category,"
                " player_count) VALUES (?,?,?,?,?,?,?,?,?)",
                (match_id, mode, guild_id, started_at or ended, ended, rounds, difficulty, category, len(results)))
            for r in results:
                await db.execute(
                    "INSERT INTO match_results (match_id, user_id, rank, score, correct, details) VALUES (?,?,?,?,?,?)",
                    (match_id, r.user_id, r.rank, r.score, r.correct, json.dumps(r.details, sort_keys=True)))
                win = 1 if (r.rank == 1 and mode != "survival") else 0
                await db.execute(
                    """INSERT INTO stats (user_id, mode, games, wins, best_score, total_score, best_streak)
                       VALUES (?, ?, 1, ?, ?, ?, ?)
                       ON CONFLICT(user_id, mode) DO UPDATE SET
                         games = games + 1, wins = wins + excluded.wins,
                         best_score = MAX(best_score, excluded.best_score),
                         total_score = total_score + excluded.total_score,
                         best_streak = MAX(best_streak, excluded.best_streak)""",
                    (r.user_id, mode, win, r.score, max(0, r.score), r.score if mode == "survival" else 0))
            await db.execute("COMMIT")
        except Exception:
            await db.execute("ROLLBACK")
            raise
    return match_id
