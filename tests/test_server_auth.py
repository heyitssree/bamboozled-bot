"""Identity and room membership against a fake Discord (httpx.MockTransport). No sleeping: the retry delay is recorded."""
import httpx
import pytest

from bamboozled.server.auth import (AuthError, DevAuthenticator, DiscordAuthenticator, DiscordUnavailable, TTLCache,
                                    build_cdn_avatar_url, clean_name)

APP = "4242"
BOT = "bot-secret"


class FakeDiscord:
    def __init__(self):
        self.tokens = {"tok-alice": {"id": "111", "username": "alice", "global_name": "Alice A", "avatar": "abc123"}}
        self.instances = {"inst1": {"users": ["111", "222"], "location": {"guild_id": "900", "channel_id": "901"}}}
        self.calls = []
        self.instance_script = None          # optional: list of bodies returned on successive instance calls
        self.rate_limits = 0
        self.fail_network = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.url.path, request.headers.get("authorization")))
        if self.fail_network:
            raise httpx.ConnectError("down")
        if self.rate_limits > 0:
            self.rate_limits -= 1
            return httpx.Response(429, headers={"retry-after": "0.5"})
        if request.url.path.endswith("/users/@me"):
            user = self.tokens.get((request.headers.get("authorization") or "").removeprefix("Bearer "))
            return httpx.Response(200, json=user) if user else httpx.Response(401, json={"message": "401: Unauthorized"})
        if "/activity-instances/" in request.url.path:
            assert request.headers["authorization"] == f"Bot {BOT}"               # the bot token, never the player's
            if self.instance_script is not None:
                body = self.instance_script.pop(0) if len(self.instance_script) > 1 else self.instance_script[0]
                return httpx.Response(200, json=body)
            body = self.instances.get(request.url.path.rsplit("/", 1)[1])
            return httpx.Response(200, json=body) if body else httpx.Response(404, json={"message": "Unknown"})
        return httpx.Response(500)

    def count(self, part):
        return sum(1 for path, _ in self.calls if part in path)


class Env:
    def __init__(self, opted_out=()):
        self.discord = FakeDiscord()
        self.now = 0.0
        self.slept = []
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.discord.handler))

        async def sleep(s):
            self.slept.append(s)
        self.auth = DiscordAuthenticator(APP, BOT, self.http, TTLCache(lambda: self.now), sleep,
                                         is_opted_out=lambda uid: uid in opted_out)


@pytest.fixture
def env():
    return Env()


async def test_valid_user_in_a_real_instance(env):
    r = await env.auth("tok-alice", "inst1")
    assert (r.user_id, r.display_name, r.room_key, r.guild_id, r.channel_id) == (111, "Alice A", "inst1", 900, 901)
    assert r.avatar_url == "https://cdn.discordapp.com/avatars/111/abc123.png?size=128"


async def test_token_discord_rejects(env):
    with pytest.raises(AuthError) as err:
        await env.auth("forged", "inst1")
    assert err.value.close_code == 4401 and err.value.code == "bad_token"
    assert env.discord.count("activity-instances") == 0                        # never reaches the instance lookup


async def test_user_who_is_not_in_the_instance_is_refused_after_three_retries(env):
    env.discord.tokens["tok-eve"] = {"id": "333", "username": "eve"}
    with pytest.raises(AuthError) as err:
        await env.auth("tok-eve", "inst1")
    assert err.value.close_code == 4403 and err.value.code == "not_in_instance"
    assert env.slept == [0.5, 0.5, 0.5] and env.discord.count("activity-instances") == 4


async def test_instance_discord_does_not_know(env):
    with pytest.raises(AuthError) as err:
        await env.auth("tok-alice", "nope")
    assert err.value.close_code == 4404 and err.value.code == "unknown_instance"


async def test_instance_that_lists_the_user_only_after_a_retry(env):
    env.discord.tokens["tok-bob"] = {"id": "444", "username": "bob"}
    loc = {"guild_id": "900", "channel_id": "901"}
    env.discord.instance_script = [{"users": ["111"], "location": loc}, {"users": ["111"], "location": loc},
                                   {"users": ["111", "444"], "location": loc}]
    r = await env.auth("tok-bob", "inst1")
    assert r.user_id == 444 and env.slept == [0.5, 0.5]


async def test_instance_vanishing_during_the_retries(env):
    env.discord.tokens["tok-bob"] = {"id": "444", "username": "bob"}
    env.discord.instance_script = [{"users": ["111"], "location": {"guild_id": "1", "channel_id": "2"}}]
    original = env.discord.handler
    state = {"n": 0}

    def handler(request):
        if "/activity-instances/" in request.url.path:
            state["n"] += 1
            if state["n"] > 1:
                return httpx.Response(404)
        return original(request)
    env.auth.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(AuthError) as err:
        await env.auth("tok-bob", "inst1")
    assert err.value.code == "unknown_instance"


async def test_caches_and_their_expiry(env):
    await env.auth("tok-alice", "inst1")
    await env.auth("tok-alice", "inst1")
    assert env.discord.count("users/@me") == 1 and env.discord.count("activity-instances") == 1
    env.now = 31                                    # the instance entry (30 s) has expired, the token entry (5 min) has not
    await env.auth("tok-alice", "inst1")
    assert env.discord.count("users/@me") == 1 and env.discord.count("activity-instances") == 2
    env.now = 400                                   # now the token entry has expired too
    await env.auth("tok-alice", "inst1")
    assert env.discord.count("users/@me") == 2


async def test_the_cache_never_keeps_the_raw_token(env):
    await env.auth("tok-alice", "inst1")
    assert all("tok-alice" not in repr(k) for k in env.auth.cache._data)


async def test_rate_limit_headers_are_honoured_then_it_works(env):
    env.discord.rate_limits = 1
    r = await env.auth("tok-alice", "inst1")
    assert r.user_id == 111 and env.slept == [0.5]


async def test_persistent_rate_limiting_means_discord_is_unavailable(env):
    env.discord.rate_limits = 10
    with pytest.raises(DiscordUnavailable):
        await env.auth("tok-alice", "inst1")


async def test_network_failure_is_discord_unavailable(env):
    env.discord.fail_network = True
    with pytest.raises(DiscordUnavailable):
        await env.auth("tok-alice", "inst1")


async def test_a_huge_retry_after_is_not_waited_out(env):
    original = env.discord.handler
    env.auth.http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(429, headers={"retry-after": "600"}) if "users" in r.url.path else original(r)))
    with pytest.raises(DiscordUnavailable):
        await env.auth("tok-alice", "inst1")
    assert env.slept == []


async def test_opted_out_user_is_refused_with_a_clear_message():
    env = Env(opted_out={111})
    with pytest.raises(AuthError) as err:
        await env.auth("tok-alice", "inst1")
    assert err.value.code == "opted_out" and err.value.close_code == 4403 and "opt_in" in err.value.message


async def test_instance_without_a_server_channel_is_refused(env):
    env.discord.instances["dm"] = {"users": ["111"], "location": {"channel_id": "5"}}
    with pytest.raises(AuthError) as err:
        await env.auth("tok-alice", "dm")
    assert err.value.code == "no_location"


async def test_garbage_user_object_is_refused(env):
    env.discord.tokens["weird"] = {"id": "not-a-number"}
    with pytest.raises(AuthError):
        await env.auth("weird", "inst1")


def test_avatar_urls():
    assert build_cdn_avatar_url(111, "a_77").endswith("/avatars/111/a_77.gif?size=128")
    assert build_cdn_avatar_url(111, None).startswith("https://cdn.discordapp.com/embed/avatars/")
    up = ".."
    assert build_cdn_avatar_url(111, f"{up}/{up}/evil").startswith("https://cdn.discordapp.com/embed/avatars/")   # no path tricks


def test_names_are_cleaned_and_bounded():
    assert clean_name({"username": "x" * 80}) == "x" * 32
    assert clean_name({"global_name": "Al​i\x00ce\n", "username": "u"}) == "Alice"
    assert clean_name({"global_name": "​​", "username": ""}) == "Player"


async def test_dev_authenticator_parses_dev_tokens_only():
    dev = DevAuthenticator(is_opted_out=lambda uid: uid == 9)
    r = await dev("dev:5:Zed", "test1")
    assert (r.user_id, r.display_name, r.room_key, r.guild_id) == (5, "Zed", "test1", 1)
    for bad in ("tok", "dev:x:y", "dev:5", "prod:5:a"):
        with pytest.raises(AuthError):
            await dev(bad, "test1")
    with pytest.raises(AuthError) as err:
        await dev("dev:9:Opt", "test1")
    assert err.value.code == "opted_out"


def test_ttl_cache_evicts_oldest_when_full():
    c = TTLCache(lambda: 0, max_items=2)
    c.set("a", 1, 10), c.set("b", 2, 10), c.set("c", 3, 10)
    assert c.get("a") is None and c.get("c") == 3
    c.clear()
    assert c.get("c") is None
