"""Phase 7 checklist items not covered elsewhere: the abuse tool itself, secrets in logs, no user data at rest."""
import asyncio
import json
import logging
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from bamboozled.server.auth import AuthError, DiscordAuthenticator

ROOT = Path(__file__).resolve().parents[1]
SECRET = "tok-SECRETVALUE123"


def run_tool(*args):
    return subprocess.run([sys.executable, "tools/abuse_check.py", *args], cwd=ROOT, capture_output=True, text=True, timeout=180)


@pytest.mark.timeout(200)
def test_the_real_build_blocks_every_abuse_check():
    out = run_tool()
    assert out.returncode == 0, out.stdout + out.stderr
    assert "13/13 blocked" in out.stdout and "VULNERABLE" not in out.stdout


@pytest.mark.timeout(200)
def test_the_tool_can_fail_against_a_weakened_build():
    out = run_tool("--weakened")
    assert out.returncode == 1 and out.stdout.count("VULNERABLE") >= 3


def test_tokens_never_reach_logs_or_error_messages(caplog):
    caplog.set_level(logging.DEBUG)

    def handler(req: httpx.Request):
        if req.url.path.endswith("/users/@me"):
            ok = req.headers["authorization"] == f"Bearer {SECRET}"
            return httpx.Response(200 if ok else 401, json={"id": "1", "username": "u"})
        return httpx.Response(200, json={"users": ["1"], "location": {"guild_id": "1", "channel_id": "2"}})

    async def go():
        auth = DiscordAuthenticator("1", "BOT-TOKEN-VALUE", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        await auth(SECRET, "inst")
        with pytest.raises(AuthError) as bad:
            await auth("wrong-" + SECRET, "inst")
        return str(bad.value) + bad.value.message

    seen = asyncio.run(go())
    for secret in (SECRET, "BOT-TOKEN-VALUE"):
        assert secret not in caplog.text and secret not in seen


def test_no_name_or_avatar_is_stored_anywhere(tmp_db):
    """After a recorded game, every text value in the database is a mode or a JSON blob of numbers."""
    from bamboozled.db.repos.matches import ResultRow, record_match
    asyncio.run(record_match("fff", 5, [ResultRow(1, 1, 100, 2, {"total_questions": 10}), ResultRow(2, 2, 50, 1, {})]))
    con = sqlite3.connect(tmp_db)
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    tables = [t for t in names if t not in ("schema_version", "sqlite_sequence")]
    for t in tables:
        for row in con.execute(f"SELECT * FROM {t}"):
            for v in row:
                if isinstance(v, str) and v != "fff" and not re.fullmatch(r"[0-9a-f:T+.-]+", v):      # ids and timestamps
                    try:
                        assert all(isinstance(x, (int, float)) for x in json.loads(v).values())
                    except ValueError:
                        pytest.fail(f"unexpected text {v!r} in {t}")


def test_a_restart_tells_players_at_once_and_the_new_process_gives_a_working_lobby():
    sys.path.insert(0, str(ROOT))
    from tools.abuse_check import Backend, Client, _lobby

    async def go():
        with Backend() as be:
            a, b = await _lobby(be)
            await a.send("START")
            await a.pump(1)
            started = asyncio.get_running_loop().time()
            be.manager.shutdown()                                   # what SIGTERM does
            code = await a.pump(5)
            took = asyncio.get_running_loop().time() - started
            assert code == 1012 and a.got("BYE") and took < 2
        with Backend() as fresh:                                    # the restarted process
            c = await Client.open(fresh, 1, "game")
            await c.pump(1)
            return c.state["phase"]

    assert asyncio.run(go()) == "lobby"
