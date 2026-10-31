"""Small server modules: rate limiters, name cache, proxy signatures, the offline question source, the DB adapter."""
import random
import sqlite3

import pytest
from nacl.signing import SigningKey

from bamboozled.engine.api import ResultRow
from bamboozled.server import proxy_sig
from bamboozled.server.names import TTL_S, NameCache
from bamboozled.server.ratelimit import KeyedLimiter, TokenBucket
from bamboozled.server.results import db_recorder
from bamboozled.services.trivia_source import OfflineQuestions


class Clock:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t


class TestRateLimiters:
    def test_bucket_allows_a_burst_then_refills(self):
        c = Clock()
        b = TokenBucket(10, 10, c)
        assert [b.allow() for _ in range(12)] == [True] * 10 + [False] * 2
        c.t += 100
        assert b.allow() and not b.allow()                           # 10/s: one token per 100 ms
        c.t += 10_000
        assert sum(b.allow() for _ in range(20)) == 10               # never more than the burst

    def test_keyed_limiter_is_per_key_and_bounded(self):
        c = Clock()
        k = KeyedLimiter(1 / 60, 2, c, max_keys=3)
        assert [k.allow("a"), k.allow("a"), k.allow("a")] == [True, True, False]
        assert k.allow("b")                                           # another key is unaffected
        for name in "cdef":
            k.allow(name)
        assert len(k.buckets) <= 3


class TestNameCache:
    async def test_cached_for_a_day_then_refetched_and_never_raises(self):
        c, calls = [0.0], []

        async def fetch(uid):
            calls.append(uid)
            if uid == 2:
                raise RuntimeError("discord down")
            return "" if uid == 3 else f"name{uid}"
        names = NameCache(fetch, clock=lambda: c[0])
        assert await names.get(1) == "name1" and await names.get(1) == "name1" and calls == [1]
        c[0] = TTL_S + 1
        assert await names.get(1) == "name1" and calls == [1, 1]
        assert await names.get(2) == "Unknown player" and await names.get(3) == "Unknown player"
        names.forget(1)
        await names.get(1)
        assert calls.count(1) == 3


class TestProxySignature:
    def setup_method(self):
        self.key = SigningKey.generate()
        self.pub = self.key.verify_key.encode().hex()

    def sign(self, ts, payload):
        return self.key.sign(ts.encode() + payload).signature.hex()

    def test_valid_signature_passes(self):
        assert proxy_sig.verify(self.pub, self.sign("1000", b"body"), "1000", b"body", now=lambda: 1000)

    @pytest.mark.parametrize("sig,ts,payload,now", [
        ("00" * 64, "1000", b"body", 1000),                         # wrong signature
        (None, "1000", b"tampered", 1000),                          # payload changed after signing
        (None, "1000", b"body", 5000),                              # too old
        (None, "not-a-number", b"body", 1000),
        ("zz", "1000", b"body", 1000),                              # not hex
    ])
    def test_bad_signatures_fail(self, sig, ts, payload, now):
        good = self.sign("1000", b"body")
        assert not proxy_sig.verify(self.pub, sig or good, ts, payload, now=lambda: now)

    def test_a_malformed_public_key_fails_closed(self):
        assert not proxy_sig.verify("nothex", "aa", "1", b"", now=lambda: 1)
        assert not proxy_sig.verify("", "", "", b"")


class TestOfflineQuestions:
    async def test_every_question_is_well_formed_and_the_bag_cycles(self):
        src = OfflineQuestions(random.Random(1))
        seen = set()
        for _ in range(len(src._items) * 2 + 3):
            q = await src({"qtype": "multiple"})
            assert len(q.answers) == 4 and 0 <= q.correct_index < 4 and len(set(q.answers)) == 4
            seen.add(q.text)
        assert len(seen) == len(src._items)

    def test_empty_file_is_an_error(self, tmp_path):
        p = tmp_path / "q.json"
        p.write_text("[]")
        with pytest.raises(ValueError):
            OfflineQuestions(path=p)


async def test_db_recorder_writes_one_match_in_the_new_tables(tmp_db):
    rows = [ResultRow(1, 1, 900, 5, {"x": 1}), ResultRow(2, 2, 400, 2)]
    await db_recorder("bamboozled", 77, rows, started_ms=0, cfg={"rounds": 5, "difficulty": "hard", "category": None})
    await db_recorder("survival", 77, [ResultRow(1, 1, 6, 6, {"reason": "wrong"})], started_ms=0, cfg={})
    con = sqlite3.connect(tmp_db)
    assert con.execute("SELECT mode, guild_id, rounds, difficulty FROM matches ORDER BY mode").fetchall() == [
        ("bamboozled", 77, 5, "hard"), ("survival", 77, None, "medium")]
    assert con.execute("SELECT COUNT(*) FROM match_results").fetchone()[0] == 3
    assert con.execute("SELECT games, wins FROM stats WHERE user_id=1 AND mode='bamboozled'").fetchone() == (1, 1)
    con.close()
