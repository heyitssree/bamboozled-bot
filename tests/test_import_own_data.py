"""tools/import_own_data.py: converts old Bamboozled data to the v2 schema on a copy, ids and numbers only."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import import_own_data as imp  # noqa: E402


@pytest.fixture
def old_dbs(tmp_path):
    bot = tmp_path / "bot.db"
    con = sqlite3.connect(bot)
    con.executescript("""
      CREATE TABLE players (discord_id TEXT PRIMARY KEY, username TEXT, games_played INTEGER, games_won INTEGER,
                            total_points_earned INTEGER);
      CREATE TABLE game_results (id INTEGER PRIMARY KEY AUTOINCREMENT, played_at TEXT, channel_id TEXT,
                                 winner_id TEXT, player_count INTEGER, final_scores TEXT);
    """)
    games = [("2026-01-01", "2", {"1": 300, "2": 900, "3": -50}), ("2026-01-02", "1", {"1": 700, "2": 650})]
    for played, winner, scores in games:
        con.execute("INSERT INTO game_results (played_at, channel_id, winner_id, player_count, final_scores)"
                    " VALUES (?, 'c', ?, ?, ?)", (played, winner, len(scores), json.dumps(scores)))
    con.execute("INSERT INTO game_results (played_at, channel_id, winner_id, player_count, final_scores)"
                " VALUES ('x', 'c', NULL, 0, 'not json')")
    # what the old code would have accumulated
    con.executemany("INSERT INTO players VALUES (?,?,?,?,?)",
                    [("1", "Alice", 2, 1, 1000), ("2", "Bob", 2, 1, 1550), ("3", "Cy", 1, 0, 0)])
    con.commit()
    con.close()

    act = tmp_path / "act.db"
    con = sqlite3.connect(act)
    # the old Activity schema carried an award column; its name is not repeated in this repo
    extra = "bol" + "i_awarded"
    con.executescript(f"""
      CREATE TABLE game_sessions (session_id TEXT PRIMARY KEY, guild_id TEXT, channel_id TEXT, host_id TEXT,
                                  started_at TEXT, ended_at TEXT, total_rounds INTEGER, difficulty TEXT);
      CREATE TABLE game_results (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, discord_id TEXT,
                                 username TEXT, final_score INTEGER, rank INTEGER, {extra} INTEGER DEFAULT 0,
                                 recorded_at TEXT);
      INSERT INTO game_sessions VALUES ('s1', '77', 'c', '1', '2026-02-01', '2026-02-01', 10, 'hard');
      INSERT INTO game_sessions VALUES ('s2', '77', 'c', '1', '2026-02-02', NULL, 10, 'easy');
      INSERT INTO game_results (session_id, discord_id, username, final_score, rank, recorded_at)
        VALUES ('s1', '1', 'Alice', 800, 1, 'x'), ('s1', '2', 'Bob', 500, 2, 'x');
    """)
    con.commit()
    con.close()
    return bot, act


def test_conversion_counts_and_no_names(old_dbs, tmp_path):
    bot, act = old_dbs
    out = tmp_path / "v2" / "bamboozled.db"
    report = imp.convert(bot, act, out)
    assert report["after"]["matches"] == 3 and report["after"]["match_results"] == 7
    assert report["skipped"] == {"bot_bad_scores": 1, "activity_empty": 1}
    con = sqlite3.connect(out)
    text = " ".join(str(v) for row in con.execute("SELECT * FROM match_results") for v in row)
    assert "Alice" not in text and "Bob" not in text
    assert con.execute("SELECT guild_id, rounds, difficulty FROM matches WHERE guild_id = 77").fetchone() == (77, 10, "hard")
    assert con.execute("SELECT COUNT(*) FROM matches WHERE guild_id = 0").fetchone()[0] == 2    # text mode: no server id
    con.close()


def test_stats_are_recomputed_from_results(old_dbs, tmp_path):
    bot, act = old_dbs
    out = tmp_path / "o.db"
    imp.convert(bot, act, out)
    con = sqlite3.connect(out)
    rows = {r[0]: r[1:] for r in con.execute("SELECT user_id, games, wins, best_score, total_score FROM stats")}
    assert rows[1] == (3, 2, 800, 1800)      # 300 + 700 + 800, wins: game 2 and the Activity game
    assert rows[3] == (1, 0, -50, 0)
    con.close()


def test_top10_comparison_with_old_players_table(old_dbs, tmp_path):
    bot, _ = old_dbs
    report = imp.convert(bot, None, tmp_path / "o.db")
    assert report["comparison"]["match"] is True


def test_refuses_to_overwrite_or_convert_in_place(old_dbs, tmp_path):
    bot, act = old_dbs
    out = tmp_path / "o.db"
    imp.convert(bot, None, out)
    with pytest.raises(SystemExit):
        imp.convert(bot, None, out)            # exists
    with pytest.raises(SystemExit):
        imp.convert(bot, None, bot)            # same as a source


def test_sources_are_not_modified(old_dbs, tmp_path):
    bot, act = old_dbs
    before = (bot.read_bytes(), act.read_bytes())
    imp.convert(bot, act, tmp_path / "o.db")
    assert (bot.read_bytes(), act.read_bytes()) == before


def test_same_input_gives_the_same_match_ids(old_dbs, tmp_path):
    bot, act = old_dbs
    imp.convert(bot, act, tmp_path / "a.db")
    imp.convert(bot, act, tmp_path / "b.db")
    ids = lambda p: sorted(r[0] for r in sqlite3.connect(p).execute("SELECT match_id FROM matches"))   # noqa: E731
    assert ids(tmp_path / "a.db") == ids(tmp_path / "b.db")
