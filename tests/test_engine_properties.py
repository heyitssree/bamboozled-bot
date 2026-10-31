"""Property tests: random legal play never breaks the engine, and hidden information stays hidden."""
import copy
import json
import random

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bamboozled.engine import GameConfig, IllegalIntent, Intent, PlayerRef, Question, get_engine
from bamboozled.engine import rules as R
from bamboozled.engine.bots import legal_intents, play

SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def question(need):
    return Question("Q?", ("right", "a", "b", "c"), 0, "Cat", "easy")


def start(mode, seed, n, rounds):
    e = get_engine(mode)
    cfg = GameConfig(mode=mode, rounds=rounds, difficulty="medium")
    return e, e.new_game(cfg, [PlayerRef(100 + i * 7) for i in range(1 if mode == "survival" else n)],
                         random.Random(seed), 0)


def viewers(state):
    ids = list(getattr(state, "players", None) or [state.player])
    return ids + [None, 999_999]               # every player, an anonymous spectator, and a stranger


@SETTINGS
@given(st.integers(0, 10**6), st.integers(1, 5), st.integers(1, 4))
def test_bamboozled_random_play_terminates_and_keeps_its_invariants(seed, n, rounds):
    e, s = start("bamboozled", seed, n, rounds)
    seen_turns = []

    def check(before, result, actor, intent):
        st_ = result.state
        assert set(st_.scores) == set(st_.players)
        assert all(isinstance(v, int) for v in st_.scores.values())
        assert 0 <= st_.turn_index < max(1, len(st_.players)) or st_.over
        for ev in result.events:
            if ev.kind == "turn_start":
                seen_turns.append((ev.payload["player"], ev.payload["round"]))
    s = play(e, s, random.Random(seed ^ 0xBEEF), question, on_step=check)
    assert e.is_over(s) and s.champion in s.players
    rows = e.results(s)
    assert [r.rank for r in rows] == list(range(1, len(rows) + 1)) and rows[0].user_id == s.champion
    # turn order is a rotation: within one round, players come up in seat order without repeats
    by_round = {}
    for pid, rnd in seen_turns:
        by_round.setdefault(rnd, []).append(pid)
    for turns in by_round.values():
        assert len(turns) == len(set(turns))


@SETTINGS
@given(st.integers(0, 10**6), st.integers(2, 5), st.integers(2, 8))
def test_fff_random_play_terminates(seed, n, rounds):
    e, s = start("fff", seed, n, rounds)
    s = play(e, s, random.Random(seed), question)
    assert e.is_over(s)
    rows = e.results(s)
    assert {r.user_id for r in rows} == set(s.players) | set(s.left)
    assert [r.rank for r in rows] == list(range(1, len(rows) + 1))
    finishers = [r for r in rows if "left" not in r.details]
    assert rows[: len(finishers)] == finishers                    # leavers always rank below finishers


@SETTINGS
@given(st.integers(0, 10**6))
def test_survival_random_play_terminates_with_a_reason(seed):
    e, s = start("survival", seed, 1, 1)
    s = play(e, s, random.Random(seed), question)
    assert s.reason in ("wrong", "timeout", "quit")
    assert e.results(s)[0].score == s.streak


@SETTINGS
@given(st.sampled_from(["bamboozled", "fff", "survival"]), st.integers(0, 10**6), st.integers(2, 4))
def test_apply_never_modifies_the_state_it_was_given(mode, seed, n):
    e, s = start(mode, seed, n, 3)
    rng = random.Random(seed)
    for step in range(400):
        if e.is_over(s):
            break
        need = e.needs_question(s)
        if need:
            frozen = copy.deepcopy(s)
            s2 = e.supply_question(s, question(need), step * 100).state
            assert s == frozen and s2 is not s
            s = s2
            continue
        frozen = copy.deepcopy(s)
        moves = legal_intents(s)
        if not moves:
            s2 = e.on_timeout(s, 10**9).state
        else:
            actor, intent = rng.choice(moves)
            s2 = e.apply(s, actor, intent, step * 100 + 50).state
        assert s == frozen, "the engine changed the state it was handed"
        assert e.on_timeout(s, 10**9).state is not s or e.next_deadline_ms(s) is None
        assert s == frozen
        s = s2


@SETTINGS
@given(st.sampled_from(["bamboozled", "fff", "survival"]), st.integers(0, 10**6))
def test_no_view_leaks_the_answer_or_other_players_pending_answers(mode, seed):
    e, s = start(mode, seed, 3, 3)
    rng = random.Random(seed)
    for step in range(300):
        if e.is_over(s):
            break
        need = e.needs_question(s)
        if need:
            s = e.supply_question(s, question(need), step * 100).state
            continue
        for viewer in viewers(s):
            view = e.view_for(s, viewer)
            if view.get("question") is not None:
                assert "correct_index" not in view["question"]
                if view.get("reveal") is None:
                    assert "correct_index" not in json.dumps(view, default=str)      # nowhere in the view
            if mode == "bamboozled" and view["mist"]:
                assert all(p["score"] is None for p in view["players"])
            if mode == "fff" and s.question is not None:
                own = s.answers.get(viewer)
                assert view["your_answer"] == (own[0] if own and own[0] >= 0 else None)
                assert all(set(p) == {"user_id", "score", "locked"} for p in view["players"])
        moves = legal_intents(s)
        if not moves:
            s = e.on_timeout(s, 10**9).state
        else:
            actor, intent = rng.choice(moves)
            s = e.apply(s, actor, intent, step * 100 + 50).state


@SETTINGS
@given(st.sampled_from(["bamboozled", "fff", "survival"]), st.integers(0, 10**6), st.integers(0, 3),
       st.sampled_from(["ANSWER", "DRAW_CARD", "SPIN", "PICK_TARGET", "PICK_RULE", "MONKEY", "FORFEIT", "LEAVE", "NOPE"]),
       st.one_of(st.none(), st.integers(-3, 9), st.integers(0, 10**6)))
def test_junk_intents_only_ever_raise_illegal_intent(mode, seed, steps, kind, number):
    e, s = start(mode, seed, 3, 3)
    rng = random.Random(seed)
    now = 0
    for _ in range(steps * 5):
        now += 100
        need = e.needs_question(s)
        if need:
            s = e.supply_question(s, question(need), now).state
        else:
            moves = legal_intents(s)
            if moves:
                actor, intent = rng.choice(moves)
                s = e.apply(s, actor, intent, now + 50).state
        if e.is_over(s):
            break
    intent = Intent(kind, index=number, user_id=number, rule_id=number, choice=str(number))
    for actor in list(getattr(s, "players", [getattr(s, "player", 0)])) + [123456789]:
        before = copy.deepcopy(s)
        try:
            e.apply(s, actor, intent, 10**7 if rng.random() < 0.2 else now + 60)
        except IllegalIntent as err:
            assert err.code
        assert s == before


@given(st.integers(-10**6, 10**6), st.integers(-10**6, 10**6))
def test_a_single_ordinary_score_change_is_capped(start_score, delta):
    from bamboozled.engine.bamboozled import BamboozledEngine, BzState
    s = BzState(cfg=GameConfig(), players=[1], scores={1: start_score}, rng_state=random.Random(0).getstate())
    applied = BamboozledEngine._pts(s, 1, delta)
    assert abs(applied) <= R.MAX_SWING and s.scores[1] == start_score + applied
    assert BamboozledEngine._pts(s, 1, delta, bypass=True) == delta


@SETTINGS
@given(st.integers(0, 10**6))
def test_same_seed_same_game(seed):
    outcomes = []
    for _ in range(2):
        e, s = start("bamboozled", seed, 3, 3)
        s = play(e, s, random.Random(seed + 1), question)
        outcomes.append(([(r.user_id, r.rank, r.score) for r in e.results(s)], s.round))
    assert outcomes[0] == outcomes[1]
