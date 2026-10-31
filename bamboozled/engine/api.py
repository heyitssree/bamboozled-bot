"""The rules-engine contract. PURE: no I/O, no clocks, no discord, no asyncio.

All randomness comes from the Random stored in the state (seeded from the `rng` given to new_game); time is the
`now_ms` argument. `apply` and friends never modify the state they are given; they return a new one.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence

MODES = ("bamboozled", "fff", "survival")

# Intent kinds a client can send. The server validates every one against the engine state and the sender.
ANSWER, DRAW_CARD, SPIN, PICK_TARGET, PICK_RULE, MONKEY, FORFEIT, LEAVE = (
    "ANSWER", "DRAW_CARD", "SPIN", "PICK_TARGET", "PICK_RULE", "MONKEY", "FORFEIT", "LEAVE")

# Names accepted in GameConfig.legacy_quirks (see docs/rules-as-implemented.md section 5).
LEGACY_QUIRKS = frozenset({"afk_skip", "mist_short", "wango_again_reset", "golden_pass_wrong_only"})


class IllegalIntent(Exception):
    """A client sent something the engine will not do. `code` is machine readable (not_your_turn, bad_phase, ...)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PlayerRef:
    user_id: int


@dataclass(frozen=True)
class Question:
    text: str
    answers: tuple[str, ...]          # exactly 4 for multiple choice (2 for true/false)
    correct_index: int
    category: str = ""
    difficulty: str = "medium"
    qtype: str = "multiple"           # "multiple" | "boolean"

    def public(self) -> dict:
        """What a client may see before the reveal: never the correct index."""
        return {"text": self.text, "answers": list(self.answers), "category": self.category,
                "difficulty": self.difficulty, "qtype": self.qtype}


@dataclass(frozen=True)
class Intent:
    kind: str
    index: Optional[int] = None        # ANSWER
    user_id: Optional[int] = None      # PICK_TARGET (None = skip, where allowed)
    rule_id: Optional[int] = None      # PICK_RULE
    choice: Optional[str] = None       # MONKEY: "belly" | "tail"


@dataclass(frozen=True)
class Event:
    """Animation and log cue for clients. Never needed to reconstruct state."""
    kind: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ResultRow:
    user_id: int
    rank: int
    score: int
    correct: int = 0
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GameConfig:
    mode: str = "bamboozled"
    rounds: int = 5                       # bamboozled rounds | fff questions
    difficulty: Optional[str] = None
    category: Optional[str] = None
    question_timeout_ms: int = 30_000
    monkey_timeout_ms: int = 15_000
    pick_timeout_ms: int = 20_000
    draw_timeout_ms: int = 10_000
    law_timeout_ms: int = 70_000
    fff_question_ms: int = 10_000
    survival_question_ms: int = 15_000
    starting_points: int = 500
    mist_turns: int = 2
    afk_kick_turns: int = 2
    legacy_quirks: frozenset = frozenset()

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"unknown mode {self.mode!r}")
        unknown = set(self.legacy_quirks) - LEGACY_QUIRKS
        if unknown:
            raise ValueError(f"unknown legacy quirk(s): {sorted(unknown)}")


@dataclass(frozen=True)
class Result:
    state: Any
    events: tuple[Event, ...] = ()


class Engine(Protocol):
    mode: str

    def new_game(self, cfg: GameConfig, players: Sequence[PlayerRef], rng: random.Random, now_ms: int) -> Any: ...
    def apply(self, state: Any, actor: int, intent: Intent, now_ms: int) -> Result: ...      # raises IllegalIntent
    def on_timeout(self, state: Any, now_ms: int) -> Result: ...                              # server calls at next_deadline_ms()
    def needs_question(self, state: Any) -> Optional[dict]: ...                               # {"kind", "qtype", "actor"}
    def supply_question(self, state: Any, question: Question, now_ms: int) -> Result: ...
    def view_for(self, state: Any, viewer: Optional[int]) -> dict: ...                        # per-player projection
    def next_deadline_ms(self, state: Any) -> Optional[int]: ...
    def is_over(self, state: Any) -> bool: ...
    def results(self, state: Any) -> list[ResultRow]: ...
