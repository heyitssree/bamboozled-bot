import asyncio
import html
import json
import logging
import random
from pathlib import Path
from typing import Optional

import aiohttp

from game_engine.constants import SAFE_OPENTDB_CATEGORY_IDS
from game_engine.trivia_api import (
    ALL_TAPI_SLUGS,
    OPENTDB_TO_TAPI,
    TAPI_VIRTUAL_IDS,
    US_SPECIFIC_RE as _US_SPECIFIC_RE,
    fetch_question_tapi,
)

logger = logging.getLogger(__name__)

_OPENTDB_API = "https://opentdb.com/api.php"
_OPENTDB_TOKEN = "https://opentdb.com/api_token.php"

_EMERGENCY_QUESTIONS = [
    {
        "question": "What is the capital of France?",
        "correct_answer": "Paris",
        "incorrect_answers": ["London", "Berlin", "Madrid"],
        "category": "Geography",
        "difficulty": "easy",
    },
    {
        "question": "How many sides does a hexagon have?",
        "correct_answer": "6",
        "incorrect_answers": ["5", "7", "8"],
        "category": "Mathematics",
        "difficulty": "easy",
    },
    {
        "question": "Which planet is known as the Red Planet?",
        "correct_answer": "Mars",
        "incorrect_answers": ["Venus", "Jupiter", "Saturn"],
        "category": "Science",
        "difficulty": "easy",
    },
    {
        "question": "What is 7 multiplied by 8?",
        "correct_answer": "56",
        "incorrect_answers": ["48", "54", "63"],
        "category": "Mathematics",
        "difficulty": "easy",
    },
    {
        "question": "Who wrote Romeo and Juliet?",
        "correct_answer": "William Shakespeare",
        "incorrect_answers": ["Charles Dickens", "Jane Austen", "Mark Twain"],
        "category": "Literature",
        "difficulty": "easy",
    },
]


def _decode(q: dict) -> dict:
    return {
        "question": html.unescape(q["question"]),
        "correct_answer": html.unescape(q["correct_answer"]),
        "incorrect_answers": [html.unescape(a) for a in q["incorrect_answers"]],
        "category": html.unescape(q.get("category", "Unknown")),
        "difficulty": q.get("difficulty", "medium"),
    }


async def fetch_session_token() -> Optional[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(_OPENTDB_TOKEN, params={"command": "request"}) as resp:
                data = await resp.json(content_type=None)
                if data.get("response_code") == 0:
                    return data.get("token")
    except Exception as exc:
        logger.warning("Failed to fetch OpenTDB session token: %s", exc)
    return None


async def _reset_token(token: str) -> Optional[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _OPENTDB_TOKEN, params={"command": "reset", "token": token}
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("response_code") == 0:
                    return data.get("token")
    except Exception as exc:
        logger.warning("Failed to reset OpenTDB token: %s", exc)
    return None


async def fetch_question(
    session_token: Optional[str] = None,
    difficulty: Optional[str] = None,
    category: Optional[int] = None,
    question_type: str = "multiple",
    seen: Optional[set] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Fetch one question. Returns (question_dict, token). Falls back on failure.
    question_type: 'multiple' (4-choice) or 'boolean' (True/False).
    seen: set of question texts already asked this session — skipped if matched."""
    params: dict = {
        "amount": 1,
        "type": question_type,
        "category": category if category is not None else random.choice(SAFE_OPENTDB_CATEGORY_IDS),
    }
    if difficulty:
        params["difficulty"] = difficulty
    if session_token:
        params["token"] = session_token

    async def _try() -> Optional[dict]:
        async with aiohttp.ClientSession() as session:
            async with session.get(_OPENTDB_API, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                return await resp.json(content_type=None)

    data: Optional[dict] = None
    try:
        data = await _try()
    except Exception as exc:
        logger.warning("OpenTDB attempt 1 failed: %s", exc)

    # Token exhausted — reset and update param
    if data and data.get("response_code") == 4 and session_token:
        session_token = await _reset_token(session_token)
        if session_token:
            params["token"] = session_token
        data = None  # force retry

    if not (data and data.get("response_code") == 0):
        await asyncio.sleep(3)
        try:
            data = await _try()
        except Exception as exc:
            logger.warning("OpenTDB attempt 2 failed: %s", exc)
            data = None

    if data and data.get("response_code") == 0 and data.get("results"):
        q = _decode(data["results"][0])
        is_us = _US_SPECIFIC_RE.search(q["question"]) or _US_SPECIFIC_RE.search(q["correct_answer"])
        is_seen = seen is not None and q["question"] in seen
        if is_us or is_seen:
            if is_us:
                logger.debug("Filtered US-specific question: %s", q["question"][:60])
            if is_seen:
                logger.debug("Filtered already-seen question: %s", q["question"][:60])
            # One retry with a fresh category draw — keep token so it advances correctly
            params["category"] = random.choice(SAFE_OPENTDB_CATEGORY_IDS)
            try:
                retry_data = await _try()
                if retry_data and retry_data.get("response_code") == 0 and retry_data.get("results"):
                    retry_q = _decode(retry_data["results"][0])
                    retry_us = _US_SPECIFIC_RE.search(retry_q["question"]) or _US_SPECIFIC_RE.search(retry_q["correct_answer"])
                    retry_seen = seen is not None and retry_q["question"] in seen
                    if not retry_us and not retry_seen:
                        return retry_q, session_token
            except Exception:
                pass
            # Retry also filtered — return original rather than stall indefinitely
        return q, session_token

    # Fallback: custom_questions.json
    custom_path = Path(__file__).parent.parent / "data" / "custom_questions.json"
    if custom_path.exists():
        try:
            with open(custom_path, encoding="utf-8") as fh:
                qs = json.load(fh)
            if qs:
                logger.warning("Using custom question fallback.")
                unseen = [_decode(q) for q in qs if (seen is None or q.get("question", "") not in seen)]
                pool = unseen if unseen else [_decode(q) for q in qs]
                return random.choice(pool), session_token
        except Exception as exc:
            logger.warning("Failed to load custom_questions.json: %s", exc)

    # Emergency hardcode
    logger.warning("Using emergency hardcoded question.")
    unseen_emergency = [q for q in _EMERGENCY_QUESTIONS if seen is None or q["question"] not in seen]
    pool = unseen_emergency if unseen_emergency else _EMERGENCY_QUESTIONS
    return _decode(random.choice(pool)), session_token


async def fetch_question_any(
    session_token: Optional[str] = None,
    difficulty: Optional[str] = None,
    category: Optional[int] = None,
    question_type: str = "multiple",
    seen: Optional[set] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Fetch a question from OpenTDB or The Trivia API.

    Routing logic:
    - category < 0  → TAPI-only virtual category (music, film_and_tv, etc.)
    - category > 0 with TAPI mapping → 50 % chance either source; falls back to OpenTDB on TAPI failure
    - category > 0, no TAPI mapping → OpenTDB only
    - category is None → 50 % chance: random TAPI slug vs OpenTDB (all-categories)

    Returns (question_dict, updated_session_token) matching fetch_question's contract.
    """
    tapi_type = "true_false" if question_type == "boolean" else "text_choice"

    # ── TAPI-only virtual category ─────────────────────────────────────────────
    if category is not None and category < 0:
        slug = TAPI_VIRTUAL_IDS.get(category)
        q = await fetch_question_tapi(difficulty, slug, tapi_type, seen)
        if q:
            return q, session_token
        # TAPI failed — fall through to OpenTDB all-categories as emergency
        return await fetch_question(session_token, difficulty, None, question_type, seen)

    # ── Specific OpenTDB category (possibly dual-source) ──────────────────────
    if category is not None:
        tapi_slug = OPENTDB_TO_TAPI.get(category)
        if tapi_slug and random.random() < 0.5:
            q = await fetch_question_tapi(difficulty, tapi_slug, tapi_type, seen)
            if q:
                return q, session_token
            # TAPI failed — fall through to OpenTDB
        return await fetch_question(session_token, difficulty, category, question_type, seen)

    # ── All categories: randomly pick source ───────────────────────────────────
    if random.random() < 0.5:
        slug = random.choice(ALL_TAPI_SLUGS)
        q = await fetch_question_tapi(difficulty, slug, tapi_type, seen)
        if q:
            return q, session_token
        # TAPI failed — fall through to OpenTDB
    return await fetch_question(session_token, difficulty, None, question_type, seen)


def shuffle_answers(question: dict) -> tuple[list[str], int]:
    """Return (shuffled_answers, correct_index)."""
    answers = [question["correct_answer"]] + list(question["incorrect_answers"])
    random.shuffle(answers)
    return answers, answers.index(question["correct_answer"])
