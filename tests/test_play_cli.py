"""tools/play_cli.py: the terminal player runs every mode to the end, with bots only and with a scripted human."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import play_cli  # noqa: E402


def run(argv, answers=None):
    lines = []
    feed = iter(answers) if answers is not None else None
    ask = (lambda prompt="": next(feed)) if feed else (lambda prompt="": pytest.fail("asked for input in --auto mode"))
    assert play_cli.main(argv, ask=ask, out=lines.append) == 0
    return "\n".join(lines)


@pytest.mark.parametrize("mode", ["bamboozled", "fff", "survival"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_bots_only_game_finishes_with_standings(mode, seed):
    text = run(["--mode", mode, "--auto", "--seed", str(seed), "--bots", "2", "--rounds", "3"])
    assert "Final standings:" in text and "1. " in text


def test_a_scripted_human_can_play_bamboozled():
    text = run(["--mode", "bamboozled", "--seed", "5", "--bots", "1", "--rounds", "2"], answers=iter(lambda: "1", None))
    assert "Final standings:" in text and "You" in text


def test_a_scripted_human_can_play_fff_and_can_quit():
    text = run(["--mode", "fff", "--seed", "5", "--bots", "2", "--rounds", "3"], answers=iter(lambda: "1", None))
    assert "Final standings:" in text
    quit_text = run(["--mode", "fff", "--seed", "5", "--bots", "1", "--rounds", "3"], answers=iter(lambda: "q", None))
    assert "You is out (quit)" in quit_text or "Final standings:" in quit_text


def test_survival_ends_on_a_wrong_answer_or_give_up():
    text = run(["--mode", "survival", "--seed", "2"], answers=iter(lambda: "2", None))
    assert "Final standings:" in text
    assert "Final standings:" in run(["--mode", "survival", "--seed", "2"], answers=iter(lambda: "q", None))


def test_legacy_quirks_can_be_switched_on():
    assert "Final standings:" in run(["--auto", "--seed", "1", "--quirks", "afk_skip,mist_short"])
    with pytest.raises(ValueError):
        run(["--auto", "--quirks", "nope"])
