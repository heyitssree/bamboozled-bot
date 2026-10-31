import pytest

from bamboozled.config import Config, ConfigError


def test_dev_auth_refuses_to_start_in_prod():
    with pytest.raises(ConfigError, match="prod"):
        Config.from_env({"BAMBOOZLED_DEV_AUTH": "1", "BAMBOOZLED_ENV": "prod"})


def test_dev_auth_refuses_to_start_with_ssm_configuration():
    with pytest.raises(ConfigError, match="SSM"):
        Config.from_env({"BAMBOOZLED_DEV_AUTH": "1", "BAMBOOZLED_ENV": "dev", "BAMBOOZLED_SSM_PREFIX": "/bamboozled/prod"})


def test_dev_auth_only_listens_on_loopback_whatever_was_asked():
    cfg = Config.from_env({"BAMBOOZLED_DEV_AUTH": "1", "BAMBOOZLED_ENV": "dev", "BAMBOOZLED_HOST": "0.0.0.0"})
    assert cfg.dev_auth and cfg.host == "127.0.0.1"


def test_only_the_exact_value_one_turns_dev_auth_on():
    for value in ("true", "yes", "0", "", "2"):
        assert not Config.from_env({"BAMBOOZLED_DEV_AUTH": value, "BAMBOOZLED_ENV": "prod"}).dev_auth


def test_normal_config_is_untouched():
    cfg = Config.from_env({"BAMBOOZLED_ENV": "prod", "DISCORD_APPLICATION_ID": "7", "BAMBOOZLED_PORT": "9000"})
    assert (cfg.env, cfg.app_id, cfg.port, cfg.host, cfg.dev_auth) == ("prod", "7", 9000, "0.0.0.0", False)


async def test_the_app_builder_picks_the_dev_authenticator_only_when_asked(monkeypatch):
    from bamboozled.app import build
    from bamboozled.server.auth import DevAuthenticator, DiscordAuthenticator
    _, _, deps, http = build(Config.from_env({"BAMBOOZLED_DEV_AUTH": "1", "BAMBOOZLED_ENV": "test"}))
    assert isinstance(deps.authenticator, DevAuthenticator)
    await http.aclose()
    _, _, deps, http = build(Config.from_env({"BAMBOOZLED_ENV": "prod", "DISCORD_APPLICATION_ID": "1", "DISCORD_TOKEN": "t"}))
    assert isinstance(deps.authenticator, DiscordAuthenticator)
    await http.aclose()


def test_setting_overrides_for_dev_and_tests():
    cfg = Config.from_env({"BAMBOOZLED_ENV": "test", "BAMBOOZLED_SETTINGS_JSON": '{"activity.reconnect_grace_seconds": 5}'})
    assert cfg.setting_overrides() == {"activity.reconnect_grace_seconds": 5}
    from bamboozled.settings import Settings
    assert Settings(cfg.setting_overrides()).get("activity.reconnect_grace_seconds") == 5


def test_setting_overrides_are_ignored_in_prod_and_bad_json_is_an_error():
    prod = Config.from_env({"BAMBOOZLED_ENV": "prod", "BAMBOOZLED_SETTINGS_JSON": '{"system.killswitch": true}'})
    assert prod.setting_overrides() == {}
    for bad in ("not json", "[1, 2]"):
        with pytest.raises(ConfigError):
            Config.from_env({"BAMBOOZLED_ENV": "dev", "BAMBOOZLED_SETTINGS_JSON": bad}).setting_overrides()
    from bamboozled.settings import Settings
    with pytest.raises(KeyError):
        Settings(Config.from_env({"BAMBOOZLED_ENV": "dev", "BAMBOOZLED_SETTINGS_JSON": '{"no.such.key": 1}'}).setting_overrides())
