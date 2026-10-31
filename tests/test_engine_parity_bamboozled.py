"""Bamboozled: the engine (with the legacy quirks switched on) equals the legacy code on seeded games."""
import pytest

from tests.parity import run_engine, run_legacy

SEEDS = range(150)


def shape(seed):
    return 2 + seed % 3, 2 + seed % 2          # players 2..4, rounds 2..3


@pytest.mark.parametrize("seed", SEEDS)
def test_engine_matches_legacy_turn_by_turn_and_in_the_final_ranking(seed):
    n, rounds = shape(seed)
    legacy_trace, legacy_rows = run_legacy(seed, n, rounds)
    engine_trace, engine_rows = run_engine(seed, n, rounds)
    for i, (a, b) in enumerate(zip(legacy_trace, engine_trace)):
        assert a == b, f"seed {seed}: first difference at turn {i}"
    assert len(legacy_trace) == len(engine_trace)
    assert legacy_rows == engine_rows


@pytest.mark.parametrize("law", range(1, 12))
@pytest.mark.parametrize("seed", range(12))
def test_every_law_in_force_from_the_first_turn_matches_legacy(law, seed):
    n, rounds = 2 + seed % 3, 3
    legacy_trace, legacy_rows = run_legacy(seed, n, rounds, initial_law=law)
    engine_trace, engine_rows = run_engine(seed, n, rounds, initial_law=law)
    assert legacy_trace == engine_trace
    assert legacy_rows == engine_rows
