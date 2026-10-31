"""Survival: one player, one run. Answer to extend the streak; one wrong answer, timeout or give-up ends it.

Several runs can be live in one room: the room keeps one SurvivalEngine state per player.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Optional, Sequence

from .api import ANSWER, FORFEIT, LEAVE, Event, GameConfig, IllegalIntent, Intent, PlayerRef, Question, Result, ResultRow
from .scoring import is_new_best

__all__ = ["SurvivalEngine", "SurvivalState", "is_new_best"]


@dataclass
class SurvivalState:
    cfg: GameConfig
    player: int
    rng_state: tuple
    streak: int = 0
    waiting_question: bool = True
    question: Optional[Question] = None
    q_start_ms: int = 0
    deadline_ms: Optional[int] = None
    reason: Optional[str] = None          # wrong | timeout | quit | error once the run is over
    over: bool = False
    last_reveal: Optional[dict] = None
    started_ms: int = 0


class SurvivalEngine:
    mode = "survival"

    def new_game(self, cfg: GameConfig, players: Sequence[PlayerRef], rng: random.Random, now_ms: int) -> SurvivalState:
        if cfg.mode != "survival":
            raise ValueError("config is for another mode")
        if len(players) != 1:
            raise ValueError("a Survival run has exactly one player")
        return SurvivalState(cfg=cfg, player=players[0].user_id, rng_state=rng.getstate(), started_ms=now_ms)

    def needs_question(self, state: SurvivalState) -> Optional[dict]:
        if state.over or not state.waiting_question:
            return None
        return {"kind": "survival", "qtype": "multiple", "actor": state.player,
                "difficulty": state.cfg.difficulty or "medium", "category": state.cfg.category}

    def supply_question(self, state: SurvivalState, question: Question, now_ms: int) -> Result:
        if state.over or not state.waiting_question:
            raise IllegalIntent("bad_phase", "no question is needed right now")
        s = copy.deepcopy(state)
        s.question, s.q_start_ms, s.waiting_question, s.last_reveal = question, now_ms, False, None
        s.deadline_ms = now_ms + s.cfg.survival_question_ms
        return Result(s, (Event("question", {"streak": s.streak, "question": question.public(),
                                             "deadline_ms": s.deadline_ms}),))

    def question_unavailable(self, state: SurvivalState) -> Result:
        """The server could not fetch a question: the run ends as an error (never a personal best)."""
        s = copy.deepcopy(state)
        if not s.over:
            s.over, s.reason, s.waiting_question = True, "error", False
        return Result(s, (Event("game_over", {"reason": "error"}),))

    def apply(self, state: SurvivalState, actor: int, intent: Intent, now_ms: int) -> Result:
        if state.over:
            raise IllegalIntent("over", "this run has ended")
        if actor != state.player:
            raise IllegalIntent("not_your_turn", "this is someone else's run")
        s = copy.deepcopy(state)
        if intent.kind in (FORFEIT, LEAVE):
            return self._end(s, "quit")
        if intent.kind != ANSWER:
            raise IllegalIntent("bad_phase", f"{intent.kind} is not used in this mode")
        if s.question is None:
            raise IllegalIntent("bad_phase", "there is no open question")
        if now_ms > s.deadline_ms:
            raise IllegalIntent("too_late", "too late")
        if intent.index is None or not 0 <= intent.index < len(s.question.answers):
            raise IllegalIntent("bad_index", "choose one of the listed answers")
        right = intent.index == s.question.correct_index
        s.last_reveal = {"correct_index": s.question.correct_index, "chosen": intent.index, "right": right}
        s.question, s.deadline_ms = None, None
        if right:
            s.streak += 1
            s.waiting_question = True
            return Result(s, (Event("streak_up", {"streak": s.streak}),))
        return self._end(s, "wrong")

    def on_timeout(self, state: SurvivalState, now_ms: int) -> Result:
        if state.over or state.question is None or state.deadline_ms is None or now_ms < state.deadline_ms:
            return Result(state, ())
        s = copy.deepcopy(state)
        s.last_reveal = {"correct_index": s.question.correct_index, "chosen": None, "right": False}
        s.question, s.deadline_ms = None, None
        return self._end(s, "timeout")

    @staticmethod
    def _end(s: SurvivalState, reason: str) -> Result:
        s.over, s.reason, s.waiting_question, s.question, s.deadline_ms = True, reason, False, None, None
        return Result(s, (Event("game_over", {"reason": reason, "streak": s.streak}),))

    def next_deadline_ms(self, state: SurvivalState) -> Optional[int]:
        return None if state.over else state.deadline_ms

    def is_over(self, state: SurvivalState) -> bool:
        return state.over

    def view_for(self, state: SurvivalState, viewer: Optional[int]) -> dict:
        s = state
        return {"mode": "survival", "you": viewer, "player": s.player, "streak": s.streak, "over": s.over,
                "reason": s.reason, "waiting_question": s.waiting_question, "deadline_ms": s.deadline_ms,
                "question": s.question.public() if s.question else None, "reveal": s.last_reveal}

    def results(self, state: SurvivalState) -> list[ResultRow]:
        s = state
        return [ResultRow(s.player, 1, s.streak, s.streak,
                          {"reason": s.reason, "difficulty": s.cfg.difficulty or "medium", "category": s.cfg.category})]
