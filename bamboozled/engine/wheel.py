"""The Wheel of Mayhem."""
import random
from enum import Enum


class WheelSegment(Enum):
    LADDER_OF_CHANCE = "Ladder of Chance"
    TAX_SEASON = "Tax Season"
    GIFT_OF_THE_BAMBOOZLE = "Gift of the Bamboozle"
    FULL_REVERSAL = "Full Reversal"
    MYSTIC_MIST = "Mystic Mist"
    BONUS_ROUND = "Bonus Round"
    WANGO_AGAIN = "Wango Again"
    MONKEYS_CHOICE = "Monkey's Choice"


_ALL = list(WheelSegment)
_NO_MONKEY = [s for s in WheelSegment if s != WheelSegment.MONKEYS_CHOICE]


def spin(rng: random.Random) -> WheelSegment:
    """One spin. Monkey's Choice is resolved here into one of the other seven segments (two draws)."""
    seg = rng.choice(_ALL)
    if seg == WheelSegment.MONKEYS_CHOICE:
        seg = rng.choice(_NO_MONKEY)
    return seg
