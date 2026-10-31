"""Numbers and the eleven Bamboozle laws. Pure functions over plain values; the engine applies the results."""
from dataclasses import dataclass
from typing import Optional

STARTING_POINTS = 500
CORRECT = 100
WRONG = -50
TIMEOUT = -100
LUCKY_LLAMA = 50
DOUBLE_DOWN_BONUS = 200
DOUBLE_DOWN_PENALTY = -200
REVERSE_UNO_PENALTY = 100
SOMBRERO_PENALTY = 25
SOMBRERO_STEP = 25
BONUS_ROUND = 150
GIFT_AMOUNT = 100
TAX_RATE = 0.20
TAX_MINIMUM = 10
MONKEY_BELLY = 300
MONKEY_TAIL = -200
MAX_SWING = 300
WANGO_AGAIN_DEPTH_LIMIT = 1
DOUBLE_WANGO_CHAIN_LIMIT = 2
MIST_TURNS = 2
MIST_MAGNET_TURNS = 4
SOMBRERO_CURSE_PENALTY = 50

SPEED_TAX_SECONDS = 5
SLOW_BURN_SECONDS = 20
KARMA_TAX = 50
UNDERDOG_BOOST = 50
HOT_STREAK_BONUS = 75
LUCKY_LAST_BONUS = 100
TIMEOUT_TERROR = 200
SPEED_TAX_PENALTY = 25
SLOW_BURN_PENALTY = 50
DOUBLE_JEOPARDY_WRONG = -100


@dataclass(frozen=True)
class LawDef:
    id: int
    name: str
    description: str
    permanent: bool


LAWS: tuple[LawDef, ...] = (
    LawDef(1, "Speed Tax", "Correct in under 5s? Lose 25 pts anyway. Slow down!", False),
    LawDef(2, "Slow Burn", "Take 20+ seconds then get it wrong or timeout? Extra -50 pts.", False),
    LawDef(3, "Double Jeopardy", "Wrong answers cost -100 pts instead of -50 for ALL players.", False),
    LawDef(4, "Hot Streak", "Two correct answers in a row earns +75 bonus pts.", False),
    LawDef(5, "Karma Tax", "First place loses 50 pts at the start of their turn.", False),
    LawDef(6, "Underdog Boost", "Last place gains 50 pts at the start of their turn.", False),
    LawDef(7, "Timeout Terror", "Timeouts cost -200 pts instead of -100 for everyone.", False),
    LawDef(8, "Lucky Last", "Last in turn order to answer correctly earns +100 bonus.", False),
    LawDef(9, "Streak Breaker", "First place drawing a Chance Card draws a Wango Card instead.", False),
    LawDef(10, "Mist Magnet", "PERMANENT: Mist duration increases to 4 turns for the game.", True),
    LawDef(11, "Sombrero Curse", "PERMANENT: Sombrero penalty rises to 50 pts per wrong answer.", True),
)
_BY_ID = {law.id: law for law in LAWS}


def law(rule_id: int) -> Optional[LawDef]:
    return _BY_ID.get(rule_id)


def make_active_law(rule_id: int, num_players: int) -> dict:
    d = _BY_ID.get(rule_id)
    if d is None:
        raise ValueError(f"unknown law id: {rule_id}")
    return {"id": d.id, "name": d.name, "permanent": d.permanent, "turns_remaining": -1 if d.permanent else num_players}


def wrong_penalty(active: Optional[dict]) -> int:
    return DOUBLE_JEOPARDY_WRONG if active and active["id"] == 3 else WRONG


def timeout_penalty(active: Optional[dict]) -> int:
    return -TIMEOUT_TERROR if active and active["id"] == 7 else TIMEOUT


def tax(score: int) -> int:
    """Tax Season: 20% of the magnitude of the score, at least 10."""
    return max(TAX_MINIMUM, int(abs(score) * TAX_RATE))
