"""Identity and room membership come from Discord, never from the browser.

1. `GET /users/@me` with the player's OAuth access token says who they are (scope `identify` is enough).
2. `GET /applications/<app>/activity-instances/<instance>` with the BOT token says who is really inside that Activity
   instance and which guild and channel it belongs to (404 = no such instance).

Nothing about a player (name, avatar, guild, channel) is ever taken from a client message.
Verify the exact response shapes against Discord's current Activity documentation (spec section 8.1).
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import httpx

DISCORD_API = "https://discord.com/api/v10"
TOKEN_TTL_S = 300
INSTANCE_TTL_S = 30
RETRIES, RETRY_DELAY_S = 3, 0.5
MAX_RATE_LIMIT_WAIT_S = 5.0


class AuthError(Exception):
    """Authentication failed. `close_code` is the WebSocket close code to use."""

    def __init__(self, code: str, message: str, close_code: int = 4401):
        super().__init__(code)
        self.code, self.message, self.close_code = code, message, close_code


class DiscordUnavailable(Exception):
    """Discord could not be reached or kept rate-limiting us."""


@dataclass(frozen=True)
class AuthResult:
    user_id: int
    display_name: str
    avatar_url: str
    room_key: str                 # the Discord activity instance id
    guild_id: int
    channel_id: int


class TTLCache:
    """Small in-memory cache; the clock is injectable."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_items: int = 5000):
        self._clock, self._max = clock, max_items
        self._data: dict[Any, tuple[float, Any]] = {}

    def get(self, key):
        hit = self._data.get(key)
        if hit is None:
            return None
        if self._clock() >= hit[0]:
            del self._data[key]
            return None
        return hit[1]

    def set(self, key, value, ttl: float) -> None:
        if len(self._data) >= self._max:
            self._data.pop(next(iter(self._data)))
        self._data[key] = (self._clock() + ttl, value)

    def clear(self) -> None:
        self._data.clear()


_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏  ⁠﻿]")


def clean_name(user: dict) -> str:
    name = _CONTROL.sub("", user.get("global_name") or user.get("username") or "Player").strip()
    return (name or "Player")[:32]


def build_cdn_avatar_url(user_id: str | int, avatar_hash: Optional[str]) -> str:
    if avatar_hash and re.fullmatch(r"(a_)?[0-9a-f]{1,64}", avatar_hash):
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{int(user_id)}/{avatar_hash}.{ext}?size=128"
    return f"https://cdn.discordapp.com/embed/avatars/{(int(user_id) >> 22) % 6}.png"


class DiscordAuthenticator:
    """Verifies an access token and that its owner is inside the claimed activity instance."""

    def __init__(self, app_id: str, bot_token: str, http: httpx.AsyncClient, cache: Optional[TTLCache] = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 is_opted_out: Optional[Callable[[int], bool]] = None):
        self.app_id, self.bot_token, self.http = app_id, bot_token, http
        self.cache = cache or TTLCache()
        self.sleep = sleep
        self.health: dict[str, tuple[float, str]] = {}          # last token check and last instance lookup: (when, result)
        self.is_opted_out = is_opted_out or (lambda _uid: False)

    async def _get(self, url: str, headers: dict) -> httpx.Response:
        """GET honouring Discord's rate-limit headers once; a persistent 429 means Discord is unavailable to us."""
        for attempt in range(2):
            try:
                resp = await self.http.get(url, headers=headers)
            except httpx.HTTPError as exc:
                raise DiscordUnavailable(type(exc).__name__) from None
            if resp.status_code != 429:
                return resp
            wait = _retry_after(resp)
            if attempt == 1 or wait > MAX_RATE_LIMIT_WAIT_S:
                raise DiscordUnavailable("rate limited")
            await self.sleep(wait)
        raise DiscordUnavailable("rate limited")                     # pragma: no cover

    async def _user(self, access_token: str) -> dict:
        key = ("tok", hashlib.sha256(access_token.encode()).hexdigest())
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        try:
            resp = await self._get(f"{DISCORD_API}/users/@me", {"Authorization": f"Bearer {access_token}"})
        except DiscordUnavailable as exc:
            self.health["token"] = (time.time(), f"unavailable ({exc})")
            raise
        self.health["token"] = (time.time(), "ok" if resp.status_code in (200, 401) else f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise AuthError("bad_token", "Discord did not accept your sign-in. Reopen the Activity and try again.")
        user = resp.json()
        if not isinstance(user, dict) or not str(user.get("id", "")).isdigit():
            raise AuthError("bad_token", "Discord returned an unexpected sign-in response.")
        self.cache.set(key, user, TOKEN_TTL_S)
        return user

    async def _instance(self, instance_id: str, fresh: bool = False) -> Optional[dict]:
        key = ("inst", instance_id)
        if not fresh:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        try:
            resp = await self._get(f"{DISCORD_API}/applications/{self.app_id}/activity-instances/{instance_id}",
                                   {"Authorization": f"Bot {self.bot_token}"})
        except DiscordUnavailable as exc:
            self.health["instance"] = (time.time(), f"unavailable ({exc})")
            raise
        self.health["instance"] = (time.time(), "ok" if resp.status_code in (200, 404) else f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            return None
        body = resp.json()
        self.cache.set(key, body, INSTANCE_TTL_S)
        return body

    async def __call__(self, access_token: str, instance_id: str, *, allow_opted_out: bool = False) -> AuthResult:
        user = await self._user(access_token)
        uid = int(user["id"])
        body = await self._instance(instance_id)
        if body is None:
            raise AuthError("unknown_instance", "This Activity session no longer exists.", 4404)
        # the first client can arrive before Discord lists it: look again a few times, ignoring the cache
        for attempt in range(RETRIES + 1):
            if str(uid) in [str(u) for u in body.get("users", [])]:
                break
            if attempt == RETRIES:
                raise AuthError("not_in_instance", "You are not part of this Activity session.", 4403)
            await self.sleep(RETRY_DELAY_S)
            body = await self._instance(instance_id, fresh=True)
            if body is None:
                raise AuthError("unknown_instance", "This Activity session no longer exists.", 4404)
        if self.is_opted_out(uid) and not allow_opted_out:
            raise AuthError("opted_out", "You have opted out of Bamboozled. Use /privacy opt_in to play again.", 4403)
        loc = body.get("location") or {}
        try:
            guild_id, channel_id = int(loc["guild_id"]), int(loc["channel_id"])
        except (KeyError, TypeError, ValueError):
            raise AuthError("no_location", "Bamboozled needs a server channel to run in.", 4403) from None
        return AuthResult(user_id=uid, display_name=clean_name(user),
                          avatar_url=build_cdn_avatar_url(uid, user.get("avatar")),
                          room_key=instance_id, guild_id=guild_id, channel_id=channel_id)


def _retry_after(resp: httpx.Response) -> float:
    for header in ("retry-after", "x-ratelimit-reset-after"):
        try:
            return max(0.0, float(resp.headers[header]))
        except (KeyError, ValueError):
            continue
    return 1.0


class DevAuthenticator:
    """Local play and tests without Discord. Tokens look like `dev:<user_id>:<name>`.

    Only constructed when Config.dev_auth is on, which refuses to start in prod or with SSM configuration and only
    listens on loopback. The instance lookup is built in: any instance id works, in guild 1 / channel 1.
    """

    def __init__(self, is_opted_out: Optional[Callable[[int], bool]] = None):
        self.is_opted_out = is_opted_out or (lambda _uid: False)

    async def __call__(self, access_token: str, instance_id: str, *, allow_opted_out: bool = False) -> AuthResult:
        parts = access_token.split(":", 2)
        if len(parts) != 3 or parts[0] != "dev" or not parts[1].isdigit():
            raise AuthError("bad_token", "Not a dev token (expected dev:<user_id>:<name>).")
        uid = int(parts[1])
        if self.is_opted_out(uid) and not allow_opted_out:
            raise AuthError("opted_out", "You have opted out of Bamboozled. Use /privacy opt_in to play again.", 4403)
        return AuthResult(user_id=uid, display_name=clean_name({"username": parts[2]}),
                          avatar_url=build_cdn_avatar_url(uid, None), room_key=instance_id, guild_id=1, channel_id=1)
