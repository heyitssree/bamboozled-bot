"""Characterisation of the legacy Bamboozled rules (cogs/game.py + game_engine/).

Each test pins what the code does today, driven by scripted decisions. The Phase 2 engine must reproduce these
outcomes (or the difference goes in the 'Intended differences' list). Expected numbers are derived from
docs/rules-as-implemented.md, which was written from the code.
"""
import pytest

from game_engine import bamboozle_rules as R
from game_engine.cards import ChanceCard, WangoCard
from game_engine.constants import MAX_SINGLE_SWING_FIXED
from game_engine.wheel import WheelSegment, monkey_choice_segment
from tests.legacy_harness import Script, legacy_env, make_game, run, snapshot

C, W, S = ChanceCard, WangoCard, WheelSegment


def chance(card, game=None, **script_kw):
    game = game or make_game()
    script = Script(**script_kw)
    with legacy_env(script, game) as (cog, ch):
        run(cog._apply_chance_card(ch, game, 1, card))
    assert not script.leftover(), script.leftover()
    return game, script, ch


def wango(card, game=None, depth=0, **script_kw):
    game = game or make_game()
    script = Script(**script_kw)
    with legacy_env(script, game) as (cog, ch):
        run(cog._apply_wango_card(ch, game, 1, card, chain_depth=depth))
    assert not script.leftover(), script.leftover()
    return game, script, ch


def wheel(segment, game=None, depth=0, pid=1, **script_kw):
    game = game or make_game()
    script = Script(**script_kw)
    with legacy_env(script, game) as (cog, ch):
        run(cog._apply_wheel_segment(ch, game, pid, segment, depth))
    assert not script.leftover(), script.leftover()
    return game, script, ch


# ───────────────────────────── GameState basics ─────────────────────────────

class TestGameStateRules:
    def test_apply_points_caps_a_single_swing_at_300(self):
        g = make_game()
        assert g.apply_points(1, 1000) == MAX_SINGLE_SWING_FIXED
        assert g.apply_points(1, -1000) == -MAX_SINGLE_SWING_FIXED
        assert g.scores[1] == 500
        assert g.apply_points(1, 1000, bypass_cap=True) == 1000 and g.scores[1] == 1500

    def test_turn_order_wraps_and_counts_rounds(self):
        g = make_game(3)
        order = []
        for _ in range(7):
            order.append((g.current_round, g.current_player_id()))
            g.advance_turn()
        assert order == [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3), (3, 1)]

    def test_next_player_wraps(self):
        g = make_game(3)
        assert [g.next_player_in_order(p) for p in (1, 2, 3)] == [2, 3, 1]

    def test_non_permanent_rule_lasts_one_full_rotation(self):
        g = make_game(3)
        g.active_bamboozle_rule = R.make_active_rule(1, 3)
        expired = [g.advance_turn() for _ in range(3)]
        assert expired == [False, False, True] and g.active_bamboozle_rule is None

    def test_permanent_rule_never_expires(self):
        g = make_game(3)
        g.active_bamboozle_rule = R.make_active_rule(10, 3)
        assert not any(g.advance_turn() for _ in range(30)) and g.active_bamboozle_rule["id"] == 10

    def test_mist_lifts_after_two_ticks_and_hides_scores(self):
        g = make_game(3)
        g.activate_mist()
        assert g.mist_active and g.mist_turns_remaining == 2
        assert set(g.scores_display().values()) <= {"unknowable", "somewhere between bad and worse",
                                                    "the mist conceals this", "??", "lost in the fog"}
        assert g.decrement_mist() is False and g.mist_active
        assert g.decrement_mist() is True and not g.mist_active
        assert g.scores_display() == {1: "500", 2: "500", 3: "500"}

    def test_decrement_without_mist_is_a_noop(self):
        assert make_game().decrement_mist() is False

    def test_reset_for_new_game_restores_lobby_state(self):
        g = make_game(2)
        g.scores = {1: 10, 2: 20}
        g.golden_pass[1] = True
        g.sombrero_holder = 2
        g.activate_mist()
        g.reset_for_new_game()
        assert g.scores == {1: 500, 2: 500} and not g.golden_pass and g.sombrero_holder is None
        assert not g.mist_active and g.current_round == 1 and g.players == [1, 2]


# ───────────────────────────── Chance cards ─────────────────────────────

class TestChanceCards:
    def test_lucky_llama(self):
        g, *_ = chance(C.LUCKY_LLAMA)
        assert g.scores == {1: 550, 2: 500, 3: 500}

    def test_golden_pass_sets_flag_only(self):
        g, *_ = chance(C.GOLDEN_PASS)
        assert g.golden_pass == {1: True} and g.scores[1] == 500

    def test_switcheroo_swaps_scores_and_is_one_use(self):
        g = make_game(3, scores={1: 500, 2: 300, 3: 700})
        g, script, _ = chance(C.SWITCHEROO, g, target=[3])
        assert g.scores == {1: 700, 2: 300, 3: 500} and g.switcheroo_used == {1: True}
        assert script.selects == [[2, 3]]          # the picker lists everyone but the drawer

    def test_switcheroo_skip_and_timeout_still_use_the_card(self):
        for pick in ("skip", None):
            g, *_ = chance(C.SWITCHEROO, make_game(3, scores={2: 300}), target=[pick])
            assert g.scores == {1: 500, 2: 300, 3: 500} and g.switcheroo_used == {1: True}

    def test_switcheroo_solo_becomes_llama_and_is_not_consumed(self):
        g, *_ = chance(C.SWITCHEROO, make_game(1))
        assert g.scores == {1: 550} and not g.switcheroo_used

    def test_switcheroo_second_use_becomes_llama(self):
        g = make_game(3)
        g.switcheroo_used[1] = True
        g, *_ = chance(C.SWITCHEROO, g)
        assert g.scores[1] == 550

    @pytest.mark.parametrize("rand,qtype", [(0.29, "boolean"), (0.30, "multiple"), (0.9, "multiple")])
    def test_double_down_question_type_is_30_percent_boolean(self, rand, qtype):
        _, script, _ = chance(C.DOUBLE_DOWN, rand=[rand], answer=[0])
        assert script.fetch_kwargs[0]["question_type"] == qtype

    @pytest.mark.parametrize("answer,delta", [(0, 200), (2, -200), ("timeout", -100)])
    def test_double_down_outcomes(self, answer, delta):
        g, *_ = chance(C.DOUBLE_DOWN, rand=[0.9], answer=[answer])
        assert g.scores[1] == 500 + delta and g.scores[2] == 500

    def test_spin_the_wheel_card_spins_at_depth_zero(self):
        g, *_ = chance(C.SPIN_THE_WHEEL, wheel=[S.BONUS_ROUND])
        assert g.scores[1] == 650

    def test_bamboozle_on_final_round_becomes_llama(self):
        g = make_game(3, total_rounds=5)
        g.current_round = 5
        g, *_ = chance(C.BAMBOOZLE, g)
        assert g.scores[1] == 550 and g.active_bamboozle_rule is None

    @pytest.mark.parametrize("rule_id", range(1, 12))
    def test_bamboozle_sets_each_law(self, rule_id):
        g, *_ = chance(C.BAMBOOZLE, rule=[rule_id])
        permanent = rule_id in (10, 11)
        assert g.active_bamboozle_rule["id"] == rule_id
        assert g.active_bamboozle_rule["turns_remaining"] == (-1 if permanent else 3)
        assert g.mist_turn_duration == (4 if rule_id == 10 else 2)
        assert g.sombrero_penalty == (50 if rule_id == 11 else 25)

    def test_bamboozle_timeout_sets_nothing(self):
        g, *_ = chance(C.BAMBOOZLE, rule=[None])
        assert g.active_bamboozle_rule is None

    def test_bamboozle_replaces_the_current_law(self):
        g = make_game(3)
        g.active_bamboozle_rule = R.make_active_rule(1, 3)
        g, *_ = chance(C.BAMBOOZLE, g, rule=[3])
        assert g.active_bamboozle_rule["id"] == 3


# ───────────────────────────── Wango cards ─────────────────────────────

class TestWangoCards:
    def test_classic_sends_to_the_wheel(self):
        g, *_ = wango(W.WANGO_CLASSIC, wheel=[S.BONUS_ROUND])
        assert g.scores[1] == 650

    def test_silence_marks_player(self):
        g, *_ = wango(W.THE_SILENCE)
        assert g.silenced == {1: True}

    def test_reverse_uno_hits_next_player_in_order(self):
        g, *_ = wango(W.REVERSE_UNO)
        assert g.scores == {1: 500, 2: 400, 3: 500}

    def test_reverse_uno_wraps_from_last_player(self):
        g = make_game(3)
        script = Script()
        with legacy_env(script, g) as (cog, ch):
            run(cog._apply_wango_card(ch, g, 3, W.REVERSE_UNO))
        assert g.scores == {1: 400, 2: 500, 3: 500}

    def test_reverse_uno_solo_does_nothing(self):
        g, *_ = wango(W.REVERSE_UNO, make_game(1))
        assert g.scores == {1: 500}

    def test_sombrero_unclaimed_lands_on_drawer(self):
        g, *_ = wango(W.THE_SOMBRERO)
        assert g.sombrero_holder == 1 and g.sombrero_penalty == 25

    def test_sombrero_drawn_by_holder_flies_to_next_player(self):
        g = make_game(3)
        g.sombrero_holder = 1
        g, *_ = wango(W.THE_SOMBRERO, g)
        assert g.sombrero_holder == 2

    def test_sombrero_drawn_by_solo_holder_raises_penalty(self):
        g = make_game(1)
        g.sombrero_holder = 1
        g, *_ = wango(W.THE_SOMBRERO, g)
        g, *_ = wango(W.THE_SOMBRERO, g)
        assert g.sombrero_holder == 1 and g.sombrero_penalty == 75

    def test_sombrero_is_stolen_from_another_holder(self):
        g = make_game(3)
        g.sombrero_holder = 3
        g.sombrero_penalty = 50
        g, *_ = wango(W.THE_SOMBRERO, g)
        assert g.sombrero_holder == 1 and g.sombrero_penalty == 50

    def test_mystic_mist_activates(self):
        g, *_ = wango(W.MYSTIC_MIST)
        assert g.mist_active and g.mist_turns_remaining == 2

    def test_double_wango_depth0_draws_two_chain_cards_at_depth_one(self):
        g, *_ = wango(W.DOUBLE_WANGO, wango=[W.THE_SILENCE, W.MYSTIC_MIST])
        assert g.silenced == {1: True} and g.mist_active

    def test_double_wango_depth1_draws_one(self):
        g, *_ = wango(W.DOUBLE_WANGO, depth=1, wango=[W.THE_SILENCE])
        assert g.silenced == {1: True} and not g.mist_active

    def test_double_wango_at_chain_limit_draws_nothing(self):
        g, *_ = wango(W.DOUBLE_WANGO, depth=2)
        assert snapshot(g) == snapshot(make_game(3))

    def test_double_wango_chain_card_that_is_double_wango_is_rerolled(self):
        g, *_ = wango(W.DOUBLE_WANGO, wango=[W.DOUBLE_WANGO, W.THE_SILENCE, W.MYSTIC_MIST])
        assert g.silenced == {1: True} and g.mist_active

    def test_double_wango_rerolled_twice_is_skipped(self):
        g, *_ = wango(W.DOUBLE_WANGO, wango=[W.DOUBLE_WANGO, W.DOUBLE_WANGO, W.MYSTIC_MIST])
        assert not g.silenced and g.mist_active

    def test_chain_cards_apply_in_order_so_a_chained_mist_is_one_activation(self):
        g, *_ = wango(W.DOUBLE_WANGO, wango=[W.MYSTIC_MIST, W.MYSTIC_MIST])
        assert g.mist_turns_remaining == 2


# ───────────────────────────── Wheel of Mayhem ─────────────────────────────

class TestWheel:
    @pytest.mark.parametrize("score,after", [(500, 400), (30, 20), (0, -10), (-200, -240), (3000, 2400), (54, 44)])
    def test_tax_season_is_20_percent_min_10_and_ignores_the_cap(self, score, after):
        g, *_ = wheel(S.TAX_SEASON, make_game(3, scores={1: score}))
        assert g.scores[1] == after

    def test_bonus_round(self):
        g, *_ = wheel(S.BONUS_ROUND)
        assert g.scores[1] == 650

    def test_mystic_mist_segment(self):
        g, *_ = wheel(S.MYSTIC_MIST)
        assert g.mist_active and g.mist_turns_remaining == 2

    def test_mist_magnet_makes_the_mist_four_turns(self):
        g = make_game(3)
        g.mist_turn_duration = 4
        g, *_ = wheel(S.MYSTIC_MIST, g)
        assert g.mist_turns_remaining == 4

    def test_gift_steals_100_from_chosen_target(self):
        g, script, _ = wheel(S.GIFT_OF_THE_BAMBOOZLE, target=[3])
        assert g.scores == {1: 600, 2: 500, 3: 400} and script.selects == [[2, 3]]

    def test_gift_timeout_changes_nothing(self):
        g, *_ = wheel(S.GIFT_OF_THE_BAMBOOZLE, target=[None])
        assert g.scores == {1: 500, 2: 500, 3: 500}

    def test_gift_solo_steals_from_the_bank(self):
        g, *_ = wheel(S.GIFT_OF_THE_BAMBOOZLE, make_game(1))
        assert g.scores == {1: 600}

    def test_gift_can_push_a_target_negative_without_cap(self):
        g, *_ = wheel(S.GIFT_OF_THE_BAMBOOZLE, make_game(3, scores={3: 20}), target=[3])
        assert g.scores[3] == -80

    def test_full_reversal_swaps_scores_in_reverse_rank_order(self):
        g, *_ = wheel(S.FULL_REVERSAL, make_game(3, scores={1: 500, 2: 300, 3: 700}))
        assert g.scores == {1: 500, 2: 700, 3: 300}

    def test_full_reversal_with_ties_uses_player_order_for_equal_scores(self):
        g, *_ = wheel(S.FULL_REVERSAL, make_game(4, scores={1: 100, 2: 400, 3: 400, 4: 900}))
        # ranked (stable): 4(900), 2(400), 3(400), 1(100) -> values reversed [100, 400, 400, 900]
        assert g.scores == {1: 900, 2: 400, 3: 400, 4: 100}

    def test_full_reversal_solo_negates_score(self):
        g, *_ = wheel(S.FULL_REVERSAL, make_game(1, scores={1: 250}))
        assert g.scores == {1: -250}

    def test_ladder_of_chance_runs_the_golden_monkey(self):
        g, *_ = wheel(S.LADDER_OF_CHANCE, rand=[0.1], monkey=["belly"])
        assert g.scores[1] == 800

    def test_wango_again_at_depth_zero_draws_and_applies_a_wango_card(self):
        g, *_ = wheel(S.WANGO_AGAIN, wango=[W.THE_SILENCE])
        assert g.silenced == {1: True} and g.scores[1] == 500

    def test_wango_again_drawing_classic_spins_a_capped_wheel(self):
        g, *_ = wheel(S.WANGO_AGAIN, wango=[W.WANGO_CLASSIC], wheel=[S.TAX_SEASON])
        assert g.scores[1] == 400

    def test_capped_wheel_turns_wango_again_into_bonus_round(self):
        g, *_ = wheel(S.WANGO_AGAIN, wango=[W.WANGO_CLASSIC], wheel=[S.WANGO_AGAIN])
        assert g.scores[1] == 650

    def test_capped_wheel_monkeys_choice_that_lands_on_wango_again_is_also_capped(self):
        g, *_ = wheel(S.WANGO_AGAIN, wango=[W.WANGO_CLASSIC], wheel=[S.MONKEYS_CHOICE], monkey_seg=[S.WANGO_AGAIN])
        assert g.scores[1] == 650

    def test_wango_again_at_depth_limit_pays_bonus_round_without_drawing(self):
        g, *_ = wheel(S.WANGO_AGAIN, depth=1)
        assert g.scores[1] == 650

    def test_wheel_inside_wango_again_chain_can_still_double_wango(self):
        g, *_ = wheel(S.WANGO_AGAIN, wango=[W.DOUBLE_WANGO, W.THE_SILENCE, W.MYSTIC_MIST])
        assert g.silenced == {1: True} and g.mist_active

    def test_monkeys_choice_is_resolved_into_a_concrete_segment(self):
        g = make_game()
        script = Script(wheel=[S.MONKEYS_CHOICE], monkey_seg=[S.BONUS_ROUND])
        with legacy_env(script, g) as (cog, ch):
            run(cog._spin_wheel(ch, g, 1, wheel_depth=0))
        assert g.scores[1] == 650 and not script.leftover()

    def test_monkey_choice_segment_never_returns_monkeys_choice(self):
        assert all(monkey_choice_segment() != S.MONKEYS_CHOICE for _ in range(500))

    def test_spin_wheel_reaches_all_eight_segments(self):
        from game_engine.wheel import spin_wheel
        assert {spin_wheel() for _ in range(2000)} == set(S)


# ───────────────────────────── Golden Monkey ─────────────────────────────

class TestGoldenMonkey:
    def monkey(self, rand, choice, wango_cards=()):
        g = make_game()
        script = Script(rand=[rand], monkey=[choice], wango=list(wango_cards))
        with legacy_env(script, g) as (cog, ch):
            run(cog._golden_monkey(ch, g, 1))
        assert not script.leftover(), script.leftover()
        return g

    def test_belly_when_belly_is_lucky(self):
        assert self.monkey(0.1, "belly").scores[1] == 800

    def test_tail_when_belly_is_lucky_costs_200_and_draws_a_wango_card(self):
        g = self.monkey(0.1, "tail", [W.THE_SILENCE])
        assert g.scores[1] == 300 and g.silenced == {1: True}

    def test_belly_when_tail_is_lucky_costs_200_and_draws_a_wango_card(self):
        g = self.monkey(0.9, "belly", [W.MYSTIC_MIST])
        assert g.scores[1] == 300 and g.mist_active

    def test_tail_when_tail_is_lucky(self):
        assert self.monkey(0.9, "tail").scores[1] == 800

    def test_timeout_defaults_to_tail_so_a_lucky_belly_means_a_penalty_and_wango(self):
        g = make_game()
        script = Script(rand=[0.1], monkey=[None], wango=[W.THE_SILENCE])
        with legacy_env(script, g) as (cog, ch):
            run(cog._golden_monkey(ch, g, 1))
        assert g.scores[1] == 300 and g.silenced == {1: True}

    def test_timeout_when_tail_is_lucky_pays_300_with_no_wango(self):
        g = make_game()
        script = Script(rand=[0.9], monkey=[None])
        with legacy_env(script, g) as (cog, ch):
            run(cog._golden_monkey(ch, g, 1))
        assert g.scores[1] == 800

    def test_belly_is_lucky_below_one_half(self):
        assert self.monkey(0.499, "belly").scores[1] == 800
        assert self.monkey(0.5, "belly", [W.THE_SILENCE]).scores[1] == 300


# ───────────────────────────── Bamboozle laws (pure functions) ─────────────────────────────

class TestLaws:
    def test_catalogue(self):
        assert [(r.id, r.is_permanent) for r in R.BAMBOOZLE_RULES] == [(i, i >= 10) for i in range(1, 12)]

    def test_effective_penalties(self):
        assert R.get_effective_wrong_penalty(None) == -50
        assert R.get_effective_wrong_penalty({"id": 3}) == -100
        assert R.get_effective_timeout_penalty(None) == -100
        assert R.get_effective_timeout_penalty({"id": 7}) == -200

    def test_karma_tax_hits_everyone_tied_for_first(self):
        g = make_game(3, scores={1: 700, 2: 700, 3: 100})
        rule = R.make_active_rule(5, 3)
        R.apply_start_of_turn(rule, g, 1)
        R.apply_start_of_turn(rule, g, 3)
        assert g.scores == {1: 650, 2: 700, 3: 100}

    def test_underdog_boost_helps_last_place_including_ties(self):
        g = make_game(3, scores={1: 700, 2: 100, 3: 100})
        rule = R.make_active_rule(6, 3)
        for p in (1, 2, 3):
            R.apply_start_of_turn(rule, g, p)
        assert g.scores == {1: 700, 2: 150, 3: 150}

    def test_speed_tax_only_when_under_five_seconds(self):
        g = make_game()
        rule = R.make_active_rule(1, 3)
        g.answer_time_seconds = 4.9
        assert R.apply_after_correct(rule, g, 1) and g.scores[1] == 475
        g.answer_time_seconds = 5.0
        assert R.apply_after_correct(rule, g, 1) is None and g.scores[1] == 475

    def test_slow_burn_only_when_over_twenty_seconds(self):
        g = make_game()
        rule = R.make_active_rule(2, 3)
        g.answer_time_seconds = 20.0
        assert R.apply_after_wrong_or_timeout(rule, g, 1) is None
        g.answer_time_seconds = 20.1
        assert R.apply_after_wrong_or_timeout(rule, g, 1) and g.scores[1] == 450

    def test_hot_streak_needs_two_in_a_row(self):
        g = make_game()
        rule = R.make_active_rule(4, 3)
        g.consecutive_correct[1] = 1
        assert R.apply_after_correct(rule, g, 1) is None
        g.consecutive_correct[1] = 2
        assert R.apply_after_correct(rule, g, 1) and g.scores[1] == 575

    def test_lucky_last_pays_the_last_seat_in_turn_order(self):
        g = make_game(3)
        rule = R.make_active_rule(8, 3)
        g.current_turn_index = 1
        assert R.apply_after_correct(rule, g, 2) is None
        g.current_turn_index = 2
        assert R.apply_after_correct(rule, g, 3) and g.scores[3] == 600

    def test_permanent_rules_apply_on_set(self):
        g = make_game()
        R.apply_on_set(R.make_active_rule(10, 3), g)
        R.apply_on_set(R.make_active_rule(11, 3), g)
        assert g.mist_turn_duration == 4 and g.sombrero_penalty == 50

    def test_unknown_rule_is_an_error(self):
        with pytest.raises(ValueError):
            R.make_active_rule(99, 3)


# ───────────────────────────── A full turn ─────────────────────────────

def turn(game, pid=1, **script_kw):
    script = Script(**script_kw)
    with legacy_env(script, game) as (cog, ch):
        run(cog._run_turn(ch, game, pid))
    assert not script.leftover(), script.leftover()
    return game, script, ch


class TestTurn:
    def test_correct_answer_scores_100_then_draws_a_chance_card(self):
        g, *_ = turn(make_game(), answer=[0], chance=[C.LUCKY_LLAMA])
        assert g.scores[1] == 650 and g.consecutive_correct[1] == 1 and g.correct_answer_count[1] == 1
        assert g.afk_turns[1] == 0

    def test_wrong_answer_costs_50_then_draws_a_wango_card(self):
        g, *_ = turn(make_game(), answer=[2], wango=[W.THE_SILENCE])
        assert g.scores[1] == 450 and g.silenced == {1: True} and g.consecutive_correct[1] == 0

    def test_wrong_answer_with_sombrero_costs_extra(self):
        g = make_game()
        g.sombrero_holder = 1
        g, *_ = turn(g, answer=[1], wango=[W.MYSTIC_MIST])
        assert g.scores[1] == 500 - 50 - 25

    def test_sombrero_does_not_penalise_other_players(self):
        g = make_game()
        g.sombrero_holder = 2
        g, *_ = turn(g, answer=[1], wango=[W.MYSTIC_MIST])
        assert g.scores[1] == 450

    def test_golden_pass_cancels_the_wango_card_and_is_spent(self):
        g = make_game()
        g.golden_pass[1] = True
        g, *_ = turn(g, answer=[1])        # no wango draw is scripted: drawing would fail the test
        assert g.scores[1] == 450 and g.golden_pass[1] is False

    def test_golden_pass_is_not_spent_on_a_correct_answer(self):
        g = make_game()
        g.golden_pass[1] = True
        g, *_ = turn(g, answer=[0], chance=[C.GOLDEN_PASS])
        assert g.golden_pass[1] is True

    def test_timeout_costs_100_resets_streak_counts_afk_and_draws_nothing(self):
        g = make_game()
        g.consecutive_correct[1] = 2
        g, *_ = turn(g, answer=["timeout"])
        assert g.scores[1] == 400 and g.consecutive_correct[1] == 0 and g.afk_turns[1] == 1
        assert not g.silenced

    def test_two_timeouts_in_a_row_accumulate_afk(self):
        g = make_game()
        turn(g, answer=["timeout"])
        turn(g, answer=["timeout"])
        assert g.afk_turns[1] == 2

    def test_wrong_answer_resets_afk(self):
        g = make_game()
        g.afk_turns[1] = 1
        turn(g, answer=[3], wango=[W.MYSTIC_MIST])
        assert g.afk_turns[1] == 0

    def test_forfeit_costs_the_timeout_penalty_and_resets_afk(self):
        g = make_game()
        g.afk_turns[1] = 1
        g, *_ = turn(g, answer=["forfeit"])
        assert g.scores[1] == 400 and g.afk_turns[1] == 0

    def test_mist_does_not_change_scoring(self):
        g = make_game()
        g.activate_mist()
        g, *_ = turn(g, answer=["timeout"])
        assert g.scores[1] == 400

    def test_hot_streak_badge_message_from_the_third_correct_answer(self):
        g = make_game()
        g.consecutive_correct[1] = 2
        _, _, ch = turn(g, answer=[0], chance=[C.GOLDEN_PASS])
        assert "HOT STREAK" in ch.text and g.consecutive_correct[1] == 3

    # ── laws in play ──
    def test_double_jeopardy_wrong_costs_100_plus_sombrero(self):
        g = make_game()
        g.active_bamboozle_rule = R.make_active_rule(3, 3)
        g.sombrero_holder = 1
        g, *_ = turn(g, answer=[1], wango=[W.MYSTIC_MIST])
        assert g.scores[1] == 500 - 100 - 25

    def test_timeout_terror_timeout_costs_200(self):
        g = make_game()
        g.active_bamboozle_rule = R.make_active_rule(7, 3)
        g, *_ = turn(g, answer=["timeout"])
        assert g.scores[1] == 300

    def test_timeout_terror_forfeit_also_costs_200(self):
        g = make_game()
        g.active_bamboozle_rule = R.make_active_rule(7, 3)
        g, *_ = turn(g, answer=["forfeit"])
        assert g.scores[1] == 300

    def test_speed_tax_applies_after_a_fast_correct_answer(self):
        g = make_game()
        g.active_bamboozle_rule = R.make_active_rule(1, 3)
        script = Script(answer=[0], chance=[C.GOLDEN_PASS])
        script.elapsed = 2.0
        with legacy_env(script, g) as (cog, ch):
            run(cog._run_turn(ch, g, 1))
        assert g.scores[1] == 500 + 100 - 25

    def test_slow_burn_after_a_slow_wrong_answer(self):
        g = make_game()
        g.active_bamboozle_rule = R.make_active_rule(2, 3)
        script = Script(answer=[1], wango=[W.MYSTIC_MIST])
        script.elapsed = 25.0
        with legacy_env(script, g) as (cog, ch):
            run(cog._run_turn(ch, g, 1))
        assert g.scores[1] == 500 - 50 - 50

    def test_slow_burn_after_a_timeout_always_applies(self):
        g = make_game()
        g.active_bamboozle_rule = R.make_active_rule(2, 3)
        g, *_ = turn(g, answer=["timeout"])
        assert g.scores[1] == 500 - 100 - 50

    def test_hot_streak_law_pays_on_the_second_consecutive_correct(self):
        g = make_game()
        g.active_bamboozle_rule = R.make_active_rule(4, 3)
        g.consecutive_correct[1] = 1
        g, *_ = turn(g, answer=[0], chance=[C.GOLDEN_PASS])
        assert g.scores[1] == 500 + 100 + 75

    def test_lucky_last_law_pays_the_last_seat(self):
        g = make_game()
        g.active_bamboozle_rule = R.make_active_rule(8, 3)
        g.current_turn_index = 2
        g, *_ = turn(g, pid=3, answer=[0], chance=[C.GOLDEN_PASS])
        assert g.scores[3] == 500 + 100 + 100

    def test_karma_tax_is_charged_before_the_question(self):
        g = make_game(3, scores={1: 900})
        g.active_bamboozle_rule = R.make_active_rule(5, 3)
        g, *_ = turn(g, answer=["timeout"])
        assert g.scores[1] == 900 - 50 - 100

    def test_underdog_boost_is_paid_before_the_question(self):
        g = make_game(3, scores={1: 100})
        g.active_bamboozle_rule = R.make_active_rule(6, 3)
        g, *_ = turn(g, answer=["timeout"])
        assert g.scores[1] == 100 + 50 - 100

    def test_streak_breaker_gives_the_leader_a_wango_card_instead_of_a_chance_card(self):
        g = make_game(3, scores={1: 900})
        g.active_bamboozle_rule = R.make_active_rule(9, 3)
        g, *_ = turn(g, answer=[0], wango=[W.THE_SILENCE])     # no chance card scripted
        assert g.scores[1] == 1000 and g.silenced == {1: True}

    def test_streak_breaker_does_not_affect_players_who_are_not_leading(self):
        g = make_game(3, scores={2: 900})
        g.active_bamboozle_rule = R.make_active_rule(9, 3)
        g, *_ = turn(g, answer=[0], chance=[C.GOLDEN_PASS])
        assert g.golden_pass == {1: True}

    def test_streak_breaker_counts_ties_for_first_as_leading(self):
        g = make_game(3)    # everyone 500; after +100 the answerer leads alone
        g.active_bamboozle_rule = R.make_active_rule(9, 3)
        g, *_ = turn(g, answer=[0], wango=[W.MYSTIC_MIST])
        assert g.mist_active

    def test_turn_fetches_with_the_games_difficulty(self):
        g = make_game()
        g.question_difficulty = "hard"
        _, script, _ = turn(g, answer=["timeout"])
        assert script.fetch_kwargs[0]["difficulty"] == "hard"
        assert "Q?" in g.asked_questions


# ───────────────────────────── The game loop ─────────────────────────────

class TestGameLoop:
    def loop(self, game, on_turn=None, rounds=None):
        calls = []
        script = Script()
        with legacy_env(script, game) as (cog, ch):
            async def fake_turn(channel, g, pid):
                calls.append(pid)
                if on_turn:
                    on_turn(len(calls), g, pid)
            cog._run_turn = fake_turn
            ended = []

            async def fake_end(channel, g):
                ended.append(snapshot(g))
            cog._run_endgame = fake_end
            run(cog._run_game(ch, game))
        return calls, ended, ch

    def test_plays_every_seat_for_every_round_then_ends(self):
        g = make_game(3, total_rounds=2)
        calls, ended, ch = self.loop(g)
        assert calls == [1, 2, 3, 1, 2, 3] and len(ended) == 1 and ended[0]["round"] == 3
        assert ch.text.count("End of Round") == 1        # not after the final round

    def test_silenced_player_loses_exactly_one_turn(self):
        g = make_game(3, total_rounds=2)
        g.silenced[2] = True
        calls, *_ = self.loop(g)
        assert calls == [1, 3, 1, 2, 3] and g.silenced[2] is False

    def test_player_is_kicked_after_two_consecutive_afk_turns(self):
        g = make_game(3, total_rounds=3)

        def afk(n, game, pid):
            if pid == 2:
                game.afk_turns[2] = game.afk_turns.get(2, 0) + 1
        calls, ended, ch = self.loop(g, afk)
        # FOUND (not fixed): kicking P2 mid-round shifts P3 into P2's seat, then advance_turn() moves on again,
        # so P3 loses their turn in round 2 and the round counter jumps. Phase 2 decides whether to keep this.
        assert calls == [1, 2, 3, 1, 2, 1, 3]
        assert g.players == [1, 3] and 2 not in g.scores and "removed for going AFK" in ch.text

    def test_kicking_the_sombrero_holder_passes_it_to_the_first_player(self):
        g = make_game(3, total_rounds=3)
        g.sombrero_holder = 2
        g.afk_turns[2] = 1

        def afk(n, game, pid):
            if pid == 2:
                game.afk_turns[2] += 1
        self.loop(g, afk)
        assert g.sombrero_holder == 1

    def test_mist_lifts_on_the_second_turn_after_activation(self):
        g = make_game(3, total_rounds=2)
        states = []

        def mist(n, game, pid):
            if n == 1:
                game.activate_mist()
            states.append((n, game.mist_active))
        _, _, ch = self.loop(g, mist)
        # activation during turn 1 is ticked at the end of turn 1 (2 -> 1) and turn 2 (1 -> 0)
        assert states[:3] == [(1, True), (2, True), (3, False)] and "The Mist clears" in ch.text

    def test_non_permanent_law_expires_after_one_rotation_and_is_announced(self):
        g = make_game(3, total_rounds=2)

        def law(n, game, pid):
            if n == 1:
                game.active_bamboozle_rule = R.make_active_rule(1, 3)
        _, _, ch = self.loop(g, law)
        assert g.active_bamboozle_rule is None and "THE LAW HAS EXPIRED" in ch.text

    def test_force_ended_game_stops_without_endgame(self):
        g = make_game(3, total_rounds=5)

        def stop(n, game, pid):
            if n == 2:
                game.active = False
        calls, ended, _ = self.loop(g, stop)
        assert len(calls) == 2 and ended == []

    def test_last_player_kicked_ends_the_game(self):
        g = make_game(1, total_rounds=5)
        g.afk_turns[1] = 1

        def afk(n, game, pid):
            game.afk_turns[1] += 1
        calls, ended, ch = self.loop(g, afk)
        assert calls == [1] and ended == [] and "No players remaining" in ch.text


# ───────────────────────────── Endgame ─────────────────────────────

class TestEndgame:
    def endgame(self, game, **script_kw):
        script = Script(**script_kw)
        game.test_mode = False
        saved = {}
        with legacy_env(script, game) as (cog, ch):
            import cogs.game as G

            async def capture(**kw):
                saved.update(kw)
            G.save_game_result.side_effect = capture
            run(cog._run_endgame(ch, game))
            stats = [c.args for c in G.update_player_stats.call_args_list]
        assert not script.leftover(), script.leftover()
        return saved, stats, ch, game

    def test_highest_score_wins_and_everyone_gets_stats(self):
        g = make_game(3, scores={1: 300, 2: 900, 3: 600})
        saved, stats, ch, g = self.endgame(g)
        assert saved["winner_id"] == "2" and saved["final_scores"] == {"1": 300, "2": 900, "3": 600}
        assert stats == [("1", False, 300), ("2", True, 900), ("3", False, 600)]

    def test_test_mode_records_nothing(self):
        g = make_game(2, scores={1: 100, 2: 200})
        script = Script()
        with legacy_env(script, g) as (cog, ch):
            import cogs.game as G
            run(cog._run_endgame(ch, g))
            assert not G.save_game_result.called and not G.update_player_stats.called

    def test_residual_mist_is_lifted_for_the_final_reveal(self):
        g = make_game(2, scores={1: 100, 2: 200})
        g.activate_mist()
        _, _, ch, g = self.endgame(g)
        assert "Mist clears for the final reveal" in ch.text

    def test_negative_scores_still_rank(self):
        g = make_game(3, scores={1: -300, 2: -100, 3: -900})
        saved, *_ = self.endgame(g)
        assert saved["winner_id"] == "2"

    def test_endgame_resets_the_game_back_to_a_lobby(self):
        g = make_game(2, scores={1: 100, 2: 200})
        *_, g = self.endgame(g)
        assert g.scores == {1: 500, 2: 500} and g.active is False and g.players == [1, 2]

    def test_tie_runs_sudden_bamboozle_wheel_then_question(self):
        g = make_game(3, scores={1: 600, 2: 600, 3: 100})
        saved, _, ch, _ = self.endgame(
            g, wheel=[S.BONUS_ROUND, S.TAX_SEASON], answer=[0, 0])
        # p1: 600 +150 +100 = 850 ; p2: 600 -120 +100 = 580
        assert saved["winner_id"] == "1" and saved["final_scores"] == {"1": 850, "2": 580, "3": 100}
        assert "SUDDEN BAMBOOZLE" in ch.text

    def test_tiebreak_repeats_until_one_player_is_ahead(self):
        g = make_game(2, scores={1: 600, 2: 600})
        saved, *_ = self.endgame(
            g, wheel=[S.BONUS_ROUND, S.BONUS_ROUND, S.BONUS_ROUND, S.BONUS_ROUND], answer=[0, 0, 0, 2])
        # round 1: both 600+150+100 = 850 (tie). round 2: p1 850+150+100=1100 ; p2 850+150-50=950
        assert saved["winner_id"] == "1" and saved["final_scores"] == {"1": 1100, "2": 950}

    def test_only_players_still_tied_for_first_take_part_in_later_tiebreaks(self):
        g = make_game(3, scores={1: 600, 2: 600, 3: 600})
        saved, *_ = self.endgame(
            g,
            # round 1: p1 +150+100 (850) | p2 +150-50 (700) | p3 +150-50 (700)... then only p1 remains
            wheel=[S.BONUS_ROUND] * 3, answer=[0, 2, 2])
        assert saved["winner_id"] == "1"
        assert saved["final_scores"] == {"1": 850, "2": 700, "3": 700}

    def test_tiebreak_question_timeout_costs_100(self):
        g = make_game(2, scores={1: 600, 2: 600})
        saved, *_ = self.endgame(g, wheel=[S.MYSTIC_MIST, S.MYSTIC_MIST], answer=["timeout", 0])
        assert saved["winner_id"] == "2" and saved["final_scores"] == {"1": 500, "2": 700}
