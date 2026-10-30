"""Migrations, match recording, stats and leaderboards (the v2 storage layer)."""
import asyncio
import json
import sqlite3

import pytest

from bamboozled.db import migrate as M
from bamboozled.db.repos import legacy_text, stats
from bamboozled.db.repos.matches import ResultRow, ranked, record_match

run = asyncio.run


def tables(path):
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


class TestMigrations:
    def test_fresh_database_reaches_latest(self, tmp_path):
        path = tmp_path / "a.db"
        assert M.migrate(path) == 2
        assert {"matches", "match_results", "stats", "settings", "schema_version"} <= tables(path)

    def test_rerun_is_a_noop(self, tmp_path):
        path = tmp_path / "a.db"
        M.migrate(path)
        assert M.migrate(path) == 2

    def test_old_v1_database_is_stamped_and_upgraded_without_losing_rows(self, tmp_path):
        path = tmp_path / "old.db"
        con = sqlite3.connect(path)
        con.executescript(
            "CREATE TABLE players (discord_id TEXT PRIMARY KEY, username TEXT, games_played INTEGER DEFAULT 0,"
            " games_won INTEGER DEFAULT 0, total_points_earned INTEGER DEFAULT 0);"
            "INSERT INTO players VALUES ('1', 'Old', 3, 1, 900);")
        con.commit()
        con.close()
        assert M.migrate(path) == 2
        con = sqlite3.connect(path)
        assert con.execute("SELECT username FROM players").fetchone() == ("Old",)
        con.close()

    def test_refuses_a_database_newer_than_the_code(self, tmp_path):
        path = tmp_path / "new.db"
        M.migrate(path)
        con = sqlite3.connect(path)
        con.execute("INSERT INTO schema_version VALUES (99, 'x')")
        con.commit()
        con.close()
        with pytest.raises(M.MigrationError):
            M.migrate(path)

    def test_failed_migration_rolls_back(self, tmp_path, monkeypatch):
        d = tmp_path / "m"
        d.mkdir()
        (d / "0001_ok.sql").write_text("CREATE TABLE a (x INTEGER);")
        (d / "0002_bad.sql").write_text("CREATE TABLE b (x INTEGER); CREATE TABLE b (x INTEGER);")
        monkeypatch.setattr(M, "MIGRATIONS_DIR", d)
        path = tmp_path / "r.db"
        with pytest.raises(sqlite3.OperationalError):
            M.migrate(path)
        assert "b" not in tables(path) and "a" in tables(path)
        con = sqlite3.connect(path)
        assert M.current_version(con) == 1
        con.close()

    def test_numbering_gaps_are_rejected(self, tmp_path, monkeypatch):
        d = tmp_path / "m"
        d.mkdir()
        (d / "0001_a.sql").write_text("SELECT 1;")
        (d / "0003_c.sql").write_text("SELECT 1;")
        monkeypatch.setattr(M, "MIGRATIONS_DIR", d)
        with pytest.raises(M.MigrationError):
            M.available()


class TestRecordMatch:
    def test_writes_match_results_and_stats_together(self, tmp_db):
        mid = run(record_match("bamboozled", 7, [ResultRow(1, 1, 900, 4), ResultRow(2, 2, 300, 1)], rounds=5,
                               difficulty="hard"))
        con = sqlite3.connect(tmp_db)
        assert con.execute("SELECT mode, guild_id, player_count, difficulty FROM matches WHERE match_id=?",
                           (mid,)).fetchone() == ("bamboozled", 7, 2, "hard")
        assert con.execute("SELECT user_id, rank, score, correct FROM match_results ORDER BY rank").fetchall() == [
            (1, 1, 900, 4), (2, 2, 300, 1)]
        assert con.execute("SELECT user_id, games, wins, best_score, total_score FROM stats ORDER BY user_id"
                           ).fetchall() == [(1, 1, 1, 900, 900), (2, 1, 0, 300, 300)]
        con.close()

    def test_stats_accumulate_and_negative_scores_add_nothing(self, tmp_db):
        run(record_match("bamboozled", 1, [ResultRow(1, 1, 800)]))
        run(record_match("bamboozled", 1, [ResultRow(1, 2, -300)]))
        s = run(stats.player_stats(1))
        assert (s["games"], s["wins"], s["best_score"], s["total_score"]) == (2, 1, 800, 800)

    def test_survival_tracks_best_streak_and_never_counts_a_win(self, tmp_db):
        for streak in (3, 7, 5):
            run(record_match("survival", 1, [ResultRow(1, 1, streak, streak)], difficulty="easy"))
        s = run(stats.player_stats(1, "survival"))
        assert (s["games"], s["wins"], s["best_streak"], s["best_score"]) == (3, 0, 7, 7)

    def test_nothing_is_written_if_a_row_fails(self, tmp_db):
        with pytest.raises(sqlite3.IntegrityError):
            run(record_match("fff", 1, [ResultRow(1, 1, 10), ResultRow(1, 2, 20)]))   # duplicate user in one match
        con = sqlite3.connect(tmp_db)
        assert con.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM stats").fetchone()[0] == 0
        con.close()

    def test_unknown_mode_is_rejected(self, tmp_db):
        with pytest.raises(ValueError):
            run(record_match("chess", 1, [ResultRow(1, 1, 1)]))

    def test_no_text_columns_hold_user_data(self, tmp_db):
        """Names and avatars are never stored: every column other than mode/details/ids is numeric or a timestamp."""
        run(record_match("fff", 5, [ResultRow(1, 1, 100, 2, {"total_questions": 10, "avg_response_ms": 900})]))
        con = sqlite3.connect(tmp_db)
        cols = {(t, c[1]) for t in ("matches", "match_results", "stats") for c in con.execute(f"PRAGMA table_info({t})")}
        assert not any("name" in c or "avatar" in c for _, c in cols)
        con.close()


class TestRanking:
    def test_order_is_score_then_user_id(self):
        assert ranked({5: 100, 2: 100, 9: 300}) == [(9, 1), (2, 2), (5, 3)]

    def test_forced_winner_is_rank_one(self):
        assert ranked({1: 100, 2: 300}, winner=1) == [(1, 1), (2, 2)]


class TestBoards:
    def test_bamboozled_board_orders_wins_then_points_then_user_id(self, tmp_db):
        run(record_match("bamboozled", 1, [ResultRow(3, 1, 500), ResultRow(1, 2, 400), ResultRow(2, 3, 400)]))
        run(record_match("bamboozled", 1, [ResultRow(1, 1, 700), ResultRow(3, 2, 100)]))
        board = run(stats.bamboozled_board(None))
        assert [(r["user_id"], r["wins"], r["total_score"]) for r in board] == [(1, 1, 1100), (3, 1, 600), (2, 0, 400)]

    def test_server_scope_only_counts_that_server(self, tmp_db):
        run(record_match("bamboozled", 1, [ResultRow(1, 1, 500)]))
        run(record_match("bamboozled", 2, [ResultRow(2, 1, 900)]))
        assert [r["user_id"] for r in run(stats.bamboozled_board(1))] == [1]
        assert [r["user_id"] for r in run(stats.bamboozled_board(None))] == [2, 1]

    def test_fff_board_best_game_first_then_faster_then_user_id(self, tmp_db):
        d = lambda ms: {"total_questions": 10, "avg_response_ms": ms}   # noqa: E731
        run(record_match("fff", 1, [ResultRow(1, 1, 700, 7, d(900)), ResultRow(2, 2, 700, 7, d(500)),
                                   ResultRow(3, 3, 300, 3, d(None))]))
        board = run(stats.fff_board(None))
        assert [r["user_id"] for r in board] == [2, 1, 3] and board[0]["total_questions"] == 10

    def test_survival_board_and_personal_best_by_difficulty_and_category(self, tmp_db):
        run(record_match("survival", 1, [ResultRow(1, 1, 4, 4)], difficulty="easy", category="History"))
        run(record_match("survival", 1, [ResultRow(1, 1, 9, 9)], difficulty="easy", category=None))
        run(record_match("survival", 1, [ResultRow(2, 1, 9, 9)], difficulty="hard", category=None))
        assert run(stats.survival_best(1, "easy", "History")) == 4
        assert run(stats.survival_best(1, "easy", None)) == 9
        assert run(stats.survival_best(1, "hard", None)) == 0
        assert [(r["user_id"], r["streak"]) for r in run(stats.survival_board(None))][:2] == [(1, 9), (2, 9)]

    def test_reset_removes_only_bamboozled(self, tmp_db):
        run(record_match("bamboozled", 1, [ResultRow(1, 1, 500)]))
        run(record_match("fff", 1, [ResultRow(1, 1, 100)]))
        assert run(stats.reset_bamboozled()) == 1
        assert run(stats.player_stats(1)) is None
        assert run(stats.player_stats(1, "fff")) is not None
        con = sqlite3.connect(tmp_db)
        assert con.execute("SELECT COUNT(*) FROM match_results").fetchone()[0] == 1     # cascade removed the rest
        con.close()


class TestLegacyTextState:
    def test_active_channels(self, tmp_db):
        run(legacy_text.register_active_channel("a"))
        run(legacy_text.register_active_channel("a"))
        run(legacy_text.register_active_channel("b"))
        run(legacy_text.unregister_active_channel("a"))
        assert run(legacy_text.get_orphaned_channels()) == ["b"]
        assert run(legacy_text.get_orphaned_channels()) == []

    def test_test_mode_per_guild(self, tmp_db):
        assert run(legacy_text.get_test_mode("1")) is False
        run(legacy_text.set_test_mode("1", True))
        assert run(legacy_text.get_test_mode("1")) is True and run(legacy_text.get_test_mode("2")) is False
        run(legacy_text.set_test_mode("1", False))
        assert run(legacy_text.get_test_mode("1")) is False


def test_details_are_valid_json(tmp_db):
    run(record_match("fff", 1, [ResultRow(1, 1, 5, 1, {"a": [1, 2]})]))
    con = sqlite3.connect(tmp_db)
    assert json.loads(con.execute("SELECT details FROM match_results").fetchone()[0]) == {"a": [1, 2]}
    con.close()
