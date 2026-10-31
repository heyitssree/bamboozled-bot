"""Runtime settings with defaults. The server reads them at use time, so a change applies to the next room at once.

Phase 5 replaces this with the full registry (labels, bounds, admin panel); the keys and defaults here are the ones it
will declare, so callers do not change.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

DEFAULTS: dict[str, Any] = {
    "system.killswitch": False,
    "feature.bamboozled": True, "feature.fff": True, "feature.survival": True, "feature.post_results": True,
    "game.total_rounds": 5, "game.question_timeout_seconds": 30, "game.fff_rounds": 10,
    "activity.max_rooms": 20, "activity.max_players": 10, "activity.allow_spectators": True,
    "activity.lobby_ttl_minutes": 15, "activity.idle_ttl_minutes": 30, "activity.reconnect_grace_seconds": 30,
    "activity.require_proxy_signature": False,
    "trivia.sources": "both", "trivia.safety_strictness": "standard",
}


class Settings:
    def __init__(self, overrides: Optional[Mapping[str, Any]] = None):
        self._values = dict(DEFAULTS)
        if overrides:
            self.update(overrides)

    def get(self, key: str) -> Any:
        return self._values[key]                  # an unknown key is a bug, not a default

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        self._values[key] = value

    def update(self, values: Mapping[str, Any]) -> None:
        for k, v in values.items():
            self.set(k, v)
