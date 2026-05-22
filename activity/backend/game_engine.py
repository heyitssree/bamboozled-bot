from __future__ import annotations

import logging
import random
from typing import Optional

from models import (
    AnswerResult,
    BamboozleCard,
    CardType,
    CARD_DESCRIPTIONS,
    CARD_LABELS,
    DIFFICULTY_BASE_POINTS,
    GamePhase,
    GameState,
    GOLDEN_MONKEY_MULTIPLIER,
    MAX_STREAK_BONUS,
    MIST_DURATION,
    CONSECUTIVE_STREAK_BONUS,
    POINT_THIEF_AMOUNT,
    WheelOutcome,
    WheelResult,
    WHEEL_LABELS,
    WHEEL_WEIGHTS,
)

logger = logging.getLogger("navi.activity.engine")


class BamboozledEngine:

    async def spin_wheel(self, state: GameState) -> WheelResult:
        population = list(WHEEL_WEIGHTS.keys())
        weights = [WHEEL_WEIGHTS[o] for o in population]
        outcome = random.choices(population, weights=weights, k=1)[0]

        affected_player_id: Optional[str] = None
        if outcome == WheelOutcome.SOMBRERO:
            # Pick a random connected player (excluding current sombrero holder if possible)
            connected = [
                pid for pid, p in state.players.items()
                if p.is_connected and not p.has_sombrero
            ]
            if not connected:
                connected = [pid for pid, p in state.players.items() if p.is_connected]
            if connected:
                affected_player_id = random.choice(connected)

        return WheelResult(
            outcome=outcome,
            label=WHEEL_LABELS[outcome],
            affected_player_id=affected_player_id,
        )

    async def draw_card(self, state: GameState) -> BamboozleCard:
        card_type = random.choice(list(CardType))
        return BamboozleCard(
            card_type=card_type,
            label=CARD_LABELS[card_type],
            description=CARD_DESCRIPTIONS[card_type],
        )

    async def apply_wheel_effects(self, state: GameState) -> GameState:
        """Apply wheel outcome side-effects to state (called after wheel ACK)."""
        if state.wheel_result is None:
            return state

        outcome = state.wheel_result.outcome

        if outcome == WheelOutcome.MYSTIC_MIST:
            state.mist_active = True
            state.mist_turns_remaining = MIST_DURATION

        elif outcome == WheelOutcome.SOMBRERO and state.wheel_result.affected_player_id:
            # Remove sombrero from previous holder
            for p in state.players.values():
                p.has_sombrero = False
                p.sombrero_forgiven = False
            target = state.players.get(state.wheel_result.affected_player_id)
            if target:
                target.has_sombrero = True

        return state

    async def process_answer(
        self,
        state: GameState,
        player_id: str,
        answer_index: int,
    ) -> AnswerResult:
        player = state.players[player_id]
        question = state.current_question
        assert question is not None

        effective_index = answer_index
        # REVERSE card: swap correct/wrong judgement
        if player.reverse_active:
            # Any index that isn't the correct answer is treated as correct
            is_correct_raw = answer_index != question.correct_index
            player.reverse_active = False
        else:
            is_correct_raw = answer_index == question.correct_index

        # Sombrero: one forgiven wrong answer
        if not is_correct_raw and player.has_sombrero and not player.sombrero_forgiven:
            is_correct_raw = True
            player.sombrero_forgiven = True

        base = DIFFICULTY_BASE_POINTS.get(question.difficulty, 100)

        # Golden Monkey multiplier
        wheel_outcome = state.wheel_result.outcome if state.wheel_result else WheelOutcome.NORMAL
        golden = wheel_outcome == WheelOutcome.GOLDEN_MONKEY

        applied_card: Optional[BamboozleCard] = None

        if is_correct_raw:
            player.consecutive_correct += 1
            streak_bonus = min(
                player.consecutive_correct * CONSECUTIVE_STREAK_BONUS,
                MAX_STREAK_BONUS,
            )
            delta = base + streak_bonus
            if golden:
                delta = int(delta * GOLDEN_MONKEY_MULTIPLIER)
            if player.double_down_active:
                delta *= 2
                player.double_down_active = False
        else:
            player.consecutive_correct = 0
            delta = -base
            if player.double_down_active:
                delta *= 2
                player.double_down_active = False

            # BAMBOOZLE spin: draw and apply a card on wrong answer
            if wheel_outcome == WheelOutcome.BAMBOOZLE:
                card = await self.draw_card(state)
                applied_card = card
                state.active_card = card
                await self._apply_card_immediate(state, player_id, card)

        player.score += delta
        player.score = max(0, player.score)  # floor at 0
        state.answers_this_round[player_id] = answer_index

        return AnswerResult(
            player_id=player_id,
            answer_index=answer_index,
            is_correct=is_correct_raw,
            points_delta=delta,
            streak=player.consecutive_correct,
            card_applied=applied_card,
        )

    async def _apply_card_immediate(
        self,
        state: GameState,
        player_id: str,
        card: BamboozleCard,
    ) -> None:
        player = state.players[player_id]

        if card.card_type == CardType.POINT_THIEF:
            others = [
                pid for pid, p in state.players.items()
                if pid != player_id and p.is_connected and p.score > 0
            ]
            if others:
                victim_id = random.choice(others)
                victim = state.players[victim_id]
                steal = min(POINT_THIEF_AMOUNT, victim.score)
                victim.score -= steal
                player.score += steal

        elif card.card_type == CardType.FREEZE:
            player.frozen_turns += 1

        elif card.card_type == CardType.DOUBLE_DOWN:
            player.double_down_active = True

        elif card.card_type == CardType.BLIND_ANSWER:
            player.blind_answer_active = True

        elif card.card_type == CardType.REVERSE:
            player.reverse_active = True

    async def advance_turn(self, state: GameState) -> GameState:
        """Move to the next player, incrementing the round when the cycle wraps."""
        if state.mist_active:
            state.mist_turns_remaining -= 1
            if state.mist_turns_remaining <= 0:
                state.mist_active = False
                state.mist_turns_remaining = 0

        connected = [pid for pid in state.join_order if state.players[pid].is_connected]
        if not connected:
            return state

        if state.current_player_id is None:
            state.current_player_id = connected[0]
            return state

        try:
            idx = connected.index(state.current_player_id)
        except ValueError:
            idx = -1

        next_idx = (idx + 1) % len(connected)

        # If we wrapped around, increment the round
        if next_idx == 0:
            state.round_number += 1

        state.current_player_id = connected[next_idx]

        # Skip frozen players (consume one frozen turn)
        visited = 0
        while state.players[state.current_player_id].frozen_turns > 0 and visited < len(connected):
            state.players[state.current_player_id].frozen_turns -= 1
            next_idx = (next_idx + 1) % len(connected)
            if next_idx == 0:
                state.round_number += 1
            state.current_player_id = connected[next_idx]
            visited += 1

        # Clear per-round answer map for new question
        state.answers_this_round = {}
        state.active_card = None
        state.wheel_result = None
        state.current_question = None

        return state

    async def check_win(self, state: GameState) -> bool:
        return state.round_number > state.config.total_rounds

    def calculate_boli(self, state: GameState) -> dict[str, int]:
        """Map discord_id → boli award based on final rankings."""
        if not state.players:
            return {}

        sorted_players = sorted(
            state.players.values(),
            key=lambda p: p.score,
            reverse=True,
        )
        awards: dict[str, int] = {}
        boli_tiers = [50, 30, 20]  # 1st, 2nd, 3rd

        for i, player in enumerate(sorted_players):
            boli = boli_tiers[i] if i < len(boli_tiers) else 10
            # Participation bonus (top-3 get extra)
            awards[player.discord_id] = boli

        return awards
