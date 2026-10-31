"""ONE process: migrate -> settings -> server task -> bot. `python -m bamboozled`."""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Optional

import httpx
import uvicorn

from .config import Config
from .db.connection import db_path
from .db.migrate import migrate_async
from .server.auth import DevAuthenticator, DiscordAuthenticator
from .server.http import WS_MAX_MESSAGE, Deps, create_app
from .server.names import NameCache
from .server.results import db_recorder
from .server.rooms import RoomManager
from .services.trivia_source import OfflineQuestions
from .settings import Settings

log = logging.getLogger("bamboozled.app")


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


async def _dev_banner() -> None:
    while True:
        log.warning("DEV AUTH IS ON: anyone who can reach this port can sign in as any user. Never use in production.")
        await asyncio.sleep(60)


def build(cfg: Config, settings: Optional[Settings] = None, bot=None):
    """Assemble the pieces. Returns (app, manager, deps, http_client)."""
    settings = settings or Settings()
    http = httpx.AsyncClient(timeout=10.0)
    authenticator = DevAuthenticator() if cfg.dev_auth else DiscordAuthenticator(cfg.app_id, cfg.bot_token, http)

    async def fetch_name(user_id: int) -> str:
        if bot is None:
            return "Unknown player"
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        return user.display_name

    manager = RoomManager(settings, monotonic_ms, OfflineQuestions(), recorder=db_recorder)
    deps = Deps(cfg=cfg, manager=manager, authenticator=authenticator, settings=settings, clock_ms=monotonic_ms,
                http=http, names=NameCache(fetch_name))
    return create_app(deps), manager, deps, http


async def run(cfg: Optional[Config] = None) -> None:
    cfg = cfg or Config.from_env()
    version = await migrate_async(db_path())
    log.info("Database ready (schema version %d).", version)
    bot = None
    if cfg.bot_token and not cfg.dev_auth:
        from bot import BamboozledBot
        bot = BamboozledBot()
    app, manager, deps, http = build(cfg, bot=bot)
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, ws_max_size=WS_MAX_MESSAGE,
                                           log_level="warning", server_header=False, date_header=False))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    tasks = [asyncio.create_task(server.serve())]
    if cfg.dev_auth:
        tasks.append(asyncio.create_task(_dev_banner()))
    if bot is not None:
        tasks.append(asyncio.create_task(bot.start(cfg.bot_token)))
    log.info("Bamboozled listening on %s:%d (env=%s)", cfg.host, cfg.port, cfg.env)
    await stop.wait()
    log.info("Shutting down: telling players to reconnect.")
    manager.shutdown()
    await asyncio.sleep(0.2)                                  # let the BYE frames out
    server.should_exit = True
    if bot is not None:
        await bot.close()
    for t in tasks[1:]:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await http.aclose()


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(run())
