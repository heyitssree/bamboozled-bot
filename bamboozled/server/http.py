"""The HTTP side of the single process: REST, the WebSocket endpoint and the built web app.

Everything is same-origin through Discord's proxy mapping, so there is no CORS. Required headers on every response:
X-Content-Type-Options and Referrer-Policy; never X-Frame-Options or a frame-ancestors rule (Discord embeds us).
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..config import Config
from ..db.repos import stats as stats_repo
from ..settings import Settings
from .auth import DISCORD_API, AuthError, DiscordUnavailable
from ..services.privacy import PrivacyService
from .names import NameCache
from .protocol import FrameError, parse_frame
from .proxy_sig import verify as verify_proxy_signature
from .ratelimit import KeyedLimiter
from .rooms import Refused, RoomManager

log = logging.getLogger("bamboozled.server")
AUTH_TIMEOUT_S = 5.0
MAX_PENDING_AUTH = 200
MAX_BODY_BYTES = 64 * 1024
WS_MAX_MESSAGE = 64 * 1024            # transport limit; the app enforces the real 4 KB limit and keeps the socket


@dataclass
class Deps:
    cfg: Config
    manager: RoomManager
    authenticator: Callable[[str, str], Awaitable]
    settings: Settings
    clock_ms: Callable[[], int]
    http: Optional[httpx.AsyncClient] = None
    names: Optional[NameCache] = None
    privacy: Optional[PrivacyService] = None
    pending_auth: int = 0
    tick_s: float = 0.25                     # how often rooms are advanced; 0 = the caller drives the clock
    ip_limiter: KeyedLimiter = field(default=None)       # type: ignore[assignment]
    code_limiter: KeyedLimiter = field(default=None)     # type: ignore[assignment]

    def __post_init__(self):
        self.ip_limiter = self.ip_limiter or KeyedLimiter(20 / 60, 20, self.clock_ms)        # 20 exchanges a minute
        self.code_limiter = self.code_limiter or KeyedLimiter(3 / 60, 3, self.clock_ms)       # 3 tries per code a minute


class Guard:
    """ASGI middleware: origin-verify header, request size limit, security headers."""

    def __init__(self, app, deps: Deps):
        self.app, self.deps = app, deps

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        secret = self.deps.cfg.origin_verify
        if secret:
            given = dict(scope["headers"]).get(b"x-origin-verify", b"").decode("latin-1")
            if not hmac.compare_digest(given, secret):
                return await self._reject(scope, receive, send, 403)
        if scope["type"] == "websocket":
            return await self.app(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return await self._reject(scope, receive, send, 413)
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > MAX_BODY_BYTES:
                    raise _TooLarge()
            return message

        async def add_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in
                           (b"x-frame-options", b"x-content-type-options", b"referrer-policy")]
                headers += [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, limited_receive, add_headers)
        except _TooLarge:
            await self._reject(scope, receive, send, 413)

    @staticmethod
    async def _reject(scope, receive, send, status: int):
        if scope["type"] == "websocket":
            await receive()                                    # the connect event, then refuse the handshake
            await send({"type": "websocket.close", "code": 4403})
            return
        body = b'{"error":"forbidden"}' if status == 403 else b'{"error":"too_large"}'
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"x-content-type-options", b"nosniff"),
                                (b"referrer-policy", b"no-referrer")]})
        await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass


class TokenRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)


async def _tick(deps: Deps) -> None:
    while True:
        try:
            await deps.manager.pump(deps.clock_ms())
        except Exception:                                    # one bad tick must not stop the clock
            log.exception("room pump failed")
        await asyncio.sleep(deps.tick_s)


def create_app(deps: Deps) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        ticker = asyncio.create_task(_tick(deps)) if deps.tick_s else None
        yield
        if ticker is not None:
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)

    app = FastAPI(title="Bamboozled", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    # ───────────────────────────── REST ─────────────────────────────

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}                                      # liveness only: no counts, no versions

    @app.post("/api/oauth/token")
    async def oauth_token(body: TokenRequest, request: Request):
        ip = request.client.host if request.client else "unknown"
        if not deps.ip_limiter.allow(ip) or not deps.code_limiter.allow(body.code[:64]):
            return JSONResponse({"error": "rate_limited"}, status_code=429)
        if deps.http is None or not deps.cfg.client_secret:
            return JSONResponse({"error": "not_configured"}, status_code=503)
        try:
            resp = await deps.http.post(f"{DISCORD_API}/oauth2/token", data={
                "client_id": deps.cfg.app_id, "client_secret": deps.cfg.client_secret,
                "grant_type": "authorization_code", "code": body.code})
        except httpx.HTTPError:
            return JSONResponse({"error": "discord_unavailable"}, status_code=502)
        if resp.status_code != 200 or "access_token" not in resp.json():
            return JSONResponse({"error": "bad_code"}, status_code=400)
        return {"access_token": resp.json()["access_token"]}          # nothing else from Discord's answer is passed on

    async def authed(request: Request, allow_opted_out: bool = False):
        token = request.headers.get("authorization", "")
        instance = request.headers.get("x-instance-id", "")
        if not token.startswith("Bearer ") or not instance:
            raise AuthError("no_credentials", "Sign in first.")
        if deps.settings.get("activity.require_proxy_signature"):
            if not verify_proxy_signature(deps.cfg.public_key, request.headers.get("x-signature-ed25519", ""),
                                          request.headers.get("x-signature-timestamp", ""),
                                          request.headers.get("x-discord-proxy-payload", "").encode()):
                raise AuthError("bad_signature", "Request was not signed by Discord.", 4403)
        return await deps.authenticator(token[7:], instance, allow_opted_out=allow_opted_out)

    @app.exception_handler(AuthError)
    async def auth_error(_request, err: AuthError):
        return JSONResponse({"error": err.code, "message": err.message}, status_code=401 if err.close_code == 4401 else 403)

    @app.exception_handler(DiscordUnavailable)
    async def discord_down(_request, _err):
        return JSONResponse({"error": "discord_unavailable"}, status_code=503)

    @app.get("/api/me/stats")
    async def my_stats(request: Request, mode: str = "bamboozled"):
        if mode not in ("bamboozled", "fff", "survival"):
            return JSONResponse({"error": "bad_mode"}, status_code=400)
        auth = await authed(request)
        row = await stats_repo.player_stats(auth.user_id, mode)
        return row or {"user_id": auth.user_id, "mode": mode, "games": 0, "wins": 0, "best_score": 0, "total_score": 0,
                       "best_streak": 0}

    @app.get("/api/leaderboard")
    async def leaderboard(request: Request, mode: str = "bamboozled", scope: str = "server"):
        boards = {"bamboozled": stats_repo.bamboozled_board, "fff": stats_repo.fff_board,
                  "survival": stats_repo.survival_board}
        if mode not in boards or scope not in ("server", "global"):
            return JSONResponse({"error": "bad_request"}, status_code=400)
        auth = await authed(request)
        rows = await boards[mode](auth.guild_id if scope == "server" else None, 50)
        for r in rows:
            r["name"] = await deps.names.get(r["user_id"]) if deps.names else "Unknown player"
        return {"mode": mode, "scope": scope, "rows": rows}

    # ───────────────────────────── WebSocket ─────────────────────────────

    @app.websocket("/api/ws")
    async def socket(ws: WebSocket):
        await ws.accept()
        if deps.pending_auth >= MAX_PENDING_AUTH:
            return await _bye(ws, 1013, "busy")
        deps.pending_auth += 1
        try:
            conn = await _authenticate(ws, deps)
        finally:
            deps.pending_auth -= 1
        if conn is None:
            return
        wake = asyncio.Event()
        conn.notify = wake.set
        if conn.outbox:
            wake.set()                                                  # the lobby state queued while connecting
        writer = asyncio.create_task(_write_loop(ws, conn, wake))
        try:
            while not conn.closed:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                data = message.get("text") if message.get("text") is not None else message.get("bytes")
                if data is not None:
                    deps.manager.handle_text(conn, data, deps.clock_ms())
        except Exception:                                               # a broken transport ends this socket only
            pass
        finally:
            deps.manager.disconnect(conn, deps.clock_ms())
            wake.set()
            await asyncio.gather(writer, return_exceptions=True)

    @app.post("/api/privacy/opt_out")
    async def privacy_opt_out(request: Request):
        auth = await authed(request)
        if deps.privacy is None:
            return JSONResponse({"error": "not_configured"}, status_code=503)
        result = await deps.privacy.opt_out(auth.user_id)
        if result.outcome == "in_game":
            return JSONResponse({"error": "in_game", "message": "Finish or leave your running game first."}, status_code=409)
        return {"status": "out", "purged": result.purged}

    @app.post("/api/privacy/opt_in")
    async def privacy_opt_in(request: Request):
        auth = await authed(request, allow_opted_out=True)          # an opted-out user can still prove who they are
        if deps.privacy is None:
            return JSONResponse({"error": "not_configured"}, status_code=503)
        result = await deps.privacy.opt_in(auth.user_id)
        if result.outcome == "cooldown":
            return JSONResponse({"error": "cooldown", "retry_at": result.retry_at,
                                 "message": "You can opt back in a little later."}, status_code=429)
        return {"status": "in"}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def no_such_api(rest: str):
        return JSONResponse({"error": "not_found"}, status_code=404)   # any method: clients can tell "absent" from "refused"

    # ───────────────────────────── the web app ─────────────────────────────

    dist = deps.cfg.web_dist.resolve()

    @app.get("/{path:path}")
    async def static(path: str):
        index = dist / "index.html"
        if not index.is_file():
            return JSONResponse({"error": "web_app_not_built"}, status_code=404)
        target = (dist / path).resolve() if path else index
        if target != index and (not target.is_file() or dist not in target.parents):
            target = index                                              # unknown paths (and any traversal) get the app
        headers = ({"Cache-Control": "no-cache"} if target == index
                   else {"Cache-Control": "public, max-age=31536000, immutable"} if "assets" in target.relative_to(dist).parts
                   else {"Cache-Control": "public, max-age=3600"})
        return FileResponse(target, headers=headers)

    app.add_middleware(GZipMiddleware, minimum_size=1000)           # the web app is mostly JavaScript: send it compressed
    app.add_middleware(Guard, deps=deps)
    return app


async def _bye(ws: WebSocket, code: int, reason: str = "") -> None:
    try:
        await ws.close(code=code, reason=reason[:120])
    except RuntimeError:
        pass


async def _authenticate(ws: WebSocket, deps: Deps):
    """First frame must be a valid AUTH within 5 seconds; identity and room come from Discord, never the client."""

    async def fail(code: str, message: str, close_code: int):
        try:
            await ws.send_json({"v": 1, "t": "ERROR", "seq": 0, "d": {"code": code, "message": message}})
        except RuntimeError:
            pass
        await _bye(ws, close_code, code)
        return None

    try:
        first = await asyncio.wait_for(ws.receive(), AUTH_TIMEOUT_S)
    except asyncio.TimeoutError:
        return await fail("auth_timeout", "Sign-in took too long.", 4401)
    if first["type"] == "websocket.disconnect":
        return None
    try:
        parsed = parse_frame(first.get("text") if first.get("text") is not None else first.get("bytes") or b"")
    except FrameError as err:
        return await fail(err.code, err.message, 4401)
    if parsed is None or parsed.t != "AUTH":
        return await fail("auth_required", "The first message must be AUTH.", 4401)
    try:
        auth = await deps.authenticator(parsed.d.access_token, parsed.d.instance_id)
    except AuthError as err:
        return await fail(err.code, err.message, err.close_code)
    except DiscordUnavailable:
        return await fail("discord_unavailable", "Discord is not answering. Try again in a moment.", 1013)
    try:
        return deps.manager.connect(auth, deps.clock_ms())
    except Refused as err:
        return await fail(err.code, err.message, err.close_code)


async def _write_loop(ws: WebSocket, conn, wake: asyncio.Event) -> None:
    try:
        while True:
            await wake.wait()
            wake.clear()
            for frame in conn.drain():
                await ws.send_json(frame)
            if conn.closed:
                await _bye(ws, conn.close_code or 1000, conn.close_reason)
                return
    except Exception:
        conn.close(1011, "transport error")
