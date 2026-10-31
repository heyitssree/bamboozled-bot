"""The pure rules engine: one implementation of each mode, shared by the game server, the CLI and the tests."""
from .api import (ANSWER, DRAW_CARD, FORFEIT, LEAVE, MONKEY, PICK_RULE, PICK_TARGET, SPIN, Engine, Event, GameConfig,
                  IllegalIntent, Intent, PlayerRef, Question, Result, ResultRow)

__all__ = ["ANSWER", "DRAW_CARD", "FORFEIT", "LEAVE", "MONKEY", "PICK_RULE", "PICK_TARGET", "SPIN", "Engine", "Event",
           "GameConfig", "IllegalIntent", "Intent", "PlayerRef", "Question", "Result", "ResultRow", "get_engine"]


def get_engine(mode: str):
    if mode == "bamboozled":
        from .bamboozled import BamboozledEngine
        return BamboozledEngine()
    if mode == "fff":
        from .fff import FastestFingersEngine
        return FastestFingersEngine()
    if mode == "survival":
        from .survival import SurvivalEngine
        return SurvivalEngine()
    raise ValueError(f"unknown mode {mode!r}")
