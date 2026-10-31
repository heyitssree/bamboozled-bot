"""Dump the slash-command tree (names, descriptions, options, choices, permissions) as JSON.

Loads every extension against an offline bot; nothing connects to Discord.
Usage: python tools/snapshot_commands.py [out.json]   (default: print to stdout)
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bamboozled.bot.client import LEGACY_EXTENSIONS, NEW_EXTENSIONS, BamboozledBot  # noqa: E402


def _normalise(obj):
    if isinstance(obj, dict):
        return {k: _normalise(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_normalise(v) for v in obj]
    return obj


async def build_tree() -> list[dict]:
    bot = BamboozledBot()
    for ext in NEW_EXTENSIONS + LEGACY_EXTENSIONS:
        await bot.load_extension(ext)
    cmds = [c.to_dict(bot.tree) for c in bot.tree.get_commands(guild=None)]
    cmds.sort(key=lambda c: c["name"])
    await bot.close()
    return _normalise(cmds)


def main(argv: list[str]) -> int:
    text = json.dumps(asyncio.run(build_tree()), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if argv:
        Path(argv[0]).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
