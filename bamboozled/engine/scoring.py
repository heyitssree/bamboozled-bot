"""Ranking and the FFF / Survival maths."""
from typing import Iterable, Optional

FFF_FIRST = 100
FFF_LATER = 75


def rank_order(scores: dict[int, int], seats: Iterable[int], winner: Optional[int] = None) -> list[int]:
    """Players best first. Ties keep seat order (a stable sort), matching the old game; `winner` is forced first."""
    order = sorted(seats, key=lambda p: scores.get(p, 0), reverse=True)
    if winner is not None and winner in order:
        order.remove(winner)
        order.insert(0, winner)
    return order


def final_order(scores: dict[int, int], seats: Iterable[int], winner: Optional[int] = None) -> list[int]:
    """Final standings: score high to low, ties by user id (the same order the database uses), `winner` first."""
    order = sorted(seats, key=lambda p: (-scores.get(p, 0), p))
    if winner is not None and winner in order:
        order.remove(winner)
        order.insert(0, winner)
    return order


def top_scorers(scores: dict[int, int], seats: Iterable[int]) -> list[int]:
    seats = list(seats)
    if not seats:
        return []
    best = max(scores.get(p, 0) for p in seats)
    return [p for p in rank_order(scores, seats) if scores.get(p, 0) == best]


def is_new_best(streak: int, previous_best: int, reason: str) -> bool:
    """Survival personal best: strictly higher, above zero, and the run ended by a wrong answer or timeout.
    Giving up and fetch errors never count."""
    return streak > previous_best and streak > 0 and reason in ("wrong", "timeout")
