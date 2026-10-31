# Rules as implemented (baseline)

Written from the code, not from intent. This is the oracle for the Phase 2 engine. Each rule names the test that pins
it. Sections marked **CONFIRM** are behaviours that look accidental; the owner decides whether the engine keeps them
(then they move to *Intended differences* or stay as rules).

Sources: `cogs/game.py`, `game_engine/{state,constants,cards,wheel,bamboozle_rules}.py`, `fastest_fingers.py`,
`survival.py`. Tests: `tests/test_characterisation_bamboozled.py` (B), `tests/test_characterisation_fff_survival.py` (F/S).

## 1. Bamboozled

### 1.1 Setup and constants (`game_engine/constants.py`)

| Item | Value |
|---|---|
| Players | 1 to 10 in the lobby code; "solo" (1 player) has special cases below |
| Starting score | 500 |
| Rounds | `total_rounds` (default 5); a round = one turn per seated player |
| Question time | 30 s; Golden Monkey 15 s; pick (target) 20 s; draw/spin button 10 s then auto-proceeds; law choice 60 s (+10 s view grace) |
| Correct / wrong / timeout | +100 / -50 / -100 |
| Single-swing cap | `apply_points` clamps any one change to +-300 (`bypass_cap` exists). Tax, Gift/steal, Switcheroo, Full Reversal write scores directly and are **not** capped |
| Difficulty multiplier | only used by the old points award (deleted in Phase 1) |

### 1.2 Turn flow (`_run_turn`, `_run_game`)  (B: TestTurn, TestGameLoop)

1. A player who is **silenced** loses the turn: flag cleared, no question, but the mist and law timers still tick and the
   turn advances.
2. Start of turn: active law's start-of-turn effect (Karma Tax, Underdog Boost) applies.
3. Question asked. Outcomes:
   - **Correct**: +100; streak +1; correct count +1; AFK counter reset. Then law effects after-correct (Speed Tax, Hot
     Streak, Lucky Last). Then a **Chance card** is drawn (or a **Wango card** instead if the Streak Breaker law is
     active and the answerer is tied-or-ahead for first *after* the +100).
   - **Wrong**: -50 (law 3: -100), and the Sombrero holder pays an extra `sombrero_penalty` (25; 50 under law 11).
     Streak reset; AFK reset. Slow Burn then applies. If the player holds a **Golden Pass** it is spent and no card is
     drawn; otherwise a **Wango card** is drawn.
   - **Timeout**: -100 (law 7: -200). Streak reset; AFK +1. Slow Burn applies. No card. Sombrero does *not* add to a
     timeout.
   - **Forfeit** (player used the forfeit command): same score as a timeout, but AFK is reset to 0 instead of +1.
   - The Mist never changes scoring; it only hides display.
4. Mist ticks down once per turn, after the turn; a non-permanent law's counter ticks once per turn.
5. **AFK kick**: after the turn, a player with 2 consecutive timeouts is removed with all their per-player state; the
   Sombrero passes to the first remaining player; the game ends if nobody is left.
6. Game over when the round counter exceeds `total_rounds`, or if `/endgame` clears `active` (no endgame is then run).

Round banner is posted when the turn index wraps to 0 and the game is not over.

### 1.3 Chance cards (uniform random of 6)  (B: TestChanceCards)

| Card | Effect |
|---|---|
| Lucky Llama | +50 |
| Switcheroo | Pick another player (20 s) and swap scores. One use per player per game. Skip or timeout still consumes the use. Solo, or already used: +50 instead (use not consumed when solo) |
| Double Down | Extra question (30% chance it is True/False). Correct +200, wrong -200, timeout -100. No cards after. Laws and Sombrero do **not** apply |
| Spin the Wheel | Spin the wheel at depth 0 |
| Golden Pass | Flag set; cancels the next Wango draw after a *wrong answer* (not other Wango sources) |
| Bamboozle | Choose a law (11 choices). On the final round (`current_round >= total_rounds`): +50 instead. Timeout: nothing. A new law replaces the current one |

### 1.4 Wango cards (uniform random of 6)  (B: TestWangoCards)

| Card | Effect |
|---|---|
| Wango Classic | Spin the wheel at depth 0 |
| The Silence | Next turn skipped |
| Reverse Uno | The *next player in seat order* (wrapping) loses 100. Solo: nothing |
| The Sombrero | No holder: drawer holds it. Drawer already holds it: solo raises the penalty by 25 each time; otherwise it flies to the next seat. Someone else holds it: moves to the drawer (penalty unchanged) |
| Double Wango | Draw `min(2, 2 - chain_depth)` more Wango cards, each applied at `chain_depth + 1`. At depth >= 2: nothing. A drawn Double Wango is re-rolled once; a second Double Wango is skipped |
| Mystic Mist | Mist on: scores hidden for `mist_turn_duration` (2; 4 under law 10) |

### 1.5 Wheel of Mayhem (uniform random of 8)  (B: TestWheel)

| Segment | Effect |
|---|---|
| Ladder of Chance | Golden Monkey |
| Tax Season | Lose `max(10, int(abs(score) * 0.20))`, uncapped (so a negative score loses 20% of its magnitude too) |
| Gift of the Bamboozle | Pick a target: target -100, you +100 (uncapped, target may go negative). Timeout: nothing. Solo: +100 from "the bank" |
| Full Reversal | Players ranked by score (stable by seat order for ties); the list of scores is reversed and reassigned. Solo: score is negated |
| Mystic Mist | Mist on |
| Bonus Round | +150 |
| Wango Again | At wheel depth 0: draw a Wango card and apply it with `chain_depth=0`; if it is Wango Classic, spin a *capped* wheel (Wango Again there becomes Bonus Round). At depth >= 1: +150 instead |
| Monkey's Choice | The monkey picks one of the other 7 segments (never Monkey's Choice) |

A wheel spun by a Chance card or Wango Classic is depth 0. The capped wheel (depth 1) also applies to a Monkey's Choice
that resolves to Wango Again.

### 1.6 Golden Monkey (B: TestGoldenMonkey)

`belly_is_lucky = random() < 0.5`. Lucky side +300, unlucky side -200 (then a Wango card is drawn and applied at depth
0). On timeout the choice defaults to **tail**: so a lucky belly means -200 plus a Wango card, an unlucky belly means
+300 and no card.

### 1.7 Bamboozle laws (B: TestLaws; `game_engine/bamboozle_rules.py`)

A non-permanent law lasts one full rotation (`turns_remaining = number of players`); it expires when it reaches 0
after `advance_turn`. Permanent laws have `turns_remaining = -1`.

| # | Law | Rule |
|---|---|---|
| 1 | Speed Tax | Correct in under 5.0 s: -25 |
| 2 | Slow Burn | Wrong or timeout after more than 20.0 s: extra -50 (a timeout is always 30 s) |
| 3 | Double Jeopardy | Wrong answers cost -100 |
| 4 | Hot Streak | Correct with a streak >= 2: +75 |
| 5 | Karma Tax | Start of turn: any player tied for highest score loses 50 |
| 6 | Underdog Boost | Start of turn: any player tied for lowest score gains 50 |
| 7 | Timeout Terror | Timeout/forfeit costs -200 |
| 8 | Lucky Last | Correct while on the last seat of the rotation: +100 |
| 9 | Streak Breaker | See 1.2 (Chance card replaced by Wango for the leader) |
| 10 | Mist Magnet | Permanent: Mist lasts 4 turns |
| 11 | Sombrero Curse | Permanent: Sombrero penalty 50 |

### 1.8 Mist (B: TestGameStateRules, TestGameLoop)

`activate_mist` sets 2 turns (4 under law 10). The counter drops by one after *every* turn, including the turn in which
it was activated, so the Mist ends at the end of the next turn. A residual Mist is cleared before final scores.

### 1.9 Endgame (B: TestEndgame)

Winners = everyone tied on the top score. While more than one winner remains: each tied player spins the wheel
(depth 0, full consequences, including picks), then each answers a question: correct +100, wrong -50, timeout -100;
laws and Sombrero do not apply. Only players still tied for the highest score continue. Repeats until one remains.
Results recorded (non test mode): winner, final scores, per-player stats. Afterwards state resets to a lobby with the
same players.

## 2. Fastest Fingers First (`fastest_fingers.py`; F: TestFastestFingers)

- 2 to 10 players, host starts; questions are fetched up front; 10 s per question; each player gets one answer.
- Per question, correct answers are ordered by the time the button was recorded. **First correct +100, every later
  correct +75.** Wrong or missing: 0. A speed tie keeps arrival order (the first recorded wins the 100).
- A question ends early when every remaining player has answered.
- AFK: a player who does not answer 2 questions in a row is removed. Quit: removed at the end of that question.
- Average response time is kept for correct answers only.
- Ranking at the end is by score, descending; ties are not broken (Python stable sort, so seat order).

## 3. Survival (`survival.py`; S: TestSurvival)

- Solo. 15 s per question. Score = streak = number of consecutive correct answers.
- Run ends on: wrong answer, timeout, give-up, or a question fetch failure ("error").
- Personal best: a run is a new best when `streak > previous best`, `streak > 0` and it did not end by give-up. A fetch
  error therefore **can** count as a personal best.
- Previous best is per (user, difficulty, category) in the old database; in v2 it comes from `stats`.
- Seen questions are tracked per run to avoid repeats.

## 4. Found (not fixed) - owner to confirm each

1. **AFK kick skips a turn.** Removing a player shifts the list, then `advance_turn` moves on again, so the next
   player loses their turn and the round counter jumps (B: `test_player_is_kicked_after_two_consecutive_afk_turns`).
   The source comment says the intent was *not* to skip. **CONFIRM:** keep, or engine fixes it.
2. **FFF removed players vanish from the results.** Quitters and AFK-kicked players are dropped from `session.scores`,
   so their points do not appear on the final board (F: `test_two_consecutive_non_answers...`). **CONFIRM.**
3. **Double Down and tiebreak questions ignore laws and the Sombrero.** **CONFIRM** this is intended.
4. **Mist length.** "2 turns" is really "rest of this turn plus one" for the activator (1.8). **CONFIRM.**
5. **Wango Again resets the chain depth.** The Wango card it draws is applied at `chain_depth=0`, so a Double Wango can
   chain again inside it. **CONFIRM.**
6. **Golden Pass only guards the post-wrong-answer draw**, not Wango cards that arrive from the wheel, the monkey or
   chains. **CONFIRM.**
7. **Survival counts a fetch error as a personal best** if the streak beats the old best. **CONFIRM.**
8. `game._wango_chain = 0` is assigned but never read (dead). `datetime.utcnow()` is deprecated (warnings in tests).
9. FFF stores `correct_answers = score // 75` ("approximate") in the old database; this is wrong for first-correct
   answers. It disappears with the old tables in Phase 1.

## 5. Intended differences (Phase 2) - owner-approved 31 Oct 2026

The owner accepted all six recommendations. The Phase 2 engine implements the new behaviour by default. Each old
behaviour stays available behind a name in `GameConfig.legacy_quirks` so the parity tests can prove that, with the
quirks on, the engine matches the legacy code exactly; everything else is identical in both modes.

| # | Quirk name | Old behaviour (legacy_quirks) | New behaviour (default) |
|---|---|---|---|
| 1 | `afk_skip` | Removing an AFK player also skips the next player's turn and bumps the round | The next player keeps their turn; the round only advances when the rotation actually wraps |
| 2 | (FFF, not a quirk flag) | Quit / kicked players vanish from the results | They stay in the results with the points they had, ranked below players who finished (`details.left`) |
| 3 | - | Double Down and tiebreak questions ignore laws and the Sombrero | **Unchanged** (kept as a rule) |
| 4 | `mist_short` | Mist = rest of the activating turn plus one | Mist covers the next `mist_turn_duration` full turns (2, or 4 under Mist Magnet) |
| 5a | `wango_again_reset` | A Wango card drawn by Wango Again restarts the Double Wango chain count | The chain count carries through |
| 5b | `golden_pass_wrong_only` | The Golden Pass only blocks the Wango card drawn after a wrong answer | It blocks the next Wango card drawn for that player from any source except extra cards inside a Double Wango chain |
| 6 | (Survival, not a quirk flag) | A fetch error can count as a personal best | An error or give-up never counts (`is_new_best`) |

The legacy text games are left untouched and remain the oracle until the cutover.
