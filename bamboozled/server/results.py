"""Adapters from the room manager to the database (and, later, the result card in Discord)."""
from __future__ import annotations

from datetime import datetime, timezone

from ..db.repos.matches import ResultRow, record_match


async def db_recorder(mode: str, guild_id: int, rows: list, *, started_ms: int, cfg: dict) -> str:
    """Write one finished game (or one Survival run) in a single transaction. Ids and numbers only."""
    return await record_match(
        mode, guild_id, [ResultRow(r.user_id, r.rank, r.score, r.correct, dict(r.details)) for r in rows],
        started_at=datetime.now(timezone.utc).isoformat(), rounds=cfg.get("rounds"),
        difficulty=cfg.get("difficulty") or ("medium" if mode == "survival" else None), category=cfg.get("category"))
