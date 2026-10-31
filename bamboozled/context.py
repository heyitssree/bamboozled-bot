"""What the bot commands and the game server share, because they run in one process: settings, the privacy service,
the room manager, the bot. Built once at start-up."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .config import Config
from .db.connection import db_path
from .db.migrate import migrate_async
from .server.names import NameCache
from .services.privacy import PrivacyService
from .settings import Settings
from .settings import store as settings_store

log = logging.getLogger("bamboozled.context")


@dataclass
class Context:
    cfg: Config
    settings: Settings
    privacy: PrivacyService
    started_at: float = field(default_factory=time.time)
    manager: Any = None  # server.rooms.RoomManager (None when the bot runs without the game server)
    authenticator: Any = None  # for the Discord health lines in the admin status
    names: Optional[NameCache] = None
    bot: Any = None
    ready: bool = False
    on_setting_changed: list[Callable[[str, Any], Any]] = field(default_factory=list)

    @classmethod
    def create(cls, cfg: Optional[Config] = None, settings: Optional[Settings] = None) -> "Context":
        cfg = cfg or Config.from_env()
        settings = settings or Settings()
        return cls(cfg=cfg, settings=settings, privacy=PrivacyService(settings, forget_name=_forgetter()))

    async def init(self) -> None:
        """Migrate the database, load stored settings (then dev/test overrides), load who has opted out. Idempotent."""
        if self.ready:
            return
        version = await migrate_async(db_path())
        stored = await settings_store.load(self.settings)
        self.settings.update(self.cfg.setting_overrides())
        opted_out = await self.privacy.load()
        log.info("Database ready (schema %d), %d stored setting(s), %d opted-out user(s).", version, stored, opted_out)
        self.ready = True

    # ───────────── changing settings (the one place that records who did it) ─────────────
    async def apply_setting(self, key: str, raw: Any, user_id: Optional[int]) -> Any:
        old = self.settings.get(key)
        value = self.settings.set(key, raw)
        await settings_store.save(key, value, user_id)
        log.info("setting %s changed %r -> %r by %s", key, old, value, user_id)
        for hook in self.on_setting_changed:
            result = hook(key, value)
            if hasattr(result, "__await__"):
                await result
        return value

    async def reset_setting(self, key: str, user_id: Optional[int]) -> Any:
        value = self.settings.reset(key)
        await settings_store.delete(key)
        log.info("setting %s reset to %r by %s", key, value, user_id)
        for hook in self.on_setting_changed:
            result = hook(key, value)
            if hasattr(result, "__await__"):
                await result
        return value

    async def import_settings(self, text: str, user_id: Optional[int]) -> list[str]:
        keys = self.settings.import_json(text)
        for key in keys:
            await settings_store.save(key, self.settings.get(key), user_id)
            for hook in self.on_setting_changed:
                result = hook(key, self.settings.get(key))
                if hasattr(result, "__await__"):
                    await result
        log.info("%d setting(s) imported by %s", len(keys), user_id)
        return keys

    def uptime_s(self) -> int:
        return int(time.time() - self.started_at)


def _forgetter():
    from .services.names import forget

    return forget
