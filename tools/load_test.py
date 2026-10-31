"""Local load check: many rooms of scripted players against the real room manager and engine on a real clock.

    python tools/load_test.py                       # 20 rooms x 6 players for 600 s (the spec's scenario)
    python tools/load_test.py --seconds 60 --rooms 20

It measures the server's own work, not the network: "latency" is the time the manager takes from receiving an intent
to having queued the updated view for every player in the room. Targets (spec 12.3): RSS under 300 MB at peak,
median under 50 ms and p95 under 150 ms, CPU under half of one vCPU on average, idle under 150 MB.
"""
import argparse
import asyncio
import json
import random
import resource
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bamboozled.engine.bots import legal_intents  # noqa: E402
from bamboozled.server.auth import AuthResult  # noqa: E402
from bamboozled.server.rooms import RoomManager  # noqa: E402
from bamboozled.services.trivia_source import OfflineQuestions  # noqa: E402
from bamboozled.settings import Settings  # noqa: E402

MODES = ["bamboozled", "fff", "survival", "bamboozled"]


def rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def to_frame(intent) -> str:
    d = {"index": intent.index} if intent.kind == "ANSWER" else {}
    if intent.kind == "PICK_TARGET":
        d = {"user_id": intent.user_id}
    elif intent.kind == "PICK_RULE":
        d = {"rule_id": intent.rule_id}
    elif intent.kind == "MONKEY":
        d = {"choice": intent.choice}
    return json.dumps({"v": 1, "t": intent.kind, "d": d})


async def main_async(a) -> dict:
    rng = random.Random(a.seed)
    clock = lambda: int(time.monotonic() * 1000)  # noqa: E731
    settings = Settings({"activity.max_rooms": max(a.rooms, 1), "activity.reconnect_grace_seconds": 120})
    mgr = RoomManager(settings, clock, OfflineQuestions(random.Random(a.seed)), recorder=None)
    idle_rss = rss_mb()

    conns, order = {}, []
    for r in range(a.rooms):
        key = f"room{r}"
        for p in range(a.players):
            uid = 1000 * (r + 1) + p
            conns[(key, uid)] = mgr.connect(AuthResult(uid, f"P{uid}", "", key, 1, 1), clock())
            order.append((key, uid))
        host = 1000 * (r + 1)
        mode = MODES[r % len(MODES)]
        mgr.handle_text(conns[(key, host)], json.dumps({"v": 1, "t": "SET_MODE", "d": {"mode": mode}}), clock())
        mgr.handle_text(conns[(key, host)], json.dumps({"v": 1, "t": "START", "d": {}}), clock())

    latencies, intents, games_done = [], 0, 0
    next_act = {k: time.monotonic() + rng.uniform(0.2, 1.5) for k in order}
    next_pump = 0.0
    cpu0, wall0 = time.process_time(), time.monotonic()
    end = wall0 + a.seconds
    peak = rss_mb()
    while time.monotonic() < end:
        now = time.monotonic()
        if now >= next_pump:
            await mgr.pump(clock())
            next_pump = now + 0.25
        for key, room in list(mgr.rooms.items()):
            if room.phase == "results":                                   # keep the load going: a rematch, same host
                games_done += 1
                host = room.host
                mgr.handle_text(conns[(key, host)], json.dumps({"v": 1, "t": "REMATCH", "d": {}}), clock())
                mgr.handle_text(conns[(key, host)], json.dumps({"v": 1, "t": "START", "d": {}}), clock())
            if room.phase != "playing":
                continue
            moves = {}
            for _, state in room.states():
                for actor, intent in legal_intents(state):
                    moves.setdefault(actor, []).append(intent)
            for actor, options in moves.items():
                k = (key, actor)
                if next_act.get(k, 0) > now:
                    continue
                intent = rng.choice(options)
                frame = to_frame(intent)
                t0 = time.perf_counter()
                mgr.handle_text(conns[k], frame, clock())
                latencies.append((time.perf_counter() - t0) * 1000)
                intents += 1
                next_act[k] = now + rng.uniform(0.3, 1.5)
        for conn in conns.values():
            conn.drain()                                                   # a real socket would be sending these
        peak = max(peak, rss_mb())
        await asyncio.sleep(0.02)
    cpu = time.process_time() - cpu0
    wall = time.monotonic() - wall0
    latencies.sort()
    return {
        "scenario": f"{a.rooms} rooms x {a.players} players, mixed modes, {a.seconds:.0f} s",
        "intents": intents, "games_finished": games_done,
        "latency_ms": {"median": round(statistics.median(latencies), 3),
                       "p95": round(latencies[int(len(latencies) * 0.95) - 1], 3),
                       "max": round(latencies[-1], 3)} if latencies else None,
        "rss_mb": {"idle_before_rooms": round(idle_rss, 1), "peak": round(peak, 1)},
        "cpu_vcpu_average": round(cpu / wall, 3), "cpu_seconds": round(cpu, 1), "wall_seconds": round(wall, 1),
        "targets": {"rss_peak_mb": 300, "latency_median_ms": 50, "latency_p95_ms": 150, "cpu_vcpu": 0.5, "idle_rss_mb": 150},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rooms", type=int, default=20)
    ap.add_argument("--players", type=int, default=6)
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--seed", type=int, default=1)
    report = asyncio.run(main_async(ap.parse_args(argv)))
    print(json.dumps(report, indent=2))
    t, lat = report["targets"], report["latency_ms"]
    ok = (report["rss_mb"]["peak"] < t["rss_peak_mb"] and lat and lat["median"] < t["latency_median_ms"]
          and lat["p95"] < t["latency_p95_ms"] and report["cpu_vcpu_average"] < t["cpu_vcpu"])
    print("TARGETS MET" if ok else "TARGETS NOT MET (see numbers above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
