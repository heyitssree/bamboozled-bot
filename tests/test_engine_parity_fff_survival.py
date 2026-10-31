"""Fastest Fingers First and Survival: the engine equals the legacy loops on seeded games."""
import random

import pytest

from bamboozled.engine import ANSWER, FORFEIT, GameConfig, Intent, PlayerRef, Question
from bamboozled.engine.fff import QUIT, FastestFingersEngine
from bamboozled.engine.survival import SurvivalEngine
from tests.test_characterisation_fff_survival import BASE_MS, play_fff, play_survival

Q = Question("Q?", ("right", "a", "b", "c"), 0, "Cat", "easy")


# ───────────────────────────── Fastest Fingers First ─────────────────────────────

def fff_script(seed: int):
    r = random.Random(seed)
    n = r.randint(2, 5)
    players = {i: f"P{i}" for i in range(1, n + 1)}
    rounds = []
    for _ in range(r.randint(2, 7)):
        answered = {}
        ids = list(players)
        r.shuffle(ids)                                     # arrival order is independent of seat order
        for uid in ids:
            roll = r.random()
            if roll < 0.18:
                continue                                   # did not answer
            if roll < 0.24:
                answered[uid] = (QUIT, r.randint(1, 9000))
            else:
                answered[uid] = (0 if r.random() < 0.6 else r.randint(1, 3), r.choice([r.randint(1, 9000), 5000]))
        rounds.append(answered)
    return players, rounds


def play_fff_engine(players, rounds):
    e = FastestFingersEngine()
    s = e.new_game(GameConfig(mode="fff", rounds=len(rounds)), [PlayerRef(u) for u in players], random.Random(0), 0)
    for answered in rounds:
        if e.is_over(s):
            break
        s = e.supply_question(s, Q, BASE_MS).state
        # the legacy loop orders by timestamp and, for equal timestamps, by arrival (dict insertion) order
        for uid, (idx, ts) in sorted(answered.items(), key=lambda kv: kv[1][1]):
            if uid not in s.players or s.question is None:
                continue
            from bamboozled.engine import LEAVE
            intent = Intent(LEAVE) if idx == QUIT else Intent(ANSWER, index=idx)
            s = e.apply(s, uid, intent, BASE_MS + ts).state
        if s.question is not None:
            s = e.on_timeout(s, BASE_MS + 10_000).state
    return e, s


@pytest.mark.parametrize("seed", range(80))
def test_fff_engine_matches_legacy(seed):
    players, rounds = fff_script(seed)
    legacy, _ = play_fff(rounds, players=players, total_q=len(rounds))
    e, s = play_fff_engine(players, rounds)
    assert sorted(s.players) == sorted(legacy.players)
    assert {u: s.scores[u] for u in s.players} == {u: legacy.scores[u] for u in legacy.players}
    assert {u: s.correct.get(u, 0) for u in s.players} == {u: legacy.correct.get(u, 0) for u in legacy.players}
    assert {u: s.times.get(u, []) for u in s.players} == {u: legacy.response_times.get(u, []) for u in legacy.players}
    legacy_rows = {r.user_id: (r.score, r.correct, r.details["avg_response_ms"]) for r in legacy.recorded["results"]}
    engine_rows = {r.user_id: (r.score, r.correct, r.details["avg_response_ms"])
                   for r in e.results(s) if "left" not in r.details}
    assert engine_rows == legacy_rows


# ───────────────────────────── Survival ─────────────────────────────

def survival_script(seed: int):
    r = random.Random(seed)
    steps = []
    while True:
        roll = r.random()
        if roll < 0.7 and len(steps) < 25:
            steps.append(0)
        else:
            steps.append(r.choice([1, 2, "timeout", "giveup"]))
            return steps


def play_survival_engine(steps):
    e = SurvivalEngine()
    s = e.new_game(GameConfig(mode="survival", difficulty="medium"), [PlayerRef(42)], random.Random(0), 0)
    now = 0
    for step in steps:
        s = e.supply_question(s, Q, now).state
        if step == "timeout":
            now += 15_000
            s = e.on_timeout(s, now).state
        elif step == "giveup":
            s = e.apply(s, 42, Intent(FORFEIT), now + 100).state
        else:
            s = e.apply(s, 42, Intent(ANSWER, index=step), now + 100).state
        now += 1000
        if e.is_over(s):
            break
    return e, s


@pytest.mark.parametrize("seed", range(60))
def test_survival_engine_matches_legacy(seed):
    steps = survival_script(seed)
    death, _, _ = play_survival(steps)
    e, s = play_survival_engine(steps)
    assert e.is_over(s)
    assert (s.reason, s.streak) == (death["reason"], death["streak"])
