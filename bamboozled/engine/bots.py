"""Scripted players: list the moves that are legal right now and play a game to the end. Pure (the caller supplies
questions and the random source); used by the property tests, the terminal player and, later, the load test."""
from __future__ import annotations

import random
from typing import Callable, Optional

from . import rules as R
from .api import (ANSWER, DRAW_CARD, FORFEIT, LEAVE, MONKEY, PICK_RULE, PICK_TARGET, SPIN, Engine, Intent, Question)


def legal_intents(state) -> list[tuple[int, Intent]]:
    """Every (actor, intent) the engine will accept right now. A timeout is not listed; see play()."""
    if getattr(state, "over", False):
        return []
    if hasattr(state, "agenda"):                                   # Bamboozled
        p = state.pending
        if p is None:
            return []
        a = p.actor
        if p.kind == "answer":
            moves = [Intent(ANSWER, index=i) for i in range(len(state.question.answers))]
            if state.q_kind == "turn":
                moves.append(Intent(FORFEIT))
        elif p.kind == "draw":
            moves = [Intent(DRAW_CARD)]
        elif p.kind == "spin":
            moves = [Intent(SPIN)]
        elif p.kind == "pick_target":
            moves = [Intent(PICK_TARGET, user_id=u) for u in state.players if u != a]
            if p.data["purpose"] == "switcheroo":
                moves.append(Intent(PICK_TARGET, user_id=None))
        elif p.kind == "pick_rule":
            moves = [Intent(PICK_RULE, rule_id=law.id) for law in R.LAWS]
        else:
            moves = [Intent(MONKEY, choice="belly"), Intent(MONKEY, choice="tail")]
        return [(a, m) for m in moves]
    if hasattr(state, "answers"):                                  # Fastest Fingers First
        if state.question is None:
            return []
        out = []
        for u in state.players:
            if u not in state.answers:
                out += [(u, Intent(ANSWER, index=i)) for i in range(len(state.question.answers))] + [(u, Intent(LEAVE))]
        return out
    if state.question is None:                                     # Survival
        return []
    return [(state.player, Intent(ANSWER, index=i)) for i in range(len(state.question.answers))] + [
        (state.player, Intent(FORFEIT))]


def deadline_of(state) -> Optional[int]:
    if hasattr(state, "pending"):
        return state.pending.deadline_ms if state.pending else None
    return state.deadline_ms


def play(engine: Engine, state, rng: random.Random, question: Callable[[dict], Question], now: int = 0,
         max_steps: int = 20_000, timeout_chance: float = 0.12, step_ms: int = 700, on_step: Optional[Callable] = None):
    """Play to the end with random legal moves, now and then letting a deadline pass. Returns the final state."""
    for _ in range(max_steps):
        if engine.is_over(state):
            return state
        need = engine.needs_question(state)
        if need:
            state = engine.supply_question(state, question(need), now).state
            continue
        moves = legal_intents(state)
        deadline = deadline_of(state)
        if not moves or (deadline is not None and rng.random() < timeout_chance):
            now = max(now, deadline if deadline is not None else now)
            state = engine.on_timeout(state, now).state
            continue
        actor, intent = rng.choice(moves)
        now += step_ms
        if deadline is not None and now > deadline:
            now = deadline
            state = engine.on_timeout(state, now).state
            continue
        result = engine.apply(state, actor, intent, now)
        if on_step:
            on_step(state, result, actor, intent)
        state = result.state
    raise AssertionError("game did not finish within the step limit")
