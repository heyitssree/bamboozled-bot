import asyncio
import random

import httpx

from bamboozled.engine import Question
from bamboozled.services import trivia_source as ts
from bamboozled.services.safety import DATA, _load
from bamboozled.services.trivia_source import OfflineQuestions, ScreenedQuestions
from bamboozled.settings import Settings

BAD = " ".join(_load(DATA / "always.txt")[0])


def q(text="A fine question?", answers=("a", "b", "c", "d"), category="History"):
    return Question(text, answers, 0, category, "easy")


def make(fetchers, sources="both", strictness="standard"):
    s = Settings({"trivia.sources": sources, "trivia.safety_strictness": strictness})
    return ScreenedQuestions(s, OfflineQuestions(random.Random(1)), http=object(), rng=random.Random(2), fetchers=fetchers)


def run(coro):
    return asyncio.run(coro)


def test_a_clean_live_question_is_served():
    async def f(http, need, rng):
        return q()
    t = make({"opentdb": f, "tapi": f})
    assert run(t({})).text == "A fine question?"
    assert sum(t.served.values()) == 1 and t.rejections.total() == 0


def test_a_rejected_question_is_counted_and_another_is_fetched():
    calls = []

    async def f(http, need, rng):
        calls.append(1)
        return q(f"what is {BAD}?") if len(calls) < 3 else q("Fine again?")
    t = make({"opentdb": f}, sources="opentdb")
    assert run(t({})).text == "Fine again?"
    assert t.rejections.counts[("opentdb", "History")] == 2


def test_the_category_and_the_wrong_answers_are_screened_too():
    async def f(http, need, rng):
        return q(answers=("a", BAD, "c", "d"))
    t = make({"tapi": f}, sources="tapi")
    run(t({}))
    assert t.rejections.total() == ts.MAX_TRIES and t.served == {"offline": 1}


def test_strict_mode_rejects_contextual_terms():
    ctx = " ".join(_load(DATA / "contextual.txt")[0])

    async def f(http, need, rng):
        return q(f"The {ctx} in history?")
    assert run(make({"opentdb": f}, "opentdb", "standard")({})).text.startswith("The ")
    strict = make({"opentdb": f}, "opentdb", "strict")
    run(strict({}))
    assert strict.rejections.total() == ts.MAX_TRIES


def test_a_failing_source_falls_back_to_offline_and_is_left_alone():
    calls = []

    async def boom(http, need, rng):
        calls.append(1)
        raise httpx.ConnectError("down")
    t = make({"opentdb": boom}, sources="opentdb")
    assert run(t({})).text and t.served == {"offline": 1} and len(calls) == 1
    assert "failed" in t.health["opentdb"][1]
    run(t({}))
    assert len(calls) == 1                                              # backed off: no second attempt


def test_custom_only_never_touches_the_network():
    async def f(http, need, rng):
        raise AssertionError("must not be called")
    t = make({"opentdb": f, "tapi": f}, sources="custom_only")
    assert run(t({})).text and t.served == {"offline": 1}


def test_a_slow_source_cannot_hold_the_game(monkeypatch):
    monkeypatch.setattr(ts, "BUDGET_S", 0.05)

    async def slow(http, need, rng):
        await asyncio.sleep(5)
    t = make({"opentdb": slow}, sources="opentdb")
    assert run(t({})).text and t.served == {"offline": 1}


def test_the_same_question_is_not_asked_twice():
    async def f(http, need, rng):
        return q()
    t = make({"opentdb": f}, sources="opentdb")
    run(t({}))
    run(t({}))
    assert t.served == {"opentdb": 1, "offline": 1}


def test_opentdb_and_tapi_responses_are_parsed():
    def handler(req: httpx.Request):
        if req.url.host == "opentdb.com":
            return httpx.Response(200, json={"response_code": 0, "results": [{
                "type": "multiple", "difficulty": "easy", "category": "Science &amp; Nature",
                "question": "Fish &amp; chips?", "correct_answer": "Yes", "incorrect_answers": ["No", "Maybe", "Never"]}]})
        return httpx.Response(200, json=[{"category": "film_and_tv", "correctAnswer": "Y", "incorrectAnswers": ["A", "B", "C"],
                                          "question": {"text": "Tapi?"}, "difficulty": "hard"}])
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    a = run(ts.fetch_opentdb(http, {}, random.Random(1)))
    assert a.text == "Fish & chips?" and a.category == "Science & Nature" and a.answers[a.correct_index] == "Yes"
    b = run(ts.fetch_tapi(http, {"difficulty": "hard"}, random.Random(1)))
    assert b.text == "Tapi?" and b.category == "Film And Tv" and b.answers[b.correct_index] == "Y"
    assert run(ts.fetch_tapi(http, {"qtype": "boolean"}, random.Random(1))) is None


def test_opentdb_boolean():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"response_code": 0, "results": [{
        "type": "boolean", "difficulty": "easy", "category": "X", "question": "Sky blue?", "correct_answer": "True",
        "incorrect_answers": ["False"]}]})))
    r = run(ts.fetch_opentdb(http, {"qtype": "boolean"}, random.Random(1)))
    assert r.qtype == "boolean" and r.answers == ("True", "False") and r.correct_index == 0
