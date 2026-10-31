"""The room manager under a fake clock: lobby rules, full games through the real engine, seats, reaping, abuse."""
import json

import pytest

from bamboozled.server.rooms import Refused
from tests.server_helpers import Q, auth, errors, kinds, last, make, msg, play_out


def lobby(n=2, **settings):
    mgr, clock, rec = make(**settings)
    conns = {u: mgr.connect(auth(u), clock.now) for u in range(1, n + 1)}
    return mgr, clock, rec, conns


def state(conn):
    return last(conn, "STATE")["d"]


# ───────────────────────────── lobby ─────────────────────────────

class TestLobby:
    def test_first_in_is_host_and_everyone_sees_the_roster(self):
        mgr, clock, _, c = lobby(3)
        s = state(c[2])
        assert s["host"] == 1 and s["phase"] == "lobby" and s["you"] == 2
        assert [m["user_id"] for m in s["members"]] == [1, 2, 3] and [m["host"] for m in s["members"]] == [True, False, False]
        assert s["members"][0]["name"] == "P1" and s["members"][0]["avatar_url"].startswith("https://cdn.example")
        assert s["min_players"] == 2 and s["can_start"] is False and state(c[1])["can_start"] is True

    def test_only_the_host_changes_mode_config_and_starts(self):
        mgr, clock, _, c = lobby()
        for m in (msg("SET_MODE", {"mode": "fff"}), msg("SET_CONFIG", {"rounds": 6}), msg("START")):
            c[2].outbox.clear()
            mgr.handle_text(c[2], m, clock.now)
            assert errors(c[2]) == ["not_host"]
        mgr.handle_text(c[1], msg("SET_MODE", {"mode": "fff"}), clock.now)
        mgr.handle_text(c[1], msg("SET_CONFIG", {"rounds": 7, "difficulty": "hard", "category": "History"}), clock.now)
        s = state(c[2])
        assert s["mode"] == "fff" and s["config"] == {"rounds": 7, "difficulty": "hard", "category": "History"}

    def test_config_is_validated_per_mode(self):
        mgr, clock, _, c = lobby()
        mgr.handle_text(c[1], msg("SET_CONFIG", {"rounds": 99}), clock.now)
        assert errors(c[1]) == ["bad_payload"]                      # beyond the protocol's own limit
        c[1].outbox.clear()
        mgr.handle_text(c[1], msg("SET_CONFIG", {"rounds": 2}), clock.now)      # bamboozled needs 3 to 20
        assert errors(c[1]) == ["bad_config"]
        mgr.handle_text(c[1], msg("SET_CONFIG", {"rounds": 4}), clock.now)
        mgr.handle_text(c[1], msg("SET_MODE", {"mode": "fff"}), clock.now)
        assert state(c[1])["config"]["rounds"] is None                # a new mode starts from its own default

    def test_disabled_mode_cannot_be_chosen_or_started(self):
        mgr, clock, _, c = lobby(**{"feature.fff": False})
        mgr.handle_text(c[1], msg("SET_MODE", {"mode": "fff"}), clock.now)
        assert errors(c[1]) == ["mode_disabled"]

    def test_start_needs_enough_connected_players(self):
        mgr, clock, _, c = lobby(1)
        mgr.handle_text(c[1], msg("START"), clock.now)
        assert errors(c[1]) == ["not_enough_players"]
        mgr.handle_text(c[1], msg("SET_MODE", {"mode": "survival"}), clock.now)
        mgr.handle_text(c[1], msg("START"), clock.now)
        assert state(c[1])["phase"] == "playing"

    def test_ready_toggles_and_resets_on_mode_change(self):
        mgr, clock, _, c = lobby()
        mgr.handle_text(c[2], msg("READY", {"ready": True}), clock.now)
        assert [m["ready"] for m in state(c[1])["members"]] == [False, True]
        mgr.handle_text(c[1], msg("SET_MODE", {"mode": "fff"}), clock.now)
        assert not any(m["ready"] for m in state(c[1])["members"])

    def test_game_messages_in_the_lobby_are_refused(self):
        mgr, clock, _, c = lobby()
        mgr.handle_text(c[1], msg("ANSWER", {"index": 0}), clock.now)
        assert errors(c[1]) == ["bad_phase"]

    def test_full_lobby_makes_spectators_or_refuses(self):
        mgr, clock, _, c = lobby(2, **{"activity.max_players": 2})
        late = mgr.connect(auth(3), clock.now)
        assert state(late)["role"] == "spectator"
        mgr2, clock2, _, _ = lobby(2, **{"activity.max_players": 2, "activity.allow_spectators": False})
        with pytest.raises(Refused) as err:
            mgr2.connect(auth(3), clock2.now)
        assert err.value.code == "room_full"

    def test_second_socket_replaces_the_first(self):
        mgr, clock, _, c = lobby()
        again = mgr.connect(auth(2), clock.now)
        assert c[2].closed and c[2].close_code == 4409 and last(c[2], "BYE")["d"]["reason"] == "kicked"
        assert not again.closed and len(state(again)["members"]) == 2
        c[2].outbox.clear()
        mgr.handle_text(c[2], msg("READY", {"ready": True}), clock.now)            # the old window is ignored
        assert c[2].outbox == [] and not mgr.rooms["r1"].members[2].ready

    def test_room_cap_and_maintenance(self):
        mgr, clock, _, c = lobby(1, **{"activity.max_rooms": 1})
        with pytest.raises(Refused) as err:
            mgr.connect(auth(9, room="other"), clock.now)
        assert err.value.code == "server_full"
        mgr.settings.set("system.killswitch", True)
        with pytest.raises(Refused) as err:
            mgr.connect(auth(5), clock.now)
        assert err.value.code == "maintenance"

    def test_shutdown_tells_everyone_to_reconnect(self):
        mgr, clock, _, c = lobby(2)
        mgr.shutdown()
        assert all(last(x, "BYE")["d"]["reason"] == "server_restart" and x.close_code == 1012 for x in c.values())
        with pytest.raises(Refused):
            mgr.connect(auth(3), clock.now)
        assert mgr.rooms == {}

    def test_spectator_in_a_lobby_can_not_ready_up(self):
        mgr, clock, _, c = lobby(2, **{"activity.max_players": 2})
        late = mgr.connect(auth(3), clock.now)
        mgr.handle_text(late, msg("READY", {"ready": True}), clock.now)
        assert errors(late) == ["spectator"]


# ───────────────────────────── whole games ─────────────────────────────

@pytest.mark.parametrize("mode,n,expected_records",
                         [("bamboozled", 2, 1), ("bamboozled", 4, 1), ("fff", 3, 1), ("survival", 3, 3)])
@pytest.mark.parametrize("seed", [1, 2])
async def test_a_whole_game_runs_through_the_real_engine_and_is_recorded_once(mode, n, expected_records, seed):
    import random
    mgr, clock, rec, c = lobby(n)
    mgr.handle_text(c[1], msg("SET_MODE", {"mode": mode}), clock.now)
    if mode != "survival":
        mgr.handle_text(c[1], msg("SET_CONFIG", {"rounds": 3 if mode == "bamboozled" else 5}), clock.now)
    mgr.handle_text(c[1], msg("START"), clock.now)
    room = await play_out(mgr, clock, c, rng=random.Random(seed))
    assert room.phase == "results"
    await mgr.pump(clock.now)
    await mgr.pump(clock.now)                                       # a second pump must not record again
    assert len(rec.calls) == expected_records
    assert all(call[1] == 10 for call in rec.calls)                 # guild comes from Discord's lookup, not the client
    s = state(c[1])
    assert s["phase"] == "results" and s["results"] and s["results"][0]["rank"] == 1
    if mode != "survival":
        assert len(mgr.overs) == 1
    host = mgr.rooms["r1"].host                                    # random play may have made someone else host
    mgr.handle_text(c[host], msg("REMATCH"), clock.now)
    assert state(c[host])["phase"] == "lobby" and state(c[host])["results"] is None


async def test_nobody_acting_still_ends_the_game_through_deadlines_and_kicks():
    mgr, clock, rec, c = lobby(2)
    mgr.handle_text(c[1], msg("SET_CONFIG", {"rounds": 3}), clock.now)
    mgr.handle_text(c[1], msg("START"), clock.now)
    for _ in range(400):
        await mgr.pump(clock.now)
        if mgr.rooms["r1"].phase != "playing":
            break
        clock.advance(31_000)
    assert mgr.rooms["r1"].phase == "results"


async def test_rematch_is_host_only_and_only_after_a_game():
    mgr, clock, _, c = lobby(2)
    mgr.handle_text(c[1], msg("REMATCH"), clock.now)
    assert errors(c[1]) == ["bad_phase"]
    mgr.handle_text(c[1], msg("START"), clock.now)
    await play_out(mgr, clock, c)
    mgr.handle_text(c[2], msg("REMATCH"), clock.now)
    assert errors(c[2])[-1] == "not_host"


class TestPlaying:
    async def started(self, n=2, mode="bamboozled"):
        mgr, clock, rec, c = lobby(n)
        mgr.handle_text(c[1], msg("SET_MODE", {"mode": mode}), clock.now)
        mgr.handle_text(c[1], msg("START"), clock.now)
        await mgr.pump(clock.now)
        return mgr, clock, rec, c

    async def test_only_the_player_whose_turn_it_is_can_answer(self):
        mgr, clock, _, c = await self.started()
        mgr.handle_text(c[2], msg("ANSWER", {"index": 0}), clock.now)
        assert errors(c[2]) == ["not_your_turn"]
        mgr.handle_text(c[1], msg("SPIN"), clock.now)
        assert errors(c[1]) == ["bad_phase"]
        c[1].outbox.clear()
        mgr.handle_text(c[1], msg("ANSWER", {"index": 0}), clock.now)
        assert errors(c[1]) == []

    async def test_late_joiners_and_spectators_watch_but_cannot_play(self):
        mgr, clock, _, c = await self.started()
        late = mgr.connect(auth(3), clock.now)
        assert state(late)["role"] == "spectator" and state(late)["game"]["question"]["text"] == Q.text
        mgr.handle_text(late, msg("ANSWER", {"index": 0}), clock.now)
        assert errors(late) == ["spectator"]

    async def test_the_correct_answer_is_nowhere_in_what_clients_receive_before_the_reveal(self):
        mgr, clock, _, c = await self.started()
        for conn in c.values():
            assert "correct_index" not in json.dumps(conn.outbox)
        mgr.handle_text(c[1], msg("ANSWER", {"index": 2}), clock.now)
        assert "correct_index" in json.dumps(c[2].outbox)               # shown once it has been answered

    async def test_internal_events_are_not_forwarded(self):
        mgr, clock, _, c = await self.started()
        mgr.handle_text(c[1], msg("ANSWER", {"index": 0}), clock.now)
        seen = {f["d"]["kind"] for f in c[2].outbox if f["t"] == "EVENT"}
        assert "reveal" in seen and "turn_resolved" not in seen

    async def test_survival_runs_are_private_but_the_board_is_shared(self):
        mgr, clock, _, c = await self.started(2, "survival")
        mgr.handle_text(c[1], msg("ANSWER", {"index": 0}), clock.now)
        s1, s2 = state(c[1]), state(c[2])
        assert s1["board"] == s2["board"] and {b["user_id"]: b["streak"] for b in s1["board"]} == {1: 1, 2: 0}
        assert s1["game"]["streak"] == 1 and s2["game"]["streak"] == 0

    async def test_idempotent_on_message_id(self):
        mgr, clock, _, c = await self.started()
        mgr.handle_text(c[1], msg("ANSWER", {"index": 0}, id="a1"), clock.now)
        n = len([f for f in c[1].outbox if f["t"] == "EVENT"])
        mgr.handle_text(c[1], msg("ANSWER", {"index": 0}, id="a1"), clock.now)
        assert last(c[1], "ACK")["d"] == {"id": "a1", "duplicate": True}
        assert len([f for f in c[1].outbox if f["t"] == "EVENT"]) == n and errors(c[1]) == []

    async def test_leaving_mid_game_removes_you_from_play_and_you_keep_watching(self):
        mgr, clock, _, c = await self.started(3)
        mgr.handle_text(c[3], msg("LEAVE"), clock.now)
        assert state(c[3])["role"] == "spectator"
        assert [p["user_id"] for p in state(c[1])["game"]["players"]] == [1, 2]


# ───────────────────────────── seats, host, reaping ─────────────────────────────

class TestSeats:
    async def test_reconnecting_within_the_grace_period_keeps_the_seat(self):
        mgr, clock, _, c = lobby(2)
        mgr.handle_text(c[2], msg("READY", {"ready": True}), clock.now)
        mgr.disconnect(c[2], clock.now)
        assert state(c[1])["members"][1]["connected"] is False
        clock.advance(29_000)
        await mgr.pump(clock.now)
        back = mgr.connect(auth(2), clock.now)
        assert state(back)["members"][1]["connected"] is True and state(back)["role"] == "player"
        clock.advance(60_000)
        await mgr.pump(clock.now)
        assert 2 in mgr.rooms["r1"].members

    async def test_after_the_grace_period_the_seat_is_dropped(self):
        mgr, clock, _, c = lobby(3)
        mgr.disconnect(c[3], clock.now)
        clock.advance(30_000)
        await mgr.pump(clock.now)
        assert [m["user_id"] for m in state(c[1])["members"]] == [1, 2]

    async def test_host_leaving_past_grace_hands_over_to_the_longest_present_player(self):
        mgr, clock, _, c = lobby(3)
        mgr.disconnect(c[1], clock.now)
        assert mgr.rooms["r1"].host == 1                                   # still host during the grace period
        clock.advance(31_000)
        await mgr.pump(clock.now)
        assert mgr.rooms["r1"].host == 2 and state(c[3])["host"] == 2

    async def test_a_player_gone_mid_game_is_removed_by_the_engine_and_returns_as_a_spectator(self):
        mgr, clock, _, c = lobby(3)
        mgr.handle_text(c[1], msg("START"), clock.now)
        await mgr.pump(clock.now)
        mgr.disconnect(c[3], clock.now)
        clock.advance(31_000)
        await mgr.pump(clock.now)
        assert 3 not in [p["user_id"] for p in state(c[1])["game"]["players"]]
        back = mgr.connect(auth(3), clock.now)
        assert state(back)["role"] == "spectator"

    async def test_a_disconnected_players_survival_run_ends_when_the_seat_expires(self):
        mgr, clock, _, c = lobby(2)
        mgr.handle_text(c[1], msg("SET_MODE", {"mode": "survival"}), clock.now)
        mgr.handle_text(c[1], msg("START"), clock.now)
        await mgr.pump(clock.now)
        mgr.disconnect(c[2], clock.now)
        clock.advance(31_000)
        await mgr.pump(clock.now)
        assert mgr.rooms["r1"].runs[2].reason == "quit"


class TestReaper:
    async def test_idle_lobby_is_closed_after_its_ttl(self):
        mgr, clock, _, c = lobby(2)
        clock.advance(14 * 60_000)
        await mgr.pump(clock.now)
        assert "r1" in mgr.rooms
        clock.advance(61_000)
        await mgr.pump(clock.now)
        assert mgr.rooms == {} and all(last(x, "BYE")["d"]["reason"] == "room_closed" for x in c.values())

    async def test_activity_resets_the_clock(self):
        mgr, clock, _, c = lobby(2)
        for _ in range(4):                                           # 40 minutes in total, never idle for 15
            clock.advance(10 * 60_000)
            mgr.handle_text(c[1], msg("READY", {"ready": True}), clock.now)
            await mgr.pump(clock.now)
        assert "r1" in mgr.rooms

    async def test_idle_game_closes_at_the_longer_ttl(self):
        mgr, clock, _, c = lobby(2)
        mgr.handle_text(c[1], msg("START"), clock.now)
        clock.advance(29 * 60_000)
        mgr.handle_text(c[1], msg("PING"), clock.now)
        await mgr.pump(clock.now)
        clock.advance(31 * 60_000)
        await mgr.pump(clock.now)
        assert mgr.rooms == {}

    async def test_killswitch_closes_everything(self):
        mgr, clock, _, c = lobby(2)
        mgr.settings.set("system.killswitch", True)
        await mgr.pump(clock.now)
        assert mgr.rooms == {} and last(c[1], "BYE")


# ───────────────────────────── bad input ─────────────────────────────

class TestAbuse:
    def test_malformed_frames_get_an_error_and_the_socket_survives(self):
        mgr, clock, _, c = lobby(2)
        bad = ["not json", "[]", "42", '{"v": 2, "t": "PING"}', '{"v": 1}', '{"v": 1, "t": 5}', "x" * 5000,
               msg("READY", {"ready": "yes"}), msg("ANSWER", {"index": 9}), msg("READY", {"ready": True, "extra": 1}),
               '{"v": 1, "t": "PING", "id": 12}']
        for i, raw in enumerate(bad):
            clock.advance(200)
            mgr.handle_text(c[1], raw, clock.now)
        assert len(errors(c[1])) == len(bad) and not c[1].closed
        mgr.handle_text(c[1], msg("PING"), clock.now + 1000)
        assert last(c[1], "PONG")

    def test_unknown_message_types_are_ignored_silently(self):
        mgr, clock, _, c = lobby(2)
        c[1].outbox.clear()
        mgr.handle_text(c[1], msg("TELEPORT"), clock.now)
        mgr.handle_text(c[1], msg("AUTH", {"access_token": "x", "instance_id": "y"}), clock.now)   # AUTH is only valid first
        assert c[1].outbox == []

    def test_binary_frames_are_treated_like_text(self):
        mgr, clock, _, c = lobby(2)
        mgr.handle_text(c[1], b"\xff\xfe\x00", clock.now)
        assert errors(c[1]) == ["bad_json"]

    def test_more_than_ten_messages_a_second_is_rate_limited(self):
        mgr, clock, _, c = lobby(2)
        for _ in range(25):
            mgr.handle_text(c[1], msg("PING"), clock.now)
        assert len([f for f in c[1].outbox if f["t"] == "PONG"]) == 10 and "rate_limited" in errors(c[1])
        clock.advance(1000)
        c[1].outbox.clear()
        mgr.handle_text(c[1], msg("PING"), clock.now)
        assert last(c[1], "PONG")

    def test_a_sustained_flood_closes_the_socket(self):
        mgr, clock, _, c = lobby(2)
        for _ in range(200):
            mgr.handle_text(c[1], msg("PING"), clock.now)
        assert c[1].closed and c[1].close_code == 4429

    def test_a_client_that_never_reads_cannot_grow_memory_forever(self):
        mgr, clock, _, c = lobby(2)
        for i in range(500):
            clock.advance(150)
            mgr.handle_text(c[1], msg("RESYNC"), clock.now)
        assert c[1].closed and c[1].close_code == 4429 and len(c[1].outbox) <= 400

    def test_a_replaced_window_cannot_act(self):
        mgr, clock, _, c = lobby(2)
        mgr.connect(auth(1), clock.now)
        from bamboozled.server.protocol import parse_frame
        mgr.handle(c[1], parse_frame(msg("READY", {"ready": True})), clock.now)
        assert not mgr.rooms["r1"].members[1].ready

    def test_resync_returns_a_full_state(self):
        mgr, clock, _, c = lobby(2)
        c[2].outbox.clear()
        mgr.handle_text(c[2], msg("RESYNC"), clock.now)
        assert kinds(c[2]) == ["STATE"] and c[2].outbox[0]["seq"] == c[2].seq

    def test_sequence_numbers_count_up_per_connection(self):
        mgr, clock, _, c = lobby(2)
        mgr.handle_text(c[1], msg("READY", {"ready": True}), clock.now)
        seqs = [f["seq"] for f in c[1].outbox]
        assert seqs == list(range(1, len(seqs) + 1))


class TestEventFiltering:
    """Events are cues for animation; none may carry numbers a player is not allowed to see."""

    def forwarded(self, events, mist):
        from bamboozled.engine import Event
        mgr, clock, _, c = lobby(2)
        c[1].outbox.clear()
        mgr._send_events(mgr.rooms["r1"], [Event(k, p) for k, p in events], mist)
        return [(f["d"]["kind"], f["d"]["payload"]) for f in c[1].outbox]

    def test_mist_strips_every_number_that_would_reveal_a_score(self):
        out = self.forwarded([("monkey_result", {"player": 1, "choice": "tail", "delta": 300}),
                               ("steal", {"from": 2, "to": 1, "amount": 100}),
                               ("law_effect", {"law": 5, "player": 1, "delta": -50})], mist=True)
        assert out == [("monkey_result", {"player": 1, "choice": "tail"}), ("steal", {"from": 2, "to": 1}),
                       ("law_effect", {"law": 5, "player": 1})]

    def test_without_the_mist_the_numbers_are_kept(self):
        out = self.forwarded([("monkey_result", {"player": 1, "choice": "tail", "delta": 300})], mist=False)
        assert out == [("monkey_result", {"player": 1, "choice": "tail", "delta": 300})]

    def test_score_snapshots_are_never_forwarded_except_at_the_endgame(self):
        out = self.forwarded([("turn_resolved", {"scores": {1: 5}}), ("mystery", {"scores": {1: 5}, "x": 1}),
                              ("endgame", {"scores": {1: 5}})], mist=False)
        assert out == [("mystery", {"x": 1}), ("endgame", {"scores": {1: 5}})]
