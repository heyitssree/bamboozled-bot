"""Acceptance tests for spec 10.2: the settings panel, /bamboozled-admin, and who may use them."""

import json
from types import SimpleNamespace

import pytest

from bamboozled.bot.cogs.admin import AdminCog, ImportModal, key_autocomplete, status_embed
from bamboozled.bot.views.panel import CHANGED, EditModal, PanelView, category_embed, overview_embed
from bamboozled.bot.views.rooms import MessageModal, RoomsView, rooms_embed
from bamboozled.settings import BY_KEY, CATEGORIES, SETTINGS
from bamboozled.settings import store
from tests.bot_helpers import ADMIN_ROLE, OWNER, FakeInteraction, interaction, user
from tests.server_helpers import auth, last

GUILD = 123456789012345678


def alternative(spec):
    """A valid value different from the default, for each kind of setting."""
    if spec.kind == "bool":
        return not spec.default
    if spec.kind == "int":
        return spec.min if spec.default != spec.min else spec.max
    if spec.kind == "choice":
        return next(c for c in spec.choices if c != spec.default)
    if spec.kind == "id_list":
        return [GUILD]
    return ADMIN_ROLE  # role


def as_text(spec, value):
    return ", ".join(map(str, value)) if isinstance(value, list) else str(value)


def admin(bot, uid=OWNER):
    cog = AdminCog(bot)
    return cog, FakeInteraction(bot, user(uid))


async def run(cmd, bot, uid=OWNER, *args):
    cog = AdminCog(bot)
    it = FakeInteraction(bot, user(uid), guild_id=GUILD)
    await AdminCog.admin.get_command(cmd).callback(cog, it, *args)
    return it


# ───────────────────────────── who may use it ─────────────────────────────


class TestWhoMayUseIt:
    async def test_the_owner_is_allowed(self, bot):
        it = interaction(bot, OWNER)
        assert await AdminCog.admin.interaction_check(it)

    async def test_a_member_with_the_panel_role_is_allowed_once_it_is_set(self, bot):
        it = FakeInteraction(bot, user(5, roles=[ADMIN_ROLE]))
        assert not await AdminCog.admin.interaction_check(it)
        bot.ctx.settings.set("system.panel_role", ADMIN_ROLE)
        assert await AdminCog.admin.interaction_check(FakeInteraction(bot, user(5, roles=[ADMIN_ROLE])))

    async def test_everyone_else_is_refused_politely(self, bot):
        bot.ctx.settings.set("system.panel_role", ADMIN_ROLE)
        it = FakeInteraction(bot, user(6, roles=[999]))
        assert not await AdminCog.admin.interaction_check(it)
        assert "Only the bot's owner" in it.said

    def test_it_is_hidden_from_non_administrators_by_default(self):
        assert AdminCog.admin.default_permissions.administrator is True


# ───────────────────────────── every setting is editable ─────────────────────────────


class TestEverySettingIsEditable:
    @pytest.mark.parametrize("spec", SETTINGS, ids=lambda s: s.key)
    async def test_from_the_panel(self, spec, bot, tmp_db):
        ctx = bot.ctx
        view = PanelView(ctx, OWNER)
        it = FakeInteraction(bot, user(OWNER), data={"values": [spec.category]})
        await view._on_category(it)  # pick its category
        it = FakeInteraction(bot, user(OWNER), data={"values": [spec.key]})
        await view._on_setting(it)  # pick the setting
        assert view.selected == spec.key
        new = alternative(spec)
        if spec.kind == "bool":
            await view._toggle(FakeInteraction(bot, user(OWNER)))  # a toggle button for switches
        else:
            modal_it = FakeInteraction(bot, user(OWNER))
            await view._edit(modal_it)  # an Edit button opens a modal
            modal = modal_it.response.send_modal.call_args.args[0]
            assert isinstance(modal, EditModal)
            modal.value._value = as_text(spec, new)
            await modal.on_submit(FakeInteraction(bot, user(OWNER)))
        assert ctx.settings.get(spec.key) == new
        by, _ = await store.who_changed(spec.key)
        assert by == OWNER  # every change records who made it
        await view._reset(FakeInteraction(bot, user(OWNER)))  # and every setting can be reset
        assert ctx.settings.is_default(spec.key) and await store.who_changed(spec.key) is None

    @pytest.mark.parametrize("spec", SETTINGS, ids=lambda s: s.key)
    async def test_with_set_get_and_reset(self, spec, bot, tmp_db):
        new = alternative(spec)
        it = await run("set", bot, OWNER, spec.key, as_text(spec, new))
        assert bot.ctx.settings.get(spec.key) == new and "is now" in it.said
        assert (await store.who_changed(spec.key))[0] == OWNER
        got = await run("get", bot, OWNER, spec.key)
        assert spec.label in got.said and "default:" in got.said  # a changed setting shows its default
        back = await run("reset", bot, OWNER, spec.key)
        assert bot.ctx.settings.is_default(spec.key) and "default" in back.said


class TestSetValidation:
    async def test_bad_values_are_explained_and_change_nothing(self, bot, tmp_db):
        it = await run("set", bot, OWNER, "game.total_rounds", "99")
        assert "from 3 to 20" in it.said and bot.ctx.settings.get("game.total_rounds") == 5
        it = await run("set", bot, OWNER, "feature.fff", "perhaps")
        assert "on or off" in it.said

    async def test_unknown_keys_say_so(self, bot, tmp_db):
        for cmd in ("set", "get", "reset"):
            args = ("nope.nothing", "1") if cmd == "set" else ("nope.nothing",)
            assert "no setting called" in (await run(cmd, bot, OWNER, *args)).said

    async def test_autocomplete_finds_keys_and_labels(self, bot):
        found = await key_autocomplete(interaction(bot), "rounds")
        assert {c.value for c in found} >= {"game.total_rounds", "game.fff_rounds"}
        assert len(await key_autocomplete(interaction(bot), "")) == min(25, len(SETTINGS))  # Discord shows at most 25

    async def test_changing_a_setting_applies_to_the_running_server_at_once(self, bot, tmp_db):
        mgr = bot.ctx.manager
        await run("set", bot, OWNER, "activity.max_rooms", "1")
        mgr.connect(auth(1, room="a"), mgr.clock_ms())
        from bamboozled.server.rooms import Refused

        with pytest.raises(Refused):
            mgr.connect(auth(2, room="b"), mgr.clock_ms())
        await run("set", bot, OWNER, "activity.max_rooms", "5")
        mgr.connect(auth(2, room="b"), mgr.clock_ms())  # no restart needed

    async def test_the_kill_switch_closes_rooms(self, bot, tmp_db):
        mgr = bot.ctx.manager
        conn = mgr.connect(auth(1), mgr.clock_ms())
        await run("set", bot, OWNER, "system.killswitch", "on")
        await mgr.pump(mgr.clock_ms())
        assert mgr.rooms == {} and last(conn, "BYE")


# ───────────────────────────── the panel itself ─────────────────────────────


class TestPanel:
    def test_overview_lists_every_category_and_counts_changes(self, bot):
        bot.ctx.settings.set("game.total_rounds", 9)
        emb = overview_embed(bot.ctx.settings)
        assert [f.name for f in emb.fields] == list(CATEGORIES)
        assert f"{CHANGED} 1 changed" in next(f.value for f in emb.fields if f.name == "Gameplay")

    def test_a_changed_setting_is_marked_and_shows_its_default(self, bot):
        bot.ctx.settings.set("game.total_rounds", 9)
        text = category_embed(bot.ctx.settings, "Gameplay", "game.total_rounds").description
        assert "▶ **Rounds (Bamboozled)**: `9` ✱ *(default: 5)*" in text
        assert "**Seconds to answer**: `30`" in text and "Seconds to answer**: `30` ✱" not in text

    async def test_back_returns_to_the_overview_and_clears_the_selection(self, bot):
        view = PanelView(bot.ctx, OWNER)
        await view._on_category(FakeInteraction(bot, user(OWNER), data={"values": ["System"]}))
        assert view.category == "System"
        await view._back(FakeInteraction(bot, user(OWNER)))
        assert view.category is None and view.selected is None

    async def test_only_the_person_who_opened_it_can_use_it(self, bot):
        view = PanelView(bot.ctx, OWNER)
        it = FakeInteraction(bot, user(31337))
        assert not await view.interaction_check(it) and "belongs to someone else" in it.said
        assert await view.interaction_check(FakeInteraction(bot, user(OWNER)))

    async def test_a_bad_edit_in_the_modal_keeps_the_panel_and_explains(self, bot, tmp_db):
        view = PanelView(bot.ctx, OWNER)
        modal = EditModal(view, BY_KEY["game.total_rounds"])
        modal.value._value = "banana"
        it = FakeInteraction(bot, user(OWNER))
        await modal.on_submit(it)
        assert "whole number" in it.said and bot.ctx.settings.get("game.total_rounds") == 5

    async def test_the_buttons_only_offer_what_applies(self, bot):
        view = PanelView(bot.ctx, OWNER)
        await view._on_category(FakeInteraction(bot, user(OWNER), data={"values": ["Features"]}))
        await view._on_setting(FakeInteraction(bot, user(OWNER), data={"values": ["feature.fff"]}))
        buttons = {b.label: b.disabled for b in view.children if hasattr(b, "label") and b.label}
        assert buttons == {"Toggle": False, "Edit…": True, "Reset": True, "Back": False}  # a default bool: nothing to reset


# ───────────────────────────── the other subcommands ─────────────────────────────


class TestOtherCommands:
    async def test_panel_opens_ephemeral_with_the_overview(self, bot):
        it = await run("panel", bot)
        assert it.sent_kwargs()["ephemeral"] is True and "Bamboozled settings" in it.said

    async def test_export_then_import_round_trips_and_is_all_or_nothing(self, bot, tmp_db):
        await run("set", bot, OWNER, "game.total_rounds", "9")
        it = await run("export", bot)
        doc = it.sent_kwargs()["file"].fp.read().decode()
        assert json.loads(doc)["settings"] == {"game.total_rounds": 9}
        await run("reset", bot, OWNER, "game.total_rounds")
        modal = ImportModal(bot.ctx)
        modal.text._value = doc
        mi = FakeInteraction(bot, user(OWNER))
        await modal.on_submit(mi)
        assert "Imported 1" in mi.said and bot.ctx.settings.get("game.total_rounds") == 9
        assert (await store.who_changed("game.total_rounds"))[0] == OWNER
        bad = ImportModal(bot.ctx)
        bad.text._value = json.dumps({"settings": {"game.total_rounds": 7, "game.fff_rounds": 999}})
        bi = FakeInteraction(bot, user(OWNER))
        await bad.on_submit(bi)
        assert "Nothing was changed" in bi.said and bot.ctx.settings.get("game.total_rounds") == 9

    async def test_testing_mode_adds_and_removes_this_server(self, bot, tmp_db):
        it = await run("testing", bot, OWNER, "on")
        assert bot.ctx.settings.get("system.testing_guilds") == [GUILD] and "Testing mode is **on**" in it.said
        await run("testing", bot, OWNER, "on")  # twice is harmless
        assert bot.ctx.settings.get("system.testing_guilds") == [GUILD]
        it = await run("testing", bot, OWNER, "off")
        assert bot.ctx.settings.get("system.testing_guilds") == [] and "**off**" in it.said

    async def test_status_reports_what_is_known(self, bot, tmp_db):
        bot.ctx.authenticator = SimpleNamespace(health={"instance": (1_700_000_000, "ok")})
        mgr = bot.ctx.manager
        mgr.connect(auth(1), mgr.clock_ms())
        emb = status_embed(bot.ctx)
        values = {f.name: f.value for f in emb.fields}
        assert values["Rooms / sockets now"] == "1 / 1"
        assert "ok" in values["Discord instance lookup"] and values["Discord token check"] == "no calls yet"
        wanted = {"Uptime", "Active games", "Database size", "Last backup / replication", "Safety rejections (since start)"}
        assert wanted <= set(values)

    async def test_status_shows_trivia_health_and_rejections(self, bot, tmp_db):
        from bamboozled.services.trivia_source import OfflineQuestions, ScreenedQuestions
        tv = bot.ctx.trivia = ScreenedQuestions(bot.ctx.settings, OfflineQuestions(), http=object())
        tv.health["opentdb"] = (1_700_000_000, "ok")
        tv.rejections.add("opentdb", "History")
        tv.served["offline"] = 2
        values = {f.name: f.value for f in status_embed(bot.ctx).fields}
        assert "opentdb: ok" in values["Trivia sources"] and "offline 2" in values["Trivia sources"]
        assert values["Safety rejections (since start)"] == "opentdb 1"

    async def test_status_works_without_a_game_server_in_the_process(self, bot, tmp_db):
        bot.ctx.manager = None
        assert any("not running" in f.value for f in status_embed(bot.ctx).fields)


class TestRooms:
    async def test_list_close_and_message(self, bot):
        mgr = bot.ctx.manager
        conn = mgr.connect(auth(1, room="roomA"), mgr.clock_ms())
        mgr.connect(auth(2, room="roomA"), mgr.clock_ms())
        assert "roomA" in rooms_embed(bot.ctx).description and "2 playing" in rooms_embed(bot.ctx).description
        view = RoomsView(bot.ctx, OWNER)
        await view._pick(FakeInteraction(bot, user(OWNER), data={"values": ["roomA"]}))
        modal = MessageModal(bot.ctx, "roomA")
        modal.text._value = "Restarting soon"
        mi = FakeInteraction(bot, user(OWNER))
        await modal.on_submit(mi)
        assert "Sent" in mi.said and last(conn, "EVENT")["d"]["payload"]["text"] == "Restarting soon"
        await view._close(FakeInteraction(bot, user(OWNER)))
        assert mgr.rooms == {} and last(conn, "BYE")["d"]["reason"] == "room_closed"
        assert "No rooms" in rooms_embed(bot.ctx).description

    async def test_messaging_a_room_that_closed_in_the_meantime(self, bot):
        modal = MessageModal(bot.ctx, "gone")
        modal.text._value = "hello"
        it = FakeInteraction(bot, user(OWNER))
        await modal.on_submit(it)
        assert "already closed" in it.said

    async def test_only_admins_can_drive_the_rooms_view(self, bot):
        view = RoomsView(bot.ctx, OWNER)
        it = FakeInteraction(bot, user(77))
        assert not await view.interaction_check(it)
        assert await view.interaction_check(FakeInteraction(bot, user(OWNER)))
