"""Dump the slash-command tree (names, descriptions, options, choices, permissions) as JSON.

Loads the cogs against an offline Bot object; nothing connects to Discord.
Usage: python tools/snapshot_commands.py [out.json]   (default: print to stdout)
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord
from discord.ext import commands

EXTENSIONS = ["cogs.game", "fastest_fingers", "survival", "quiz_stats"]


def _normalise(obj):
    if isinstance(obj, dict):
        return {k: _normalise(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_normalise(v) for v in obj]
    return obj


async def build_tree() -> list[dict]:
    from activity_launcher import register_activity_command

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    for ext in EXTENSIONS:
        await bot.load_extension(ext)
    register_activity_command(bot.tree)
    cmds = [c.to_dict(bot.tree) for c in bot.tree.get_commands(guild=None)]
    cmds.sort(key=lambda c: c["name"])
    await bot.close()
    return _normalise(cmds)


def main(argv: list[str]) -> int:
    tree = asyncio.run(build_tree())
    text = json.dumps(tree, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if argv:
        Path(argv[0]).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
