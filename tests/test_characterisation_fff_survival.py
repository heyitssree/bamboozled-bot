"""Characterisation of Fastest Fingers First (fastest_fingers.py) and Survival (survival.py).

Discord views, the clock and the database are replaced; the scoring loops run as written. Scores, ranks, streaks,
kicks and the personal-best rule are the oracle for engine/fff.py and engine/survival.py.
"""
import asyncio
import types
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import fastest_fingers as F
import survival as S

BASE_MS = 100_000      # fake monotonic() == 100.0 s, so q_start_ms == 100000


async def _noop_sleep(*_a, **_k):
    return None


class FakeMessage:
    async def edit(self, **_kw):
        return None


class FakeThread:
    id = 777

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, content=None, *, embed=None, **_kw):
        self.sent.append(content or f"[embed:{getattr(embed, 'title', '')}]")
        return FakeMessage()

    async def edit(self, **_kw):
        return None

    @property
    def text(self):
        return "\n".join(self.sent)


# ───────────────────────────── FFF ─────────────────────────────

def play_fff(rounds, players=None, total_q=None):
    """rounds: one dict per question mapping user_id -> (answer_index, offset_ms) or F._QUIT_SENTINEL.
    answer index 0 is the correct answer; players that are absent from a round's dict did not answer."""
    players = players or {1: "P1", 2: "P2", 3: "P3"}
    session = F.FFFSession(session_id="s" * 8, host_id=1, channel_id=777, guild_id=1, players=dict(players),
                           scores={uid: 0 for uid in players})
    session.questions = [{"question": f"Q{i}", "correct_answer": "right", "incorrect_answers": ["a", "b", "c"],
                          "category": "Cat", "difficulty": "easy"} for i in range(len(rounds))]
    script = list(rounds)

    class FakeAnswerView:
        def __init__(self, sess, answers):
            self.children = []
            self._all_responded = asyncio.Event()
            for uid, spec in script.pop(0).items():
                idx, offset = spec
                sess.answers_this_round[uid] = (idx, BASE_MS + offset)
            self._all_responded.set()

        def stop(self):
            pass

    thread = FakeThread()
    recorded = {}

    async def recorder(mode, guild_id, results, **kw):
        recorded.update(mode=mode, guild_id=guild_id, results=results, **kw)
    session.recorded = recorded
    cog = F.FastestFingersCog(MagicMock())
    with ExitStack() as st:
        st.enter_context(patch.object(F, "AnswerView", FakeAnswerView))
        st.enter_context(patch.object(F, "asyncio", types.SimpleNamespace(
            sleep=_noop_sleep, wait_for=asyncio.wait_for, gather=asyncio.gather,
            TimeoutError=asyncio.TimeoutError, Event=asyncio.Event)))
        st.enter_context(patch.object(F, "time", types.SimpleNamespace(monotonic=lambda: 100.0)))
        st.enter_context(patch.object(F, "shuffle_answers", lambda q: (["right", "a", "b", "c"], 0)))
        st.enter_context(patch.object(F, "record_match", recorder))
        asyncio.run(cog._run_game(thread, session, total_q or len(rounds), "easy", None))
    return session, thread


class TestFastestFingers:
    def test_first_correct_gets_100_and_later_correct_get_75_in_speed_order(self):
        s, _ = play_fff([{1: (0, 900), 2: (0, 300), 3: (0, 600)}])
        assert s.scores == {1: 75, 2: 100, 3: 75}

    def test_wrong_and_missing_answers_score_nothing(self):
        s, _ = play_fff([{1: (0, 500), 2: (2, 100)}])      # 3 did not answer
        assert s.scores == {1: 100, 2: 0, 3: 0}

    def test_a_fast_wrong_answer_does_not_claim_the_first_bonus(self):
        s, _ = play_fff([{1: (3, 10), 2: (0, 800)}])
        assert s.scores == {1: 0, 2: 100, 3: 0}

    def test_speed_tie_goes_to_whoever_locked_in_first_in_arrival_order(self):
        s, _ = play_fff([{2: (0, 400), 1: (0, 400)}])
        assert s.scores == {1: 75, 2: 100, 3: 0}

    def test_scores_accumulate_over_questions(self):
        s, _ = play_fff([{1: (0, 100), 2: (0, 200), 3: (1, 50)}, {2: (0, 100), 1: (0, 200), 3: (1, 50)}, {3: (0, 50)}])
        assert s.scores == {1: 175, 2: 175, 3: 100}

    def test_response_time_is_recorded_for_correct_answers_only(self):
        s, _ = play_fff([{1: (0, 250), 2: (1, 100)}])
        assert s.response_times == {1: [250]}

    def test_two_consecutive_non_answers_remove_the_player_and_their_score(self):
        s, th = play_fff([{1: (0, 100), 2: (0, 200)}, {1: (0, 100), 2: (0, 200)}, {1: (0, 100), 2: (0, 200)}])
        # P3 never answered: removed after question 2. FOUND: the removed player's score is dropped entirely.
        assert 3 not in s.players and 3 not in s.scores and "removed for going AFK" in th.text
        assert s.scores == {1: 300, 2: 225}

    def test_answering_resets_the_afk_counter(self):
        s, _ = play_fff([{1: (0, 100)}, {1: (0, 100), 2: (1, 300), 3: (1, 300)}, {1: (0, 100)}])
        assert set(s.players) == {1, 2, 3}      # P2 and P3 skipped Q1, answered (wrongly) Q2, skipped Q3: counter 1

    def test_quit_removes_the_player_immediately_and_scores_nothing_that_round(self):
        s, th = play_fff([{1: (0, 100), 2: (F._QUIT_SENTINEL, 150), 3: (0, 300)}])
        assert set(s.players) == {1, 3} and s.scores == {1: 100, 3: 75} and "left the game" in th.text

    def test_everyone_gone_ends_the_game_early(self):
        s, th = play_fff([{1: (F._QUIT_SENTINEL, 1), 2: (F._QUIT_SENTINEL, 1), 3: (F._QUIT_SENTINEL, 1)},
                          {}], total_q=2)
        assert not s.players and "No players remaining" in th.text

    def test_results_are_recorded_with_rank_correct_count_and_average_time(self):
        s, _ = play_fff([{1: (0, 100), 2: (0, 300), 3: (1, 50)}, {1: (0, 500), 2: (0, 200)}], total_q=2)
        # P3 answered one wrong and skipped one: still in the game
        rec = s.recorded
        assert rec["mode"] == "fff" and rec["guild_id"] == 1 and rec["rounds"] == 2
        got = {r.user_id: (r.rank, r.score, r.correct, r.details["avg_response_ms"], r.details["total_questions"])
               for r in rec["results"]}
        # P1: 100 + 75 = 175 (avg 300 ms) | P2: 75 + 100 = 175 (avg 250 ms) | P3: 0
        assert got == {1: (1, 175, 2, 300, 2), 2: (2, 175, 2, 250, 2), 3: (3, 0, 0, None, 2)}

    def test_game_ends_after_the_last_question(self):
        _, th = play_fff([{1: (0, 100)}])
        assert "Final Results" in th.text


# ───────────────────────────── Survival ─────────────────────────────

def play_survival(answers, difficulty="medium", cat_slug=None, prev_best=0, questions=None):
    """answers: one entry per question: an index (0 = correct) | 'timeout' | 'giveup'. Returns what the run produced."""
    session = S.SurvivalSession(session_id="x" * 8, player_id=42, username="U", channel_id=1, guild_id=1,
                                difficulty=difficulty, category_slug=cat_slug, category_name=None)
    script = list(answers)
    fetched = []
    death = {}
    qs = list(questions) if questions is not None else None

    async def fake_fetch(**kw):
        fetched.append(kw)
        if qs is not None:
            q = qs.pop(0)
            return q
        return {"question": f"Q{len(fetched)}", "correct_answer": "right", "incorrect_answers": ["a", "b", "c"],
                "category": "Cat", "difficulty": difficulty}

    class _Answered:
        def __init__(self, mode):
            self.mode = mode

        async def wait(self):
            if self.mode == "timeout":
                raise TimeoutError

    class FakeView:
        GIVE_UP_SENTINEL = S.SurvivalAnswerView.GIVE_UP_SENTINEL

        def __init__(self, player_id, answers_, sess):
            mode = script.pop(0)
            self.children = []
            self._answered = _Answered(mode)
            self.selected_answer = self.GIVE_UP_SENTINEL if mode == "giveup" else (None if mode == "timeout" else mode)

        def stop(self):
            pass

    async def fake_death(sess, reason, personal_best, is_new_pb):
        death.update(reason=reason, streak=sess.streak, personal_best=personal_best, is_new_pb=is_new_pb)
        return MagicMock()

    thread = FakeThread()

    async def saved_match(mode, guild_id, results, **kw):
        death["saved"] = (mode, results[0].score, results[0].details["reason"], kw["difficulty"])
    cog = S.SurvivalCog(MagicMock())
    with ExitStack() as st:
        st.enter_context(patch.object(S, "SurvivalAnswerView", FakeView))
        st.enter_context(patch.object(S, "asyncio", types.SimpleNamespace(
            sleep=_noop_sleep, wait_for=asyncio.wait_for, TimeoutError=asyncio.TimeoutError,
            create_task=lambda c: (c.close(), MagicMock())[1])))
        st.enter_context(patch.object(S, "fetch_question_tapi", fake_fetch))
        st.enter_context(patch.object(S, "shuffle_answers", lambda q: (["right", "a", "b", "c"], 0)))
        st.enter_context(patch.object(S, "_previous_best", AsyncMock(return_value=prev_best)))
        st.enter_context(patch.object(S, "record_match", saved_match))
        st.enter_context(patch.object(S, "_build_death_embed", fake_death))
        player = MagicMock()
        player.id = 42
        asyncio.run(cog._run_survival(thread, session, player, difficulty, cat_slug, None))
    return death, fetched, thread


class TestSurvival:
    def test_streak_counts_correct_answers_until_a_wrong_one(self):
        death, *_ = play_survival([0, 0, 0, 2])
        assert (death["reason"], death["streak"]) == ("wrong", 3)

    def test_first_question_wrong_is_a_streak_of_zero(self):
        death, *_ = play_survival([1])
        assert (death["reason"], death["streak"], death["is_new_pb"]) == ("wrong", 0, False)

    def test_timeout_ends_the_run(self):
        death, *_ = play_survival([0, 0, "timeout"])
        assert (death["reason"], death["streak"]) == ("timeout", 2)

    def test_give_up_ends_the_run_and_never_counts_as_a_personal_best(self):
        death, *_ = play_survival([0, 0, 0, "giveup"], prev_best=1)
        assert (death["reason"], death["streak"], death["is_new_pb"]) == ("quit", 3, False)

    def test_new_personal_best_needs_a_strictly_higher_streak(self):
        assert play_survival([0, 0, 0, 1], prev_best=2)[0]["is_new_pb"] is True
        assert play_survival([0, 0, 1], prev_best=2)[0]["is_new_pb"] is False      # equal is not a new best
        assert play_survival([0, 1], prev_best=2)[0]["is_new_pb"] is False

    def test_the_run_is_saved_with_streak_reason_and_difficulty(self):
        death, *_ = play_survival([0, 0, "timeout"], difficulty="hard")
        assert death["saved"] == ("survival", 2, "timeout", "hard")

    def test_previous_best_is_passed_through(self):
        assert play_survival([1], prev_best=9)[0]["personal_best"] == 9

    def test_a_fetch_failure_ends_the_run_as_an_error(self):
        death, *_ = play_survival([0], questions=[{"question": "Q1", "correct_answer": "right",
                                                   "incorrect_answers": ["a", "b", "c"], "category": "C",
                                                   "difficulty": "easy"}, None])
        assert (death["reason"], death["streak"]) == ("error", 1)

    def test_fetch_receives_difficulty_and_category_slug_and_the_seen_set(self):
        _, fetched, _ = play_survival([0, 0, 1], difficulty="hard", cat_slug="history")
        assert [f["difficulty"] for f in fetched] == ["hard"] * 3 and fetched[0]["tapi_slug"] == "history"
        assert fetched[0]["seen"] is fetched[2]["seen"] and len(fetched[2]["seen"]) == 3
