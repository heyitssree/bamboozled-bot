from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class GamePhase(str, Enum):
    LOBBY = "LOBBY"
    WHEEL = "WHEEL"
    QUESTION = "QUESTION"
    CARD = "CARD"
    REVEAL = "REVEAL"
    ENDED = "ENDED"


class WheelOutcome(str, Enum):
    NORMAL = "NORMAL"
    BAMBOOZLE = "BAMBOOZLE"
    GOLDEN_MONKEY = "GOLDEN_MONKEY"
    MYSTIC_MIST = "MYSTIC_MIST"
    SOMBRERO = "SOMBRERO"


class CardType(str, Enum):
    POINT_THIEF = "POINT_THIEF"
    FREEZE = "FREEZE"
    DOUBLE_DOWN = "DOUBLE_DOWN"
    BLIND_ANSWER = "BLIND_ANSWER"
    REVERSE = "REVERSE"


WHEEL_WEIGHTS = {
    WheelOutcome.NORMAL: 35,
    WheelOutcome.BAMBOOZLE: 25,
    WheelOutcome.GOLDEN_MONKEY: 15,
    WheelOutcome.MYSTIC_MIST: 15,
    WheelOutcome.SOMBRERO: 10,
}

WHEEL_LABELS = {
    WheelOutcome.NORMAL: "Normal Round",
    WheelOutcome.BAMBOOZLE: "Bamboozle!",
    WheelOutcome.GOLDEN_MONKEY: "Golden Monkey",
    WheelOutcome.MYSTIC_MIST: "Mystic Mist",
    WheelOutcome.SOMBRERO: "El Sombrero",
}

CARD_LABELS = {
    CardType.POINT_THIEF: "Point Thief",
    CardType.FREEZE: "Freeze",
    CardType.DOUBLE_DOWN: "Double Down",
    CardType.BLIND_ANSWER: "Blind Answer",
    CardType.REVERSE: "Reverse",
}

CARD_DESCRIPTIONS = {
    CardType.POINT_THIEF: "Steal 50 points from a random opponent.",
    CardType.FREEZE: "Skip your next turn.",
    CardType.DOUBLE_DOWN: "Your next question is worth double — win or lose.",
    CardType.BLIND_ANSWER: "Answer your next question without seeing the options.",
    CardType.REVERSE: "Correct and wrong answers are swapped for your next question.",
}

DIFFICULTY_BASE_POINTS = {
    "easy": 50,
    "medium": 100,
    "hard": 150,
}

GOLDEN_MONKEY_MULTIPLIER = 2.0
CONSECUTIVE_STREAK_BONUS = 10
MAX_STREAK_BONUS = 50
POINT_THIEF_AMOUNT = 50
MIST_DURATION = 3  # turns


@dataclass
class Player:
    discord_id: str
    username: str
    avatar_url: str
    score: int = 0
    has_sombrero: bool = False
    consecutive_correct: int = 0
    is_connected: bool = True
    frozen_turns: int = 0            # turns remaining for FREEZE card
    double_down_active: bool = False  # DOUBLE_DOWN card pending
    blind_answer_active: bool = False  # BLIND_ANSWER card pending
    reverse_active: bool = False      # REVERSE card pending
    sombrero_forgiven: bool = False   # sombrero protection used flag


@dataclass
class Question:
    text: str
    correct_answer: str
    incorrect_answers: list[str]
    shuffled_answers: list[str]
    correct_index: int
    category: str
    difficulty: str


@dataclass
class WheelResult:
    outcome: WheelOutcome
    label: str
    affected_player_id: Optional[str] = None  # for SOMBRERO


@dataclass
class BamboozleCard:
    card_type: CardType
    label: str
    description: str


@dataclass
class AnswerResult:
    player_id: str
    answer_index: int
    is_correct: bool
    points_delta: int
    streak: int
    card_applied: Optional[BamboozleCard] = None


@dataclass
class GameConfig:
    total_rounds: int = 10
    category: Optional[str] = None
    difficulty: str = "medium"
    time_per_question: int = 30


@dataclass
class GameState:
    session_id: str
    guild_id: str
    channel_id: str
    phase: GamePhase
    players: dict[str, Player]          # discord_id → Player
    join_order: list[str]               # discord_ids in join order
    host_id: str
    current_question: Optional[Question]
    current_player_id: Optional[str]
    wheel_result: Optional[WheelResult]
    active_card: Optional[BamboozleCard]
    mist_active: bool
    mist_turns_remaining: int
    round_number: int
    config: GameConfig
    answers_this_round: dict[str, int]  # player_id → answer_index (-1 = no answer)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "phase": self.phase.value,
            "players": {
                pid: {
                    "discord_id": p.discord_id,
                    "username": p.username,
                    "avatar_url": p.avatar_url,
                    "score": p.score,
                    "has_sombrero": p.has_sombrero,
                    "consecutive_correct": p.consecutive_correct,
                    "is_connected": p.is_connected,
                    "frozen_turns": p.frozen_turns,
                    "double_down_active": p.double_down_active,
                    "blind_answer_active": p.blind_answer_active,
                    "reverse_active": p.reverse_active,
                }
                for pid, p in self.players.items()
            },
            "join_order": self.join_order,
            "host_id": self.host_id,
            "current_question": (
                {
                    "text": self.current_question.text,
                    "shuffled_answers": self.current_question.shuffled_answers,
                    "category": self.current_question.category,
                    "difficulty": self.current_question.difficulty,
                    # correct_index is withheld until REVEAL phase
                }
                if self.current_question and self.phase != GamePhase.REVEAL
                else (
                    {
                        "text": self.current_question.text,
                        "shuffled_answers": self.current_question.shuffled_answers,
                        "correct_index": self.current_question.correct_index,
                        "category": self.current_question.category,
                        "difficulty": self.current_question.difficulty,
                    }
                    if self.current_question
                    else None
                )
            ),
            "current_player_id": self.current_player_id,
            "wheel_result": (
                {
                    "outcome": self.wheel_result.outcome.value,
                    "label": self.wheel_result.label,
                    "affected_player_id": self.wheel_result.affected_player_id,
                }
                if self.wheel_result
                else None
            ),
            "active_card": (
                {
                    "card_type": self.active_card.card_type.value,
                    "label": self.active_card.label,
                    "description": self.active_card.description,
                }
                if self.active_card
                else None
            ),
            "mist_active": self.mist_active,
            "mist_turns_remaining": self.mist_turns_remaining,
            "round_number": self.round_number,
            "total_rounds": self.config.total_rounds,
            "answers_this_round": self.answers_this_round,
            "config": {
                "total_rounds": self.config.total_rounds,
                "category": self.config.category,
                "difficulty": self.config.difficulty,
                "time_per_question": self.config.time_per_question,
            },
        }
