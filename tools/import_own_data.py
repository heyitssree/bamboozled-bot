"""Convert Bamboozled's OWN old data into the v2 schema, on a copy (never in place).

    python tools/import_own_data.py --bot-db db/bamboozled.db --activity-db <path> --out data/v2/bamboozled.db

Reads (read-only): the bot's `game_results` and the Activity's `game_sessions` + `game_results`.
Writes: matches, match_results and stats in a NEW database. Ids and numbers only; no usernames are copied.

Notes on what the old data cannot say:
  * the text-mode `game_results` table has a channel id but no server id, so those matches get guild_id 0
    (they count on global boards, not on per-server boards);
  * stats are recomputed from the imported results, so they stay consistent with match_results.
Prints per-table counts before and after and compares the Bamboozled top 10 old vs new.
"""
import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bamboozled.db.migrate import migrate  # noqa: E402
from bamboozled.db.repos.matches import ranked  # noqa: E402

NAMESPACE = uuid.UUID("5d4c3a52-6f33-4c58-a0d1-0b6c1f2f9f10")   # fixed, so re-running gives the same match ids


def _ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _has(con: sqlite3.Connection, table: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _counts(path: Path) -> dict[str, int]:
    con = _ro(path)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in sorted(names)}
    finally:
        con.close()


def _insert_match(out: sqlite3.Connection, match_id: str, guild_id: int, started: str, ended: str,
                  rounds, difficulty, results: list[tuple[int, int, int]]) -> None:
    out.execute("INSERT INTO matches (match_id, mode, guild_id, started_at, ended_at, rounds, difficulty,"
                " player_count) VALUES (?, 'bamboozled', ?, ?, ?, ?, ?, ?)",
                (match_id, guild_id, started, ended, rounds, difficulty, len(results)))
    for user_id, rank, score in results:
        out.execute("INSERT INTO match_results (match_id, user_id, rank, score, correct, details) VALUES (?,?,?,?,0,'{}')",
                    (match_id, user_id, rank, score))


def convert(bot_db: Path | None, activity_db: Path | None, out_path: Path) -> dict:
    if out_path.exists():
        raise SystemExit(f"refusing to overwrite {out_path}; choose a new --out path")
    for src in (bot_db, activity_db):
        if src and src.resolve() == out_path.resolve():
            raise SystemExit("--out must not be one of the source databases (no in-place conversion)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(out_path)
    out = sqlite3.connect(out_path)
    out.execute("PRAGMA foreign_keys = ON")
    skipped = {"bot_bad_scores": 0, "activity_empty": 0}
    bot_only: dict[int, list[tuple[int, int]]] = {}       # user -> [(rank, score)] from the text-mode data

    if bot_db:
        src = _ro(bot_db)
        if _has(src, "game_results"):
            for row in src.execute("SELECT id, played_at, winner_id, final_scores FROM game_results ORDER BY id"):
                try:
                    scores = {int(k): int(v) for k, v in json.loads(row["final_scores"] or "{}").items()}
                    winner = int(row["winner_id"]) if row["winner_id"] else None
                except (ValueError, TypeError):
                    skipped["bot_bad_scores"] += 1
                    continue
                if not scores:
                    skipped["bot_bad_scores"] += 1
                    continue
                ranks = ranked(scores, winner if winner in scores else None)
                played = row["played_at"] or ""
                _insert_match(out, str(uuid.uuid5(NAMESPACE, f"bot:{row['id']}")), 0, played, played, None, None,
                              [(u, r, scores[u]) for u, r in ranks])
                for u, r in ranks:
                    bot_only.setdefault(u, []).append((r, scores[u]))
        src.close()

    if activity_db:
        src = _ro(activity_db)
        if _has(src, "game_sessions") and _has(src, "game_results"):
            for s in src.execute("SELECT * FROM game_sessions ORDER BY started_at"):
                rows = src.execute("SELECT discord_id, final_score, rank FROM game_results WHERE session_id = ?",
                                   (s["session_id"],)).fetchall()
                if not rows:
                    skipped["activity_empty"] += 1
                    continue
                try:
                    guild = int(s["guild_id"])
                except (ValueError, TypeError):
                    guild = 0
                _insert_match(out, str(uuid.uuid5(NAMESPACE, f"activity:{s['session_id']}")), guild,
                              s["started_at"], s["ended_at"] or s["started_at"], s["total_rounds"], s["difficulty"],
                              [(int(r["discord_id"]), int(r["rank"]), int(r["final_score"])) for r in rows])
        src.close()

    out.execute("""INSERT INTO stats (user_id, mode, games, wins, best_score, total_score, best_streak)
                   SELECT r.user_id, 'bamboozled', COUNT(*), SUM(r.rank = 1), MAX(r.score),
                          SUM(MAX(r.score, 0)), 0
                   FROM match_results r JOIN matches m USING (match_id) WHERE m.mode = 'bamboozled'
                   GROUP BY r.user_id""")
    out.commit()

    # Compare the top 10 of the old `players` table with the same board built from the imported text-mode games.
    comparison = None
    if bot_db:
        src = _ro(bot_db)
        if _has(src, "players"):
            old = [(int(r["discord_id"]), r["games_won"], r["total_points_earned"]) for r in src.execute(
                "SELECT discord_id, games_won, total_points_earned FROM players WHERE games_played > 0")]
            old.sort(key=lambda t: (-t[1], -t[2], t[0]))
            new = [(u, sum(1 for r, _ in g if r == 1), sum(max(0, s) for _, s in g)) for u, g in bot_only.items()]
            new.sort(key=lambda t: (-t[1], -t[2], t[0]))
            comparison = {"old_top10": old[:10], "new_top10": new[:10], "match": old[:10] == new[:10]}
        src.close()
    out.close()
    return {"skipped": skipped, "comparison": comparison, "after": _counts(out_path)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bot-db", type=Path)
    ap.add_argument("--activity-db", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if not (a.bot_db or a.activity_db):
        ap.error("give at least one of --bot-db / --activity-db")
    for p in (a.bot_db, a.activity_db):
        if p and not p.is_file():
            ap.error(f"not found: {p}")
        if p:
            print(f"before: {p}")
            for t, n in _counts(p).items():
                print(f"  {t:<24}{n:>8}")
    report = convert(a.bot_db, a.activity_db, a.out)
    print(f"after: {a.out}")
    for t, n in report["after"].items():
        print(f"  {t:<24}{n:>8}")
    print(f"skipped: {report['skipped']}")
    c = report["comparison"]
    if c is not None:
        print(f"top 10 (wins, points) old players table vs imported text-mode games: {'SAME' if c['match'] else 'DIFFERENT'}")
        if not c["match"]:
            print("  old:", c["old_top10"])
            print("  new:", c["new_top10"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
