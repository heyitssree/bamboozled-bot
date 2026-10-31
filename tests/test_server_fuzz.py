"""Protocol fuzzing: random frames never crash the manager, and hidden data never reaches a viewer who must not see it."""
import json
import random

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.server_helpers import auth, make, msg

KINDS = ["AUTH", "READY", "SET_MODE", "SET_CONFIG", "START", "ANSWER", "DRAW_CARD", "SPIN", "PICK_TARGET", "PICK_RULE",
         "MONKEY", "FORFEIT", "LEAVE", "REMATCH", "PING", "RESYNC", "NOPE", "", "ready"]
scalar = st.one_of(st.none(), st.booleans(), st.integers(-10**12, 10**12), st.floats(allow_nan=True), st.text(max_size=30))
json_like = st.recursive(scalar, lambda kids: st.one_of(st.lists(kids, max_size=4),
                                                       st.dictionaries(st.text(max_size=8), kids, max_size=4)), max_leaves=12)
payload = st.dictionaries(st.sampled_from(["index", "user_id", "rule_id", "choice", "mode", "rounds", "difficulty", "category",
                                           "ready", "access_token", "instance_id", "x"]), json_like, max_size=5)
frame = st.one_of(
    st.text(max_size=300), st.binary(max_size=300),
    st.builds(lambda t, d, i, v: json.dumps({"v": v, "t": t, "d": d, **({"id": i} if i is not None else {})}, default=str),
              st.sampled_from(KINDS), payload, st.one_of(st.none(), st.text(max_size=80), st.integers()),
              st.sampled_from([1, 1, 1, 2, None])),
    json_like.map(lambda x: json.dumps(x, default=str)),
)
SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])


def playing(mode="bamboozled", n=3):
    mgr, clock, rec = make()
    conns = {u: mgr.connect(auth(u), clock.now) for u in range(1, n + 1)}
    mgr.handle_text(conns[1], msg("SET_MODE", {"mode": mode}), clock.now)
    mgr.handle_text(conns[1], msg("START"), clock.now)
    return mgr, clock, conns


@SETTINGS
@given(st.lists(frame, min_size=1, max_size=25), st.sampled_from(["bamboozled", "fff", "survival"]))
async def test_random_frames_never_crash_or_close_a_good_socket_without_cause(frames, mode):
    mgr, clock, conns = playing(mode)
    await mgr.pump(clock.now)
    for i, raw in enumerate(frames):
        clock.advance(150)                                       # under the 10/s limit, so every frame is looked at
        sender = conns[1 + i % 3]
        mgr.handle_text(sender, raw, clock.now)
        await mgr.pump(clock.now)
    for c in conns.values():
        for f in c.outbox:
            assert f["v"] == 1 and isinstance(f["seq"], int) and f["t"] in ("STATE", "EVENT", "ERROR", "ACK", "PONG", "BYE")
            json.dumps(f)                                         # everything we send is serialisable


@SETTINGS
@given(st.lists(frame, min_size=1, max_size=25))
async def test_hidden_data_never_reaches_a_viewer_who_must_not_see_it(frames):
    mgr, clock, conns = playing("bamboozled")
    spectator = mgr.connect(auth(9), clock.now)
    await mgr.pump(clock.now)
    for i, raw in enumerate(frames):
        clock.advance(150)
        mgr.handle_text(conns[1 + i % 3], raw, clock.now)
        mgr.handle_text(spectator, raw, clock.now)
        await mgr.pump(clock.now)
    for c in list(conns.values()) + [spectator]:
        for f in c.outbox:
            if f["t"] != "STATE" or not f["d"]["game"]:
                continue
            game = f["d"]["game"]
            if game["question"] is not None and game["reveal"] is None:
                assert "correct_index" not in json.dumps(f)
            if game["mist"]:
                assert all(p["score"] is None for p in game["players"])
    # a spectator can never act, whatever it sends
    room = mgr.rooms.get("r1")
    if room and 9 in room.members:
        assert room.members[9].spectator


@SETTINGS
@given(st.lists(st.sampled_from(["READY", "SET_MODE", "SET_CONFIG", "START", "LEAVE", "REMATCH", "PING"]), max_size=40),
       st.integers(0, 10**6))
async def test_random_lobby_actions_keep_the_room_consistent(actions, seed):
    rng = random.Random(seed)
    mgr, clock, rec = make()
    conns = {u: mgr.connect(auth(u), clock.now) for u in (1, 2, 3)}
    for action in actions:
        clock.advance(150)
        who = conns[rng.choice([1, 2, 3])]
        data = {"READY": {"ready": rng.random() < 0.5}, "SET_MODE": {"mode": rng.choice(["fff", "survival", "bamboozled"])},
                "SET_CONFIG": {"rounds": rng.randint(1, 30)}}.get(action, {})
        mgr.handle_text(who, msg(action, data), clock.now)
        await mgr.pump(clock.now)
        room = mgr.rooms.get("r1")
        if room is None:
            break
        assert room.host is None or room.host in room.members
        assert len(room.players()) <= 10
        if room.phase == "lobby":
            assert room.game is None and not room.runs
