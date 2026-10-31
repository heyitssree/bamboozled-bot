"""Bamboozled: turn-based chaos trivia. Server-authoritative, pure, deterministic.

How it works. A turn is a list of steps (the *agenda*) that the engine walks through until it needs something from
outside: a question (supply_question), or a decision from a player (a *pending* item with a deadline). Each card,
wheel segment or monkey outcome pushes more steps on the front of the agenda, so nesting (a wheel spin that leads to
a Wango card that leads to another spin) needs no recursion and survives a restart as plain data.

Step tuples are (kind, actor, *args):
    ask    actor kind [qtype]          wait for a question; kind is turn | double_down | tiebreak
    draw   actor which prompt source   which is chance | wango; prompt=True waits for the player to press draw
    chance actor card                  apply a Chance card
    wango  actor card chain            apply a Wango card (chain = Double Wango depth)
    dw     actor i n chain             next extra card of a Double Wango
    spin   actor wheel_depth chain     wait for the player to spin
    seg    actor segment depth chain   apply a wheel segment
    monkey actor lucky_belly           the Golden Monkey (lucky_belly is decided once, on entry)
    pick   actor purpose               pick a target (switcheroo | gift)
    law    actor                       pick a Bamboozle law

Legacy behaviour that the owner decided to change is switchable through GameConfig.legacy_quirks, so the parity tests
can prove the engine equals the old code when the quirks are on (docs/rules-as-implemented.md, section 5).
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import rules as R
from .api import (ANSWER, DRAW_CARD, FORFEIT, LEAVE, MONKEY, PICK_RULE, PICK_TARGET, SPIN, Event, GameConfig,
                  IllegalIntent, Intent, PlayerRef, Question, Result, ResultRow)
from .cards import ChanceCard, WangoCard, draw_chance, draw_wango
from .scoring import final_order, top_scorers
from .wheel import WheelSegment, spin

_KIND_FOR_PENDING = {"answer": (ANSWER, FORFEIT), "draw": (DRAW_CARD,), "spin": (SPIN,), "pick_target": (PICK_TARGET,),
                     "pick_rule": (PICK_RULE,), "monkey": (MONKEY,)}


@dataclass
class Pending:
    kind: str
    actor: int
    deadline_ms: int
    data: dict = field(default_factory=dict)


@dataclass
class BzState:
    """Never mutate a state you were handed; the engine copies before it changes anything."""
    cfg: GameConfig
    players: list
    scores: dict
    rng_state: tuple
    round: int = 1
    turn_index: int = 0
    turn_player: int = 0
    stage: str = "turns"                       # turns | endgame
    agenda: list = field(default_factory=list)
    pending: Optional[Pending] = None
    waiting_question: bool = False
    question: Optional[Question] = None
    q_kind: str = "turn"
    q_actor: int = 0
    q_type: str = "multiple"
    q_start_ms: int = 0
    answer_time_s: float = 0.0
    golden_pass: dict = field(default_factory=dict)
    silenced: dict = field(default_factory=dict)
    sombrero_holder: Optional[int] = None
    sombrero_penalty: int = R.SOMBRERO_PENALTY
    law: Optional[dict] = None
    mist_active: bool = False
    mist_turns: int = 0
    mist_duration: int = R.MIST_TURNS
    streak: dict = field(default_factory=dict)
    correct_count: dict = field(default_factory=dict)
    afk: dict = field(default_factory=dict)
    switcheroo_used: dict = field(default_factory=dict)
    leaving: list = field(default_factory=list)
    tied: list = field(default_factory=list)
    last_reveal: Optional[dict] = None
    over: bool = False
    champion: Optional[int] = None
    started_ms: int = 0


def snapshot(s: BzState) -> dict:
    """The observable rules state; this is what the parity tests compare step by step."""
    return {
        "scores": dict(s.scores), "turn_index": s.turn_index, "round": s.round, "players": list(s.players),
        "golden_pass": {k: v for k, v in s.golden_pass.items() if v},
        "silenced": {k: v for k, v in s.silenced.items() if v}, "sombrero": s.sombrero_holder,
        "sombrero_penalty": s.sombrero_penalty, "mist": (s.mist_active, s.mist_turns), "mist_duration": s.mist_duration,
        "rule": (s.law["id"], s.law["turns_remaining"]) if s.law else None,
        "streak": dict(s.streak), "afk": dict(s.afk),
    }


def _rng(s: BzState) -> random.Random:
    r = random.Random()
    r.setstate(s.rng_state)
    return r


class BamboozledEngine:
    mode = "bamboozled"

    # ───────────────────────────── public API ─────────────────────────────

    def new_game(self, cfg: GameConfig, players: Sequence[PlayerRef], rng: random.Random, now_ms: int) -> BzState:
        if cfg.mode != "bamboozled":
            raise ValueError("config is for another mode")
        seats = [p.user_id for p in players]
        if not seats or len(set(seats)) != len(seats):
            raise ValueError("need at least one player, each listed once")
        s = BzState(cfg=cfg, players=seats, scores={p: cfg.starting_points for p in seats}, rng_state=rng.getstate(),
                    started_ms=now_ms)
        s.mist_duration = cfg.mist_turns
        self._begin_turn(s, now_ms, [])
        self._run(s, now_ms, _rng(s), [])
        return s

    def apply(self, state: BzState, actor: int, intent: Intent, now_ms: int) -> Result:
        s = copy.deepcopy(state)
        ev: list[Event] = []
        rng = _rng(s)
        if s.over:
            raise IllegalIntent("over", "the game has ended")
        if actor not in s.players:
            raise IllegalIntent("not_in_game", "you are not a player in this game")
        if intent.kind == LEAVE:
            self._leave(s, actor, now_ms, rng, ev)
        else:
            p = s.pending
            if p is None:
                raise IllegalIntent("bad_phase", "nothing is waiting for a decision right now")
            if intent.kind not in _KIND_FOR_PENDING[p.kind]:
                raise IllegalIntent("bad_phase", f"expected {' or '.join(_KIND_FOR_PENDING[p.kind])}")
            if actor != p.actor:
                raise IllegalIntent("not_your_turn", "this decision belongs to another player")
            if now_ms > p.deadline_ms:
                raise IllegalIntent("too_late", "the time for this decision has passed")
            self._validate(s, p, intent)
            self._resolve(s, p, intent, now_ms, rng, ev)
        self._run(s, now_ms, rng, ev)
        s.rng_state = rng.getstate()
        return Result(s, tuple(ev))

    def on_timeout(self, state: BzState, now_ms: int) -> Result:
        p = state.pending
        if state.over or p is None or now_ms < p.deadline_ms:
            return Result(state, ())
        s = copy.deepcopy(state)
        ev: list[Event] = []
        rng = _rng(s)
        self._resolve(s, s.pending, None, now_ms, rng, ev)
        self._run(s, now_ms, rng, ev)
        s.rng_state = rng.getstate()
        return Result(s, tuple(ev))

    def needs_question(self, state: BzState) -> Optional[dict]:
        if state.over or not state.waiting_question:
            return None
        return {"kind": state.q_kind, "qtype": state.q_type, "actor": state.q_actor}

    def supply_question(self, state: BzState, question: Question, now_ms: int) -> Result:
        if not state.waiting_question or state.over:
            raise IllegalIntent("bad_phase", "no question is needed right now")
        if not 0 <= question.correct_index < len(question.answers):
            raise ValueError("correct_index out of range")
        s = copy.deepcopy(state)
        s.question = question
        s.q_start_ms = now_ms
        s.waiting_question = False
        s.pending = Pending("answer", s.q_actor, now_ms + s.cfg.question_timeout_ms, {})
        s.last_reveal = None
        return Result(s, (Event("question", {"kind": s.q_kind, "actor": s.q_actor, "question": question.public()}),))

    def next_deadline_ms(self, state: BzState) -> Optional[int]:
        return None if state.over or state.pending is None else state.pending.deadline_ms

    def is_over(self, state: BzState) -> bool:
        return state.over

    def results(self, state: BzState) -> list[ResultRow]:
        order = final_order(state.scores, state.players, state.champion)
        return [ResultRow(p, i + 1, state.scores.get(p, 0), state.correct_count.get(p, 0)) for i, p in enumerate(order)]

    def view_for(self, state: BzState, viewer: Optional[int]) -> dict:
        s = state
        hide = s.mist_active
        p = s.pending
        view = {
            "mode": "bamboozled", "you": viewer, "stage": s.stage, "round": s.round, "total_rounds": s.cfg.rounds,
            "over": s.over, "champion": s.champion, "turn_player": s.turn_player, "mist": s.mist_active,
            "players": [{"user_id": u, "score": None if hide else s.scores.get(u, 0), "silenced": bool(s.silenced.get(u)),
                         "golden_pass": bool(s.golden_pass.get(u)), "sombrero": s.sombrero_holder == u,
                         "streak": s.streak.get(u, 0)} for u in s.players],
            "law": ({"id": s.law["id"], "name": s.law["name"], "permanent": s.law["permanent"]} if s.law else None),
            "pending": ({"kind": p.kind, "actor": p.actor, "deadline_ms": p.deadline_ms,
                         "options": [u for u in s.players if u != p.actor] if p.kind == "pick_target" else None,
                         "can_skip": p.data.get("purpose") == "switcheroo",
                         "which": p.data.get("which"), "purpose": p.data.get("purpose")} if p else None),
            "waiting_question": s.waiting_question,
            "deadline_ms": p.deadline_ms if p else None,
            "question": s.question.public() if s.question else None,       # the correct index is NOT here
            "reveal": s.last_reveal,                                       # only exists after the answer is in
        }
        return view

    # ───────────────────────────── validation ─────────────────────────────

    def _validate(self, s: BzState, p: Pending, intent: Intent) -> None:
        if p.kind == "answer":
            if intent.kind == FORFEIT:
                if s.q_kind != "turn":
                    raise IllegalIntent("bad_phase", "only a normal turn can be forfeited")
            elif intent.index is None or not 0 <= intent.index < len(s.question.answers):
                raise IllegalIntent("bad_index", "choose one of the listed answers")
        elif p.kind == "pick_target":
            can_skip = p.data["purpose"] == "switcheroo"
            if intent.user_id is None:
                if not can_skip:
                    raise IllegalIntent("bad_target", "choose a player")
            elif intent.user_id == p.actor or intent.user_id not in s.players:
                raise IllegalIntent("bad_target", "choose another player in this game")
        elif p.kind == "pick_rule":
            if R.law(intent.rule_id or -1) is None:
                raise IllegalIntent("bad_rule", "unknown law")
        elif p.kind == "monkey":
            if intent.choice not in ("belly", "tail"):
                raise IllegalIntent("bad_choice", "belly or tail")

    # ───────────────────────────── the loop ─────────────────────────────

    def _run(self, s: BzState, now: int, rng: random.Random, ev: list) -> None:
        while not s.over:
            if s.pending is not None and s.pending.actor in s.leaving:
                self._resolve(s, s.pending, None, now, rng, ev)          # someone who left takes the default
                continue
            if s.waiting_question and s.q_actor in s.leaving:
                s.waiting_question = False
                s.agenda = [i for i in s.agenda if i[1] != s.q_actor]
                continue
            if s.pending is not None or s.waiting_question:
                return
            if s.agenda:
                self._step(s, now, rng, ev)        # may leave us waiting; the checks above then decide whether to stop
                continue
            if s.stage == "turns":
                self._end_turn(s, now, ev)
            else:
                self._endgame_advance(s, ev)

    # ───────────────────────────── turns ─────────────────────────────

    def _begin_turn(self, s: BzState, now: int, ev: list) -> None:
        pid = s.players[s.turn_index]
        s.turn_player = pid
        ev.append(Event("turn_start", {"player": pid, "round": s.round}))
        if s.silenced.get(pid):
            s.silenced[pid] = False
            ev.append(Event("turn_skipped", {"player": pid, "why": "silence"}))
            self._end_turn(s, now, ev, skipped=True)
            return
        if s.law:
            self._law_start_of_turn(s, pid, ev)
        s.answer_time_s = 0.0
        s.agenda = [("ask", pid, "turn")]

    def _end_turn(self, s: BzState, now: int, ev: list, skipped: bool = False) -> None:
        pid = s.turn_player
        removed = False
        if not skipped:
            ev.append(Event("turn_resolved", snapshot(s)))
            if pid in s.players and (s.afk.get(pid, 0) >= s.cfg.afk_kick_turns or pid in s.leaving):
                why = "left" if pid in s.leaving else "afk"
                self._remove_player(s, pid, why, ev)
                removed = True
                if not s.players:
                    s.over = True
                    ev.append(Event("game_over", {"reason": "no_players"}))
                    return
        if s.mist_active:
            s.mist_turns -= 1
            if s.mist_turns <= 0:
                s.mist_active, s.mist_turns = False, 0
                ev.append(Event("mist_off", {}))
        prev_law = s.law
        legacy_skip = "afk_skip" in s.cfg.legacy_quirks
        if removed and not legacy_skip:
            # the next player slid into the removed seat: they keep their turn
            if s.turn_index >= len(s.players):
                s.turn_index, s.round = 0, s.round + 1
        else:
            if removed:
                s.turn_index = 0 if s.turn_index >= len(s.players) else s.turn_index
            s.turn_index += 1
            if s.turn_index >= len(s.players):
                s.turn_index, s.round = 0, s.round + 1
        if s.law is not None and not s.law["permanent"]:
            s.law["turns_remaining"] -= 1
            if s.law["turns_remaining"] <= 0:
                s.law = None
                ev.append(Event("law_expired", {"law": prev_law["id"]}))
        if s.turn_index == 0 and s.round <= s.cfg.rounds:
            ev.append(Event("round_end", {"round": s.round - 1}))
        if s.round > s.cfg.rounds:
            self._begin_endgame(s, ev)
        else:
            self._begin_turn(s, now, ev)

    def _remove_player(self, s: BzState, pid: int, why: str, ev: list) -> None:
        idx = s.players.index(pid)
        s.players.remove(pid)
        for d in (s.scores, s.afk, s.streak, s.golden_pass, s.silenced, s.switcheroo_used):
            d.pop(pid, None)
        if s.sombrero_holder == pid:
            s.sombrero_holder = s.players[0] if s.players else None
        s.leaving = [p for p in s.leaving if p != pid]
        s.tied = [p for p in s.tied if p != pid]
        if idx < s.turn_index:
            s.turn_index -= 1
        ev.append(Event("player_removed", {"player": pid, "why": why}))

    def _leave(self, s: BzState, actor: int, now: int, rng: random.Random, ev: list) -> None:
        if s.stage == "turns" and actor == s.turn_player and len(s.players) > 0:
            if actor not in s.leaving:
                s.leaving.append(actor)
            p = s.pending
            if p is not None and p.actor == actor:
                forfeit = p.kind == "answer" and s.q_kind == "turn"
                self._resolve(s, p, Intent(FORFEIT) if forfeit else None, now, rng, ev)
            return                                                       # _run drops anything else waiting on them
        # not their turn (or the endgame): they just go, and anything waiting on them is dropped
        self._remove_player(s, actor, "left", ev)
        s.agenda = [i for i in s.agenda if i[1] != actor]
        if s.pending is not None and s.pending.actor == actor:
            s.pending, s.question = None, None
        if s.waiting_question and s.q_actor == actor:
            s.waiting_question = False
        if not s.players:
            s.over = True
            ev.append(Event("game_over", {"reason": "no_players"}))

    # ───────────────────────────── scoring helpers ─────────────────────────────

    @staticmethod
    def _pts(s: BzState, pid: int, delta: int, bypass: bool = False) -> int:
        if not bypass:
            delta = max(-R.MAX_SWING, min(R.MAX_SWING, delta))
        s.scores[pid] = s.scores.get(pid, 0) + delta
        return delta

    def _law_start_of_turn(self, s: BzState, pid: int, ev: list) -> None:
        lid = s.law["id"]
        if lid == 5 and s.scores.get(pid, 0) >= max(s.scores.values(), default=0):
            self._pts(s, pid, -R.KARMA_TAX)
            ev.append(Event("law_effect", {"law": 5, "player": pid, "delta": -R.KARMA_TAX}))
        elif lid == 6 and s.scores.get(pid, 0) <= min(s.scores.values(), default=0):
            self._pts(s, pid, R.UNDERDOG_BOOST)
            ev.append(Event("law_effect", {"law": 6, "player": pid, "delta": R.UNDERDOG_BOOST}))

    def _law_after_correct(self, s: BzState, pid: int, ev: list) -> None:
        lid = s.law["id"]
        delta = 0
        if lid == 1 and s.answer_time_s < R.SPEED_TAX_SECONDS:
            delta = -R.SPEED_TAX_PENALTY
        elif lid == 4 and s.streak.get(pid, 0) >= 2:
            delta = R.HOT_STREAK_BONUS
        elif lid == 8 and s.turn_index == len(s.players) - 1:
            delta = R.LUCKY_LAST_BONUS
        if delta:
            self._pts(s, pid, delta)
            ev.append(Event("law_effect", {"law": lid, "player": pid, "delta": delta}))

    def _law_after_wrong(self, s: BzState, pid: int, ev: list) -> None:
        if s.law["id"] == 2 and s.answer_time_s > R.SLOW_BURN_SECONDS:
            self._pts(s, pid, -R.SLOW_BURN_PENALTY)
            ev.append(Event("law_effect", {"law": 2, "player": pid, "delta": -R.SLOW_BURN_PENALTY}))

    def _activate_mist(self, s: BzState, ev: list) -> None:
        s.mist_active = True
        s.mist_turns = s.mist_duration + (0 if "mist_short" in s.cfg.legacy_quirks else 1)
        ev.append(Event("mist_on", {"turns": s.mist_duration}))

    # ───────────────────────────── steps ─────────────────────────────

    def _step(self, s: BzState, now: int, rng: random.Random, ev: list) -> bool:
        """Run the head of the agenda. Returns True when the game is now waiting for something."""
        item = s.agenda[0]
        kind, pid = item[0], item[1]
        cfg = s.cfg
        if kind == "ask":
            s.waiting_question, s.q_kind, s.q_actor = True, item[2], pid
            s.q_type = item[3] if len(item) > 3 else "multiple"
            return True
        if kind == "draw":
            _, _, which, prompt, source = item
            if (which == "wango" and source != "chain" and s.golden_pass.get(pid)
                    and "golden_pass_wrong_only" not in cfg.legacy_quirks):
                s.golden_pass[pid] = False
                s.agenda.pop(0)
                ev.append(Event("golden_pass_used", {"player": pid}))
                return False
            if prompt:
                s.pending = Pending("draw", pid, now + cfg.draw_timeout_ms, {"which": which})
                return True
            s.agenda.pop(0)
            self._do_draw(s, pid, which, 0, rng, ev)
            return False
        if kind == "spin":
            s.pending = Pending("spin", pid, now + cfg.draw_timeout_ms, {})
            return True
        if kind == "monkey":
            if item[2] is None:
                item = ("monkey", pid, rng.random() < 0.5)         # which side is lucky: the monkey knows, the player doesn't
                s.agenda[0] = item
            s.pending = Pending("monkey", pid, now + cfg.monkey_timeout_ms, {})
            return True
        if kind == "pick":
            s.pending = Pending("pick_target", pid, now + cfg.pick_timeout_ms, {"purpose": item[2]})
            return True
        if kind == "law":
            s.pending = Pending("pick_rule", pid, now + cfg.law_timeout_ms, {})
            return True
        s.agenda.pop(0)
        if kind == "chance":
            self._apply_chance(s, pid, item[2], rng, ev)
        elif kind == "wango":
            self._apply_wango(s, pid, item[2], item[3], rng, ev)
        elif kind == "dw":
            self._double_wango_step(s, pid, item[2], item[3], item[4], rng, ev)
        elif kind == "seg":
            self._apply_segment(s, pid, item[2], item[3], item[4], rng, ev)
        else:                                                     # pragma: no cover - agenda is engine-built
            raise AssertionError(f"unknown step {kind}")
        return False

    def _push(self, s: BzState, *items: tuple) -> None:
        s.agenda[0:0] = list(items)

    def _do_draw(self, s: BzState, pid: int, which: str, chain: int, rng: random.Random, ev: list) -> None:
        if which == "chance":
            card = draw_chance(rng)
            ev.append(Event("card_drawn", {"player": pid, "deck": "chance", "card": card.value}))
            self._push(s, ("chance", pid, card))
        else:
            card = draw_wango(rng)
            ev.append(Event("card_drawn", {"player": pid, "deck": "wango", "card": card.value}))
            self._push(s, ("wango", pid, card, chain))

    # ───────────────────────────── resolving a decision ─────────────────────────────

    def _resolve(self, s: BzState, p: Pending, intent: Optional[Intent], now: int, rng: random.Random, ev: list) -> None:
        pid = p.actor
        s.pending = None
        if p.kind == "answer":
            self._resolve_answer(s, p, intent, now, ev)
        elif p.kind == "draw":
            item = s.agenda.pop(0)
            self._do_draw(s, pid, item[2], 0, rng, ev)
        elif p.kind == "spin":
            item = s.agenda.pop(0)
            depth, chain = item[2], item[3]
            seg = spin(rng)
            if depth >= 1 and seg == WheelSegment.WANGO_AGAIN:
                seg = WheelSegment.BONUS_ROUND                    # the chain cap: Wango Again becomes Bonus Round
            ev.append(Event("wheel_result", {"player": pid, "segment": seg.value}))
            self._push(s, ("seg", pid, seg, depth, chain))
        elif p.kind == "monkey":
            item = s.agenda.pop(0)
            self._resolve_monkey(s, pid, item[2], None if intent is None else intent.choice, ev)
        elif p.kind == "pick_target":
            item = s.agenda.pop(0)
            self._resolve_pick(s, pid, item[2], None if intent is None else intent.user_id, ev)
        elif p.kind == "pick_rule":
            s.agenda.pop(0)
            if intent is None:
                ev.append(Event("law_timeout", {"player": pid}))
                return
            s.law = R.make_active_law(intent.rule_id, len(s.players))
            ev.append(Event("law_set", {"player": pid, "law": intent.rule_id}))
            if s.law["permanent"]:
                if intent.rule_id == 10:
                    s.mist_duration = R.MIST_MAGNET_TURNS
                elif intent.rule_id == 11:
                    s.sombrero_penalty = R.SOMBRERO_CURSE_PENALTY

    def _resolve_answer(self, s: BzState, p: Pending, intent: Optional[Intent], now: int, ev: list) -> None:
        pid, kind, q = p.actor, s.q_kind, s.question
        timed_out = intent is None
        forfeit = intent is not None and intent.kind == FORFEIT
        chosen = None if (timed_out or forfeit) else intent.index
        right = chosen is not None and chosen == q.correct_index
        s.last_reveal = {"kind": kind, "player": pid, "correct_index": q.correct_index, "chosen": chosen,
                         "timed_out": timed_out, "forfeit": forfeit}
        ev.append(Event("reveal", dict(s.last_reveal)))
        s.agenda.pop(0)
        s.question = None
        if kind == "double_down":
            delta = R.TIMEOUT if timed_out else (R.DOUBLE_DOWN_BONUS if right else R.DOUBLE_DOWN_PENALTY)
            self._pts(s, pid, delta)
            return
        if kind == "tiebreak":
            delta = R.TIMEOUT if timed_out else (R.CORRECT if right else R.WRONG)
            self._pts(s, pid, delta)
            return
        # a normal turn
        if timed_out or forfeit:
            s.answer_time_s = s.cfg.question_timeout_ms / 1000
            self._pts(s, pid, R.timeout_penalty(s.law))
            s.streak[pid] = 0
            s.afk[pid] = (s.afk.get(pid, 0) + 1) if (timed_out and not forfeit) else 0
            if s.law:
                self._law_after_wrong(s, pid, ev)
            return
        s.answer_time_s = (now - s.q_start_ms) / 1000
        if right:
            s.afk[pid] = 0
            self._pts(s, pid, R.CORRECT)
            s.streak[pid] = s.streak.get(pid, 0) + 1
            s.correct_count[pid] = s.correct_count.get(pid, 0) + 1
            if s.law:
                self._law_after_correct(s, pid, ev)
            if s.law and s.law["id"] == 9 and s.scores.get(pid, 0) >= max(s.scores.values(), default=0):
                ev.append(Event("streak_breaker", {"player": pid}))
                self._push(s, ("draw", pid, "wango", True, "streak"))
            else:
                self._push(s, ("draw", pid, "chance", True, "correct"))
            return
        penalty = R.wrong_penalty(s.law)
        if s.sombrero_holder == pid:
            penalty -= s.sombrero_penalty
        self._pts(s, pid, penalty)
        s.streak[pid] = 0
        s.afk[pid] = 0
        if s.law:
            self._law_after_wrong(s, pid, ev)
        if s.golden_pass.get(pid):
            s.golden_pass[pid] = False
            ev.append(Event("golden_pass_used", {"player": pid}))
            return
        self._push(s, ("draw", pid, "wango", True, "wrong"))

    def _resolve_monkey(self, s: BzState, pid: int, lucky_belly: bool, choice: Optional[str], ev: list) -> None:
        pick = choice or "tail"                                    # on timeout the monkey picks the tail for you
        belly = pick == "belly"
        pts = R.MONKEY_BELLY if (belly == lucky_belly) else R.MONKEY_TAIL
        self._pts(s, pid, pts)
        ev.append(Event("monkey_result", {"player": pid, "choice": pick, "delta": pts, "timed_out": choice is None}))
        if pts < 0:
            self._push(s, ("draw", pid, "wango", False, "monkey"))

    def _resolve_pick(self, s: BzState, pid: int, purpose: str, target: Optional[int], ev: list) -> None:
        if purpose == "switcheroo":
            if target is None:
                ev.append(Event("switcheroo_skipped", {"player": pid}))
                return
            s.scores[pid], s.scores[target] = s.scores[target], s.scores[pid]
            ev.append(Event("scores_swapped", {"a": pid, "b": target}))
            return
        if target is None:
            ev.append(Event("gift_timeout", {"player": pid}))
            return
        s.scores[target] = s.scores.get(target, 0) - R.GIFT_AMOUNT
        s.scores[pid] = s.scores.get(pid, 0) + R.GIFT_AMOUNT
        ev.append(Event("steal", {"from": target, "to": pid, "amount": R.GIFT_AMOUNT}))

    # ───────────────────────────── cards ─────────────────────────────

    def _solo(self, s: BzState) -> bool:
        return len(s.players) == 1

    def _apply_chance(self, s: BzState, pid: int, card: ChanceCard, rng: random.Random, ev: list) -> None:
        if card == ChanceCard.LUCKY_LLAMA:
            self._pts(s, pid, R.LUCKY_LLAMA)
        elif card == ChanceCard.SWITCHEROO:
            if self._solo(s) or s.switcheroo_used.get(pid):
                self._pts(s, pid, R.LUCKY_LLAMA)
            else:
                s.switcheroo_used[pid] = True
                self._push(s, ("pick", pid, "switcheroo"))
        elif card == ChanceCard.DOUBLE_DOWN:
            qtype = "boolean" if rng.random() < 0.30 else "multiple"
            self._push(s, ("ask", pid, "double_down", qtype))
        elif card == ChanceCard.SPIN_THE_WHEEL:
            self._push(s, ("spin", pid, 0, 0))
        elif card == ChanceCard.GOLDEN_PASS:
            s.golden_pass[pid] = True
        elif card == ChanceCard.BAMBOOZLE:
            if s.round >= s.cfg.rounds:
                self._pts(s, pid, R.LUCKY_LLAMA)                   # a law would expire before it did anything
            else:
                self._push(s, ("law", pid))

    def _next_in_order(self, s: BzState, pid: int) -> int:
        return s.players[(s.players.index(pid) + 1) % len(s.players)]

    def _apply_wango(self, s: BzState, pid: int, card: WangoCard, chain: int, rng: random.Random, ev: list) -> None:
        if card == WangoCard.WANGO_CLASSIC:
            self._push(s, ("spin", pid, 0, chain))
        elif card == WangoCard.THE_SILENCE:
            s.silenced[pid] = True
        elif card == WangoCard.REVERSE_UNO:
            if not self._solo(s):
                self._pts(s, self._next_in_order(s, pid), -R.REVERSE_UNO_PENALTY)
        elif card == WangoCard.THE_SOMBRERO:
            if s.sombrero_holder is None:
                s.sombrero_holder = pid
            elif s.sombrero_holder == pid:
                if self._solo(s):
                    s.sombrero_penalty += R.SOMBRERO_STEP
                else:
                    s.sombrero_holder = self._next_in_order(s, pid)
            else:
                s.sombrero_holder = pid
        elif card == WangoCard.DOUBLE_WANGO:
            remaining = R.DOUBLE_WANGO_CHAIN_LIMIT - chain
            if remaining > 0:
                self._push(s, ("dw", pid, 0, min(2, remaining), chain))
        elif card == WangoCard.MYSTIC_MIST:
            self._activate_mist(s, ev)

    def _double_wango_step(self, s: BzState, pid: int, i: int, n: int, chain: int, rng: random.Random, ev: list) -> None:
        if i >= n:
            return
        extra = draw_wango(rng)
        if extra == WangoCard.DOUBLE_WANGO:
            extra = draw_wango(rng)                                # a chain cannot re-chain: one re-roll...
            if extra == WangoCard.DOUBLE_WANGO:
                ev.append(Event("chain_recoil", {"player": pid}))  # ...then the card is skipped
                self._push(s, ("dw", pid, i + 1, n, chain))
                return
        ev.append(Event("card_drawn", {"player": pid, "deck": "wango", "card": extra.value, "chain": True}))
        self._push(s, ("wango", pid, extra, chain + 1), ("dw", pid, i + 1, n, chain))

    # ───────────────────────────── wheel ─────────────────────────────

    def _apply_segment(self, s: BzState, pid: int, seg: WheelSegment, depth: int, chain: int, rng: random.Random,
                       ev: list) -> None:
        if seg == WheelSegment.LADDER_OF_CHANCE:
            self._push(s, ("monkey", pid, None))
        elif seg == WheelSegment.TAX_SEASON:
            cur = s.scores.get(pid, 0)
            s.scores[pid] = cur - R.tax(cur)                       # a percentage: it ignores the swing cap
        elif seg == WheelSegment.GIFT_OF_THE_BAMBOOZLE:
            if self._solo(s):
                s.scores[pid] = s.scores.get(pid, 0) + R.GIFT_AMOUNT
            else:
                self._push(s, ("pick", pid, "gift"))
        elif seg == WheelSegment.FULL_REVERSAL:
            if self._solo(s):
                s.scores[pid] = -s.scores.get(pid, 0)
            else:
                ranked = sorted(s.players, key=lambda p: s.scores.get(p, 0), reverse=True)
                values = list(reversed([s.scores.get(p, 0) for p in ranked]))
                for p, v in zip(ranked, values):
                    s.scores[p] = v
        elif seg == WheelSegment.MYSTIC_MIST:
            self._activate_mist(s, ev)
        elif seg == WheelSegment.BONUS_ROUND:
            self._pts(s, pid, R.BONUS_ROUND)
        elif seg == WheelSegment.WANGO_AGAIN:
            if depth >= R.WANGO_AGAIN_DEPTH_LIMIT:
                self._pts(s, pid, R.BONUS_ROUND)                   # already inside a chain: consolation prize
                return
            if s.golden_pass.get(pid) and "golden_pass_wrong_only" not in s.cfg.legacy_quirks:
                s.golden_pass[pid] = False
                ev.append(Event("golden_pass_used", {"player": pid}))
                return
            card = draw_wango(rng)
            ev.append(Event("card_drawn", {"player": pid, "deck": "wango", "card": card.value, "source": "wango_again"}))
            carried = 0 if "wango_again_reset" in s.cfg.legacy_quirks else chain
            if card == WangoCard.WANGO_CLASSIC:
                self._push(s, ("spin", pid, 1, carried))           # this spin cannot land on Wango Again
            else:
                self._push(s, ("wango", pid, card, carried))

    # ───────────────────────────── endgame ─────────────────────────────

    def _begin_endgame(self, s: BzState, ev: list) -> None:
        s.stage = "endgame"
        if s.mist_active:
            s.mist_active, s.mist_turns = False, 0
            ev.append(Event("mist_off", {"final": True}))
        s.tied = list(s.players)
        ev.append(Event("endgame", {"scores": dict(s.scores)}))

    def _endgame_advance(self, s: BzState, ev: list) -> None:
        """Called when the agenda is empty during the endgame: crown a champion or run another Sudden Bamboozle."""
        contenders = [p for p in s.tied if p in s.players]
        winners = top_scorers(s.scores, contenders)
        if len(winners) == 1:
            s.champion, s.over = winners[0], True
            ev.append(Event("game_over", {"champion": s.champion}))
            return
        s.tied = winners
        ev.append(Event("sudden_bamboozle", {"players": list(winners)}))
        s.agenda = [("spin", w, 0, 0) for w in winners] + [("ask", w, "tiebreak") for w in winners]
