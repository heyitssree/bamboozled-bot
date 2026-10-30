"""The slash-command tree must match tests/fixtures/command_tree_baseline.json.

Later phases change the tree only where the spec says so; when they do, regenerate with
    python tools/snapshot_commands.py tests/fixtures/command_tree_baseline.json
and review the diff.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from snapshot_commands import build_tree  # noqa: E402


def test_command_tree_matches_baseline():
    baseline = json.loads((ROOT / "tests/fixtures/command_tree_baseline.json").read_text())
    assert asyncio.run(build_tree()) == baseline
