"""Client for The Trivia API (https://the-trivia-api.com/v2/).

Response shape:
[{
    "category": "music",
    "id": "...",
    "correctAnswer": "Percussion",
    "incorrectAnswers": ["Woodwind", "Stringed", "Brass"],
    "question": {"text": "What type of instrument are the castanets?"},
    "type": "text_choice",   # or "true_false"
    "difficulty": "medium",
    "regions": [],
    "isNiche": false,
    "tags": [...]
}]
"""
import logging
import random
import re
from typing import Optional

import aiohttp

# US-sports and US-culture references unlikely to be relevant outside North America.
# Shared with trivia.py (imported from there) so both OpenTDB and TAPI paths are filtered.
US_SPECIFIC_RE = re.compile(
    r'\b('
    r'NFL|NBA|MLB|NHL|MLS|WNBA|NASCAR|PGA Tour'
    r'|Super Bowl|World Series|Stanley Cup|March Madness|Rose Bowl|Cotton Bowl'
    r'|quarterback|touchdowns?|gridiron|pigskin'
    r'|American football(?!\s+club)'
    r'|AFL(?!\s+(?:Cup|Grand Final))'
    r'|CFL\b'
    r')',
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

_TAPI_BASE = "https://the-trivia-api.com/v2/questions"

# ── Category metadata ─────────────────────────────────────────────────────────

# All valid TAPI category slugs (primary slug per category)
ALL_TAPI_SLUGS: list[str] = [
    "general_knowledge",
    "science",
    "geography",
    "history",
    "arts_and_literature",
    "music",
    "film_and_tv",
    "food_and_drink",
    "society_and_culture",
    "sport_and_leisure",
]

# Slug → display name (used to populate the "category" field in normalised dicts)
SLUG_TO_DISPLAY: dict[str, str] = {
    "general_knowledge":  "General Knowledge",
    "science":            "Science",
    "geography":          "Geography",
    "history":            "History",
    "arts_and_literature": "Arts & Literature",
    "music":              "Music",
    "film_and_tv":        "Film & TV",
    "food_and_drink":     "Food & Drink",
    "society_and_culture": "Society & Culture",
    "sport_and_leisure":  "Sport & Leisure",
}

# OpenTDB integer category ID → TAPI slug, for categories that exist in both
# IDs absent from this dict have no TAPI equivalent and stay OpenTDB-only.
OPENTDB_TO_TAPI: dict[int, str] = {
    9:  "general_knowledge",   # General Knowledge
    17: "science",             # Science & Nature
    18: "science",             # Computers
    19: "science",             # Mathematics
    21: "sport_and_leisure",   # Sports
    22: "geography",           # Geography
    23: "history",             # History
    25: "arts_and_literature", # Art
    30: "science",             # Science: Gadgets
}

# Negative "virtual" category IDs used in select-menu values for categories
# that only exist in TAPI (no OpenTDB equivalent).
TAPI_VIRTUAL_IDS: dict[int, str] = {
    -1: "music",
    -2: "film_and_tv",
    -3: "food_and_drink",
    -4: "society_and_culture",
}


# ── Normaliser ────────────────────────────────────────────────────────────────

def _normalize(q: dict) -> dict:
    """Convert a raw TAPI question dict to the shared internal format."""
    slug = q.get("category", "")
    return {
        "question":          q["question"]["text"],
        "correct_answer":    q["correctAnswer"],
        "incorrect_answers": list(q["incorrectAnswers"]),
        "category":          SLUG_TO_DISPLAY.get(slug, slug.replace("_", " ").title()),
        "difficulty":        q.get("difficulty", "medium"),
    }


# ── Fetcher ───────────────────────────────────────────────────────────────────

async def fetch_question_tapi(
    difficulty: Optional[str] = None,
    tapi_slug: Optional[str] = None,
    question_type: str = "text_choice",   # "text_choice" or "true_false"
    seen: Optional[set] = None,
) -> Optional[dict]:
    """Fetch one question from The Trivia API.

    Returns a normalised question dict (same shape as fetch_question output),
    or None if the API is unreachable or returns no results.
    """
    params: dict = {"limit": 1, "types": question_type}
    if tapi_slug:
        params["categories"] = tapi_slug
    if difficulty:
        params["difficulties"] = difficulty

    async def _try() -> Optional[list]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _TAPI_BASE, params=params, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    logger.warning("TAPI HTTP %d for params %s", resp.status, params)
                    return None
                data = await resp.json(content_type=None)
                return data if isinstance(data, list) and data else None

    results = None
    try:
        results = await _try()
    except Exception as exc:
        logger.warning("TAPI attempt 1 failed: %s", exc)

    if not results:
        return None

    q = _normalize(results[0])

    def _is_filtered(question: dict) -> bool:
        return (
            US_SPECIFIC_RE.search(question["question"]) is not None
            or US_SPECIFIC_RE.search(question["correct_answer"]) is not None
            or (seen is not None and question["question"] in seen)
        )

    if _is_filtered(q):
        if US_SPECIFIC_RE.search(q["question"]) or US_SPECIFIC_RE.search(q["correct_answer"]):
            logger.debug("TAPI: filtered US-specific question: %s", q["question"][:60])
        else:
            logger.debug("TAPI: filtered already-seen question: %s", q["question"][:60])
        try:
            retry = await _try()
            if retry:
                retry_q = _normalize(retry[0])
                if not _is_filtered(retry_q):
                    return retry_q
        except Exception:
            pass
        # Retry also filtered — return original rather than stall indefinitely

    return q
