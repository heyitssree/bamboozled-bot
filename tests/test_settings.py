"""The settings registry: validation, defaults, export and import, persistence and who-changed-what."""

import json

import pytest

from bamboozled.settings import BY_KEY, CATEGORIES, SETTINGS, SettingError, Settings
from bamboozled.settings import store

ROLE = "123456789012345678"


class TestRegistry:
    def test_every_spec_entry_is_present_with_its_bounds(self):
        keys = {s.key for s in SETTINGS}
        for must in (
            "system.killswitch",
            "system.testing_guilds",
            "system.panel_role",
            "feature.text_mode",
            "feature.post_results",
            "game.total_rounds",
            "activity.max_rooms",
            "activity.reconnect_grace_seconds",
            "trivia.sources",
            "channel.results",
            "privacy.optin_cooldown_days",
            "privacy.block_during_game",
        ):
            assert must in keys
        assert (BY_KEY["game.total_rounds"].min, BY_KEY["game.total_rounds"].max) == (3, 20)
        assert BY_KEY["trivia.sources"].choices == ("opentdb", "tapi", "both", "custom_only")
        assert BY_KEY["system.testing_guilds"].legacy_keys == ("server_settings.test_mode",)
        assert CATEGORIES[0] == "System" and "Privacy" in CATEGORIES

    def test_defaults_are_valid_under_their_own_rules(self):
        s = Settings()
        for spec in SETTINGS:
            assert s.is_default(spec.key)
            s.set(spec.key, spec.default)  # a default must itself pass validation

    def test_the_server_keys_all_exist(self):
        """Every key the game server reads must be declared (an undeclared key would raise at use time)."""
        import pathlib
        import re

        text = (pathlib.Path(__file__).resolve().parents[1] / "bamboozled" / "server" / "rooms.py").read_text()
        for key in set(re.findall(r'settings\.get\(f?"([a-z_.{}]+)"', text)):
            if "{" in key:
                continue
            assert key in BY_KEY, key


class TestValidation:
    @pytest.mark.parametrize(
        "raw,expected", [("on", True), ("Yes", True), ("1", True), ("off", False), ("false", False), (True, True)]
    )
    def test_bool(self, raw, expected):
        assert Settings().set("feature.fff", raw) is expected

    @pytest.mark.parametrize("raw", ["maybe", "", "2"])
    def test_bad_bool(self, raw):
        with pytest.raises(SettingError, match="on or off"):
            Settings().set("feature.fff", raw)

    def test_int_bounds_and_junk(self):
        s = Settings()
        assert s.set("game.total_rounds", "7") == 7
        for bad in ("2", "21", "abc", "7.5", True):
            with pytest.raises(SettingError):
                s.set("game.total_rounds", bad)
        assert s.get("game.total_rounds") == 7  # a refused value changes nothing

    def test_choice_is_case_insensitive_and_closed(self):
        s = Settings()
        assert s.set("trivia.sources", "OpenTDB") == "opentdb"
        with pytest.raises(SettingError, match="choose one of"):
            s.set("trivia.sources", "wikipedia")

    def test_id_lists(self):
        s = Settings()
        assert s.set("system.testing_guilds", f"{ROLE}, 223456789012345678 {ROLE}") == [int(ROLE), 223456789012345678]
        assert s.set("channel.results", [f"<#{ROLE}>"]) == [int(ROLE)]
        assert s.set("system.testing_guilds", "") == []
        for bad in ("12", "abc", "1" * 30):
            with pytest.raises(SettingError):
                s.set("system.testing_guilds", bad)
        with pytest.raises(SettingError, match="at most"):
            s.set("system.testing_guilds", [str(10**17 + i) for i in range(60)])

    def test_role(self):
        s = Settings()
        assert s.set("system.panel_role", f"<@&{ROLE}>") == int(ROLE)
        assert s.set("system.panel_role", "none") is None
        with pytest.raises(SettingError):
            s.set("system.panel_role", "admins")

    def test_unknown_keys_are_errors_not_defaults(self):
        s = Settings()
        with pytest.raises(KeyError):
            s.get("no.such")
        with pytest.raises(KeyError):
            s.set("no.such", 1)
        with pytest.raises(KeyError):
            Settings({"no.such": 1})

    def test_list_defaults_are_not_shared_between_instances(self):
        a, b = Settings(), Settings()
        a.get("system.testing_guilds").append(1)
        assert b.get("system.testing_guilds") == []


class TestResetExportImport:
    def test_reset_and_overrides(self):
        s = Settings()
        s.set("game.total_rounds", 9)
        s.set("feature.text_mode", False)
        assert s.overrides() == {"game.total_rounds": 9, "feature.text_mode": False}
        s.reset("game.total_rounds")
        assert s.is_default("game.total_rounds") and "game.total_rounds" not in s.overrides()

    def test_export_then_import_round_trips(self):
        s = Settings()
        s.set("game.total_rounds", 9)
        s.set("system.testing_guilds", [int(ROLE)])
        doc = s.export_json()
        assert json.loads(doc)["version"] == 1
        t = Settings()
        assert sorted(t.import_json(doc)) == ["game.total_rounds", "system.testing_guilds"]
        assert t.overrides() == s.overrides()

    def test_import_is_all_or_nothing(self):
        s = Settings()
        with pytest.raises(SettingError):
            s.import_json(json.dumps({"settings": {"game.total_rounds": 9, "game.fff_rounds": 999}}))
        assert s.is_default("game.total_rounds")
        for bad in ("not json", "[1]", json.dumps({"settings": {"nope": 1}}), json.dumps({"settings": 5})):
            with pytest.raises(SettingError):
                s.import_json(bad)

    def test_import_accepts_a_bare_object(self):
        s = Settings()
        s.import_json('{"game.total_rounds": 8}')
        assert s.get("game.total_rounds") == 8

    def test_listeners_hear_every_change(self):
        s, heard = Settings(), []
        s.on_change(lambda k, v: heard.append((k, v)))
        s.set("feature.fff", False)
        s.reset("feature.fff")
        assert heard == [("feature.fff", False), ("feature.fff", True)]


class TestPersistence:
    async def test_values_survive_and_record_who_changed_them(self, tmp_db):
        await store.save("game.total_rounds", 9, 4242)
        await store.save("system.testing_guilds", [int(ROLE)], 4242)
        s = Settings()
        assert await store.load(s) == 2
        assert s.get("game.total_rounds") == 9 and s.get("system.testing_guilds") == [int(ROLE)]
        by, at = await store.who_changed("game.total_rounds")
        assert by == 4242 and at
        await store.save("game.total_rounds", 11, 77)  # a later change replaces the author
        assert (await store.who_changed("game.total_rounds"))[0] == 77
        await store.delete("game.total_rounds")
        assert await store.who_changed("game.total_rounds") is None

    async def test_an_unknown_key_in_the_database_stops_start_up(self, tmp_db):
        await store.save("old.thing", 1, None)
        with pytest.raises(SettingError, match="unknown setting"):
            await store.load(Settings())

    async def test_an_invalid_stored_value_stops_start_up(self, tmp_db):
        await store.save("game.total_rounds", 999, None)
        with pytest.raises(SettingError):
            await store.load(Settings())
