"""Acceptance tests for spec 10.4: the result card and its Play again button."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bamboozled.bot.views.card import PlayAgainView
from bamboozled.engine.api import ResultRow
from bamboozled.server.rooms import Room
from bamboozled.services import results_card
from bamboozled.services.results_card import build_card, post_result_card
from tests.bot_helpers import interaction

CHANNEL = 4040


def rows(n=3, **details):
    return [ResultRow(i + 1, i + 1, 1000 - i * 100, 3, dict(details) if i == n - 1 else {}) for i in range(n)]


def room(channel=CHANNEL, mode="bamboozled"):
    return Room(key="k", guild_id=9, channel_id=channel, created_ms=0, last_activity_ms=0, mode=mode)


def channel(can_send=True, can_embed=True):
    ch = MagicMock()
    ch.send = AsyncMock()
    ch.guild = SimpleNamespace(me=object(), get_member=lambda uid: None)
    ch.permissions_for = lambda _me: SimpleNamespace(send_messages=can_send, embed_links=can_embed)
    return ch


@pytest.fixture(autouse=True)
def fresh_warnings():
    results_card._warned.clear()


class TestBuildCard:
    def test_podium_with_medals_scores_and_a_hint_to_play_again(self):
        emb = build_card("bamboozled", rows(4), {1: "Ann", 2: "Bob", 3: "Cy", 4: "Di"})
        lines = emb.description.split("\n")
        assert lines[0].startswith("🥇 Ann — **1,000** pts") and lines[1].startswith("🥈") and lines[2].startswith("🥉")
        assert lines[3].startswith("**4.** Di")
        assert "Bamboozled results" in emb.title and "Play again" in emb.footer.text

    def test_names_cannot_ping_or_format(self):
        emb = build_card("bamboozled", rows(1), {1: "@everyone <@123456789012345678> **bold**"})
        assert "@everyone" not in emb.description.replace("@​everyone", "") and "<@123456789012345678>" not in emb.description
        assert "\\*\\*bold\\*\\*" in emb.description

    def test_survival_shows_streaks_and_a_leaver_is_marked(self):
        emb = build_card("survival", rows(2, left="quit"), {1: "A", 2: "B"})
        assert "**1,000** streak" in emb.description and "*(left early)*" in emb.description.split("\n")[1]

    def test_a_long_result_is_cut_and_an_empty_one_is_friendly(self):
        many = build_card("fff", [ResultRow(i, i, 10) for i in range(1, 15)], {})
        assert many.description.endswith("…and 4 more") and len(many.description.split("\n")) == 11
        assert "Nobody finished" in build_card("fff", [], {}).description


class TestPosting:
    async def post(self, bot, rws=None, rm=None):
        return await post_result_card(bot.ctx, rm or room(), rws if rws is not None else rows(3))

    async def test_it_posts_one_embed_with_no_mentions_and_a_play_again_button(self, bot):
        ch = bot.channels[CHANNEL] = channel()
        assert await self.post(bot) is True
        ch.send.assert_awaited_once()
        kwargs = ch.send.call_args.kwargs
        assert kwargs["allowed_mentions"].to_dict() == discord.AllowedMentions.none().to_dict()
        assert isinstance(kwargs["view"], PlayAgainView) and "results" in kwargs["embed"].title
        assert set(kwargs) == {"embed", "view", "allowed_mentions"}  # no message text that could ping

    async def test_the_channel_is_the_one_discord_reported_for_the_instance(self, bot):
        other = bot.channels[1] = channel()
        ch = bot.channels[CHANNEL] = channel()
        await self.post(bot, rm=room(channel=CHANNEL))
        ch.send.assert_awaited_once()
        other.send.assert_not_awaited()

    async def test_a_channel_we_can_only_fetch_still_works(self, bot):
        bot.fetch_channel = AsyncMock(return_value=(ch := channel()))
        assert await self.post(bot) is True and ch.send.await_count == 1

    async def test_opted_out_players_are_left_off(self, bot):
        ch = bot.channels[CHANNEL] = channel()
        bot.ctx.privacy._out.add(2)
        await self.post(bot)
        text = ch.send.call_args.kwargs["embed"].description
        assert "User2" not in text and "User1" in text and "User3" in text

    async def test_nothing_is_posted_if_everybody_opted_out(self, bot):
        ch = bot.channels[CHANNEL] = channel()
        bot.ctx.privacy._out.update({1, 2, 3})
        assert await self.post(bot) is False and ch.send.await_count == 0

    async def test_result_channels_can_be_restricted(self, bot):
        ch = bot.channels[CHANNEL] = channel()
        bot.ctx.settings.set("channel.results", [123456789012345678])  # a list that does not include this channel
        assert await self.post(bot) is False and ch.send.await_count == 0

    async def test_a_listed_channel_is_posted_to(self, bot):
        listed = 123456789012345678
        ch = bot.channels[listed] = channel()
        bot.ctx.settings.set("channel.results", [listed])
        assert await self.post(bot, rm=room(channel=listed)) is True and ch.send.await_count == 1

    async def test_without_permission_it_skips_quietly_and_logs_once(self, bot, caplog):
        ch = bot.channels[CHANNEL] = channel(can_send=False)
        with caplog.at_level(logging.WARNING, logger="bamboozled.results_card"):
            assert await self.post(bot) is False and await self.post(bot) is False and await self.post(bot) is False
        assert ch.send.await_count == 0
        assert len([r for r in caplog.records if "result card skipped" in r.message]) == 1

    async def test_a_channel_that_refuses_at_send_time_is_also_logged_once(self, bot, caplog):
        ch = bot.channels[CHANNEL] = channel()
        ch.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="x"), "no")
        with caplog.at_level(logging.WARNING, logger="bamboozled.results_card"):
            assert await self.post(bot) is False and await self.post(bot) is False
        assert len([r for r in caplog.records if "result card skipped" in r.message]) == 1

    async def test_an_unreachable_channel_and_other_failures_never_raise(self, bot):
        bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="x"), "gone"))
        assert await self.post(bot) is False
        ch = bot.channels[CHANNEL] = channel()
        ch.send.side_effect = discord.HTTPException(SimpleNamespace(status=500, reason="x"), "boom")
        assert await self.post(bot) is False

    async def test_without_a_bot_there_is_nothing_to_post_with(self, bot):
        bot.ctx.bot = None
        assert await self.post(bot) is False


class TestPlayAgain:
    def test_the_button_is_persistent_so_old_cards_keep_working(self):
        view = PlayAgainView()
        assert view.timeout is None and view.is_persistent()
        assert [b.custom_id for b in view.children] == ["bamboozled:play_again"]

    async def test_pressing_it_launches_the_activity(self, bot):
        it = interaction(bot, 1)
        await PlayAgainView.play_again(PlayAgainView(), it, None)
        it.response.launch_activity.assert_awaited_once()

    async def test_an_opted_out_player_is_refused(self, bot):
        bot.ctx.privacy._out.add(1)
        it = interaction(bot, 1)
        await PlayAgainView.play_again(PlayAgainView(), it, None)
        assert "opted out" in it.said and it.response.launch_activity.await_count == 0

    async def test_the_kill_switch_stops_it(self, bot):
        bot.ctx.settings.set("system.killswitch", True)
        it = interaction(bot, 1)
        await PlayAgainView.play_again(PlayAgainView(), it, None)
        assert "maintenance" in it.said and it.response.launch_activity.await_count == 0

    async def test_it_explains_the_app_launcher_if_discord_refuses(self, bot):
        it = interaction(bot, 1)
        it.response.launch_activity.side_effect = discord.HTTPException(SimpleNamespace(status=400, reason="x"), "no")
        await PlayAgainView.play_again(PlayAgainView(), it, None)
        assert "App Launcher" in it.said


class TestWiring:
    async def test_the_room_manager_posts_a_card_when_a_game_ends_unless_testing_or_switched_off(self, bot, tmp_db):
        """The hook the app gives the manager is post_result_card; it respects feature.post_results and testing servers."""
        from bamboozled.app import build
        from bamboozled.config import Config

        bot.channels[CHANNEL] = ch = channel()
        _, mgr, _, http = build(Config(env="test", dev_auth=True), bot.ctx, bot)
        r = room()
        mgr._to_flush.append((r, rows(2), {"started_ms": 0, "cfg": {}, "mode": "bamboozled", "runs": {}}))
        await mgr._flush()
        assert ch.send.await_count == 1
        bot.ctx.settings.set("feature.post_results", False)
        mgr._to_flush.append((r, rows(2), {"started_ms": 0, "cfg": {}, "mode": "bamboozled", "runs": {}}))
        await mgr._flush()
        assert ch.send.await_count == 1
        bot.ctx.settings.set("feature.post_results", True)
        bot.ctx.settings.set("system.testing_guilds", [r.guild_id + 10**17])
        r.guild_id += 10**17
        mgr._to_flush.append((r, rows(2), {"started_ms": 0, "cfg": {}, "mode": "bamboozled", "runs": {}}))
        await mgr._flush()
        assert ch.send.await_count == 1
        await http.aclose()
