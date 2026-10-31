"""Rooms and the room manager.

One room per Discord activity instance. A room moves lobby -> playing -> results and can go back to the lobby for a
rematch. All game rules live in the engine; this module only decides who may send what, keeps the seats, and moves
messages. Everything here is synchronous and takes the time as an argument (`now` in milliseconds), so tests drive it
with a fake clock; the only `await`s are in `pump`, which fetches questions and flushes results.

Behaviour (spec 8.2):
  * the host is the first participant; when the host is gone for longer than the reconnect grace the longest-present
    player takes over;
  * players who join a running game are spectators until the next game;
  * a disconnect keeps the seat for `activity.reconnect_grace_seconds`; after that the player is treated as having
    left (their seat is dropped, the engine removes them), and if they come back they are a spectator;
  * a second socket for the same user replaces the first;
  * rooms are capped and reaped (lobby and idle TTLs); a restart sends BYE{server_restart}.
"""
from __future__ import annotations

import random
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..engine import (ANSWER, DRAW_CARD, FORFEIT, LEAVE, MONKEY, PICK_RULE, PICK_TARGET, SPIN, GameConfig, IllegalIntent,
                      Intent, PlayerRef, Question, get_engine)
from ..settings import Settings
from .auth import AuthResult
from .protocol import FrameError, Parsed, envelope, parse_frame
from .ratelimit import TokenBucket

MIN_PLAYERS = {"bamboozled": 2, "fff": 2, "survival": 1}
HARD_MAX_PLAYERS = 10
ROUNDS_BOUNDS = {"bamboozled": (3, 20), "fff": (5, 30), "survival": (1, 1)}
GAME_KINDS = {"ANSWER": ANSWER, "DRAW_CARD": DRAW_CARD, "SPIN": SPIN, "PICK_TARGET": PICK_TARGET, "PICK_RULE": PICK_RULE,
              "MONKEY": MONKEY, "FORFEIT": FORFEIT}
# Engine events that are bookkeeping for the server, not cues for clients. turn_resolved carries every score.
INTERNAL_EVENTS = {"turn_resolved"}
NUMBERS_HIDDEN_BY_MIST = ("delta", "amount", "scores")
MAX_OUTBOX = 400
FLOOD_STRIKES = 60


class Refused(Exception):
    """The server will not let this connection in. `code` is machine readable."""

    def __init__(self, code: str, message: str, close_code: int = 1013):
        super().__init__(code)
        self.code, self.message, self.close_code = code, message, close_code


class Conn:
    """One authenticated socket. The transport drains `outbox`; tests just read it."""

    def __init__(self, auth: AuthResult, clock_ms: Callable[[], int]):
        self.auth = auth
        self.user_id = auth.user_id
        self.room_key = auth.room_key
        self.outbox: list[dict] = []
        self.seq = 0
        self.closed = False
        self.close_code: Optional[int] = None
        self.close_reason = ""
        self.bucket = TokenBucket(10, 10, clock_ms)
        self.strikes = 0
        self.seen_ids: OrderedDict[str, None] = OrderedDict()
        self.notify: Optional[Callable[[], None]] = None

    def send(self, t: str, d: dict, msg_id: Optional[str] = None) -> None:
        if self.closed:
            return
        if len(self.outbox) >= MAX_OUTBOX:                     # a client that never reads must not grow memory forever
            self.close(4429, "too slow to keep up")
            return
        self.seq += 1
        self.outbox.append(envelope(t, d, self.seq, msg_id))
        if self.notify:
            self.notify()

    def close(self, code: int, reason: str = "") -> None:
        if not self.closed:
            self.closed, self.close_code, self.close_reason = True, code, reason
            if self.notify:
                self.notify()

    def drain(self) -> list[dict]:
        out, self.outbox = self.outbox, []
        return out


@dataclass
class Member:
    user_id: int
    name: str
    avatar_url: str
    joined_ms: int
    conn: Optional[Conn] = None
    ready: bool = False
    spectator: bool = False
    disconnected_at: Optional[int] = None

    @property
    def connected(self) -> bool:
        return self.conn is not None and not self.conn.closed


@dataclass
class Room:
    key: str
    guild_id: int
    channel_id: int
    created_ms: int
    last_activity_ms: int
    phase: str = "lobby"                     # lobby | playing | results
    members: dict = field(default_factory=dict)
    host: Optional[int] = None
    mode: str = "bamboozled"
    cfg: dict = field(default_factory=lambda: {"rounds": None, "difficulty": None, "category": None})
    game: Any = None                         # engine state (bamboozled, fff)
    runs: dict = field(default_factory=dict)  # user_id -> engine state (survival: one run per player)
    results: Optional[list] = None
    started_ms: int = 0
    fetching: bool = False

    def players(self) -> list[Member]:
        return [m for m in self.members.values() if not m.spectator]

    def states(self) -> list[tuple[Optional[int], Any]]:
        if self.mode == "survival":
            return list(self.runs.items())
        return [(None, self.game)] if self.game is not None else []


QuestionProvider = Callable[[dict], Awaitable[Optional[Question]]]
Recorder = Callable[..., Awaitable[Any]]
GameOverHook = Callable[[Room, list], Awaitable[Any]]


class RoomManager:
    def __init__(self, settings: Settings, clock_ms: Callable[[], int], provider: QuestionProvider,
                 recorder: Optional[Recorder] = None, on_game_over: Optional[GameOverHook] = None,
                 rng_factory: Callable[[], random.Random] = lambda: random.Random(random.SystemRandom().getrandbits(64))):
        self.settings, self.clock_ms, self.provider = settings, clock_ms, provider
        self.recorder, self.on_game_over, self.rng_factory = recorder, on_game_over, rng_factory
        self.rooms: dict[str, Room] = {}
        self.shutting_down = False
        self._to_flush: list[tuple[Room, list, dict]] = []

    # ───────────────────────────── connecting ─────────────────────────────

    def connect(self, auth: AuthResult, now: int) -> Conn:
        """Seat an authenticated user. Raises Refused when the server cannot take them."""
        if self.shutting_down or self.settings.get("system.killswitch"):
            raise Refused("maintenance", "Bamboozled is closed for maintenance. Try again shortly.", 1012)
        room = self.rooms.get(auth.room_key)
        if room is None:
            if len(self.rooms) >= self.settings.get("activity.max_rooms"):
                raise Refused("server_full", "Bamboozled is full right now. Try again in a few minutes.")
            room = Room(auth.room_key, auth.guild_id, auth.channel_id, now, now)
            self.rooms[auth.room_key] = room
            room.mode = next((m for m in ("bamboozled", "fff", "survival") if self.settings.get(f"feature.{m}")), "bamboozled")
        member = room.members.get(auth.user_id)
        if member is not None:
            old = member.conn
            if old is not None and not old.closed:
                old.send("BYE", {"reason": "kicked"})              # one live socket per user per room
                old.close(4409, "signed in from another window")
        else:
            spectator = room.phase != "lobby" or len(room.players()) >= self._max_players()
            if spectator and not self.settings.get("activity.allow_spectators"):
                raise Refused("room_full", "This game is full or already running." if room.phase != "lobby"
                              else "This game is full.")
            member = Member(auth.user_id, auth.display_name, auth.avatar_url, now, spectator=spectator)
            room.members[auth.user_id] = member
        conn = Conn(auth, self.clock_ms)
        member.conn, member.disconnected_at = conn, None
        member.name, member.avatar_url = auth.display_name, auth.avatar_url      # always from the verified user object
        room.last_activity_ms = now
        if room.host is None or room.host not in room.members:
            room.host = auth.user_id
        self._broadcast_state(room, now)
        return conn

    def disconnect(self, conn: Conn, now: int) -> None:
        room = self.rooms.get(conn.room_key)
        conn.close(conn.close_code or 1000, conn.close_reason)
        if room is None:
            return
        member = room.members.get(conn.user_id)
        if member is not None and member.conn is conn:
            member.disconnected_at = now
            self._broadcast_state(room, now)

    # ───────────────────────────── incoming messages ─────────────────────────────

    def handle_text(self, conn: Conn, raw: str | bytes, now: int) -> None:
        """Entry point for every frame after AUTH. Never raises: a bad frame gets an ERROR and the socket lives on."""
        if conn.closed:
            return
        if not conn.bucket.allow():
            conn.strikes += 1
            if conn.strikes >= FLOOD_STRIKES:
                conn.close(4429, "too many messages")
            elif conn.strikes % 10 == 1:
                conn.send("ERROR", {"code": "rate_limited", "message": "Slow down: at most 10 messages a second."})
            return
        conn.strikes = 0
        try:
            parsed = parse_frame(raw)
        except FrameError as err:
            conn.send("ERROR", {"code": err.code, "message": err.message})
            return
        if parsed is None or parsed.t == "AUTH":                    # unknown type ignored; AUTH only valid first
            return
        self.handle(conn, parsed, now)

    def handle(self, conn: Conn, msg: Parsed, now: int) -> None:
        room = self.rooms.get(conn.room_key)
        member = room.members.get(conn.user_id) if room else None
        if room is None or member is None or member.conn is not conn:
            conn.send("ERROR", {"code": "not_in_room", "message": "This window is no longer part of the game."})
            return
        if msg.id is not None:                                      # idempotent on the client's message id
            if msg.id in conn.seen_ids:
                conn.send("ACK", {"id": msg.id, "duplicate": True})
                return
            conn.seen_ids[msg.id] = None
            if len(conn.seen_ids) > 64:
                conn.seen_ids.popitem(last=False)
        room.last_activity_ms = now
        try:
            self._dispatch(room, member, msg, now)
        except IllegalIntent as err:
            conn.send("ERROR", {"code": err.code, "message": err.message})
        except Refusal as err:
            conn.send("ERROR", {"code": err.code, "message": err.message})

    def _dispatch(self, room: Room, member: Member, msg: Parsed, now: int) -> None:
        t, d = msg.t, msg.d
        if t == "PING":
            member.conn.send("PONG", {"server_now_ms": now})
            return
        if t == "RESYNC":
            member.conn.send("STATE", self._state_for(room, member, now))
            return
        if t in GAME_KINDS:
            return self._game_intent(room, member, t, d, now)
        if t == "LEAVE":
            return self._leave(room, member, now)
        if t == "READY":
            self._need(room.phase == "lobby", "bad_phase", "You can only ready up in the lobby.")
            self._need(not member.spectator, "spectator", "Spectators cannot ready up.")
            member.ready = d.ready
        elif t == "SET_MODE":
            self._host_lobby(room, member)
            if not self.settings.get(f"feature.{d.mode}"):
                raise Refusal("mode_disabled", "That mode is switched off right now.")
            room.mode = d.mode
            room.cfg["rounds"] = None                                  # each mode has its own sensible default
            for m in room.members.values():
                m.ready = False
        elif t == "SET_CONFIG":
            self._host_lobby(room, member)
            self._set_config(room, d)
        elif t == "START":
            self._host_lobby(room, member)
            self._start(room, now)
        elif t == "REMATCH":
            self._need(room.host == member.user_id, "not_host", "Only the host can start a rematch.")
            self._need(room.phase == "results", "bad_phase", "There is no finished game to replay.")
            self._reset_to_lobby(room)
        self._broadcast_state(room, now)

    @staticmethod
    def _need(cond: bool, code: str, message: str) -> None:
        if not cond:
            raise Refusal(code, message)

    def _host_lobby(self, room: Room, member: Member) -> None:
        self._need(room.host == member.user_id, "not_host", "Only the host can do that.")
        self._need(room.phase == "lobby", "bad_phase", "That is only possible in the lobby.")

    def _set_config(self, room: Room, d) -> None:
        lo, hi = ROUNDS_BOUNDS[room.mode]
        sent = d.model_fields_set
        if "rounds" in sent:
            if d.rounds is not None and not lo <= d.rounds <= hi:
                raise Refusal("bad_config", f"Rounds must be between {lo} and {hi} for this mode.")
            room.cfg["rounds"] = d.rounds
        if "difficulty" in sent:
            room.cfg["difficulty"] = d.difficulty
        if "category" in sent:
            room.cfg["category"] = d.category

    # ───────────────────────────── starting and finishing ─────────────────────────────

    def _max_players(self) -> int:
        return min(self.settings.get("activity.max_players"), HARD_MAX_PLAYERS)

    def _game_config(self, room: Room) -> GameConfig:
        rounds = room.cfg["rounds"] or (self.settings.get("game.fff_rounds") if room.mode == "fff"
                                        else self.settings.get("game.total_rounds"))
        lo, hi = ROUNDS_BOUNDS[room.mode]
        rounds = min(max(rounds, lo), hi)
        return GameConfig(mode=room.mode, rounds=rounds, difficulty=room.cfg["difficulty"], category=room.cfg["category"],
                          question_timeout_ms=self.settings.get("game.question_timeout_seconds") * 1000)

    def _start(self, room: Room, now: int) -> None:
        roster = [m for m in room.players() if m.connected]
        need = MIN_PLAYERS[room.mode]
        self._need(len(roster) >= need, "not_enough_players", f"This mode needs at least {need} player(s).")
        self._need(self.settings.get(f"feature.{room.mode}"), "mode_disabled", "That mode is switched off right now.")
        for m in room.players():
            if not m.connected:
                m.spectator = True                                   # not here at the start: watching this time
        engine, cfg = get_engine(room.mode), self._game_config(room)
        refs = [PlayerRef(m.user_id) for m in roster]
        room.results, room.game, room.runs = None, None, {}
        if room.mode == "survival":
            for ref in refs:
                room.runs[ref.user_id] = engine.new_game(cfg, [ref], self.rng_factory(), now)
        else:
            room.game = engine.new_game(cfg, refs, self.rng_factory(), now)
        room.phase, room.started_ms = "playing", now

    def _reset_to_lobby(self, room: Room) -> None:
        room.phase, room.game, room.runs, room.results = "lobby", None, {}, None
        for m in list(room.members.values()):
            m.ready = False
            if m.spectator and m.connected and len(room.players()) < self._max_players():
                m.spectator = False

    def _finish_if_over(self, room: Room, now: int) -> None:
        engine = get_engine(room.mode)
        states = room.states()
        if room.phase != "playing" or not states or not all(engine.is_over(s) for _, s in states):
            return
        if room.mode == "survival":
            rows = [engine.results(s)[0] for _, s in states]
            order = sorted(rows, key=lambda r: (-r.score, r.user_id))
            from ..engine.api import ResultRow
            room.results = [ResultRow(r.user_id, i + 1, r.score, r.correct, r.details) for i, r in enumerate(order)]
        else:
            room.results = engine.results(room.game)
        room.phase = "results"
        for m in room.members.values():
            m.ready = False
        self._to_flush.append((room, list(room.results), {"started_ms": room.started_ms, "cfg": dict(room.cfg),
                                                          "mode": room.mode, "runs": {u: engine.results(s)[0]
                                                                                       for u, s in room.runs.items()}}))
        self._broadcast(room, "EVENT", {"kind": "game_over", "payload": {}})

    # ───────────────────────────── gameplay ─────────────────────────────

    def _game_intent(self, room: Room, member: Member, kind: str, d, now: int) -> None:
        self._need(room.phase == "playing", "bad_phase", "No game is running.")
        self._need(not member.spectator, "spectator", "Spectators can watch but not play.")
        intent = Intent(kind=GAME_KINDS[kind], index=getattr(d, "index", None), user_id=getattr(d, "user_id", None),
                        rule_id=getattr(d, "rule_id", None), choice=getattr(d, "choice", None))
        self._apply(room, member.user_id, intent, now)

    def _apply(self, room: Room, uid: int, intent: Intent, now: int) -> None:
        engine = get_engine(room.mode)
        key = uid if room.mode == "survival" else None
        state = room.runs.get(key) if room.mode == "survival" else room.game
        if state is None:
            raise Refusal("not_playing", "You are not in this game.")
        result = engine.apply(state, uid, intent, now)
        self._store(room, key, state, result, now)

    def _store(self, room: Room, key: Optional[int], before: Any, result, now: int) -> None:
        if room.mode == "survival":
            room.runs[key] = result.state
        else:
            room.game = result.state
        mist = bool(getattr(before, "mist_active", False) or getattr(result.state, "mist_active", False))
        self._send_events(room, result.events, mist)
        self._finish_if_over(room, now)
        self._broadcast_state(room, now)

    def _send_events(self, room: Room, events, mist: bool) -> None:
        for ev in events:
            if ev.kind in INTERNAL_EVENTS:
                continue
            payload = ev.payload
            if mist:
                payload = {k: v for k, v in payload.items() if k not in NUMBERS_HIDDEN_BY_MIST}
            elif ev.kind != "game_over":
                payload = {k: v for k, v in payload.items() if k != "scores" or ev.kind == "endgame"}
            self._broadcast(room, "EVENT", {"kind": ev.kind, "payload": payload})

    def _leave(self, room: Room, member: Member, now: int) -> None:
        if room.phase == "playing" and not member.spectator:
            try:
                self._apply(room, member.user_id, Intent(LEAVE), now)
            except (IllegalIntent, Refusal):
                pass
        member.spectator, member.ready = True, False
        self._after_departure(room, member.user_id, now)
        self._broadcast_state(room, now)

    def _after_departure(self, room: Room, uid: int, now: int) -> None:
        if room.host == uid or room.host not in room.members or room.members[room.host].spectator:
            self._new_host(room)

    @staticmethod
    def _new_host(room: Room) -> None:
        """The longest-present connected player; failing that any connected member; failing that nobody."""
        for pool in ([m for m in room.members.values() if not m.spectator and m.connected],
                     [m for m in room.members.values() if m.connected]):
            if pool:
                room.host = pool[0].user_id
                if pool[0].spectator and room.phase == "lobby":
                    pool[0].spectator = False
                return
        room.host = None

    # ───────────────────────────── time ─────────────────────────────

    async def pump(self, now: int) -> None:
        """Advance the world to `now`: seat/reap, fire engine deadlines, fetch questions, flush results."""
        if self.settings.get("system.killswitch"):
            self._close_all("room_closed", 1000)
            return
        for room in list(self.rooms.values()):
            self._expire_seats(room, now)
            if self._reap(room, now):
                continue
            if room.phase == "playing":
                self._fire_deadlines(room, now)
        for room in list(self.rooms.values()):
            if room.phase == "playing":
                await self._supply_questions(room, now)
        await self._flush()

    def _expire_seats(self, room: Room, now: int) -> None:
        grace = self.settings.get("activity.reconnect_grace_seconds") * 1000
        gone = [m for m in room.members.values() if m.disconnected_at is not None and now - m.disconnected_at >= grace]
        for m in gone:
            if room.phase == "playing" and not m.spectator:
                try:
                    self._apply(room, m.user_id, Intent(LEAVE), now)    # a seat that never came back is treated as left
                except (IllegalIntent, Refusal):
                    pass
            room.members.pop(m.user_id, None)
            self._after_departure(room, m.user_id, now)
        if gone and room.members:
            self._broadcast_state(room, now)

    def _reap(self, room: Room, now: int) -> bool:
        idle_min = self.settings.get("activity.lobby_ttl_minutes" if room.phase == "lobby" else "activity.idle_ttl_minutes")
        if not room.members or now - room.last_activity_ms >= idle_min * 60_000:
            self.close_room(room.key, "room_closed")
            return True
        return False

    def _fire_deadlines(self, room: Room, now: int) -> None:
        engine = get_engine(room.mode)
        for key, state in room.states():
            guard = 0
            while room.phase == "playing" and guard < 50:
                guard += 1
                current = room.runs.get(key) if room.mode == "survival" else room.game
                dl = engine.next_deadline_ms(current)
                if dl is None or dl > now:
                    break
                result = engine.on_timeout(current, now)
                if result.state is current:
                    break
                self._store(room, key, current, result, now)

    async def _supply_questions(self, room: Room, now: int) -> None:
        engine = get_engine(room.mode)
        for key, state in room.states():
            need = engine.needs_question(state)
            if not need:
                continue
            ask = {**need, "mode": room.mode, "difficulty": room.cfg["difficulty"] or need.get("difficulty"),
                   "category": room.cfg["category"] or need.get("category")}
            q = await self.provider(ask)
            current = room.runs.get(key) if room.mode == "survival" else room.game
            if current is not state or room.phase != "playing":
                continue                                               # the world moved on while we were fetching
            t = max(now, self.clock_ms())
            if q is None:
                if room.mode != "survival":
                    continue                                           # the provider falls back itself; try next pump
                result = engine.question_unavailable(current)
            else:
                result = engine.supply_question(current, q, t)
            self._store(room, key, current, result, t)

    async def _flush(self) -> None:
        pending, self._to_flush = self._to_flush, []
        for room, rows, info in pending:
            if self.recorder is not None and rows:
                guild = room.guild_id
                if info["mode"] == "survival":
                    for uid, row in info["runs"].items():
                        await self.recorder("survival", guild, [row], started_ms=info["started_ms"], cfg=info["cfg"])
                else:
                    await self.recorder(info["mode"], guild, rows, started_ms=info["started_ms"], cfg=info["cfg"])
            if self.on_game_over is not None and self.settings.get("feature.post_results"):
                await self.on_game_over(room, rows)

    # ───────────────────────────── closing ─────────────────────────────

    def close_room(self, key: str, reason: str, close_code: int = 1000) -> None:
        room = self.rooms.pop(key, None)
        if room is None:
            return
        for m in room.members.values():
            if m.conn is not None:
                m.conn.send("BYE", {"reason": reason})
                m.conn.close(close_code, reason)

    def _close_all(self, reason: str, close_code: int) -> None:
        for key in list(self.rooms):
            self.close_room(key, reason, close_code)

    def shutdown(self) -> None:
        """Stop taking rooms and tell everyone to reconnect (a restart ends running games)."""
        self.shutting_down = True
        self._close_all("server_restart", 1012)

    # ───────────────────────────── views ─────────────────────────────

    def _broadcast(self, room: Room, t: str, d: dict) -> None:
        for m in room.members.values():
            if m.connected:
                m.conn.send(t, d)

    def _broadcast_state(self, room: Room, now: int) -> None:
        for m in room.members.values():
            if m.connected:
                m.conn.send("STATE", self._state_for(room, m, now))

    def _state_for(self, room: Room, viewer: Member, now: int) -> dict:
        engine = get_engine(room.mode)
        game, board, deadline = None, None, None
        if room.mode == "survival" and room.runs:
            own = room.runs.get(viewer.user_id)
            game = engine.view_for(own, viewer.user_id) if own is not None else None
            board = [{"user_id": u, "streak": s.streak, "over": s.over, "reason": s.reason} for u, s in room.runs.items()]
            deadline = game["deadline_ms"] if game else None
        elif room.game is not None:
            game = engine.view_for(room.game, viewer.user_id)
            deadline = game.get("deadline_ms") if isinstance(game, dict) else None
        need = MIN_PLAYERS[room.mode]
        return {
            "phase": room.phase, "mode": room.mode, "you": viewer.user_id, "role": "spectator" if viewer.spectator else "player",
            "host": room.host, "server_now_ms": now, "deadline_ms": deadline,
            "config": {"rounds": room.cfg["rounds"], "difficulty": room.cfg["difficulty"], "category": room.cfg["category"]},
            "min_players": need, "max_players": self._max_players(),
            "can_start": room.phase == "lobby" and room.host == viewer.user_id
            and len([m for m in room.players() if m.connected]) >= need,
            "members": [{"user_id": m.user_id, "name": m.name, "avatar_url": m.avatar_url, "ready": m.ready,
                         "connected": m.connected, "spectator": m.spectator, "host": m.user_id == room.host}
                        for m in room.members.values()],
            "game": game, "board": board,
            "results": ([{"user_id": r.user_id, "rank": r.rank, "score": r.score, "correct": r.correct, "details": r.details}
                         for r in room.results] if room.results is not None else None),
        }

    # ───────────────────────────── admin helpers ─────────────────────────────

    def snapshot(self) -> dict:
        """Counts for health/admin screens (never exposed on the unauthenticated health route)."""
        return {"rooms": len(self.rooms), "sockets": sum(1 for r in self.rooms.values() for m in r.members.values()
                                                         if m.connected),
                "by_mode": {m: sum(1 for r in self.rooms.values() if r.phase == "playing" and r.mode == m)
                            for m in MIN_PLAYERS}}


class Refusal(Exception):
    """A well-formed request the room will not honour (not the host, wrong phase, ...)."""

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message
