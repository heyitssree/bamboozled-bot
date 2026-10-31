"""Two scripted clients play a full game of each mode over the real WebSocket against the real engine (dev auth stub).

The clients decide only from the views the server sends them: they never see a correct answer.
"""
import queue
import random
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from bamboozled.config import Config
from bamboozled.server.auth import DevAuthenticator
from bamboozled.server.http import Deps, create_app
from bamboozled.server.rooms import RoomManager
from bamboozled.settings import Settings
from tests.server_helpers import Recorder, provider


BENIGN = ("not_your_turn", "bad_phase", "too_late", "already_answered")      # races between two eager clients


class Client:
    def __init__(self, test_client, user, instance="e2e"):
        self.user, self.state, self.rng = user, None, random.Random(user)
        self.inbox: queue.Queue = queue.Queue()
        self.cm = test_client.websocket_connect("/api/ws")
        self.ws = self.cm.__enter__()
        self.ws.send_json({"v": 1, "t": "AUTH", "d": {"access_token": f"dev:{user}:U{user}", "instance_id": instance}})
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                self.inbox.put(self.ws.receive_json())
        except Exception:
            self.inbox.put(None)

    def send(self, t, d=None):
        self.ws.send_json({"v": 1, "t": t, "d": d or {}})

    def until(self, pred, timeout=10.0):
        """Keep reading until the latest STATE satisfies pred (or fail)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.state is not None and pred(self.state):
                return self.state
            try:
                frame = self.inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            if frame is None:
                break
            if frame["t"] == "STATE":
                self.state = frame["d"]
            elif frame["t"] == "ERROR" and frame["d"]["code"] not in BENIGN:
                raise AssertionError(f"unexpected error {frame['d']}")
        raise AssertionError(f"timed out; last state: {self.state and self.state['phase']}")

    def move(self):
        """One move chosen from this client's own view, or None."""
        g = self.state["game"]
        if not g:
            return None
        mode = self.state["mode"]
        if mode == "survival":
            return ("ANSWER", {"index": self.rng.randrange(4)}) if g["question"] and not g["over"] else None
        if mode == "fff":
            mine = next((p for p in g["players"] if p["user_id"] == self.user), None)
            if g["question"] and mine and not mine["locked"]:
                return ("ANSWER", {"index": self.rng.randrange(4)})
            return None
        p = g["pending"]
        if not p or p["actor"] != self.user:
            return None
        return {
            "answer": lambda: ("ANSWER", {"index": self.rng.randrange(4)}),
            "draw": lambda: ("DRAW_CARD", {}), "spin": lambda: ("SPIN", {}),
            "pick_target": lambda: ("PICK_TARGET", {"user_id": self.rng.choice(p["options"])}),
            "pick_rule": lambda: ("PICK_RULE", {"rule_id": self.rng.randint(1, 11)}),
            "monkey": lambda: ("MONKEY", {"choice": self.rng.choice(["belly", "tail"])}),
        }[p["kind"]]()

    def close(self):
        self.cm.__exit__(None, None, None)


@pytest.fixture
def app_env(tmp_path):
    rec = Recorder()
    settings = Settings({"game.question_timeout_seconds": 10})
    mgr = RoomManager(settings, lambda: int(time.monotonic() * 1000), provider, recorder=rec,
                      rng_factory=lambda: random.Random(11))
    deps = Deps(cfg=Config(env="test", dev_auth=True, web_dist=tmp_path), manager=mgr, authenticator=DevAuthenticator(),
                settings=settings, clock_ms=lambda: int(time.monotonic() * 1000),
                http=httpx.AsyncClient(), tick_s=0.01)
    with TestClient(create_app(deps)) as client:               # entering the context starts the server's own ticker
        yield client, deps, rec


@pytest.mark.parametrize("mode,rounds", [("bamboozled", 3), ("fff", 5), ("survival", None)])
def test_two_clients_play_a_whole_game(app_env, mode, rounds):
    client, deps, rec = app_env
    a, b = Client(client, 1), Client(client, 2)
    try:
        a.until(lambda s: len(s["members"]) == 2)
        b.until(lambda s: len(s["members"]) == 2)
        a.send("SET_MODE", {"mode": mode})
        if rounds:
            a.send("SET_CONFIG", {"rounds": rounds})
        a.until(lambda s: s["mode"] == mode)
        a.send("START")
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            for c in (a, b):
                c.until(lambda s: s["phase"] in ("playing", "results"))
            if a.state["phase"] == "results" and b.state["phase"] == "results":
                break
            for c in (a, b):
                m = c.move()
                if m:
                    c.send(*m)
            for c in (a, b):                                    # wait for the server to react before the next round of moves
                try:
                    frame = c.inbox.get(timeout=0.05)
                    if frame and frame["t"] == "STATE":
                        c.state = frame["d"]
                except queue.Empty:
                    pass
        assert a.state["phase"] == "results" and b.state["phase"] == "results"
        assert a.state["results"] and a.state["results"][0]["rank"] == 1
        assert a.state["results"] == b.state["results"]
        time.sleep(0.1)                                         # the ticker flushes results to the recorder
        expected = 2 if mode == "survival" else 1
        assert len(rec.calls) == expected and all(call[0] == mode for call in rec.calls)
    finally:
        a.close()
        b.close()
