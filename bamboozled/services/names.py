"""Resolve Discord ids to display names at display time. Names are cached in memory for 24 h and never stored."""
import time
from typing import Optional

import discord

_TTL = 24 * 3600
_cache: dict[int, tuple[float, str]] = {}


def clear() -> None:
    _cache.clear()


async def display_name(bot: discord.Client, user_id: int, guild: Optional[discord.Guild] = None) -> str:
    hit = _cache.get(user_id)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    name = None
    member = guild.get_member(user_id) if guild else None
    if member:
        name = member.display_name
    else:
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except discord.HTTPException:
                user = None
        if user:
            name = user.display_name
    name = name or "Unknown player"
    _cache[user_id] = (time.monotonic(), name)
    return name


def forget(user_id: int) -> None:
    _cache.pop(user_id, None)


def safe_name(name: str) -> str:
    """Make a player-supplied name safe to embed in a message: no markdown, no @mentions."""
    return discord.utils.escape_mentions(discord.utils.escape_markdown(name))


def ping_only(*user_ids: int) -> discord.AllowedMentions:
    """Allowed mentions for a message that must ping exactly these users and nobody else."""
    return discord.AllowedMentions(everyone=False, roles=False, users=[discord.Object(id=i) for i in user_ids],
                                   replied_user=False)
