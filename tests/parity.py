"""Drive the legacy Bamboozled code and the new engine through the same game and compare them step by step.

Both sides share one seeded stream of game draws (cards, wheel, monkey) and one seeded stream of player decisions.
They only stay in step if the engine asks for the same decisions, in the same order, and consumes randomness in the
same order as the old code, so a match over many seeds is strong evidence of equivalence.
"""
import random

import cogs.game as G
import game_engine.cards as LC
import game_engine.wheel as LW
from bamboozled.engine import ANSWER, DRAW_CARD, MONKEY, PICK_RULE, PICK_TARGET, SPIN, GameConfig, Intent, PlayerRef, Question
from bamboozled.engine import cards as EC
from bamboozled.engine import wheel as EW
from bamboozled.engine.api import LEGACY_QUIRKS
from bamboozled.engine.bamboozled import BamboozledEngine
from tests.legacy_harness import Script, legacy_env, make_game, run, snapshot

ALL_QUIRKS = frozenset(LEGACY_QUIRKS)
QUESTION = Question("Q?", ("right", "a", "b", "c"), 0, "Cat", "easy")
_NO_MONKEY = [s for s in EW.WheelSegment if s != EW.WheelSegment.MONKEYS_CHOICE]


def decisions(dr: random.Random):
    """Player decisions, a pure function of the decision stream (never of the game), so both sides see the same."""
    def decide(key, ctx):
        if key == "answer":
            r = dr.random()
            mode = 0 if r < 0.55 else (1 if r < 0.85 else "timeout")
            return mode, dr.choice([2.0, 4.9, 5.0, 7.0, 20.0, 20.5, 25.0])
        if key == "target":
            r = dr.random()
            return None if r < 0.1 else ("skip" if r < 0.2 else dr.choice(ctx))
        if key == "monkey":
            r = dr.random()
            return None if r < 0.15 else ("belly" if r < 0.6 else "tail")
        if key == "rule":
            return None if dr.random() < 0.1 else dr.randint(1, 11)
        raise AssertionError(key)
    return decide


def legacy_policy(shared: random.Random, dr: random.Random):
    decide = decisions(dr)

    def policy(key, ctx):
        if key == "chance":
            return LC.ChanceCard(EC.draw_chance(shared).value)
        if key == "wango":
            return LC.WangoCard(EC.draw_wango(shared).value)
        if key == "wheel":
            return LW.WheelSegment(shared.choice(list(EW.WheelSegment)).value)
        if key == "monkey_seg":
            return LW.WheelSegment(shared.choice(_NO_MONKEY).value)
        if key == "rand":
            return shared.random()
        return decide(key, ctx)
    return policy


def run_legacy(seed: int, n: int, rounds: int, initial_law: int = 0):
    shared, dr = random.Random(seed), random.Random(seed + 10_000)
    game = make_game(n, total_rounds=rounds)
    game.test_mode = False
    if initial_law:
        from game_engine.bamboozle_rules import apply_on_set, make_active_rule
        game.active_bamboozle_rule = make_active_rule(initial_law, n)
        apply_on_set(game.active_bamboozle_rule, game)
    script = Script()
    script.policy = legacy_policy(shared, dr)
    trace, saved = [], {}
    with legacy_env(script, game) as (cog, ch):
        original = cog._run_turn

        async def wrapped(channel, g, pid):
            script.reset_clock()
            await original(channel, g, pid)
            trace.append(snapshot(g))
        cog._run_turn = wrapped

        async def capture(mode, guild_id, results, **kw):
            saved["rows"] = [(r.user_id, r.rank, r.score) for r in results]
        G.record_match.side_effect = capture
        run(cog._run_game(ch, game))
    return trace, saved.get("rows")


def run_engine(seed: int, n: int, rounds: int, quirks=ALL_QUIRKS, max_steps: int = 5000, initial_law: int = 0):
    shared, dr = random.Random(seed), random.Random(seed + 10_000)
    decide = decisions(dr)
    e = BamboozledEngine()
    state = e.new_game(GameConfig(rounds=rounds, legacy_quirks=quirks), [PlayerRef(i) for i in range(1, n + 1)], shared, 0)
    if initial_law:
        # a law that is already in force when the game opens (the same condition the legacy run starts from)
        from bamboozled.engine import rules as ER
        state.law = ER.make_active_law(initial_law, n)
        if initial_law == 10:
            state.mist_duration = ER.MIST_MAGNET_TURNS
        elif initial_law == 11:
            state.sombrero_penalty = ER.SOMBRERO_CURSE_PENALTY
        if initial_law in (5, 6):
            e._law_start_of_turn(state, state.turn_player, [])          # the first turn's start-of-turn effect
    trace, now = [], 0

    def take(result):
        for ev in result.events:
            if ev.kind == "turn_resolved":
                trace.append(ev.payload)
        return result.state

    for _ in range(max_steps):
        if e.is_over(state):
            break
        if e.needs_question(state):
            state = take(e.supply_question(state, QUESTION, now))
            continue
        p = state.pending
        if p.kind == "answer":
            mode, elapsed = decide("answer", None)
            if mode == "timeout":
                now = p.deadline_ms
                state = take(e.on_timeout(state, now))
            else:
                now = state.q_start_ms + int(elapsed * 1000)
                state = take(e.apply(state, p.actor, Intent(ANSWER, index=mode), now))
        elif p.kind in ("draw", "spin"):
            state = take(e.apply(state, p.actor, Intent(DRAW_CARD if p.kind == "draw" else SPIN), now))
        elif p.kind == "pick_target":
            options = [u for u in state.players if u != p.actor]
            v = decide("target", options)
            if v is None or (v == "skip" and p.data["purpose"] != "switcheroo"):
                now = p.deadline_ms
                state = take(e.on_timeout(state, now))
            else:
                state = take(e.apply(state, p.actor, Intent(PICK_TARGET, user_id=None if v == "skip" else v), now))
        elif p.kind == "pick_rule":
            v = decide("rule", None)
            if v is None:
                now = p.deadline_ms
                state = take(e.on_timeout(state, now))
            else:
                state = take(e.apply(state, p.actor, Intent(PICK_RULE, rule_id=v), now))
        elif p.kind == "monkey":
            v = decide("monkey", None)
            if v is None:
                now = p.deadline_ms
                state = take(e.on_timeout(state, now))
            else:
                state = take(e.apply(state, p.actor, Intent(MONKEY, choice=v), now))
    else:
        raise AssertionError("engine did not finish")
    return trace, [(r.user_id, r.rank, r.score) for r in e.results(state)]
