"""Directed engine tests: the owner's six decisions, every illegal-intent code, and the paths random play rarely hits."""
import copy
import random

import pytest

from bamboozled.engine import (ANSWER, DRAW_CARD, FORFEIT, LEAVE, MONKEY, PICK_RULE, PICK_TARGET, GameConfig,
                               IllegalIntent, Intent, PlayerRef, Question, get_engine)
from bamboozled.engine import rules as R
from bamboozled.engine.bamboozled import BamboozledEngine
from bamboozled.engine.cards import ChanceCard, WangoCard, draw_wango
from bamboozled.engine.fff import FastestFingersEngine
from bamboozled.engine.scoring import final_order, is_new_best, rank_order, top_scorers
from bamboozled.engine.survival import SurvivalEngine
from bamboozled.engine.wheel import WheelSegment

Q = Question("Q?", ("right", "a", "b", "c"), 0, "Cat", "easy")
E = BamboozledEngine()


def new(n=3, rounds=5, quirks=(), seed=1):
    return E.new_game(GameConfig(rounds=rounds, legacy_quirks=frozenset(quirks)), [PlayerRef(i) for i in range(1, n + 1)],
                      random.Random(seed), 0)


def inject(state, *items, now=0):
    """Replace the agenda (white-box) and let the engine run until it needs something."""
    s = copy.deepcopy(state)
    s.agenda, s.pending, s.waiting_question, s.question = list(items), None, False, None
    rng = random.Random()
    rng.setstate(s.rng_state)
    E._run(s, now, rng, [])
    s.rng_state = rng.getstate()
    return s


def ask(s, now=0):
    return E.supply_question(s, Q, now).state


def answer(s, idx, now=1000):
    return E.apply(s, s.pending.actor, Intent(ANSWER, index=idx), now).state


def timeout(s):
    return E.on_timeout(s, s.pending.deadline_ms).state


def draw_that_gives(card_type, wanted):
    """A seed whose next draw of that deck is `wanted`, found by search."""
    for seed in range(500):
        if card_type(random.Random(seed)) == wanted:
            return seed
    raise AssertionError("no seed found")


# ───────────────────────────── the owner's decisions ─────────────────────────────

class TestDecision1AfkKick:
    def run_to_kick(self, quirks):
        s = new(3, rounds=5, quirks=quirks)
        s.afk[2] = 1                                   # P2 has already missed one turn
        s = ask(inject(s, ("ask", 2, "turn")))
        s.turn_index, s.turn_player = 1, 2
        s = timeout(s)                                 # second miss: P2 is removed after the turn
        return s

    def test_new_behaviour_the_next_player_keeps_their_turn(self):
        s = self.run_to_kick(())
        assert s.players == [1, 3] and s.turn_player == 3 and s.round == 1

    def test_legacy_quirk_skips_them_and_bumps_the_round(self):
        s = self.run_to_kick(("afk_skip",))
        assert s.players == [1, 3] and s.turn_player == 1 and s.round == 2

    def test_kicking_the_last_seat_wraps_to_a_new_round(self):
        s = new(3, rounds=5)
        s.afk[3] = 1
        s = ask(inject(s, ("ask", 3, "turn")))
        s.turn_index, s.turn_player = 2, 3
        s = timeout(s)
        assert s.players == [1, 2] and s.turn_player == 1 and s.round == 2

    def test_the_sombrero_passes_on_when_its_holder_is_kicked(self):
        s = new(3)
        s.afk[2], s.sombrero_holder = 1, 2
        s = ask(inject(s, ("ask", 2, "turn")))
        s.turn_index, s.turn_player = 1, 2
        assert timeout(s).sombrero_holder == 1

    def test_everyone_gone_ends_the_game(self):
        s = new(1, rounds=5)
        s.afk[1] = 1
        s = timeout(ask(s))
        assert s.over and E.results(s) == []


class TestDecision4Mist:
    def mist_flags(self, quirks):
        s = new(3, rounds=9, quirks=quirks)
        s = inject(s, ("wango", 1, WangoCard.MYSTIC_MIST, 0), ("ask", 1, "turn"))
        flags = []
        for _ in range(4):                              # P1's turn (mist starts in it), then P2, P3, P1
            s = ask(s)
            flags.append((s.turn_player, s.mist_active))
            s = timeout(s)
        return flags

    def test_new_behaviour_mist_covers_the_next_two_full_turns(self):
        # it is up during P1's own turn and stays for the next two full turns (P2's and P3's)
        assert self.mist_flags(()) == [(1, True), (2, True), (3, True), (1, False)]

    def test_legacy_quirk_ends_it_after_one_more_turn(self):
        assert self.mist_flags(("mist_short",)) == [(1, True), (2, True), (3, False), (1, False)]

    def test_mist_magnet_makes_it_four(self):
        s = new(3, rounds=9)
        s.mist_duration = 4
        s = inject(s, ("wango", 1, WangoCard.MYSTIC_MIST, 0), ("ask", 1, "turn"))
        assert s.mist_turns == 5                       # 4 full turns after the one it started in

    def test_scores_are_hidden_while_the_mist_is_up_and_visible_after(self):
        s = inject(new(), ("wango", 1, WangoCard.MYSTIC_MIST, 0))
        assert all(p["score"] is None for p in E.view_for(s, 1)["players"])
        s.mist_active = False
        assert all(p["score"] == 500 for p in E.view_for(s, 1)["players"])


class TestDecision5aWangoAgainChain:
    def double_wango_seed(self):
        return draw_that_gives(draw_wango, WangoCard.DOUBLE_WANGO)

    def after_wango_again(self, quirks, chain, monkeypatch):
        seen = []
        original = BamboozledEngine._double_wango_step

        def spy(self_, s, pid, i, n, ch, rng, ev):
            seen.append((i, n, ch))
            return original(self_, s, pid, i, n, ch, rng, ev)
        monkeypatch.setattr(BamboozledEngine, "_double_wango_step", spy)
        s = new(3, quirks=quirks)
        s.rng_state = random.Random(self.double_wango_seed()).getstate()
        inject(s, ("seg", 1, WheelSegment.WANGO_AGAIN, 0, chain))
        return seen[0]                                   # the first extra-card step: (index, cards to draw, chain depth)

    def test_new_behaviour_the_chain_count_carries_through(self, monkeypatch):
        assert self.after_wango_again((), 1, monkeypatch) == (0, 1, 1)          # only one more card allowed

    def test_legacy_quirk_restarts_the_chain(self, monkeypatch):
        assert self.after_wango_again(("wango_again_reset",), 1, monkeypatch) == (0, 2, 0)

    def test_at_the_chain_limit_a_double_wango_draws_nothing(self):
        assert not any(i[0] == "dw" for i in inject(new(), ("wango", 1, WangoCard.DOUBLE_WANGO, 2)).agenda)


class TestDecision5bGoldenPass:
    def monkey_penalty(self, quirks):
        s = new(3, quirks=quirks)
        s.golden_pass[1] = True
        s.rng_state = random.Random(0).getstate()
        return inject(s, ("draw", 1, "wango", False, "monkey"))

    def test_new_behaviour_blocks_a_wango_card_from_any_source(self):
        s = self.monkey_penalty(())
        assert s.golden_pass[1] is False and s.rng_state == random.Random(0).getstate()      # spent, and no card was drawn

    def test_legacy_quirk_only_guards_the_draw_after_a_wrong_answer(self):
        s = self.monkey_penalty(("golden_pass_wrong_only",))
        assert s.golden_pass[1] is True

    def test_it_also_blocks_the_streak_breaker_draw_and_wango_again(self):
        s = new(3)
        s.golden_pass[1] = True
        assert inject(s, ("draw", 1, "wango", True, "streak")).golden_pass[1] is False
        s.golden_pass[1] = True
        assert inject(s, ("seg", 1, WheelSegment.WANGO_AGAIN, 0, 0)).golden_pass[1] is False

    def test_it_does_not_block_extra_cards_inside_a_double_wango_chain(self):
        s = new(3)
        s.golden_pass[1] = True
        s = inject(s, ("draw", 1, "wango", False, "chain"))
        assert s.golden_pass[1] is True

    def test_after_a_wrong_answer_it_is_spent_and_no_card_is_drawn(self):
        s = new(3)
        s.golden_pass[1] = True
        s = answer(ask(s), 1)
        assert s.golden_pass[1] is False and s.scores[1] == 450 and s.turn_player == 2


class TestDecision3DoubleDownKeepsRules:
    def test_a_law_and_the_sombrero_do_not_touch_a_double_down_answer(self):
        s = new(3)
        s.law, s.sombrero_holder = R.make_active_law(3, 3), 1       # Double Jeopardy and the Sombrero
        s = ask(inject(s, ("ask", 1, "double_down")))
        assert answer(s, 1).scores[1] == 300                        # exactly -200


class TestDecision2FffLeavers:
    def play(self):
        e = FastestFingersEngine()
        s = e.new_game(GameConfig(mode="fff", rounds=3), [PlayerRef(u) for u in (5, 6, 7)], random.Random(0), 0)
        s = e.supply_question(s, Q, 0).state
        s = e.apply(s, 6, Intent(ANSWER, index=0), 100).state                 # P6: 100
        s = e.apply(s, 5, Intent(ANSWER, index=0), 200).state                 # P5: 75
        s = e.apply(s, 7, Intent(LEAVE), 300).state                           # P7 quits (no points yet)
        return e, s

    def test_a_leaver_stays_in_the_results_below_the_finishers(self):
        e, s = self.play()
        s = e.supply_question(s, Q, 0).state
        s = e.apply(s, 6, Intent(LEAVE), 50).state                            # P6 quits with 100 points
        s = e.apply(s, 5, Intent(ANSWER, index=0), 90).state                  # P5 finishes it
        rows = e.results(e.on_timeout(e.supply_question(s, Q, 0).state if s.question is None else s, 10**6).state
                         if not e.is_over(s) else s)
        order = [(r.user_id, r.details.get("left")) for r in rows]
        assert order[0][0] == 5 and order[0][1] is None
        assert (6, "quit") in order and order.index((6, "quit")) > 0

    def test_points_scored_before_leaving_are_kept(self):
        e, s = self.play()
        left = s.left[7]
        assert left["why"] == "quit"
        s2 = e.supply_question(s, Q, 0).state
        s2 = e.apply(s2, 6, Intent(ANSWER, index=0), 100).state
        s2 = e.apply(s2, 5, Intent(LEAVE), 200).state                         # P5 leaves holding 75
        assert s2.left[5]["score"] == 75 and 5 not in s2.scores


class TestDecision6Survival:
    @pytest.mark.parametrize("streak,best,reason,expected", [
        (5, 3, "wrong", True), (5, 3, "timeout", True), (3, 3, "wrong", False), (0, 0, "wrong", False),
        (9, 1, "quit", False), (9, 1, "error", False)])
    def test_new_best_rule(self, streak, best, reason, expected):
        assert is_new_best(streak, best, reason) is expected

    def test_a_fetch_error_ends_the_run_and_is_recorded_as_an_error(self):
        e = SurvivalEngine()
        s = e.new_game(GameConfig(mode="survival"), [PlayerRef(1)], random.Random(0), 0)
        s = e.question_unavailable(s).state
        assert e.is_over(s) and e.results(s)[0].details["reason"] == "error"
        assert e.question_unavailable(s).state.reason == "error"


# ───────────────────────────── illegal intents ─────────────────────────────

class TestIllegalIntents:
    def code(self, s, actor, intent, now=1000):
        with pytest.raises(IllegalIntent) as err:
            E.apply(s, actor, intent, now)
        return err.value.code

    def test_codes(self):
        s = ask(new())
        assert self.code(s, 99, Intent(ANSWER, index=0)) == "not_in_game"
        assert self.code(s, 2, Intent(ANSWER, index=0)) == "not_your_turn"
        assert self.code(s, 1, Intent(DRAW_CARD)) == "bad_phase"
        assert self.code(s, 1, Intent(ANSWER, index=7)) == "bad_index"
        assert self.code(s, 1, Intent(ANSWER)) == "bad_index"
        assert self.code(s, 1, Intent(ANSWER, index=0), now=10**9) == "too_late"
        assert self.code(new(), 1, Intent(ANSWER, index=0)) == "bad_phase"       # still waiting for a question

    def test_forfeit_only_on_a_real_turn(self):
        assert answer(ask(new()), 0) is not None
        s = ask(inject(new(), ("ask", 1, "double_down")))
        assert self.code(s, 1, Intent(FORFEIT)) == "bad_phase"
        assert E.apply(ask(new()), 1, Intent(FORFEIT), 1000).state.scores[1] == 400

    def test_picking_targets(self):
        s = inject(new(), ("pick", 1, "gift"))
        assert self.code(s, 1, Intent(PICK_TARGET, user_id=1)) == "bad_target"        # yourself
        assert self.code(s, 1, Intent(PICK_TARGET, user_id=42)) == "bad_target"       # not in the game
        assert self.code(s, 1, Intent(PICK_TARGET, user_id=None)) == "bad_target"     # a gift cannot be skipped
        assert E.apply(inject(new(), ("pick", 1, "switcheroo")), 1, Intent(PICK_TARGET, user_id=None), 5).state.scores[1] == 500

    def test_law_and_monkey_choices(self):
        assert self.code(inject(new(), ("law", 1)), 1, Intent(PICK_RULE, rule_id=99)) == "bad_rule"
        assert self.code(inject(new(), ("monkey", 1, True)), 1, Intent(MONKEY, choice="nose")) == "bad_choice"

    def test_nothing_waiting_and_game_over(self):
        s = copy.deepcopy(new())
        s.pending, s.waiting_question = None, False
        assert self.code(s, 1, Intent(DRAW_CARD)) == "bad_phase"
        s.over = True
        assert self.code(s, 1, Intent(DRAW_CARD)) == "over"

    def test_supplying_a_question_when_none_is_needed(self):
        with pytest.raises(IllegalIntent):
            E.supply_question(ask(new()), Q, 0)
        with pytest.raises(ValueError):
            E.supply_question(new(), Question("x", ("a", "b"), 5), 0)

    def test_timeout_before_the_deadline_changes_nothing(self):
        s = ask(new())
        assert E.on_timeout(s, 5).state is s
        assert E.next_deadline_ms(s) == s.pending.deadline_ms
        assert E.on_timeout(new(), 10**9).state.waiting_question

    def test_setup_validation(self):
        with pytest.raises(ValueError):
            E.new_game(GameConfig(), [], random.Random(0), 0)
        with pytest.raises(ValueError):
            E.new_game(GameConfig(), [PlayerRef(1), PlayerRef(1)], random.Random(0), 0)
        with pytest.raises(ValueError):
            E.new_game(GameConfig(mode="fff"), [PlayerRef(1)], random.Random(0), 0)
        with pytest.raises(ValueError):
            GameConfig(mode="chess")
        with pytest.raises(ValueError):
            GameConfig(legacy_quirks=frozenset({"nope"}))
        with pytest.raises(ValueError):
            get_engine("chess")


# ───────────────────────────── leaving, silence and the endgame ─────────────────────────────

class TestLeavingAndEndgame:
    def test_a_player_leaving_before_their_turn_is_removed_at_once(self):
        s = E.apply(ask(new()), 3, Intent(LEAVE), 10).state
        assert s.players == [1, 2] and s.pending.actor == 1

    def test_the_active_player_leaving_forfeits_then_goes_at_turn_end(self):
        s = E.apply(ask(new()), 1, Intent(LEAVE), 10).state
        assert s.players == [2, 3] and s.turn_player == 2 and s.round == 1

    @pytest.mark.parametrize("seed", range(40))
    def test_leaving_while_a_card_decision_is_pending_takes_the_defaults_all_the_way(self, seed):
        s = answer(ask(new(seed=seed)), 0)                          # P1 answered; now they must press draw
        assert s.pending.kind == "draw"
        s = E.apply(s, 1, Intent(LEAVE), 20).state
        # whatever the card was (spin, pick, law, double down, monkey...), nothing is left waiting on P1
        assert 1 not in s.players and (s.pending is None or s.pending.actor != 1)
        assert s.turn_player == 2 or s.stage == "endgame"

    def test_a_non_current_player_can_leave_during_the_endgame(self):
        s = new(3, rounds=1)
        for _ in range(3):
            s = timeout(ask(s))
        assert s.stage == "endgame" or s.over
        s = new(3, rounds=1)
        s.scores = {1: 600, 2: 600, 3: 600}
        s = inject(s, ("ask", 1, "turn"))
        s = ask(s)
        s = E.apply(s, 3, Intent(LEAVE), 5).state
        assert 3 not in s.players

    def test_everybody_leaving_ends_the_game(self):
        s = new(2)
        s = E.apply(ask(s), 2, Intent(LEAVE), 5).state
        s = E.apply(s, 1, Intent(LEAVE), 6).state
        assert s.over

    def test_silence_skips_exactly_one_turn(self):
        s = new(3, rounds=5)
        s.silenced[2] = True
        s = timeout(ask(s))                                        # P1's turn ends; P2 is skipped, P3 is up
        assert s.turn_player == 3 and s.silenced[2] is False

    def test_a_tie_runs_sudden_bamboozle_until_someone_leads(self):
        s = new(2, rounds=1)
        s = inject(s, ("ask", 1, "turn"))
        s = ask(s)
        s = timeout(s)                                             # P1 -100
        s = timeout(ask(s))                                        # P2 -100: tied at 400
        assert s.stage == "endgame" and s.pending.kind == "spin"
        guard = 0
        while not s.over and guard < 60:
            guard += 1
            need = E.needs_question(s)
            if need:
                s = ask(s, guard)
            elif s.pending.kind == "answer":
                s = answer(s, 0 if s.pending.actor == 1 else 1, guard + 5)
            else:
                s = E.on_timeout(s, s.pending.deadline_ms).state
        assert s.over and s.champion in (1, 2)

    def test_results_and_view_after_the_game(self):
        s = new(2, rounds=1)
        s.scores = {1: 100, 2: 900}
        s.over, s.champion = True, 2
        rows = E.results(s)
        assert [(r.user_id, r.rank) for r in rows] == [(2, 1), (1, 2)]
        v = E.view_for(s, None)
        assert v["over"] and v["champion"] == 2


class TestWinningPaths:
    def test_tie_order_helpers(self):
        assert rank_order({1: 5, 2: 5, 3: 9}, [2, 1, 3]) == [3, 2, 1]
        assert final_order({1: 5, 2: 5, 3: 9}, [2, 1, 3]) == [3, 1, 2]
        assert final_order({1: 5, 2: 5}, [1, 2], winner=2) == [2, 1]
        assert top_scorers({}, []) == []

    def test_chance_cards_each_resolve(self):
        for card in ChanceCard:
            s = inject(new(3, rounds=5), ("chance", 1, card))
            if s.pending:
                assert s.pending.actor == 1

    def test_law_choices_each_resolve(self):
        for law in R.LAWS:
            s = inject(new(3, rounds=5), ("law", 1))
            s = E.apply(s, 1, Intent(PICK_RULE, rule_id=law.id), 5).state
            assert s.law["id"] == law.id

    def test_bamboozle_in_the_final_round_is_a_llama(self):
        s = new(3, rounds=1)
        s = inject(s, ("chance", 1, ChanceCard.BAMBOOZLE))
        assert s.scores[1] == 550 and s.law is None

    def test_spin_and_draw_timeouts_take_the_default(self):
        s = inject(new(), ("spin", 1, 0, 0))
        s = E.on_timeout(s, s.pending.deadline_ms).state
        assert s.pending is None or s.pending.kind != "spin"
        s = inject(new(), ("draw", 1, "chance", True, "correct"))
        s = E.on_timeout(s, s.pending.deadline_ms).state
        assert s.pending is None or s.pending.kind != "draw"

    def test_monkey_timeout_is_the_tail(self):
        s = inject(new(), ("monkey", 1, False))                       # tail is the lucky side
        s = E.on_timeout(s, s.pending.deadline_ms).state
        assert s.scores[1] == 800
        s = inject(new(), ("monkey", 1, True), ("wango", 1, WangoCard.THE_SILENCE, 0))
        s = E.on_timeout(s, s.pending.deadline_ms).state
        assert s.scores[1] == 300

    def test_view_for_a_spectator_and_a_player(self):
        s = ask(new())
        assert E.view_for(s, 1)["question"]["text"] == "Q?"
        assert E.view_for(s, None)["pending"]["kind"] == "answer"
        s2 = inject(new(), ("pick", 1, "switcheroo"))
        v = E.view_for(s2, 1)
        assert v["pending"]["options"] == [2, 3] and v["pending"]["can_skip"] is True
        assert E.needs_question(s2) is None and E.next_deadline_ms(s2) == s2.pending.deadline_ms


# ───────────────────────────── Fastest Fingers First ─────────────────────────────

class TestFffRules:
    def setup_method(self):
        self.e = FastestFingersEngine()
        self.s = self.e.new_game(GameConfig(mode="fff", rounds=2), [PlayerRef(u) for u in (1, 2, 3)], random.Random(0), 0)

    def open(self, s=None):
        return self.e.supply_question(s or self.s, Q, 0).state

    def test_errors(self):
        e, s = self.e, self.open()
        for intent, now, code in [(Intent(ANSWER, index=9), 5, "bad_index"), (Intent(ANSWER), 5, "bad_index"),
                                  (Intent(ANSWER, index=0), 10**6, "too_late"), (Intent(DRAW_CARD), 5, "bad_phase")]:
            with pytest.raises(IllegalIntent) as err:
                e.apply(s, 1, intent, now)
            assert err.value.code == code
        s = e.apply(s, 1, Intent(ANSWER, index=1), 5).state
        with pytest.raises(IllegalIntent) as err:
            e.apply(s, 1, Intent(ANSWER, index=0), 6)
        assert err.value.code == "already_answered"
        with pytest.raises(IllegalIntent):
            e.apply(s, 99, Intent(ANSWER, index=0), 6)
        with pytest.raises(IllegalIntent):
            e.apply(self.s, 1, Intent(ANSWER, index=0), 6)                     # no open question yet
        with pytest.raises(IllegalIntent):
            e.supply_question(s, Q, 0)

    def test_locking_is_visible_but_the_choice_is_not(self):
        e = self.e
        s = e.apply(self.open(), 2, Intent(ANSWER, index=3), 50).state
        assert e.view_for(s, 1)["players"][1] == {"user_id": 2, "score": 0, "locked": True}
        assert e.view_for(s, 1)["your_answer"] is None and e.view_for(s, 2)["your_answer"] == 3

    def test_everyone_leaving_ends_it_and_a_leave_between_questions_is_immediate(self):
        e = self.e
        s = e.apply(self.s, 3, Intent(LEAVE), 1).state
        assert s.players == [1, 2] and s.left[3]["why"] == "quit"
        s = self.open(s)
        for u in (1, 2):
            s = e.apply(s, u, Intent(LEAVE), 10).state
        assert e.is_over(s) and e.next_deadline_ms(s) is None
        with pytest.raises(IllegalIntent):
            e.apply(s, 1, Intent(LEAVE), 11)
        assert e.needs_question(s) is None and e.on_timeout(s, 10**9).state is s

    def test_leaving_after_answering_still_removes_at_round_end(self):
        e = self.e
        s = e.apply(self.open(), 1, Intent(ANSWER, index=0), 10).state
        s = e.apply(s, 1, Intent(LEAVE), 11).state
        s = e.on_timeout(s, 10_000).state
        assert 1 in s.left and s.left[1]["score"] == 100

    def test_two_missed_questions_remove_a_player_and_the_game_runs_its_length(self):
        e, s = self.e, self.s
        for _ in range(2):
            s = e.on_timeout(self.open(s), 10_000).state
        assert e.is_over(s) and sorted(s.left) == [1, 2, 3]
        assert e.view_for(s, 1)["over"]
        assert e.needs_question(self.s)["kind"] == "fff"


# ───────────────────────────── Survival ─────────────────────────────

class TestSurvivalRules:
    def setup_method(self):
        self.e = SurvivalEngine()
        self.s = self.e.new_game(GameConfig(mode="survival", difficulty="hard"), [PlayerRef(7)], random.Random(0), 0)

    def test_errors_and_views(self):
        e, s = self.e, self.s
        assert e.needs_question(s)["difficulty"] == "hard"
        with pytest.raises(ValueError):
            e.new_game(GameConfig(mode="survival"), [PlayerRef(1), PlayerRef(2)], random.Random(0), 0)
        with pytest.raises(ValueError):
            e.new_game(GameConfig(), [PlayerRef(1)], random.Random(0), 0)
        with pytest.raises(IllegalIntent):
            e.apply(s, 7, Intent(ANSWER, index=0), 1)                   # no open question
        s = e.supply_question(s, Q, 0).state
        for actor, intent, now, code in [(8, Intent(ANSWER, index=0), 5, "not_your_turn"),
                                         (7, Intent(DRAW_CARD), 5, "bad_phase"), (7, Intent(ANSWER, index=9), 5, "bad_index"),
                                         (7, Intent(ANSWER, index=0), 10**6, "too_late")]:
            with pytest.raises(IllegalIntent) as err:
                e.apply(s, actor, intent, now)
            assert err.value.code == code
        with pytest.raises(IllegalIntent):
            e.supply_question(s, Q, 0)
        assert "correct_index" not in e.view_for(s, 7)["question"] and e.next_deadline_ms(s) == 15_000
        s = e.apply(s, 7, Intent(ANSWER, index=0), 100).state
        assert s.streak == 1 and e.on_timeout(s, 10**9).state is s
        s = e.apply(e.supply_question(s, Q, 200).state, 7, Intent(LEAVE), 300).state
        assert s.reason == "quit"
        with pytest.raises(IllegalIntent):
            e.apply(s, 7, Intent(ANSWER, index=0), 400)
