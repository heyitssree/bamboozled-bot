"""Numbered SQL migrations: migrations/NNNN_name.sql, applied in order, each in one transaction.

The runner owns the schema_version table. It refuses to touch a database that is newer than the code.
A database created before migrations existed (it has the v1 `players` table) is stamped as version 1.
"""
import asyncio
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    pass


def available() -> list[tuple[int, Path]]:
    found = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = _NAME.match(p.name)
        if not m:
            raise MigrationError(f"bad migration file name: {p.name}")
        found.append((int(m.group(1)), p))
    versions = [v for v, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"migration numbers must be 1..N without gaps, got {versions}")
    return found


def current_version(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]


def migrate(path: Path | str) -> int:
    """Apply pending migrations to the database at `path`. Returns the resulting version."""
    migrations = available()
    latest = migrations[-1][0] if migrations else 0
    con = sqlite3.connect(path, isolation_level=None)  # explicit transactions below
    try:
        con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        version = current_version(con)
        if version == 0 and con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='players'").fetchone():
            _stamp(con, 1)           # pre-migration v1 database: the baseline is already in place
            version = 1
        if version > latest:
            raise MigrationError(f"database is at version {version} but this code only knows up to {latest}")
        for number, file in migrations:
            if number <= version:
                continue
            con.execute("BEGIN")
            try:
                for statement in _statements(file.read_text()):
                    con.execute(statement)
                _stamp(con, number)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return current_version(con)
    finally:
        con.close()


def _stamp(con: sqlite3.Connection, version: int) -> None:
    con.execute("INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()))


def _statements(sql: str) -> list[str]:
    """Split a script into statements. Migration files must not contain semicolons inside strings or triggers."""
    cleaned = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [s.strip() for s in cleaned.split(";") if s.strip()]


async def migrate_async(path: Path | str) -> int:
    return await asyncio.to_thread(migrate, path)
