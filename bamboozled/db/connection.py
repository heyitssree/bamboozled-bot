"""SQLite access. One file, path from BAMBOOZLED_DB_PATH (default data/bamboozled.db)."""
import os
from pathlib import Path

import aiosqlite

ROOT = Path(__file__).resolve().parents[2]


def db_path() -> Path:
    return Path(os.getenv("BAMBOOZLED_DB_PATH") or ROOT / "data" / "bamboozled.db")


def connect() -> aiosqlite.Connection:
    """Use as `async with connect() as db`. Foreign keys are on so ON DELETE CASCADE works."""
    return _Connect()


class _Connect:
    async def __aenter__(self) -> aiosqlite.Connection:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(path)
        await self._db.execute("PRAGMA foreign_keys = ON")
        self._db.row_factory = aiosqlite.Row
        return self._db

    async def __aexit__(self, *exc):
        await self._db.close()
