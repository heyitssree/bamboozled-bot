"""Chance and Wango cards. Draws are uniform over the enum, in declaration order."""
import random
from enum import Enum


class ChanceCard(Enum):
    LUCKY_LLAMA = "Lucky Llama"
    SWITCHEROO = "Switcheroo"
    DOUBLE_DOWN = "Double Down"
    SPIN_THE_WHEEL = "Spin the Wheel"
    GOLDEN_PASS = "Golden Pass"
    BAMBOOZLE = "Bamboozle"


class WangoCard(Enum):
    WANGO_CLASSIC = "Wango Classic"
    THE_SILENCE = "The Silence"
    REVERSE_UNO = "Reverse Uno"
    THE_SOMBRERO = "The Sombrero"
    DOUBLE_WANGO = "Double Wango"
    MYSTIC_MIST = "Mystic Mist"


def draw_chance(rng: random.Random) -> ChanceCard:
    return rng.choice(list(ChanceCard))


def draw_wango(rng: random.Random) -> WangoCard:
    return rng.choice(list(WangoCard))
