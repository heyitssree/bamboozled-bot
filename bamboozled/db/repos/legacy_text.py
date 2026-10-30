"""State that only the legacy text mode needs (orphan notices after a restart, per-server test mode).
Replaced by in-memory rooms and the settings registry in Phase 5; deleted with the text mode."""
from bamboozled.db.connection import connect


async def register_active_channel(channel_id: str) -> None:
    async with connect() as db:
        await db.execute("INSERT OR IGNORE INTO active_channels (channel_id) VALUES (?)", (channel_id,))
        await db.commit()


async def unregister_active_channel(channel_id: str) -> None:
    async with connect() as db:
        await db.execute("DELETE FROM active_channels WHERE channel_id = ?", (channel_id,))
        await db.commit()


async def get_orphaned_channels() -> list[str]:
    async with connect() as db:
        rows = await (await db.execute("SELECT channel_id FROM active_channels")).fetchall()
        await db.execute("DELETE FROM active_channels")
        await db.commit()
    return [r[0] for r in rows]


async def get_test_mode(guild_id: str) -> bool:
    async with connect() as db:
        row = await (await db.execute("SELECT test_mode FROM server_settings WHERE guild_id = ?", (guild_id,))).fetchone()
    return bool(row[0]) if row else False


async def set_test_mode(guild_id: str, enabled: bool) -> None:
    async with connect() as db:
        await db.execute(
            "INSERT INTO server_settings (guild_id, test_mode) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET test_mode = excluded.test_mode", (guild_id, 1 if enabled else 0))
        await db.commit()
