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
from .context import Context
from .services import heartbeat
from .server.auth import DevAuthenticator, DiscordAuthenticator
from .server.http import WS_MAX_MESSAGE, Deps, create_app
from .server.names import NameCache
from .server.results import db_recorder
from .server.rooms import RoomManager
from .services.names import forget as forget_display_name
from .services.results_card import post_result_card
from .services.trivia_source import OfflineQuestions, ScreenedQuestions
from .settings import Settings
from .ssm_config import load_ssm_into_environ

log = logging.getLogger("bamboozled.app")


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


async def _dev_banner() -> None:
    while True:
        log.warning("DEV AUTH IS ON: anyone who can reach this port can sign in as any user. Never use in production.")
        await asyncio.sleep(60)


def build(cfg: Config, ctx: Optional[Context] = None, bot=None):
    """Assemble the pieces around one shared Context. Returns (app, manager, deps, http_client)."""
    ctx = ctx or Context.create(cfg, Settings(cfg.setting_overrides()))
    http = httpx.AsyncClient(timeout=10.0)
    optout = ctx.privacy.is_opted_out
    if cfg.dev_auth:
        authenticator = DevAuthenticator(is_opted_out=optout)
    else:
        authenticator = DiscordAuthenticator(cfg.app_id, cfg.bot_token, http, is_opted_out=optout)

    async def fetch_name(user_id: int) -> str:
        if bot is None:
            return "Unknown player"
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        return user.display_name

    async def card(room, rows):
        await post_result_card(ctx, room, rows)

    ctx.trivia = ScreenedQuestions(ctx.settings, OfflineQuestions(), http)
    manager = RoomManager(
        ctx.settings, monotonic_ms, ctx.trivia, recorder=db_recorder, on_game_over=card, is_opted_out=optout
    )
    names = NameCache(fetch_name)
    ctx.manager, ctx.authenticator, ctx.names = manager, authenticator, names
    ctx.privacy.in_running_game = manager.in_running_game
    ctx.privacy.evict = manager.evict_user
    ctx.privacy.forget_name = lambda uid: (forget_display_name(uid), names.forget(uid))
    deps = Deps(cfg=cfg, manager=manager, authenticator=authenticator, settings=ctx.settings, clock_ms=monotonic_ms,
                http=http, names=names, privacy=ctx.privacy)
    return create_app(deps), manager, deps, http


async def run(cfg: Optional[Config] = None) -> None:
    cfg = cfg or Config.from_env()
    ctx = Context.create(cfg)
    await ctx.init()
    bot = None
    if cfg.bot_token and not cfg.dev_auth:
        from .bot.client import BamboozledBot
        bot = BamboozledBot(ctx)
    app, manager, deps, http = build(cfg, ctx, bot)
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
    if cfg.env == "prod" and heartbeat.enabled():
        tasks.append(asyncio.create_task(heartbeat.run_heartbeat(cfg.env)))
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
    load_ssm_into_environ()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(run())
