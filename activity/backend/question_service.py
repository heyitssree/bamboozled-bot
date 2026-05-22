from __future__ import annotations

import html
import logging
import random
from typing import Optional

import httpx

from models import Question

logger = logging.getLogger("navi.activity.questions")

_OPENTDB_URL = "https://opentdb.com/api.php"

SAFE_CATEGORY_IDS = [
    9,   # General Knowledge
    17,  # Science & Nature
    18,  # Science: Computers
    19,  # Science: Mathematics
    20,  # Mythology
    22,  # Geography
    23,  # History
    25,  # Art
    27,  # Animals
    28,  # Vehicles
    29,  # Entertainment: Comics
    30,  # Science: Gadgets
    31,  # Entertainment: Japanese Anime & Manga
    32,  # Entertainment: Cartoon & Animations
]

CATEGORY_NAMES = {
    9: "General Knowledge",
    17: "Science & Nature",
    18: "Computers",
    19: "Mathematics",
    20: "Mythology",
    22: "Geography",
    23: "History",
    25: "Art",
    27: "Animals",
    28: "Vehicles",
    29: "Comics",
    30: "Gadgets",
    31: "Anime & Manga",
    32: "Cartoons",
}


async def fetch_question(
    difficulty: str = "medium",
    category_id: Optional[int] = None,
) -> Optional[Question]:
    params: dict = {
        "amount": 1,
        "type": "multiple",
        "difficulty": difficulty,
    }
    if category_id:
        params["category"] = category_id
    else:
        params["category"] = random.choice(SAFE_CATEGORY_IDS)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_OPENTDB_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("OpenTDB fetch failed: %s", exc)
        return _fallback_question()

    results = data.get("results", [])
    if not results:
        logger.warning("OpenTDB returned no results (code=%s)", data.get("response_code"))
        return _fallback_question()

    item = results[0]
    correct = html.unescape(item["correct_answer"])
    incorrect = [html.unescape(a) for a in item["incorrect_answers"]]
    all_answers = incorrect + [correct]
    random.shuffle(all_answers)
    correct_index = all_answers.index(correct)

    cat_id = params.get("category", 9)
    category_name = CATEGORY_NAMES.get(cat_id, "General Knowledge")

    return Question(
        text=html.unescape(item["question"]),
        correct_answer=correct,
        incorrect_answers=incorrect,
        shuffled_answers=all_answers,
        correct_index=correct_index,
        category=category_name,
        difficulty=item.get("difficulty", difficulty),
    )


def _fallback_question() -> Question:
    """Return a hardcoded question when OpenTDB is unavailable."""
    correct = "Paris"
    options = ["Paris", "London", "Berlin", "Madrid"]
    random.shuffle(options)
    return Question(
        text="What is the capital of France?",
        correct_answer=correct,
        incorrect_answers=["London", "Berlin", "Madrid"],
        shuffled_answers=options,
        correct_index=options.index(correct),
        category="Geography",
        difficulty="easy",
    )
