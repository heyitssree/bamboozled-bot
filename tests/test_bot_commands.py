"""Acceptance tests for spec 10.1: the commands, the guard that refuses opted-out users, and the legacy text-mode switch."""

import discord

from bamboozled.bot.client import LEGACY_EXTENSIONS, NEW_EXTENSIONS, BamboozledBot
from bamboozled.bot.cogs.help import HelpCog
from bamboozled.bot.cogs.play import PlayCog
from bamboozled.bot.cogs.stats import StatsCog
from bamboozled.db.repos.matches import ResultRow, record_match
from tests.bot_helpers import FakeInteraction, interaction, make_ctx, user


async def play(bot, uid=1):
    it = interaction(bot, uid)
    await PlayCog(bot).play.callback(PlayCog(bot), it)
    return it


class TestPlay:
    async def test_it_launches_the_activity_from_this_channel(self, bot):
        it = await play(bot)
        it.response.launch_activity.assert_awaited_once()

    async def test_it_says_so_when_the_bot_is_closed_for_maintenance(self, bot):
        bot.ctx.settings.set("system.killswitch", True)
        it = await play(bot)
        it.response.launch_activity.assert_not_awaited()
        assert "maintenance" in it.said

    async def test_it_explains_the_app_launcher_when_discord_will_not_launch(self, bot):
        it = interaction(bot)
        it.response.launch_activity.side_effect = discord.HTTPException(type("R", (), {"status": 400, "reason": "x"})(), "no")
        await PlayCog(bot).play.callback(PlayCog(bot), it)
        assert "App Launcher" in it.said


class TestStats:
    async def seed(self):
        await record_match("bamboozled", 555, [ResultRow(1, 1, 900, 4), ResultRow(2, 2, 300, 1)])
        await record_match("survival", 555, [ResultRow(1, 1, 7, 7, {})], difficulty="medium")

    async def run(self, bot, asker, target=None, mode=None):
        cog = StatsCog(bot)
        it = interaction(bot, asker)
        await cog.stats.callback(cog, it, target, mode)
        return it

    async def test_your_own_stats_are_private_and_complete(self, bot, tmp_db):
        await self.seed()
        it = await self.run(bot, 1)
        assert it.sent_kwargs()["ephemeral"] is True
        assert "1 games" in it.said and "best 900" in it.said and "best streak **7**" in it.said

    async def test_another_players_stats_and_a_single_mode(self, bot, tmp_db):
        await self.seed()
        it = await self.run(bot, 1, user(2), "bamboozled")
        assert "User2" in it.said and "0 wins" in it.said and "Survival" not in it.said

    async def test_nothing_to_show_says_so(self, bot, tmp_db):
        it = await self.run(bot, 1, user(404))
        assert "No stats found for User404" in it.said

    async def test_an_opted_out_player_has_no_stats_for_anyone_else_to_see(self, bot, tmp_db):
        await self.seed()
        bot.ctx.privacy._out.add(2)
        it = await self.run(bot, 1, user(2))
        assert "No stats found" in it.said and "900" not in it.said


class TestLeaderboard:
    async def seed(self):
        await record_match("bamboozled", 555, [ResultRow(1, 1, 900, 4), ResultRow(2, 2, 300, 1), ResultRow(3, 3, 100, 0)])
        await record_match("bamboozled", 999, [ResultRow(4, 1, 5000, 9)])

    async def board(self, bot, **kw):
        cog = StatsCog(bot)
        it = interaction(bot, 1)
        await cog.leaderboard.callback(cog, it, **kw)
        return it

    async def test_this_server_versus_everywhere(self, bot, tmp_db):
        await self.seed()
        here = (await self.board(bot, mode="bamboozled", scope="server")).said
        everywhere = (await self.board(bot, mode="bamboozled", scope="global")).said
        assert "User1" in here and "User4" not in here and "This server" in here
        assert everywhere.index("User4") < everywhere.index("User1") and "Everywhere" in everywhere

    async def test_opted_out_players_never_appear(self, bot, tmp_db):
        await self.seed()
        bot.ctx.privacy._out.add(1)
        said = (await self.board(bot, mode="bamboozled", scope="server")).said
        assert "User1" not in said and "User2" in said

    async def test_empty_board_points_at_play(self, bot, tmp_db):
        assert "/play" in (await self.board(bot, mode="fff", scope="server")).said

    async def test_names_with_mentions_are_neutralised(self, bot, tmp_db):
        await self.seed()
        bot.get_user = lambda uid: type("U", (), {"display_name": "@everyone <@123456789012345678>"})()
        said = (await self.board(bot, mode="bamboozled", scope="server")).said
        assert "@everyone" not in said and "<@123456789012345678>" not in said

    async def test_a_long_board_is_paged(self, bot, tmp_db):
        for i in range(1, 25):
            await record_match("bamboozled", 555, [ResultRow(i, 1, 100 + i, 1)])
        it = await self.board(bot, mode="bamboozled", scope="server")
        assert it.followup.send.call_args.kwargs["view"] is not discord.utils.MISSING


class TestHelp:
    async def test_explains_how_to_start_and_shows_a_screenshot(self, bot):
        it = interaction(bot)
        await HelpCog(bot).help.callback(HelpCog(bot), it)
        assert "/play" in it.said and "App Launcher" in it.said
        assert it.sent_kwargs()["file"].filename == "help.png" and it.sent_kwargs()["ephemeral"] is True


class TestTheGuard:
    """Every slash command passes through the command tree's check first."""

    def tree_bot(self, **settings):
        ctx = make_ctx(with_manager=False, **settings)
        b = BamboozledBot(ctx)
        return b, ctx

    async def load_all(self, b):
        for ext in NEW_EXTENSIONS + LEGACY_EXTENSIONS:
            await b.load_extension(ext)

    async def check(self, b, name, uid, sub=None):
        cmd = b.tree.get_command(name)
        it = FakeInteraction(b, user(uid), command=cmd.get_command(sub) if sub else cmd)
        return await b.tree.interaction_check(it), it

    async def test_opted_out_users_are_refused_everywhere_except_privacy_and_help(self):
        b, ctx = self.tree_bot()
        await self.load_all(b)
        ctx.privacy._out.add(7)
        for name, sub in [
            ("play", None),
            ("stats", None),
            ("leaderboard", None),
            ("bamboozled", "join"),
            ("fff", None),
            ("survival", None),
            ("quizstats", None),
            ("bamboozled-admin", "panel"),
        ]:
            ok, it = await self.check(b, name, 7, sub)
            assert not ok and "opted out" in it.said, name
        for name, sub in [("privacy", "status"), ("privacy", "opt_in"), ("help", None)]:
            ok, _ = await self.check(b, name, 7, sub)
            assert ok, name
        ok, _ = await self.check(b, "play", 8)  # everyone else is untouched
        assert ok
        await b.close()

    async def test_legacy_commands_are_refused_for_everyone_while_text_mode_is_off(self):
        b, ctx = self.tree_bot(**{"feature.text_mode": False})
        await self.load_all(b)
        for name, sub in [("bamboozled", "join"), ("fff", None), ("survival", None), ("quizstats", None)]:
            ok, it = await self.check(b, name, 1, sub)
            assert not ok and "/play" in it.said, name
        assert (await self.check(b, "play", 1))[0]
        await b.close()


class TestTextModeSwitch:
    async def test_the_old_commands_exist_only_while_text_mode_is_on(self, tmp_db):
        ctx = make_ctx(with_manager=False)
        b = BamboozledBot(ctx)
        for ext in NEW_EXTENSIONS:
            await b.load_extension(ext)
        b.sync_commands = _noop
        names = lambda: {c.name for c in b.tree.get_commands()}  # noqa: E731
        assert names() == {"play", "stats", "leaderboard", "privacy", "help", "bamboozled-admin"}
        await ctx.apply_setting("feature.text_mode", True, 1)  # already on by default: register the legacy cogs
        await b._load_legacy()
        assert {"bamboozled", "fff", "survival", "quizstats"} <= names()
        await ctx.apply_setting("feature.text_mode", False, 1)  # the hook unloads them again
        await b._setting_changed("feature.text_mode", False)
        assert names() == {"play", "stats", "leaderboard", "privacy", "help", "bamboozled-admin"}
        await b._setting_changed("feature.text_mode", True)
        assert "bamboozled" in names()
        await b.close()


async def _noop():
    return None


def test_the_alias_and_the_new_commands_share_one_leaderboard_builder():
    import quiz_stats
    from bamboozled.bot import leaderboards

    assert quiz_stats.build_pages is leaderboards.build_pages


class TestStartUp:
    async def test_setup_hook_loads_every_cog_and_registers_the_play_again_button(self, tmp_db):
        ctx = make_ctx(with_manager=False)
        b = BamboozledBot(ctx)
        b.sync_commands = _noop  # no network: everything else is the real start-up
        await b.setup_hook()
        assert ctx.ready
        names = {c.name for c in b.tree.get_commands()}
        assert {
            "play",
            "stats",
            "leaderboard",
            "privacy",
            "help",
            "bamboozled-admin",
            "bamboozled",
            "fff",
            "survival",
            "quizstats",
        } <= names
        assert any(
            isinstance(v, __import__("bamboozled.bot.views.card", fromlist=["PlayAgainView"]).PlayAgainView)
            for v in b.persistent_views
        )
        await b.close()

    async def test_with_text_mode_off_only_the_new_commands_load(self, tmp_db):
        ctx = make_ctx(with_manager=False, **{"feature.text_mode": False})
        b = BamboozledBot(ctx)
        b.sync_commands = _noop
        await b.setup_hook()
        assert {c.name for c in b.tree.get_commands()} == {"play", "stats", "leaderboard", "privacy", "help", "bamboozled-admin"}
        await b.close()

    async def test_stored_settings_and_opt_outs_are_loaded_at_start(self, tmp_db):
        from bamboozled.settings import store
        from bamboozled.services.privacy import PrivacyService

        await store.save("game.total_rounds", 9, 1)
        seed = PrivacyService(make_ctx(with_manager=False).settings)
        await seed.load()
        await seed.opt_out(321)
        ctx = make_ctx(with_manager=False)
        b = BamboozledBot(ctx)
        b.sync_commands = _noop
        await b.setup_hook()
        assert ctx.settings.get("game.total_rounds") == 9 and ctx.privacy.is_opted_out(321)
        await b.close()
