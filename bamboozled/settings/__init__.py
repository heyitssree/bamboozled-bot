"""Runtime settings, backed by the registry. Values are read at use time, so a change applies to the next room at once."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Optional

from .registry import BY_KEY, CATEGORIES, SETTINGS, Setting

__all__ = ["Settings", "SettingError", "SETTINGS", "BY_KEY", "CATEGORIES", "Setting"]

_TRUE = {"true", "on", "yes", "1", "enabled"}
_FALSE = {"false", "off", "no", "0", "disabled"}
MAX_IDS = 50


class SettingError(ValueError):
    """A value the registry will not accept. The message is written for the person who typed it."""


def coerce(spec: Setting, raw: Any) -> Any:
    """Turn what a person typed (or JSON stored) into a valid value, or explain what is wrong."""
    k = spec.kind
    if k == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise SettingError(f"{spec.label}: use on or off.")
    if k == "int":
        if isinstance(raw, bool):
            raise SettingError(f"{spec.label}: use a whole number.")
        try:
            value = int(str(raw).strip()) if not isinstance(raw, int) else raw
        except ValueError:
            raise SettingError(f"{spec.label}: '{raw}' is not a whole number.") from None
        if (spec.min is not None and value < spec.min) or (spec.max is not None and value > spec.max):
            raise SettingError(f"{spec.label}: use a number from {spec.min} to {spec.max}.")
        return value
    if k == "choice":
        text = str(raw).strip().lower()
        if text not in spec.choices:
            raise SettingError(f"{spec.label}: choose one of {', '.join(spec.choices)}.")
        return text
    if k == "role":
        if raw is None or str(raw).strip().lower() in ("", "none", "off", "0"):
            return None
        text = str(raw).strip().strip("<@&>")
        if not text.isdigit() or not 17 <= len(text) <= 20:
            raise SettingError(f"{spec.label}: give a role id (a long number) or 'none'.")
        return int(text)
    if k == "id_list":
        items = raw if isinstance(raw, list) else [p for p in str(raw).replace(",", " ").split() if p]
        out: list[int] = []
        for item in items:
            text = str(item).strip().strip("<#@&>")
            if not text.isdigit() or not 17 <= len(text) <= 20:
                raise SettingError(f"{spec.label}: '{item}' is not an id (a long number).")
            if int(text) not in out:
                out.append(int(text))
        if len(out) > MAX_IDS:
            raise SettingError(f"{spec.label}: at most {MAX_IDS} ids.")
        return out
    raise AssertionError(k)  # pragma: no cover


class Settings:
    def __init__(self, overrides: Optional[Mapping[str, Any]] = None):
        self._values: dict[str, Any] = {s.key: _copy(s.default) for s in SETTINGS}
        self._listeners: list[Callable[[str, Any], None]] = []
        if overrides:
            self.update(overrides)

    # ───────────── reading ─────────────
    def get(self, key: str) -> Any:
        return self._values[key]  # an unknown key is a bug, not a default

    def is_default(self, key: str) -> bool:
        return self._values[key] == BY_KEY[key].default

    def overrides(self) -> dict[str, Any]:
        """Only the settings that differ from their defaults (what is stored and exported)."""
        return {s.key: _copy(self._values[s.key]) for s in SETTINGS if not self.is_default(s.key)}

    # ───────────── writing ─────────────
    def spec(self, key: str) -> Setting:
        try:
            return BY_KEY[key]
        except KeyError:
            raise KeyError(f"unknown setting: {key}") from None

    def set(self, key: str, value: Any) -> Any:
        """Validate and apply. Returns the stored value. Raises KeyError for unknown keys, SettingError for bad values."""
        spec = self.spec(key)
        value = coerce(spec, value)
        self._values[key] = value
        for listener in self._listeners:
            listener(key, value)
        return value

    def reset(self, key: str) -> Any:
        return self.set(key, _copy(self.spec(key).default))

    def update(self, values: Mapping[str, Any]) -> None:
        """All-or-nothing: nothing is applied if any key or value is invalid."""
        staged = {}
        for key, raw in values.items():
            staged[key] = coerce(self.spec(key), raw)
        for key, value in staged.items():
            self.set(key, value)

    def on_change(self, listener: Callable[[str, Any], None]) -> None:
        self._listeners.append(listener)

    # ───────────── export / import ─────────────
    def export_json(self) -> str:
        return json.dumps({"version": 1, "settings": self.overrides()}, indent=2, sort_keys=True)

    def import_json(self, text: str) -> list[str]:
        """Apply an exported file. Returns the keys that were set. Nothing changes if anything is wrong."""
        try:
            doc = json.loads(text)
        except ValueError:
            raise SettingError("That is not valid JSON.") from None
        values = doc.get("settings") if isinstance(doc, dict) and "settings" in doc else doc
        if not isinstance(values, dict):
            raise SettingError("Expected a JSON object of settings.")
        unknown = [k for k in values if k not in BY_KEY]
        if unknown:
            raise SettingError(f"Unknown setting(s): {', '.join(unknown[:5])}.")
        self.update(values)
        return list(values)


def _copy(value: Any) -> Any:
    return list(value) if isinstance(value, list) else value
