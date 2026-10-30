"""Read-side queries for stats and leaderboards. Every ordering ends in user_id so ties are deterministic."""
from typing import Optional

from bamboozled.db.connection import connect


async def player_stats(user_id: int, mode: str = "bamboozled") -> Optional[dict]:
    async with connect() as db:
        cur = await db.execute("SELECT * FROM stats WHERE user_id = ? AND mode = ?", (user_id, mode))
        row = await cur.fetchone()
    return dict(row) if row else None


async def survival_best(user_id: int, difficulty: str, category: Optional[str]) -> int:
    """Highest streak this user has reached at this difficulty and category (None = any category)."""
    sql = ("SELECT COALESCE(MAX(r.score), 0) FROM match_results r JOIN matches m USING (match_id) "
           "WHERE m.mode = 'survival' AND r.user_id = ? AND m.difficulty = ? AND ")
    args: list = [user_id, difficulty]
    if category:
        sql += "m.category = ?"
        args.append(category)
    else:
        sql += "m.category IS NULL"
    async with connect() as db:
        cur = await db.execute(sql, args)
        return (await cur.fetchone())[0]


async def bamboozled_board(guild_id: Optional[int], limit: int = 100) -> list[dict]:
    """Wins first, then points. guild_id None = everywhere."""
    if guild_id is None:
        sql = ("SELECT user_id, games, wins, total_score FROM stats WHERE mode = 'bamboozled' "
               "ORDER BY wins DESC, total_score DESC, user_id ASC LIMIT ?")
        args: tuple = (limit,)
    else:
        sql = ("SELECT r.user_id AS user_id, COUNT(*) AS games, SUM(r.rank = 1) AS wins, "
               "SUM(MAX(r.score, 0)) AS total_score FROM match_results r JOIN matches m USING (match_id) "
               "WHERE m.mode = 'bamboozled' AND m.guild_id = ? GROUP BY r.user_id "
               "ORDER BY wins DESC, total_score DESC, user_id ASC LIMIT ?")
        args = (guild_id, limit)
    async with connect() as db:
        return [dict(r) for r in await (await db.execute(sql, args)).fetchall()]


async def fff_board(guild_id: Optional[int], limit: int = 100) -> list[dict]:
    """Best single games: most correct answers, then fastest average response."""
    where = "" if guild_id is None else "AND m.guild_id = ?"
    sql = (f"SELECT r.user_id AS user_id, r.correct AS correct_answers, "
           f"json_extract(r.details, '$.total_questions') AS total_questions, "
           f"json_extract(r.details, '$.avg_response_ms') AS avg_response_ms, m.ended_at AS played_at "
           f"FROM match_results r JOIN matches m USING (match_id) WHERE m.mode = 'fff' {where} "
           f"ORDER BY r.correct DESC, COALESCE(json_extract(r.details, '$.avg_response_ms'), 1e18) ASC, "
           f"r.user_id ASC LIMIT ?")
    args = (limit,) if guild_id is None else (guild_id, limit)
    async with connect() as db:
        return [dict(r) for r in await (await db.execute(sql, args)).fetchall()]


async def survival_board(guild_id: Optional[int], limit: int = 100) -> list[dict]:
    where = "" if guild_id is None else "AND m.guild_id = ?"
    sql = (f"SELECT r.user_id AS user_id, r.score AS streak, m.difficulty AS difficulty, m.category AS category, "
           f"m.ended_at AS played_at FROM match_results r JOIN matches m USING (match_id) "
           f"WHERE m.mode = 'survival' {where} ORDER BY r.score DESC, m.ended_at ASC, r.user_id ASC LIMIT ?")
    args = (limit,) if guild_id is None else (guild_id, limit)
    async with connect() as db:
        return [dict(r) for r in await (await db.execute(sql, args)).fetchall()]


async def reset_bamboozled() -> int:
    """Admin reset: remove every Bamboozled-mode match, result and stat. Returns the number of players cleared."""
    async with connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM stats WHERE mode = 'bamboozled'")
        n = (await cur.fetchone())[0]
        await db.execute("DELETE FROM matches WHERE mode = 'bamboozled'")   # results cascade
        await db.execute("DELETE FROM stats WHERE mode = 'bamboozled'")
        await db.commit()
    return n
