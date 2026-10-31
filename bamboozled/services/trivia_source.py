"""Where questions come from, and the one place they are screened, so every mode shares it. A game never blocks on
trivia: live sources are tried with a time budget, screened, and anything that goes wrong falls back to the offline file."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import time
from pathlib import Path
from typing import Optional

import httpx

from ..engine import Question
from .safety import Rejections, Screen, question_texts

log = logging.getLogger("bamboozled.trivia")

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "data" / "custom_questions.json"


class OfflineQuestions:
    """Owner-reviewed questions from data/custom_questions.json, shuffled, repeating only when they run out."""

    def __init__(self, rng: Optional[random.Random] = None, path: Path = DEFAULT_FILE):
        self.rng = rng or random.Random()
        self._items = json.loads(Path(path).read_text(encoding="utf-8"))
        if not self._items:
            raise ValueError("no offline questions available")
        self._bag: list[dict] = []

    async def __call__(self, need: dict) -> Question:
        if not self._bag:
            self._bag = list(self._items)
            self.rng.shuffle(self._bag)
        item = self._bag.pop()
        answers = [item["correct_answer"]] + list(item["incorrect_answers"])
        self.rng.shuffle(answers)
        return Question(item["question"], tuple(answers), answers.index(item["correct_answer"]),
                        item.get("category", ""), item.get("difficulty", "medium"))


# OpenTDB category ids that suit the audience (no US-centric Sports).
OPENTDB_CATEGORIES = (9, 17, 18, 19, 20, 22, 23, 24, 25, 26, 27, 28)
TAPI_CATEGORIES = ("general_knowledge", "science", "geography", "history", "arts_and_literature", "music",
                   "film_and_tv", "food_and_drink", "society_and_culture")
MAX_TRIES = 5
BUDGET_S = 8.0               # all live attempts for one question together
BACKOFF_S = 30.0             # after a source fails, leave it alone this long
SEEN_MAX = 500


def _shuffled(correct: str, wrong: list[str], text: str, category: str, difficulty: str, qtype: str, rng) -> Question:
    answers = [correct] + wrong
    if qtype != "boolean":
        rng.shuffle(answers)
    return Question(text, tuple(answers), answers.index(correct), category, difficulty, qtype)


async def fetch_opentdb(http: httpx.AsyncClient, need: dict, rng) -> Optional[Question]:
    boolean = need.get("qtype") == "boolean"
    params = {"amount": 1, "type": "boolean" if boolean else "multiple", "category": rng.choice(OPENTDB_CATEGORIES)}
    if need.get("difficulty"):
        params["difficulty"] = need["difficulty"]
    data = (await http.get("https://opentdb.com/api.php", params=params)).json()
    if data.get("response_code") != 0 or not data.get("results"):
        return None
    r = data["results"][0]
    un = html.unescape
    answers = [un(a) for a in r["incorrect_answers"]]
    if boolean:
        answers = ["True", "False"]
        return Question(un(r["question"]), tuple(answers), answers.index(un(r["correct_answer"])), un(r["category"]),
                        r["difficulty"], "boolean")
    return _shuffled(un(r["correct_answer"]), answers, un(r["question"]), un(r["category"]), r["difficulty"], "multiple", rng)


async def fetch_tapi(http: httpx.AsyncClient, need: dict, rng) -> Optional[Question]:
    if need.get("qtype") == "boolean":
        return None                                           # this source only has multiple choice
    params = {"limit": 1, "types": "text_choice", "categories": rng.choice(TAPI_CATEGORIES)}
    if need.get("difficulty"):
        params["difficulties"] = need["difficulty"]
    data = (await http.get("https://the-trivia-api.com/v2/questions", params=params)).json()
    if not data:
        return None
    r = data[0]
    return _shuffled(r["correctAnswer"], list(r["incorrectAnswers"]), r["question"]["text"],
                     r["category"].replace("_", " ").title(), r.get("difficulty", "medium"), "multiple", rng)


FETCHERS = {"opentdb": fetch_opentdb, "tapi": fetch_tapi}


class ScreenedQuestions:
    """The provider the game server uses: live sources per the trivia.sources setting, every question screened."""

    def __init__(self, settings, offline: OfflineQuestions, http: Optional[httpx.AsyncClient] = None,
                 rng: Optional[random.Random] = None, fetchers: Optional[dict] = None, screen: Optional[Screen] = None):
        self.settings, self.offline = settings, offline
        self.http = http or httpx.AsyncClient(timeout=4.0)
        self.rng = rng or random.Random()
        self.fetchers = fetchers if fetchers is not None else FETCHERS
        self.screen = screen or Screen()
        self.rejections = Rejections()
        self.health: dict[str, tuple[float, str]] = {}        # source -> (when, "ok" | error)
        self.served: dict[str, int] = {}                      # source -> questions used (offline included)
        self._down_until: dict[str, float] = {}
        self._seen: list[str] = []

    def _sources(self) -> list[str]:
        mode = self.settings.get("trivia.sources")
        names = {"opentdb": ["opentdb"], "tapi": ["tapi"], "both": ["opentdb", "tapi"]}.get(mode, [])
        now = time.monotonic()
        return [n for n in names if self._down_until.get(n, 0) <= now]

    async def _live(self, need: dict) -> Optional[Question]:
        strictness = self.settings.get("trivia.safety_strictness")
        for _ in range(MAX_TRIES):
            names = self._sources()
            if not names:
                return None
            name = self.rng.choice(names)
            try:
                q = await self.fetchers[name](self.http, need, self.rng)
            except Exception as exc:                          # network, bad JSON, rate limit: leave this source alone a while
                self.health[name] = (time.time(), f"failed ({type(exc).__name__})")
                self._down_until[name] = time.monotonic() + BACKOFF_S
                continue
            if q is None:
                self.health[name] = (time.time(), "no question returned")
                continue
            self.health[name] = (time.time(), "ok")
            if q.text in self._seen:
                continue
            if not self.screen.is_clean(*question_texts(q), strictness=strictness):
                self.rejections.add(name, q.category)
                continue
            self._seen = (self._seen + [q.text])[-SEEN_MAX:]
            self.served[name] = self.served.get(name, 0) + 1
            return q
        return None

    async def __call__(self, need: dict) -> Question:
        try:
            q = await asyncio.wait_for(self._live(need), BUDGET_S)
        except asyncio.TimeoutError:
            q = None
        if q is None:
            self.served["offline"] = self.served.get("offline", 0) + 1
            q = await self.offline(need)
        return q
