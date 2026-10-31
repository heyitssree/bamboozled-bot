"""Reproduces the known exploits against a LOCAL copy of the real server. Every check must report BLOCKED.

    python tools/abuse_check.py                # the real build (production auth, a fake Discord): expect all BLOCKED
    python tools/abuse_check.py --weakened     # dev auth on and the origin check off: must report VULNERABLE (proves the
                                               # tool can fail); exit code 1

It starts its own server on a loopback port with a throwaway database, and answers Discord's API itself. There is no
option to aim it at another host.
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
import websockets  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="abuse_check_")
os.environ["BAMBOOZLED_DB_PATH"] = os.path.join(_tmp, "bamboozled.db")
os.environ["BAMBOOZLED_PRIVACY_DB_PATH"] = os.path.join(_tmp, "privacy.db")

from bamboozled.app import build  # noqa: E402
from bamboozled.config import Config  # noqa: E402
from bamboozled.context import Context  # noqa: E402
from bamboozled.server.http import WS_MAX_MESSAGE  # noqa: E402
from bamboozled.settings import Settings  # noqa: E402

USERS = range(1, 31)
SECRET = "origin-secret-for-the-check"


def fake_discord(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/users/@me"):
        token = request.headers.get("authorization", "")
        if token.startswith("Bearer tok-"):
            uid = token.removeprefix("Bearer tok-")
            return httpx.Response(200, json={"id": uid, "username": f"user{uid}"})
        return httpx.Response(401, json={"message": "401: Unauthorized"})
    if "/activity-instances/" in path:
        if path.rsplit("/", 1)[-1].startswith("unknown"):
            return httpx.Response(404, json={"message": "Unknown"})
        return httpx.Response(200, json={"users": [str(u) for u in USERS], "location": {"guild_id": "10", "channel_id": "20"}})
    return httpx.Response(404)


class Backend:
    """The real application on a loopback port. `weakened` switches dev auth on and the origin check off."""

    def __init__(self, weakened: bool = False, origin_verify: str = "", max_rooms: int = 50, opted_out=()):
        cfg = Config(env="dev" if weakened else "prod", app_id="1", bot_token="bot", port=0, host="127.0.0.1",
                     dev_auth=weakened, origin_verify="" if weakened else origin_verify)
        self.ctx = Context.create(cfg, Settings())
        self.ctx.settings.set("trivia.sources", "custom_only")
        self.ctx.settings.set("activity.max_rooms", max_rooms)
        self.ctx.privacy._out.update(opted_out)
        app, self.manager, deps, http = build(cfg, self.ctx)
        if not weakened:
            deps.authenticator.http = httpx.AsyncClient(transport=httpx.MockTransport(fake_discord))
            deps.authenticator.cache.clear()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", ws_max_size=WS_MAX_MESSAGE))

    def __enter__(self):
        self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve()), daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started and self.server.servers:
                break
            time.sleep(0.05)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}/api/ws"
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)


class Client:
    def __init__(self, ws):
        self.ws, self.frames, self.state = ws, [], None

    @classmethod
    async def open(cls, be: Backend, uid: int, instance: str = "inst", token: str | None = None, headers=None, auth=True):
        c = cls(await websockets.connect(be.url, additional_headers=headers or {}, open_timeout=5))
        if auth:
            await c.send("AUTH", {"access_token": token or f"tok-{uid}", "instance_id": instance})
        return c

    async def send(self, t, d=None, raw=None):
        await self.ws.send(raw if raw is not None else json.dumps({"v": 1, "t": t, "d": d or {}}))

    async def pump(self, seconds: float, until=None):
        """Read frames for up to `seconds` (or until `until(frame)`); returns the close code if the socket closed."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), max(0.01, end - time.monotonic()))
            except asyncio.TimeoutError:
                return None
            except websockets.ConnectionClosed:
                return self.ws.close_code
            f = json.loads(raw)
            self.frames.append(f)
            if f["t"] == "STATE":
                self.state = f["d"]
            if until and until(f):
                return None
        return None

    def got(self, t, code=None):
        return any(f["t"] == t and (code is None or f["d"].get("code") == code) for f in self.frames)

    async def close(self):
        await self.ws.close()


def blocked(ok: bool, why: str):
    return ok, why


async def ws_without_auth(w):
    with Backend(w) as be:
        c = await Client.open(be, 1, auth=False)
        await c.send("PING")
        code = await c.pump(3)
        return blocked(code == 4401 and not c.got("STATE"), f"closed {code}, state sent: {c.got('STATE')}")


async def ws_with_fake_token(w):
    with Backend(w) as be:
        c = await Client.open(be, 7, token="dev:7:Mallory")
        code = await c.pump(3)
        return blocked(code == 4401 and not c.got("STATE"), f"closed {code}, state sent: {c.got('STATE')}")


async def user_not_in_instance(w):
    with Backend(w) as be:
        c = await Client.open(be, 99, token="tok-99") if not w else await Client.open(be, 99, token="dev:99:x")
        code = await c.pump(5)
        return blocked(code == 4403 and not c.got("STATE"), f"closed {code}, state sent: {c.got('STATE')}")


async def unknown_instance(w):
    with Backend(w) as be:
        c = await Client.open(be, 1, instance="unknown-1", token="dev:1:x" if w else None)
        code = await c.pump(3)
        return blocked(code == 4404 and not c.got("STATE"), f"closed {code}, state sent: {c.got('STATE')}")


async def duplicate_socket(w):
    with Backend(w) as be:
        a = await Client.open(be, 1, token="dev:1:x" if w else None)
        await a.pump(1)
        b = await Client.open(be, 1, token="dev:1:x" if w else None)
        code = await a.pump(2)
        await b.pump(1)
        room = next(iter(be.manager.rooms.values()))
        return blocked(code == 4409 and a.got("BYE") and b.state is not None and len(room.members) == 1,
                       f"first socket closed {code}, members {len(room.members)}")


async def _lobby(be, n=2, instance="game", w=False):
    cs = [await Client.open(be, i + 1, instance, token=f"dev:{i + 1}:u" if w else None) for i in range(n)]
    for c in cs:
        await c.pump(1)
    return cs


async def non_host_actions(w):
    with Backend(w) as be:
        host, other = await _lobby(be, w=w)
        await other.send("SET_MODE", {"mode": "fff"})
        await other.send("START")
        await other.pump(1)
        await host.pump(0.5)
        refused = sum(1 for f in other.frames if f["t"] == "ERROR" and f["d"]["code"] == "not_host")
        return blocked(refused == 2 and host.state["phase"] == "lobby" and host.state["mode"] != "fff",
                       f"{refused}/2 refused, phase {host.state['phase']}")


async def wrong_phase(w):
    with Backend(w) as be:
        host, other = await _lobby(be, w=w)
        await host.send("ANSWER", {"index": 0})
        await host.pump(1)
        early = host.got("ERROR")
        await host.send("START")
        await host.pump(3, until=lambda f: f["t"] == "STATE" and (f["d"].get("game") or {}).get("question"))
        await other.pump(0.5)
        who = other if host.state["game"]["turn_player"] == host.state["you"] else host
        n = len(who.frames)
        await who.send("ANSWER", {"index": 0})
        await who.pump(1)
        late = any(f["t"] == "ERROR" and f["d"]["code"] == "not_your_turn" for f in who.frames[n:])
        return blocked(early and late, f"answer in lobby refused: {early}; answer out of turn refused: {late}")


async def malformed_frames(w):
    with Backend(w) as be:
        (c,) = await _lobby(be, 1, w=w)
        await c.send("", raw="x" * 5000)
        await c.send("", raw="{not json")
        await c.send("NOPE")
        await c.send("PING")
        code = await c.pump(2)
        ok = code is None and c.got("ERROR", "frame_too_big") and c.got("ERROR", "bad_json") and c.got("PONG")
        return blocked(ok, f"closed {code}; codes {[f['d'].get('code') for f in c.frames if f['t'] == 'ERROR']}")


async def flood(w):
    with Backend(w) as be:
        (c,) = await _lobby(be, 1, w=w)
        for _ in range(300):
            await c.send("PING")
        code = await c.pump(3)
        pongs = sum(1 for f in c.frames if f["t"] == "PONG")
        return blocked(pongs < 300 and (c.got("ERROR", "rate_limited") or code == 4429), f"{pongs}/300 answered, closed {code}")


async def room_cap(w):
    with Backend(w, max_rooms=2) as be:
        outcomes = []
        for i in range(3):
            c = await Client.open(be, i + 1, f"room-{i}", token=f"dev:{i + 1}:u" if w else None)
            await c.pump(1.5)
            outcomes.append(c.state is not None)
        rooms = len(be.manager.rooms)
        return blocked(outcomes == [True, True, False] and rooms == 2, f"seated {outcomes}, rooms {rooms}")


def _leaks(frame) -> list[str]:
    found = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if "correct" in k.lower() or k.lower() in ("solution", "answer_index"):
                    found.append(".".join(path + [k]))
                walk(v, path + [k])
        elif isinstance(o, list):
            for v in o:
                walk(v, path)
    walk(frame["d"], [])
    return found


async def answer_not_leaked(w):
    seen, leaks = 0, []
    for mode, n in (("bamboozled", 2), ("fff", 2), ("survival", 1)):
        with Backend(w) as be:
            cs = await _lobby(be, n, instance=mode, w=w)
            await cs[0].send("SET_MODE", {"mode": mode})
            for c in cs:
                await c.send("READY", {"ready": True})
            await cs[0].send("START")
            for c in cs:
                await c.pump(2.5)
            for c in cs:
                for f in c.frames:
                    g = (f["d"].get("game") or {}) if f["t"] == "STATE" else {}
                    if f["t"] == "STATE" and not g.get("reveal") and f["d"]["phase"] != "results":
                        seen += 1 if g.get("question") else 0
                        leaks += _leaks(f)
    return blocked(seen > 0 and not leaks, f"{seen} question state(s) inspected, leaking keys: {sorted(set(leaks)) or 'none'}")


async def opted_out_user(w):
    with Backend(w, opted_out=[5]) as be:
        c = await Client.open(be, 5, token="dev:5:x" if w else None)
        code = await c.pump(3)
        return blocked(code == 4403 and not c.got("STATE"), f"closed {code}, state sent: {c.got('STATE')}")


async def origin_verify(w):
    with Backend(w, origin_verify=SECRET) as be:
        base = f"http://127.0.0.1:{be.port}/api/health"
        async with httpx.AsyncClient() as h:
            without = (await h.get(base)).status_code
            wrong = (await h.get(base, headers={"x-origin-verify": "nope"})).status_code
            right = (await h.get(base, headers={"x-origin-verify": SECRET})).status_code
        try:                                                      # refused at the handshake, or closed right after it
            c = await Client.open(be, 1, token="dev:1:x" if w else None)
            code, got_state = await c.pump(2), c.got("STATE")
        except websockets.InvalidStatus as exc:
            code, got_state = exc.response.status_code, False
        ok = without == 403 and wrong == 403 and right == 200 and code in (403, 4403) and not got_state
        return blocked(ok, f"no header {without}, wrong {wrong}, right {right}; websocket without header refused with {code}")


CHECKS = {
    "unauthenticated websocket is closed (4401)": ws_without_auth,
    "forged identity: dev token rejected when BAMBOOZLED_ENV=prod": ws_with_fake_token,
    "valid user but NOT in the activity instance (4403)": user_not_in_instance,
    "instance that Discord does not know (404) is rejected": unknown_instance,
    "one user on two sockets is one player; second socket replaces the first": duplicate_socket,
    "intent from a non-host (START, SET_MODE) is refused": non_host_actions,
    "intent in the wrong phase / wrong turn is refused": wrong_phase,
    "oversize frame, malformed JSON, unknown type: dropped, socket survives": malformed_frames,
    "flood above 10 msgs/s is rate-limited": flood,
    "more than activity.max_rooms rooms are refused": room_cap,
    "correct answer is absent from every STATE before REVEAL": answer_not_leaked,
    "opted-out user is refused at AUTH": opted_out_user,
    "request without the origin-verify header is refused (when configured)": origin_verify,
}


async def main(weakened: bool) -> int:
    bad = 0
    for name, fn in CHECKS.items():
        try:
            ok, why = await fn(weakened)
        except Exception as exc:                                  # a check that cannot run is not a pass
            ok, why = False, f"check failed to run: {type(exc).__name__}: {exc}"
        bad += not ok
        print(f"{'BLOCKED   ' if ok else 'VULNERABLE'}  {name}\n            {why}")
    print(f"\n{len(CHECKS) - bad}/{len(CHECKS)} blocked" + (" (weakened build)" if weakened else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weakened", action="store_true", help="run against a deliberately weakened build (must fail)")
    sys.exit(asyncio.run(main(ap.parse_args().weakened)))
