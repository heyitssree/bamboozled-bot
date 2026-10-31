"""Where questions come from. Phase 3 ships the offline source only; Phase 6 adds the live sources and the safety
screen in this same place, so every mode shares it. A game never blocks on trivia: this source cannot fail."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

from ..engine import Question

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
