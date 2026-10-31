"""Play any mode in a terminal against scripted bots, to judge the rules before any GUI exists.

    python tools/play_cli.py --mode bamboozled --bots 2 --rounds 3
    python tools/play_cli.py --mode fff --bots 3 --rounds 6
    python tools/play_cli.py --mode survival
    python tools/play_cli.py --mode bamboozled --auto --seed 4      # bots only: watch a whole game

You are player 1. Questions come from data/custom_questions.json (offline). Deadlines are simulated: you may think as
long as you like, and the bots' replies and any timeouts follow the same clock the real server would use.
Use --quirks to switch the old behaviours back on (afk_skip, mist_short, wango_again_reset, golden_pass_wrong_only).
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bamboozled.engine import (ANSWER, DRAW_CARD, FORFEIT, LEAVE, PICK_RULE, PICK_TARGET, SPIN,  # noqa: E402
                               GameConfig, Intent, PlayerRef, Question, get_engine)
from bamboozled.engine import rules as R  # noqa: E402
from bamboozled.engine.bots import deadline_of, legal_intents  # noqa: E402

HUMAN = 1
LETTERS = "ABCD"


def load_questions(rng: random.Random):
    raw = json.loads((ROOT / "data" / "custom_questions.json").read_text(encoding="utf-8"))
    rng.shuffle(raw)

    def make(_need=None):
        item = raw.pop() if raw else {"question": "Placeholder question?", "correct_answer": "Yes",
                                      "incorrect_answers": ["No", "Maybe", "Never"], "category": "Misc", "difficulty": "easy"}
        answers = [item["correct_answer"]] + list(item["incorrect_answers"])
        rng.shuffle(answers)
        return Question(item["question"], tuple(answers), answers.index(item["correct_answer"]),
                        item.get("category", ""), item.get("difficulty", "medium"))
    return make


def name(uid: int) -> str:
    return "You" if uid == HUMAN else f"Bot{uid - 1}"


def describe(ev) -> str:
    p = ev.payload
    k = ev.kind
    who = name(p["player"]) if "player" in p else ""
    table = {
        "turn_start": lambda: f"--- {who}'s turn (round {p['round']}) ---",
        "turn_skipped": lambda: f"{who} is silenced and loses this turn",
        "card_drawn": lambda: f"{who} draws {p['card']} ({p['deck']})",
        "wheel_result": lambda: f"The wheel lands on {p['segment']} for {who}",
        "monkey_result": lambda: f"Golden Monkey: {who} picks {p['choice']} -> {p['delta']:+d}",
        "scores_swapped": lambda: f"{name(p['a'])} and {name(p['b'])} swap scores",
        "steal": lambda: f"{name(p['to'])} steals {p['amount']} from {name(p['from'])}",
        "law_set": lambda: f"{who} sets a new law: {R.law(p['law']).name}",
        "law_expired": lambda: f"Law {R.law(p['law']).name} has expired",
        "law_effect": lambda: f"Law {R.law(p['law']).name}: {who} {p['delta']:+d}",
        "mist_on": lambda: "The Mystic Mist descends: scores are hidden",
        "mist_off": lambda: "The Mist clears",
        "golden_pass_used": lambda: f"{who} burns their Golden Pass",
        "player_removed": lambda: f"{name(p['player'])} is out ({p['why']})",
        "player_left": lambda: f"{name(p['player'])} is out ({p['why']})",
        "sudden_bamboozle": lambda: "TIE! Sudden Bamboozle",
        "streak_up": lambda: f"Streak: {p['streak']}",
        "game_over": lambda: "GAME OVER",
        "chain_recoil": lambda: "The Double Wango chain recoils",
        "streak_breaker": lambda: f"Streak Breaker: {who} gets a Wango card instead",
    }
    if k == "reveal":
        if "correct_index" in p and "kind" in p:
            return f"Answer: {LETTERS[p['correct_index']]}" + ("  (timed out)" if p.get("timed_out") else "")
        return f"Answer: {LETTERS[p['correct_index']]}  winners: {', '.join(name(u) for u in p['winners']) or 'nobody'}"
    return table[k]() if k in table else ""


def show_scores(e, state, out):
    v = e.view_for(state, HUMAN)
    if v["mode"] == "survival":
        out(f"  streak: {v['streak']}")
        return
    cells = [f"{name(p['user_id'])}: {'??' if p['score'] is None else p['score']}" for p in v["players"]]
    out("  scores | " + " | ".join(cells))


def ask_choice(prompt, options, ask, out):
    for i, text in enumerate(options, 1):
        out(f"   {i}) {text}")
    while True:
        raw = ask(f"{prompt} > ").strip().lower()
        if raw in ("q", "quit"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        out("   pick a number from the list (or q to quit)")


def human_move(state, moves, ask, out):
    p = getattr(state, "pending", None)
    if p is not None and p.kind == "answer" or (p is None and hasattr(state, "answers")) or hasattr(state, "player"):
        q = state.question
        out(f"\n? {q.text}")
        answer_moves = [(a, m) for a, m in moves if m.kind == ANSWER]
        for i, text in enumerate(q.answers):
            out(f"   {LETTERS[i]}) {text}")
        extra = [(a, m) for a, m in moves if m.kind in (FORFEIT, LEAVE)]
        options = [f"answer {LETTERS[i]}" for i in range(len(answer_moves))] + (["give up / leave"] if extra else [])
        i = ask_choice("your move", options, ask, out)
        if i is None:
            return extra[0] if extra else None
        return (answer_moves + extra)[i]
    kinds = {m.kind for _, m in moves}
    if DRAW_CARD in kinds:
        out(f"\n{name(p.actor)}: press enter to draw a {p.data['which']} card")
        ask("")
        return moves[0]
    if SPIN in kinds:
        out("\nPress enter to spin the wheel")
        ask("")
        return moves[0]
    if PICK_TARGET in kinds:
        labels = [("skip" if m.user_id is None else name(m.user_id)) for _, m in moves]
        i = ask_choice("choose a player", labels, ask, out)
        return moves[0 if i is None else i]
    if PICK_RULE in kinds:
        i = ask_choice("choose a law", [f"{law.name}: {law.description}" for law in R.LAWS], ask, out)
        return moves[0 if i is None else i]
    i = ask_choice("Golden Monkey", ["belly", "tail"], ask, out)
    return moves[0 if i is None else i]


def play(args, ask=input, out=print):
    rng = random.Random(args.seed)
    e = get_engine(args.mode)
    n = 1 if args.mode == "survival" else 1 + args.bots
    cfg = GameConfig(mode=args.mode, rounds=args.rounds, difficulty=args.difficulty,
                     legacy_quirks=frozenset(q for q in args.quirks.split(",") if q))
    state = e.new_game(cfg, [PlayerRef(i + 1) for i in range(n)], random.Random(args.seed + 1), 0)
    next_question = load_questions(rng)
    now = 0
    out(f"Bamboozled CLI - {args.mode}, {n} player(s), seed {args.seed}. You are 'You'.")

    def emit(result):
        for ev in result.events:
            text = describe(ev)
            if text:
                out(text)
        return result.state

    for _ in range(100_000):
        if e.is_over(state):
            break
        need = e.needs_question(state)
        if need:
            state = emit(e.supply_question(state, next_question(need), now))
            if args.mode == "fff":
                q = state.question
                out(f"\n? {q.text}")
                for i, text in enumerate(q.answers):
                    out(f"   {LETTERS[i]}) {text}")
                state = fff_round(e, state, rng, ask, out, emit, args.auto)
                now = state.q_start_ms + 10_000 if state.question else now
                show_scores(e, state, out)
            continue
        moves = legal_intents(state)
        deadline = deadline_of(state)
        actor = moves[0][0] if moves else None
        if args.mode == "survival" and not args.auto:
            choice = human_move(state, moves, ask, out)
            now += 3000
            state = emit(e.apply(state, choice[0], choice[1], now))
            continue
        if actor == HUMAN and not args.auto:
            show_scores(e, state, out)
            choice = human_move(state, moves, ask, out)
            now += 3000
            if deadline is not None and now > deadline:
                now = deadline
                state = emit(e.on_timeout(state, now))
            else:
                state = emit(e.apply(state, choice[0], choice[1], now))
            continue
        # a bot (or --auto): a random legal move, now and then letting the clock run out
        if not moves or (deadline is not None and rng.random() < 0.1):
            now = max(now, deadline or now)
            state = emit(e.on_timeout(state, now))
        else:
            a, intent = rng.choice(moves)
            now += 800
            state = emit(e.apply(state, a, intent, now))
    out("\nFinal standings:")
    for r in e.results(state):
        extra = f" ({r.details['left']})" if r.details.get("left") else ""
        out(f"  {r.rank}. {name(r.user_id)}: {r.score}{extra}")
    return state


def fff_round(e, state, rng, ask, out, emit, auto):
    """Everyone answers the same question: you pick, the bots reply at random speeds (some do not answer)."""
    start = state.q_start_ms
    plan = []
    for u in list(state.players):
        if u == HUMAN and not auto:
            i = ask_choice("your answer", [f"answer {c}" for c in LETTERS[:len(state.question.answers)]] + ["leave"], ask, out)
            plan.append((start + 2500, u, Intent(LEAVE) if i is None or i >= len(state.question.answers)
                         else Intent(ANSWER, index=i)))
        elif rng.random() < 0.85:
            plan.append((start + rng.randint(800, 9000), u, Intent(ANSWER, index=rng.randrange(len(state.question.answers)))))
    for ts, u, intent in sorted(plan, key=lambda t: t[0]):
        if state.question is None:
            break
        state = emit(e.apply(state, u, intent, ts))
    if state.question is not None:
        state = emit(e.on_timeout(state, start + 10_000))
    return state


def main(argv=None, ask=input, out=print):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["bamboozled", "fff", "survival"], default="bamboozled")
    ap.add_argument("--bots", type=int, default=2)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--difficulty", default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--auto", action="store_true", help="bots play every seat, including yours")
    ap.add_argument("--quirks", default="", help="comma-separated legacy quirks to switch on")
    args = ap.parse_args(argv)
    play(args, ask, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
