"""Opt-out and opt-in (spec 10.3).

State lives in its own file, privacy.db, which is never purged: `privacy_state(user_id, status 'out'|'in', changed_at)`.
Opting out, in this order: write the state to privacy.db FIRST, add the id to an in-memory set (so the game server
refuses them at once), then in one transaction delete the user's rows from match_results and stats and any match left
with no results, and forget their cached name. Names and avatars are never stored, so there is little to purge.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import aiosqlite

from ..db.connection import connect, db_path
from ..settings import Settings

DAY_S = 86_400
SCHEMA = """CREATE TABLE IF NOT EXISTS privacy_state (
  user_id INTEGER PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('out', 'in')),
  changed_at INTEGER NOT NULL)"""


def privacy_db_path() -> Path:
    return Path(os.getenv("BAMBOOZLED_PRIVACY_DB_PATH") or db_path().parent / "privacy.db")


@dataclass(frozen=True)
class Status:
    status: str  # 'out' | 'in'
    changed_at: Optional[int]
    can_opt_in_at: Optional[int]  # when an opted-out user may opt back in (None if they are in)


@dataclass(frozen=True)
class OptOutResult:
    outcome: str  # 'ok' | 'already' | 'in_game'
    purged: Optional[dict] = None


@dataclass(frozen=True)
class OptInResult:
    outcome: str  # 'ok' | 'already' | 'cooldown'
    retry_at: Optional[int] = None


class PrivacyService:
    def __init__(
        self,
        settings: Settings,
        clock: Callable[[], float] = time.time,
        forget_name: Optional[Callable[[int], None]] = None,
        in_running_game: Optional[Callable[[int], bool]] = None,
        evict: Optional[Callable[[int], None]] = None,
    ):
        self.settings, self.clock = settings, clock
        self.forget_name = forget_name or (lambda _uid: None)
        self.in_running_game = in_running_game or (lambda _uid: False)
        self.evict = evict or (lambda _uid: None)
        self._out: set[int] = set()
        self._loaded = False

    # ───────────── in-memory view (what every enforcement point asks) ─────────────
    def is_opted_out(self, user_id: int) -> bool:
        return user_id in self._out

    def filter_in(self, user_ids):
        return [u for u in user_ids if u not in self._out]

    async def load(self) -> int:
        path = privacy_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(path) as db:
            await db.execute(SCHEMA)
            await db.commit()
            rows = await (await db.execute("SELECT user_id FROM privacy_state WHERE status = 'out'")).fetchall()
        self._out = {r[0] for r in rows}
        self._loaded = True
        return len(self._out)

    async def _row(self, user_id: int) -> Optional[tuple[str, int]]:
        async with aiosqlite.connect(privacy_db_path()) as db:
            await db.execute(SCHEMA)
            row = await (
                await db.execute("SELECT status, changed_at FROM privacy_state WHERE user_id = ?", (user_id,))
            ).fetchone()
        return (row[0], row[1]) if row else None

    async def _write(self, user_id: int, status: str) -> int:
        now = int(self.clock())
        async with aiosqlite.connect(privacy_db_path()) as db:
            await db.execute(SCHEMA)
            await db.execute(
                "INSERT INTO privacy_state (user_id, status, changed_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET status = excluded.status, changed_at = excluded.changed_at",
                (user_id, status, now),
            )
            await db.commit()
        return now

    def _cooldown_ends(self, changed_at: int) -> int:
        return changed_at + int(self.settings.get("privacy.optin_cooldown_days")) * DAY_S

    # ───────────── the three actions ─────────────
    async def status(self, user_id: int) -> Status:
        row = await self._row(user_id)
        if row is None or row[0] == "in":
            return Status("in", row[1] if row else None, None)
        return Status("out", row[1], self._cooldown_ends(row[1]))

    async def opt_out(self, user_id: int) -> OptOutResult:
        if user_id in self._out:
            return OptOutResult("already")
        if self.settings.get("privacy.block_during_game") and self.in_running_game(user_id):
            return OptOutResult("in_game")
        await self._write(user_id, "out")  # 1. the durable record first
        self._out.add(user_id)  # 2. refuse them everywhere at once
        self.evict(user_id)  #    and take them out of any room they are sitting in
        purged = await self._purge(user_id)  # 3. one transaction over the results
        self.forget_name(user_id)  # 4. the cached display name
        return OptOutResult("ok", purged)

    async def opt_in(self, user_id: int) -> OptInResult:
        row = await self._row(user_id)
        if row is None or row[0] == "in":
            return OptInResult("already")
        ends = self._cooldown_ends(row[1])
        if self.clock() < ends:
            return OptInResult("cooldown", ends)
        await self._write(user_id, "in")  # restores nothing: the next game starts a fresh profile
        self._out.discard(user_id)
        return OptInResult("ok")

    async def _purge(self, user_id: int) -> dict:
        async with connect() as db:
            await db.execute("BEGIN")
            try:
                results = (await db.execute("DELETE FROM match_results WHERE user_id = ?", (user_id,))).rowcount
                stats = (await db.execute("DELETE FROM stats WHERE user_id = ?", (user_id,))).rowcount
                matches = (
                    await db.execute("DELETE FROM matches WHERE match_id NOT IN (SELECT DISTINCT match_id FROM match_results)")
                ).rowcount
                await db.execute("COMMIT")
            except Exception:
                await db.execute("ROLLBACK")
                raise
        return {"match_results": results, "stats": stats, "matches": matches}
