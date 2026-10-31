"""Acceptance tests for spec 10.3: /privacy and everything that must stop once someone opts out."""

import asyncio
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from bamboozled.bot.cogs.privacy import PrivacyCog
from bamboozled.config import Config
from bamboozled.db.repos import stats as stats_repo
from bamboozled.db.repos.matches import ResultRow, record_match
from bamboozled.server.auth import AuthError, DevAuthenticator
from bamboozled.server.http import Deps, create_app
from bamboozled.server.names import NameCache
from bamboozled.services import names as display_names
from bamboozled.services.privacy import DAY_S, PrivacyService, privacy_db_path
from bamboozled.settings import Settings
from tests.bot_helpers import FakeInteraction, interaction, user
from tests.server_helpers import Clock, auth, errors, msg


async def seed():
    await record_match("bamboozled", 555, [ResultRow(1, 1, 900, 4), ResultRow(2, 2, 300, 1)])
    await record_match("bamboozled", 555, [ResultRow(2, 1, 500, 2)])
    await record_match("survival", 555, [ResultRow(2, 1, 6, 6)], difficulty="medium")


def rows(db, sql):
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


class Cmd:
    """Drives a /privacy sub-command, answering its Confirm prompt like a person would."""

    def __init__(self, bot, uid=2):
        self.bot, self.uid, self.cog = bot, uid, PrivacyCog(bot)

    def command(self, name):
        return PrivacyCog.privacy.get_command(name).callback

    async def simple(self, name):
        it = interaction(self.bot, self.uid)
        await self.command(name)(self.cog, it)
        return it

    async def opt_out(self, press="confirm"):
        it = interaction(self.bot, self.uid)
        task = asyncio.create_task(self.command("opt_out")(self.cog, it))
        for _ in range(200):  # wait for the prompt to appear
            if it.response.send_message.await_count or task.done():
                break
            await asyncio.sleep(0)
        view = it.response.send_message.call_args.kwargs.get("view") if it.response.send_message.await_count else None
        pressed = FakeInteraction(self.bot, user(self.uid))
        if view is not None:
            if press == "confirm":
                await view.confirm_btn.callback(pressed)
            elif press == "cancel":
                await view.cancel_btn.callback(pressed)
            else:  # nothing pressed within 60 seconds
                await view.on_timeout()
                view.stop()
        await asyncio.wait_for(task, 5)
        return it, pressed, view


class TestStatus:
    async def test_in_and_out(self, bot, tmp_db):
        c = Cmd(bot)
        assert "**in**" in (await c.simple("status")).said
        await bot.ctx.privacy.opt_out(2)
        said = (await c.simple("status")).said
        assert "opted out" in said and "<t:" in said and "opt_in" in said


class TestOptOut:
    async def test_it_explains_what_is_deleted_and_how_long_backups_and_logs_last(self, bot, tmp_db):
        it, _, view = await Cmd(bot).opt_out("cancel")
        text = it.said
        assert "never saved your name or picture" in text and "72 hours" in text and "14 days" in text and "60 seconds" in text
        assert it.sent_kwargs()["ephemeral"] is True and view.timeout == 60

    async def test_nothing_is_deleted_until_confirm_is_pressed(self, bot, tmp_db):
        await seed()
        _, pressed, _ = await Cmd(bot).opt_out("cancel")
        assert "Nothing was deleted" in pressed.said
        assert not bot.ctx.privacy.is_opted_out(2) and len(rows(tmp_db, "SELECT * FROM match_results WHERE user_id=2")) == 3

    async def test_letting_the_60_seconds_pass_cancels(self, bot, tmp_db):
        await seed()
        it, _, _ = await Cmd(bot).opt_out("timeout")
        assert "took too long" in it.said and not bot.ctx.privacy.is_opted_out(2)

    async def test_only_the_person_who_asked_can_press_the_buttons(self, bot, tmp_db):
        it = interaction(bot, 2)
        task = asyncio.create_task(PrivacyCog.privacy.get_command("opt_out").callback(PrivacyCog(bot), it))
        for _ in range(100):
            if it.response.send_message.await_count:
                break
            await asyncio.sleep(0)
        view = it.response.send_message.call_args.kwargs["view"]
        stranger = FakeInteraction(bot, user(99))
        assert not await view.interaction_check(stranger) and "someone else" in stranger.said
        view.stop()
        await task

    async def test_confirming_deletes_results_and_stats_and_empty_matches_but_nobody_elses(self, bot, tmp_db):
        await seed()
        display_names._cache.clear()
        await display_names.display_name(bot, 2)  # their name is cached
        _, pressed, _ = await Cmd(bot).opt_out()
        assert "Done. You are opted out" in pressed.said and "72 hours" in pressed.said
        assert rows(tmp_db, "SELECT COUNT(*) FROM match_results WHERE user_id=2") == [(0,)]
        assert rows(tmp_db, "SELECT COUNT(*) FROM stats WHERE user_id=2") == [(0,)]
        assert rows(tmp_db, "SELECT mode, COUNT(*) FROM matches GROUP BY mode") == [
            ("bamboozled", 1)
        ]  # two matches had only them, or were emptied
        assert rows(tmp_db, "SELECT user_id FROM match_results") == [(1,)]  # player 1's result is untouched
        assert (await stats_repo.player_stats(1))["wins"] == 1
        assert 2 not in display_names._cache  # and their cached name is gone

    async def test_the_privacy_record_is_written_first_and_survives_purging(self, bot, tmp_db):
        await seed()
        priv = bot.ctx.privacy
        seen = {}
        real_purge = priv._purge

        async def spy(uid):
            seen["status_when_purging"] = (await priv._row(uid))[0]
            seen["in_memory_when_purging"] = priv.is_opted_out(uid)
            return await real_purge(uid)

        priv._purge = spy
        await priv.opt_out(2)
        assert seen == {"status_when_purging": "out", "in_memory_when_purging": True}
        assert privacy_db_path().name == "privacy.db" and privacy_db_path().parent == tmp_db.parent
        assert rows(privacy_db_path(), "SELECT user_id, status FROM privacy_state") == [(2, "out")]
        fresh = PrivacyService(Settings())  # a restart: still opted out
        assert await fresh.load() == 1 and fresh.is_opted_out(2)

    async def test_it_is_refused_while_you_are_in_a_running_game_unless_the_setting_is_off(self, bot, tmp_db):
        mgr = bot.ctx.manager
        from tests.server_helpers import msg as m

        c1, c2 = mgr.connect(auth(1), mgr.clock_ms()), mgr.connect(auth(2), mgr.clock_ms())
        mgr.handle_text(c1, m("START"), mgr.clock_ms())
        it = await Cmd(bot, 2).simple("opt_out")
        assert "game that is still running" in it.said and not bot.ctx.privacy.is_opted_out(2)
        bot.ctx.settings.set("privacy.block_during_game", False)
        await Cmd(bot, 2).opt_out()
        assert bot.ctx.privacy.is_opted_out(2) and c2.closed  # and their socket was closed

    async def test_a_game_that_starts_between_asking_and_confirming_is_still_respected(self, bot, tmp_db):
        mgr = bot.ctx.manager
        c = Cmd(bot, 2)
        it = interaction(bot, 2)
        task = asyncio.create_task(c.command("opt_out")(c.cog, it))
        for _ in range(100):
            if it.response.send_message.await_count:
                break
            await asyncio.sleep(0)
        mgr.connect(auth(1), mgr.clock_ms()), mgr.connect(auth(2), mgr.clock_ms())
        mgr.handle_text(mgr.rooms["r1"].members[1].conn, msg("START"), mgr.clock_ms())
        pressed = FakeInteraction(bot, user(2))
        await it.response.send_message.call_args.kwargs["view"].confirm_btn.callback(pressed)
        await task
        assert "still running" in pressed.said and not bot.ctx.privacy.is_opted_out(2)

    async def test_opting_out_twice_is_harmless(self, bot, tmp_db):
        await bot.ctx.privacy.opt_out(2)
        assert "already opted out" in (await Cmd(bot).simple("opt_out")).said


class TestOptIn:
    async def test_it_waits_for_the_cooldown_then_restores_nothing(self, bot, tmp_db):
        clock = Clock(1_700_000_000)
        priv = bot.ctx.privacy
        priv.clock = clock
        await seed()
        await priv.opt_out(2)
        said = (await Cmd(bot).simple("opt_in")).said
        assert "can opt back in <t:" in said and priv.is_opted_out(2)
        clock.now += 6 * DAY_S
        assert priv.is_opted_out(2) and (await priv.opt_in(2)).outcome == "cooldown"
        clock.now += 1 * DAY_S
        said = (await Cmd(bot).simple("opt_in")).said
        assert "Welcome back" in said and "fresh profile" in said and not priv.is_opted_out(2)
        assert await stats_repo.player_stats(2) is None  # nothing came back
        assert (await priv.opt_in(2)).outcome == "already"

    async def test_the_cooldown_length_is_a_setting(self, bot, tmp_db):
        bot.ctx.settings.set("privacy.optin_cooldown_days", 0)
        await bot.ctx.privacy.opt_out(2)
        assert (await bot.ctx.privacy.opt_in(2)).outcome == "ok"

    async def test_someone_who_never_opted_out_is_simply_in(self, bot, tmp_db):
        assert "already in" in (await Cmd(bot).simple("opt_in")).said


# ───────────────────────────── the enforcement points ─────────────────────────────


class TestEnforcement:
    async def test_the_websocket_refuses_an_opted_out_user_with_a_clear_message(self, bot, tmp_db):
        bot.ctx.privacy._out.add(2)
        with pytest.raises(AuthError) as err:
            await DevAuthenticator(is_opted_out=bot.ctx.privacy.is_opted_out)("dev:2:Bob", "inst")
        assert err.value.close_code == 4403 and "opted out" in err.value.message and "opt_in" in err.value.message

    async def test_they_never_appear_in_leaderboards_others_stats_or_result_cards(self, bot, tmp_db):
        from bamboozled.bot.cogs.stats import StatsCog
        from bamboozled.services.results_card import post_result_card

        await seed()
        await bot.ctx.privacy.opt_out(2)
        cog = StatsCog(bot)
        board = interaction(bot, 1)
        await cog.leaderboard.callback(cog, board, "bamboozled", "global")
        assert "User2" not in board.said and "User1" in board.said
        lookup = interaction(bot, 1)
        await cog.stats.callback(cog, lookup, user(2), None)
        assert "No stats found" in lookup.said
        assert (
            await post_result_card(bot.ctx, type("R", (), {"channel_id": 1, "mode": "bamboozled"})(), [ResultRow(2, 1, 5)])
            is False
        )  # nobody left to show

    async def test_the_lobby_and_room_code_never_list_them(self, bot, tmp_db):
        mgr = bot.ctx.manager
        await bot.ctx.privacy.opt_out(2)
        from bamboozled.server.rooms import Refused

        conn = mgr.connect(auth(1), mgr.clock_ms())
        with pytest.raises(Refused):
            mgr.connect(auth(2), mgr.clock_ms())
        assert [m["user_id"] for m in conn.outbox[-1]["d"]["members"]] == [1]

    async def test_opting_out_removes_you_from_the_lobby_you_are_sitting_in(self, bot, tmp_db):
        mgr = bot.ctx.manager
        c1, c2 = mgr.connect(auth(1), mgr.clock_ms()), mgr.connect(auth(2), mgr.clock_ms())
        await bot.ctx.privacy.opt_out(2)
        assert c2.closed and c2.close_code == 4403 and "opted_out" in errors(c2)
        assert [m["user_id"] for m in c1.outbox[-1]["d"]["members"]] == [1]

    async def test_the_old_text_games_refuse_the_join_button_too(self, bot, tmp_db):
        from cogs.game import LobbyView

        bot.ctx.privacy._out.add(2)
        it = interaction(bot, 2)
        view = type("V", (), {"game": type("G", (), {"active": False})()})()
        await LobbyView.join_btn(view, it, None)
        assert "opted out" in it.said


# ───────────────────────────── the same actions from the Activity ─────────────────────────────


@pytest.fixture
def web(tmp_path):
    (tmp_path / "dist").mkdir()
    return tmp_path / "dist"


def client_for(ctx, web):
    mgr = ctx.manager
    deps = Deps(
        cfg=Config(env="test", dev_auth=True, web_dist=web),
        manager=mgr,
        settings=ctx.settings,
        clock_ms=mgr.clock_ms,
        authenticator=DevAuthenticator(is_opted_out=ctx.privacy.is_opted_out),
        http=httpx.AsyncClient(),
        names=NameCache(lambda uid: _name(uid)),
        privacy=ctx.privacy,
    )
    return TestClient(create_app(deps))


async def _name(uid):
    return f"User{uid}"


HEAD = {"authorization": "Bearer dev:2:Bob", "x-instance-id": "r1"}


class TestRestEndpoints:
    def test_opt_out_then_opt_in_with_the_cooldown(self, ctx, web, tmp_db):
        asyncio.run(ctx.privacy.load())
        ctx.privacy.clock = clock = Clock(1_700_000_000)
        client = client_for(ctx, web)
        r = client.post("/api/privacy/opt_out", headers=HEAD)
        assert r.status_code == 200 and r.json()["status"] == "out" and ctx.privacy.is_opted_out(2)
        assert client.get("/api/me/stats", headers=HEAD).status_code == 403  # now refused everywhere
        r = client.post("/api/privacy/opt_in", headers=HEAD)  # but they can still prove who they are
        assert r.status_code == 429 and r.json()["error"] == "cooldown" and r.json()["retry_at"] > clock.now
        clock.now += 8 * DAY_S
        assert client.post("/api/privacy/opt_in", headers=HEAD).json() == {"status": "in"}
        assert not ctx.privacy.is_opted_out(2)

    def test_opt_out_is_refused_in_a_running_game(self, ctx, web, tmp_db):
        asyncio.run(ctx.privacy.load())
        mgr = ctx.manager
        c1, _ = mgr.connect(auth(1), mgr.clock_ms()), mgr.connect(auth(2), mgr.clock_ms())
        mgr.handle_text(c1, msg("START"), mgr.clock_ms())
        r = client_for(ctx, web).post("/api/privacy/opt_out", headers=HEAD)
        assert r.status_code == 409 and r.json()["error"] == "in_game" and not ctx.privacy.is_opted_out(2)

    def test_both_need_a_sign_in(self, ctx, web, tmp_db):
        client = client_for(ctx, web)
        assert client.post("/api/privacy/opt_out").status_code == 401
        assert client.post("/api/privacy/opt_in").status_code == 401
