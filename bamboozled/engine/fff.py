"""Fastest Fingers First: everyone answers the same question; speed decides the points.

First correct answer 100, every later correct answer 75, wrong or missing 0. A player who skips two questions in a
row is removed; a player can also leave. Leavers keep the points they had and are ranked below the finishers
(owner decision: the old game dropped them from the results).
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .api import ANSWER, LEAVE, Event, GameConfig, IllegalIntent, Intent, PlayerRef, Question, Result, ResultRow
from .scoring import FFF_FIRST, FFF_LATER, final_order

QUIT = -999


@dataclass
class FFState:
    cfg: GameConfig
    players: list
    scores: dict
    rng_state: tuple
    q_index: int = 0
    total_q: int = 10
    waiting_question: bool = True
    question: Optional[Question] = None
    q_start_ms: int = 0
    deadline_ms: Optional[int] = None
    answers: dict = field(default_factory=dict)       # user_id -> (index, ts_ms, arrival_seq)
    seq: int = 0
    afk: dict = field(default_factory=dict)
    correct: dict = field(default_factory=dict)
    times: dict = field(default_factory=dict)         # user_id -> [ms for each correct answer]
    left: dict = field(default_factory=dict)          # user_id -> {"score", "correct", "why", "order"}
    leaving: list = field(default_factory=list)       # answered this round, then left: removed when the round ends
    last_round: Optional[dict] = None
    over: bool = False
    started_ms: int = 0


class FastestFingersEngine:
    mode = "fff"

    def new_game(self, cfg: GameConfig, players: Sequence[PlayerRef], rng: random.Random, now_ms: int) -> FFState:
        if cfg.mode != "fff":
            raise ValueError("config is for another mode")
        seats = [p.user_id for p in players]
        if not seats or len(set(seats)) != len(seats):
            raise ValueError("need at least one player, each listed once")
        return FFState(cfg=cfg, players=seats, scores={p: 0 for p in seats}, rng_state=rng.getstate(),
                       total_q=cfg.rounds, started_ms=now_ms)

    def needs_question(self, state: FFState) -> Optional[dict]:
        if state.over or not state.waiting_question:
            return None
        return {"kind": "fff", "qtype": "multiple", "actor": None, "difficulty": state.cfg.difficulty,
                "category": state.cfg.category}

    def supply_question(self, state: FFState, question: Question, now_ms: int) -> Result:
        if state.over or not state.waiting_question:
            raise IllegalIntent("bad_phase", "no question is needed right now")
        s = copy.deepcopy(state)
        s.question, s.q_start_ms, s.waiting_question = question, now_ms, False
        s.deadline_ms = now_ms + s.cfg.fff_question_ms
        s.answers, s.seq, s.last_round = {}, 0, None
        return Result(s, (Event("question", {"index": s.q_index, "question": question.public(),
                                             "deadline_ms": s.deadline_ms}),))

    def apply(self, state: FFState, actor: int, intent: Intent, now_ms: int) -> Result:
        if state.over:
            raise IllegalIntent("over", "the game has ended")
        if actor not in state.players:
            raise IllegalIntent("not_in_game", "you are not in this game")
        s = copy.deepcopy(state)
        ev: list[Event] = []
        if intent.kind == LEAVE:
            if s.question is None:
                self._drop(s, actor, "quit", ev)
                self._after_removal(s, ev)
                return Result(s, tuple(ev))
            if actor in s.answers:
                if actor not in s.leaving:
                    s.leaving.append(actor)                    # the answer they locked still counts
            else:
                self._lock(s, actor, QUIT, now_ms, ev)
        elif intent.kind == ANSWER:
            if s.question is None:
                raise IllegalIntent("bad_phase", "there is no open question")
            if now_ms > s.deadline_ms:
                raise IllegalIntent("too_late", "too late")
            if actor in s.answers:
                raise IllegalIntent("already_answered", "you already locked an answer")
            if intent.index is None or not 0 <= intent.index < len(s.question.answers):
                raise IllegalIntent("bad_index", "choose one of the listed answers")
            self._lock(s, actor, intent.index, now_ms, ev)
        else:
            raise IllegalIntent("bad_phase", f"{intent.kind} is not used in this mode")
        if s.question is not None and all(p in s.answers for p in s.players):
            self._resolve_round(s, ev)
        return Result(s, tuple(ev))

    def on_timeout(self, state: FFState, now_ms: int) -> Result:
        if state.over or state.question is None or state.deadline_ms is None or now_ms < state.deadline_ms:
            return Result(state, ())
        s = copy.deepcopy(state)
        ev: list[Event] = []
        self._resolve_round(s, ev)
        return Result(s, tuple(ev))

    def next_deadline_ms(self, state: FFState) -> Optional[int]:
        return None if state.over or state.question is None else state.deadline_ms

    def is_over(self, state: FFState) -> bool:
        return state.over

    # ───────────────────────────── internals ─────────────────────────────

    @staticmethod
    def _lock(s: FFState, uid: int, idx: int, now: int, ev: list) -> None:
        s.answers[uid] = (idx, now, s.seq)
        s.seq += 1
        ev.append(Event("answer_locked", {"player": uid}))            # who locked, never which answer

    @staticmethod
    def _drop(s: FFState, uid: int, why: str, ev: list) -> None:
        s.left[uid] = {"score": s.scores.pop(uid, 0), "correct": s.correct.pop(uid, 0), "why": why, "order": len(s.left)}
        s.players.remove(uid)
        s.afk.pop(uid, None)
        ev.append(Event("player_left", {"player": uid, "why": why}))

    def _resolve_round(self, s: FFState, ev: list) -> None:
        q = s.question
        quitters = [u for u, (i, _, _) in s.answers.items() if i == QUIT and u in s.players]
        quitters += [u for u in s.leaving if u in s.players and u not in quitters]
        s.leaving = []
        winners: list[int] = []
        claimed = False
        for uid, (idx, ts, _seq) in sorted(s.answers.items(), key=lambda kv: (kv[1][1], kv[1][2])):
            if uid not in s.players or idx == QUIT:
                continue
            if idx == q.correct_index:
                s.times.setdefault(uid, []).append(ts - s.q_start_ms)
                s.correct[uid] = s.correct.get(uid, 0) + 1
                s.scores[uid] = s.scores.get(uid, 0) + (FFF_LATER if claimed else FFF_FIRST)
                claimed = True
                winners.append(uid)
            s.afk[uid] = 0                                             # a wrong answer still counts as answering
        for uid in s.players:
            if uid not in s.answers:
                s.afk[uid] = s.afk.get(uid, 0) + 1
        s.last_round = {"index": s.q_index, "correct_index": q.correct_index, "winners": winners,
                        "answers": {u: a[0] for u, a in s.answers.items() if a[0] != QUIT},
                        "order": [u for u, _ in sorted(s.answers.items(), key=lambda kv: (kv[1][1], kv[1][2]))]}
        ev.append(Event("reveal", dict(s.last_round)))
        for uid in quitters:
            self._drop(s, uid, "quit", ev)
        for uid in list(s.players):
            if s.afk.get(uid, 0) >= s.cfg.afk_kick_turns:
                self._drop(s, uid, "afk", ev)
        s.question, s.deadline_ms, s.answers = None, None, {}
        if s.q_index + 1 >= s.total_q or not s.players:
            s.over = True
            ev.append(Event("game_over", {}))
        else:
            s.q_index += 1
            s.waiting_question = True

    @staticmethod
    def _after_removal(s: FFState, ev: list) -> None:
        if not s.players:
            s.over = True
            ev.append(Event("game_over", {"reason": "no_players"}))

    # ───────────────────────────── views and results ─────────────────────────────

    def view_for(self, state: FFState, viewer: Optional[int]) -> dict:
        s = state
        mine = s.answers.get(viewer) if viewer is not None else None
        return {
            "mode": "fff", "you": viewer, "over": s.over, "q_index": s.q_index, "total_q": s.total_q,
            "players": [{"user_id": u, "score": s.scores.get(u, 0), "locked": u in s.answers} for u in s.players],
            "waiting_question": s.waiting_question,
            "deadline_ms": s.deadline_ms,
            "question": s.question.public() if s.question else None,
            "your_answer": (mine[0] if mine and mine[0] != QUIT else None),     # only your own pending answer
            "reveal": s.last_round,
        }

    def results(self, state: FFState) -> list[ResultRow]:
        s = state
        rows: list[ResultRow] = []

        def avg(u):
            t = s.times.get(u, [])
            return int(sum(t) / len(t)) if t else None

        for i, u in enumerate(final_order(s.scores, s.players)):
            rows.append(ResultRow(u, i + 1, s.scores.get(u, 0), s.correct.get(u, 0),
                                  {"total_questions": s.total_q, "avg_response_ms": avg(u)}))
        gone = sorted(s.left.items(), key=lambda kv: (-kv[1]["score"], kv[1]["order"]))
        for j, (u, info) in enumerate(gone):
            rows.append(ResultRow(u, len(rows) + 1, info["score"], info["correct"],
                                  {"total_questions": s.total_q, "avg_response_ms": avg(u), "left": info["why"]}))
        return rows
