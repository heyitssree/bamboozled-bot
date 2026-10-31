"""Display names for the REST API: resolved at request time through a 24-hour in-memory cache, never stored."""
from __future__ import annotations

import time
from typing import Awaitable, Callable

TTL_S = 24 * 3600


class NameCache:
    def __init__(self, fetch: Callable[[int], Awaitable[str]], clock: Callable[[], float] = time.monotonic,
                 max_items: int = 20_000):
        self._fetch, self._clock, self._max = fetch, clock, max_items
        self._data: dict[int, tuple[float, str]] = {}

    async def get(self, user_id: int) -> str:
        hit = self._data.get(user_id)
        if hit and self._clock() < hit[0]:
            return hit[1]
        try:
            name = await self._fetch(user_id) or "Unknown player"
        except Exception:
            name = "Unknown player"
        if len(self._data) >= self._max:
            self._data.pop(next(iter(self._data)))
        self._data[user_id] = (self._clock() + TTL_S, name)
        return name

    def forget(self, user_id: int) -> None:
        self._data.pop(user_id, None)
