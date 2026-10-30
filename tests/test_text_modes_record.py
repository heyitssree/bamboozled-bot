"""Each text mode's real end-of-game code writes to the new tables (real SQLite, nothing mocked in the DB layer)."""
import asyncio
import sqlite3
from datetime import datetime
from unittest.mock import patch

import cogs.game as G
import fastest_fingers as F
import survival as S
from bamboozled.db.repos.matches import record_match
from bamboozled.db.repos.stats import bamboozled_board, fff_board, player_stats, survival_best, survival_board
from tests.legacy_harness import Script, legacy_env, make_game

run = asyncio.run


def test_bamboozled_endgame_records_match_results_and_stats(tmp_db):
    g = make_game(3, scores={1: 300, 2: 900, 3: 600}, total_rounds=7)
    g.test_mode = False
    g.guild_id = 4242
    g.correct_answer_count = {2: 5, 3: 2}
    with legacy_env(Script(), g) as (cog, ch), patch.object(G, "record_match", record_match):
        run(cog._run_endgame(ch, g))
    con = sqlite3.connect(tmp_db)
    assert con.execute("SELECT mode, guild_id, rounds, player_count FROM matches").fetchone() == ("bamboozled", 4242, 7, 3)
    assert con.execute("SELECT user_id, rank, score, correct FROM match_results ORDER BY rank").fetchall() == [
        (2, 1, 900, 5), (3, 2, 600, 2), (1, 3, 300, 0)]
    con.close()
    assert run(player_stats(2))["wins"] == 1 and run(player_stats(1))["wins"] == 0
    assert [r["user_id"] for r in run(bamboozled_board(4242))] == [2, 3, 1]
    assert run(bamboozled_board(999)) == []


def test_test_mode_game_records_nothing(tmp_db):
    g = make_game(2, scores={1: 100, 2: 200})
    with legacy_env(Script(), g) as (cog, ch), patch.object(G, "record_match", record_match):
        run(cog._run_endgame(ch, g))
    assert sqlite3.connect(tmp_db).execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


def test_fff_result_is_saved_with_correct_counts_and_average_time(tmp_db):
    s = F.FFFSession(session_id="abcdefgh", host_id=1, channel_id=9, guild_id=31, players={1: "A", 2: "B"},
                     scores={1: 175, 2: 100}, started_at=datetime(2026, 1, 1))
    s.correct = {1: 2, 2: 1}
    s.response_times = {1: [200, 400], 2: [900]}
    run(F._save_result(s, 10))
    board = run(fff_board(31))
    assert [(r["user_id"], r["correct_answers"], r["total_questions"], r["avg_response_ms"]) for r in board] == [
        (1, 2, 10, 300), (2, 1, 10, 900)]
    assert run(player_stats(1, "fff"))["wins"] == 1


def test_survival_result_is_saved_and_feeds_the_personal_best(tmp_db):
    s = S.SurvivalSession(session_id="x", player_id=8, username="U", channel_id=1, guild_id=31, difficulty="medium",
                          category_slug=None, category_name=None, streak=6)
    assert run(S._previous_best(s)) == 0
    run(S._save_result(s, "wrong"))
    assert run(S._previous_best(s)) == 6 and run(survival_best(8, "medium", None)) == 6
    assert [(r["user_id"], r["streak"]) for r in run(survival_board(31))] == [(8, 6)]
    assert run(player_stats(8, "survival"))["best_streak"] == 6
