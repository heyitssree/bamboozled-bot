"""The real FastAPI app with the dev authenticator: REST, static files, middleware and the WebSocket handshake."""
import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from bamboozled.config import Config
from bamboozled.db.repos.matches import ResultRow, record_match
from bamboozled.server import http as http_mod
from bamboozled.server.auth import DevAuthenticator
from bamboozled.server.http import Deps, create_app
from bamboozled.server.names import NameCache
from bamboozled.server.rooms import RoomManager
from bamboozled.settings import Settings
from tests.server_helpers import Clock, Recorder, provider

SECRET = "origin-secret"


def oauth_handler(request: httpx.Request) -> httpx.Response:
    form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
    if form.get("code") == "good-code":
        return httpx.Response(200, json={"access_token": "dev:7:Newbie", "refresh_token": "SECRET", "scope": "identify"})
    return httpx.Response(400, json={"error": "invalid_grant"})


@pytest.fixture
def web(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.abc123.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("do not serve")
    return dist


def make_client(web, opted_out=(), **cfg):
    config = Config(env="test", dev_auth=True, app_id="42", client_secret="cs", web_dist=web, **cfg)
    clock, settings = Clock(), Settings()
    mgr = RoomManager(settings, clock, provider, recorder=Recorder())
    names = {7: "Newbie", 1: "Alice"}

    async def fetch(uid):
        return names.get(uid, "")
    deps = Deps(cfg=config, manager=mgr, authenticator=DevAuthenticator(is_opted_out=lambda u: u in opted_out),
                settings=settings, clock_ms=clock, http=httpx.AsyncClient(transport=httpx.MockTransport(oauth_handler)),
                names=NameCache(fetch))
    return TestClient(create_app(deps)), deps


def hello(user=1, name="Alice", instance="test1"):
    return {"v": 1, "t": "AUTH", "d": {"access_token": f"dev:{user}:{name}", "instance_id": instance}}


# ───────────────────────────── plain HTTP ─────────────────────────────

def test_health_is_liveness_only(web):
    client, _ = make_client(web)
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_no_docs_and_the_right_headers_and_no_frame_blocking(web):
    client, _ = make_client(web)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).headers["content-type"].startswith(("text/html", "application/json"))
        assert "swagger" not in client.get(path).text.lower()
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
    assert "x-frame-options" not in r.headers and "frame-ancestors" not in r.headers.get("content-security-policy", "")
    assert "access-control-allow-origin" not in client.get("/api/health", headers={"Origin": "https://evil.example"}).headers


def test_static_files_and_cache_headers(web):
    client, _ = make_client(web)
    index = client.get("/")
    assert index.text == "<html>app</html>" and index.headers["cache-control"] == "no-cache"
    asset = client.get("/assets/app.abc123.js")
    assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
    assert "max-age=3600" in client.get("/favicon.svg").headers["cache-control"]
    deep = client.get("/some/deep/link")
    assert deep.text == "<html>app</html>" and deep.headers["cache-control"] == "no-cache"


def test_path_traversal_gets_the_app_not_the_file(web):
    client, _ = make_client(web)
    up = ".."                                                         # built here so this file has no literal parent paths
    for evil in (f"/{up}/secret.txt", "/%2e%2e/secret.txt", f"/assets/{up}/{up}/secret.txt", f"/{up}%2fsecret.txt"):
        assert "do not serve" not in client.get(evil).text


def test_unknown_api_paths_are_404_json_and_a_missing_build_is_explained(web, tmp_path):
    client, _ = make_client(web)
    assert client.get("/api/nope").status_code == 404
    bare, _ = make_client(tmp_path / "nothing")
    assert bare.get("/").status_code == 404 and bare.get("/").json()["error"] == "web_app_not_built"


def test_request_size_limit(web):
    client, _ = make_client(web)
    r = client.post("/api/oauth/token", content=b"x" * 70_000, headers={"content-type": "application/json"})
    assert r.status_code == 413


# ───────────────────────────── origin verification ─────────────────────────────

def test_origin_verify_header_is_required_when_configured(web):
    client, _ = make_client(web, origin_verify=SECRET)
    assert client.get("/api/health").status_code == 403
    assert client.get("/api/health", headers={"x-origin-verify": "wrong"}).status_code == 403
    assert client.get("/api/health", headers={"x-origin-verify": SECRET}).status_code == 200
    with pytest.raises(WebSocketDisconnect) as err:
        with client.websocket_connect("/api/ws"):
            pass
    assert err.value.code == 4403
    with client.websocket_connect("/api/ws", headers={"x-origin-verify": SECRET}) as ws:
        ws.send_json(hello())
        assert ws.receive_json()["t"] == "STATE"


# ───────────────────────────── OAuth code exchange ─────────────────────────────

def test_oauth_exchange_returns_only_the_access_token(web):
    client, _ = make_client(web)
    r = client.post("/api/oauth/token", json={"code": "good-code"})
    assert r.status_code == 200 and r.json() == {"access_token": "dev:7:Newbie"}
    assert client.post("/api/oauth/token", json={"code": "bad"}).status_code == 400
    assert client.post("/api/oauth/token", json={}).status_code == 422
    assert client.post("/api/oauth/token", json={"code": "x" * 600}).status_code == 422


def test_oauth_exchange_is_rate_limited_per_code_and_per_ip(web):
    client, _ = make_client(web)
    codes = [client.post("/api/oauth/token", json={"code": "same"}).status_code for _ in range(5)]
    assert codes[:3] == [400, 400, 400] and codes[3:] == [429, 429]
    client2, _ = make_client(web)
    statuses = [client2.post("/api/oauth/token", json={"code": f"c{i}"}).status_code for i in range(25)]
    assert statuses.count(429) == 5


def test_oauth_without_a_client_secret_is_not_configured(web):
    config = Config(env="test", dev_auth=True, web_dist=web)
    clock, settings = Clock(), Settings()
    deps = Deps(cfg=config, manager=RoomManager(settings, clock, provider), authenticator=DevAuthenticator(),
                settings=settings, clock_ms=clock, http=None)
    assert TestClient(create_app(deps)).post("/api/oauth/token", json={"code": "c"}).status_code == 503


# ───────────────────────────── stats and boards ─────────────────────────────

def test_stats_and_leaderboard_need_a_valid_sign_in(web, tmp_db):
    import asyncio
    asyncio.run(record_match("bamboozled", 1, [ResultRow(1, 1, 900, 3), ResultRow(2, 2, 100, 1)]))
    asyncio.run(record_match("bamboozled", 99, [ResultRow(2, 1, 500, 2)]))
    client, _ = make_client(web)
    assert client.get("/api/me/stats").status_code == 401
    assert client.get("/api/me/stats", headers={"authorization": "Bearer nope", "x-instance-id": "i"}).status_code == 401
    ok = {"authorization": "Bearer dev:1:Alice", "x-instance-id": "test1"}
    s = client.get("/api/me/stats", headers=ok).json()
    assert (s["games"], s["wins"], s["best_score"]) == (1, 1, 900)
    assert client.get("/api/me/stats?mode=fff", headers=ok).json()["games"] == 0
    assert client.get("/api/me/stats?mode=chess", headers=ok).status_code == 400
    board = client.get("/api/leaderboard?mode=bamboozled&scope=server", headers=ok).json()
    assert [r["user_id"] for r in board["rows"]] == [1, 2] and board["rows"][0]["name"] == "Alice"
    assert board["rows"][1]["name"] == "Unknown player"                    # the name lookup had nothing: placeholder, not stored
    glob = client.get("/api/leaderboard?mode=bamboozled&scope=global", headers=ok).json()
    assert [r["user_id"] for r in glob["rows"]] == [1, 2]            # one win each; user 1 has more points
    assert client.get("/api/leaderboard?mode=x", headers=ok).status_code == 400


# ───────────────────────────── the WebSocket handshake ─────────────────────────────

def test_a_valid_user_gets_the_lobby_state_and_a_second_one_appears_for_both(web):
    client, deps = make_client(web)
    with client.websocket_connect("/api/ws") as a:
        a.send_json(hello(1, "Alice"))
        s = a.receive_json()
        assert s["t"] == "STATE" and s["d"]["you"] == 1 and s["d"]["host"] == 1 and s["seq"] == 1
        with client.websocket_connect("/api/ws") as b:
            b.send_json(hello(2, "Bob"))
            assert [m["user_id"] for m in b.receive_json()["d"]["members"]] == [1, 2]
            assert [m["name"] for m in a.receive_json()["d"]["members"]] == ["Alice", "Bob"]
            b.send_json({"v": 1, "t": "START", "d": {}})
            assert b.receive_json()["d"]["code"] == "not_host"
    assert deps.manager.snapshot()["sockets"] == 0


def test_first_frame_must_be_auth(web):
    client, _ = make_client(web)
    for first in ({"v": 1, "t": "READY", "d": {"ready": True}}, {"nonsense": True}):
        with client.websocket_connect("/api/ws") as ws:
            ws.send_json(first)
            assert ws.receive_json()["t"] == "ERROR"
            with pytest.raises(WebSocketDisconnect) as err:
                ws.receive_json()
            assert err.value.code == 4401


def test_a_bad_token_is_closed_with_4401(web):
    client, _ = make_client(web)
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"v": 1, "t": "AUTH", "d": {"access_token": "forged", "instance_id": "i"}})
        assert ws.receive_json()["d"]["code"] == "bad_token"
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 4401


def test_silence_after_connecting_times_out(web, monkeypatch):
    monkeypatch.setattr(http_mod, "AUTH_TIMEOUT_S", 0.05)
    client, _ = make_client(web)
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["d"]["code"] == "auth_timeout"
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 4401


def test_opted_out_user_is_refused_at_auth(web):
    client, _ = make_client(web, opted_out={5})
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json(hello(5, "Opt"))
        assert ws.receive_json()["d"]["code"] == "opted_out"
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 4403


def test_server_full_and_maintenance_are_explained_before_closing(web):
    client, deps = make_client(web)
    deps.settings.set("system.killswitch", True)
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json(hello())
        assert ws.receive_json()["d"]["code"] == "maintenance"
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 1012


def test_bad_frames_after_auth_do_not_kill_the_socket(web):
    client, _ = make_client(web)
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json(hello())
        ws.receive_json()
        ws.send_text("this is not json")
        assert ws.receive_json()["d"]["code"] == "bad_json"
        ws.send_text("x" * 5000)
        assert ws.receive_json()["d"]["code"] == "frame_too_big"
        ws.send_bytes(b"\x00\x01")
        assert ws.receive_json()["d"]["code"] == "bad_json"
        ws.send_json({"v": 1, "t": "TELEPORT", "d": {}})                     # unknown: silently ignored
        ws.send_json({"v": 1, "t": "PING", "d": {}})
        assert ws.receive_json()["t"] == "PONG"


def test_the_manager_dropping_a_connection_closes_the_socket(web):
    client, deps = make_client(web)
    with client.websocket_connect("/api/ws") as a:
        a.send_json(hello(1, "Alice"))
        a.receive_json()
        with client.websocket_connect("/api/ws") as dup:                       # same user again: the first is replaced
            dup.send_json(hello(1, "Alice"))
            dup.receive_json()
            assert a.receive_json()["d"]["reason"] == "kicked"
            with pytest.raises(WebSocketDisconnect) as err:
                a.receive_json()
            assert err.value.code == 4409
