"""Harness that drives the legacy (Discord-coupled) rules without Discord.

The legacy rules live inside cogs/game.py, fastest_fingers.py and survival.py and talk to a channel, UI views,
the clock and `random`. This module swaps those collaborators for fakes driven by a Script, so a test can say
"the wheel lands on Tax Season, the player picks user 3" and then assert the score deltas.

These characterisation tests are the oracle for the Phase 2 engine (see docs/rules-as-implemented.md).
Nothing here imports or calls the network or a database.
"""
from __future__ import annotations

import asyncio
import contextlib
import random as _random
import time as _time
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import cogs.game as G
from game_engine.state import GameState

QUESTION = {
    "question": "Q?", "correct_answer": "right", "incorrect_answers": ["a", "b", "c"],
    "category": "Cat", "difficulty": "easy",
}


class ScriptExhausted(AssertionError):
    pass


class Script:
    """Named FIFO queues of scripted decisions. An empty queue is a test failure, never a silent default."""

    def __init__(self, **queues: list):
        self.q = {k: list(v) for k, v in queues.items()}
        self.game: GameState | None = None
        self.elapsed = 7.0          # seconds the active player "took" to answer
        self.fetch_kwargs: list[dict] = []
        self.selects: list[list[int]] = []

    def next(self, key: str, *default: Any) -> Any:
        if self.q.get(key):
            return self.q[key].pop(0)
        if default:
            return default[0]
        raise ScriptExhausted(f"script has nothing left for '{key}'")

    def leftover(self) -> dict[str, list]:
        return {k: v for k, v in self.q.items() if v}


class FakeMessage:
    id = 9001

    async def edit(self, **_kw):
        return None


class FakeChannel:
    id = 555

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, content=None, *, embed=None, view=None, **_kw):
        parts = [content or ""]
        if embed is not None:
            parts.append(f"[embed:{getattr(embed, 'title', '')}]")
        self.sent.append(" ".join(p for p in parts if p))
        return FakeMessage()

    async def edit(self, **_kw):
        return None

    @property
    def text(self) -> str:
        return "\n".join(self.sent)


def make_game(n: int = 3, scores: dict[int, int] | None = None, **kw) -> GameState:
    players = list(range(1, n + 1))
    g = GameState(channel_id=555, host_id=1, players=players,
                  player_names={p: f"P{p}" for p in players},
                  scores={p: 500 for p in players}, active=True, test_mode=True, **kw)
    if scores:
        g.scores.update(scores)
    return g


def snapshot(game: GameState) -> dict:
    """The observable rules state: what a Phase 2 engine must reproduce step by step."""
    rule = game.active_bamboozle_rule
    return {
        "scores": dict(game.scores), "turn_index": game.current_turn_index, "round": game.current_round,
        "players": list(game.players), "golden_pass": {k: v for k, v in game.golden_pass.items() if v},
        "silenced": {k: v for k, v in game.silenced.items() if v}, "sombrero": game.sombrero_holder,
        "sombrero_penalty": game.sombrero_penalty, "mist": (game.mist_active, game.mist_turns_remaining),
        "mist_duration": game.mist_turn_duration, "rule": (rule["id"], rule["turns_remaining"]) if rule else None,
        "streak": dict(game.consecutive_correct), "afk": dict(game.afk_turns),
    }


# ── fake UI views (same constructor signatures as the real ones) ─────────────────────────────

def _views(script: Script) -> dict[str, Any]:
    class FakeAnswerView:
        def __init__(self, answers, correct_idx, active_player_id):
            self.children: list = []
            self.chosen_idx: int | None = None
            self.timed_out = False
            self._stopped = False
            self._mode = script.next("answer")      # int index | "timeout" | "forfeit"
            self.active_player_id = active_player_id

        async def wait(self):
            if self._mode == "forfeit":
                script.game.forfeit_requested = True     # the watcher then stops the view
                return
            if self._mode == "timeout":
                self.timed_out = True
            else:
                self.chosen_idx = self._mode
            self._stopped = True

        def is_finished(self):
            return self._stopped

        def stop(self):
            self._stopped = True

    class FakePlayerSelectView:
        def __init__(self, game, active_player_id, placeholder, timeout, allow_skip=False, skip_label=""):
            script.selects.append([p for p in game.players if p != active_player_id])
            v = script.next("target")                # user id | "skip" | None (timeout)
            self.target_id = v if isinstance(v, int) else None
            self.skipped = v == "skip"
            self.timed_out = v is None
            self.children: list = []

        async def wait(self):
            return None

    class FakeDrawCardView:
        def __init__(self, active_player_id, label):
            self.children: list = []

        async def wait(self):
            return None

    class FakeGoldenMonkeyView:
        def __init__(self, active_player_id):
            self.choice = script.next("monkey")      # "belly" | "tail" | None (timeout)
            self.timed_out = self.choice is None

        async def wait(self):
            return None

    class FakeRuleButton:
        def __init__(self, active_player_id):
            rid = script.next("rule")                # rule id | None (timeout)
            self.selected_rule_id = rid
            self.done = rid is not None

        async def wait(self):
            return None

    return dict(AnswerView=FakeAnswerView, PlayerSelectView=FakePlayerSelectView, DrawCardView=FakeDrawCardView,
                GoldenMonkeyView=FakeGoldenMonkeyView, BamboozleRuleTriggerButton=FakeRuleButton)


async def _noop_sleep(*_a, **_k):
    return None


def _close_task(coro):
    coro.close()
    return MagicMock()


class FakeBot:
    def __init__(self, channel):
        self._channel = channel

    def get_channel(self, _cid):
        return self._channel


@contextlib.contextmanager
def legacy_env(script: Script, game: GameState | None = None):
    """Patch cogs.game so its rules run offline under `script`. Yields (cog, channel)."""
    script.game = game
    channel = FakeChannel()
    cog = G.BamboozledCog(FakeBot(channel))

    clock = {"n": 0}

    def monotonic():
        clock["n"] += 1
        return 0.0 if clock["n"] % 2 == 1 else script.elapsed

    async def fake_fetch(_token, **kwargs):
        script.fetch_kwargs.append(kwargs)
        return dict(QUESTION), "tok"

    rand = types.SimpleNamespace(
        random=lambda: script.next("rand", 0.5), shuffle=_random.shuffle, choice=_random.choice,
    )
    patches = [
        patch.object(G, "asyncio", types.SimpleNamespace(
            sleep=_noop_sleep, gather=asyncio.gather, create_task=_close_task, TimeoutError=asyncio.TimeoutError)),
        patch.object(G, "random", rand),
        patch.object(G, "time", types.SimpleNamespace(monotonic=monotonic, time=_time.time)),
        patch.object(G, "draw_chance_card", lambda: script.next("chance")),
        patch.object(G, "draw_wango_card", lambda: script.next("wango")),
        patch.object(G, "spin_wheel", lambda: script.next("wheel")),
        patch.object(G, "monkey_choice_segment", lambda: script.next("monkey_seg")),
        patch.object(G, "fetch_question_any", fake_fetch),
        patch.object(G, "shuffle_answers", lambda q: (["right", "a", "b", "c"], 0)),
        patch.object(G, "save_game_result", AsyncMock()),
        patch.object(G, "update_player_stats", AsyncMock()),
        patch.object(G, "unregister_active_channel", AsyncMock()),
        patch.object(G, "LobbyView", MagicMock()),
    ] + [patch.object(G, name, cls) for name, cls in _views(script).items()]
    saved_games = dict(G._active_games)
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        try:
            yield cog, channel
        finally:
            G._active_games.clear()
            G._active_games.update(saved_games)


def run(coro):
    return asyncio.run(coro)
