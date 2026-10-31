"""Shared helpers for the server tests: a fake clock, scripted clients and a fake question provider."""
import json
import random

from bamboozled.engine import ANSWER, DRAW_CARD, FORFEIT, LEAVE, MONKEY, PICK_RULE, PICK_TARGET, SPIN, Question
from bamboozled.engine.bots import legal_intents
from bamboozled.server.auth import AuthResult
from bamboozled.server.rooms import RoomManager
from bamboozled.settings import Settings

Q = Question("Q?", ("right", "a", "b", "c"), 0, "Cat", "easy")


class Clock:
    def __init__(self, now: int = 1_000_000):
        self.now = now

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> int:
        self.now += ms
        return self.now


async def provider(need):
    return Q


class Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, mode, guild_id, rows, *, started_ms, cfg):
        self.calls.append((mode, guild_id, [(r.user_id, r.rank, r.score) for r in rows], cfg))


def make(settings=None, **overrides):
    clock, rec, overs = Clock(), Recorder(), []

    async def on_over(room, rows):
        overs.append((room.key, [(r.user_id, r.rank) for r in rows]))

    mgr = RoomManager(settings or Settings(overrides), clock, provider, recorder=rec, on_game_over=on_over,
                      rng_factory=lambda: random.Random(7))
    mgr.overs = overs
    return mgr, clock, rec


def auth(uid, room="r1", name=None, guild=10, channel=20):
    return AuthResult(uid, name or f"P{uid}", f"https://cdn.example/{uid}.png", room, guild, channel)


def msg(t, d=None, id=None):
    obj = {"v": 1, "t": t, "d": d or {}}
    if id is not None:
        obj["id"] = id
    return json.dumps(obj)


def to_msg(intent):
    k = intent.kind
    if k == ANSWER:
        return msg("ANSWER", {"index": intent.index})
    if k == PICK_TARGET:
        return msg("PICK_TARGET", {"user_id": intent.user_id})
    if k == PICK_RULE:
        return msg("PICK_RULE", {"rule_id": intent.rule_id})
    if k == MONKEY:
        return msg("MONKEY", {"choice": intent.choice})
    return msg({DRAW_CARD: "DRAW_CARD", SPIN: "SPIN", FORFEIT: "FORFEIT", LEAVE: "LEAVE"}[k])


def kinds(conn):
    return [f["t"] for f in conn.outbox]


def last(conn, t):
    return next((f for f in reversed(conn.outbox) if f["t"] == t), None)


def errors(conn):
    return [f["d"]["code"] for f in conn.outbox if f["t"] == "ERROR"]


async def play_out(mgr, clock, conns, room_key="r1", max_steps=4000, rng=None):
    """Drive a running room to the results screen using random legal moves sent as real messages."""
    rng = rng or random.Random(3)
    room = mgr.rooms[room_key]
    for _ in range(max_steps):
        if room.phase != "playing":
            return room
        await mgr.pump(clock.now)
        if room.phase != "playing":
            return room
        moves = [(a, i) for _, s in room.states() for a, i in legal_intents(s)]
        if not moves or rng.random() < 0.1:
            clock.advance(35_000)                         # let a deadline pass
            continue
        actor, intent = rng.choice(moves)
        clock.advance(300)
        mgr.handle_text(conns[actor], to_msg(intent), clock.now)
    raise AssertionError("room did not finish")
