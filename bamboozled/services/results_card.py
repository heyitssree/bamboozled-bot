"""The result card posted in the channel when a game ends (spec 10.4)."""

from __future__ import annotations

import logging
from typing import Iterable

import discord

from .names import display_name, safe_name

log = logging.getLogger("bamboozled.results_card")
MEDALS = ["🥇", "🥈", "🥉"]
TITLES = {"bamboozled": "🎡 Bamboozled", "fff": "⚡ Fastest Fingers First", "survival": "💀 Survival"}
_warned: set[int] = set()  # channels where we already logged a permission problem (log once)


def build_card(mode: str, rows: Iterable, names: dict[int, str]) -> discord.Embed:
    """A podium and the scores. `rows` are engine result rows (already without opted-out players)."""
    rows = list(rows)
    unit = "streak" if mode == "survival" else "pts"
    embed = discord.Embed(title=f"{TITLES.get(mode, 'Bamboozled')} results", color=discord.Color.gold())
    lines = []
    for r in rows[:10]:
        marker = MEDALS[r.rank - 1] if r.rank <= 3 else f"**{r.rank}.**"
        left = " *(left early)*" if r.details.get("left") else ""
        lines.append(f"{marker} {safe_name(names.get(r.user_id, 'A player'))} — **{r.score:,}** {unit}{left}")
    if len(rows) > 10:
        lines.append(f"…and {len(rows) - 10} more")
    embed.description = "\n".join(lines) or "Nobody finished this one."
    embed.set_footer(text="Tap Play again to launch another game.")
    return embed


async def post_result_card(ctx, room, rows) -> bool:
    """Post the card for a finished game. Quiet by design: no mentions, never from a client-supplied channel (the
    channel is the one Discord reported for the Activity instance), skipped without a fuss if we lack permission."""
    bot = ctx.bot
    if bot is None:
        return False
    allowed = ctx.settings.get("channel.results")
    if allowed and room.channel_id not in allowed:
        log.info("result card not posted: channel %s is not in channel.results", room.channel_id)
        return False
    rows = [r for r in rows if not ctx.privacy.is_opted_out(r.user_id)]
    if not rows:
        return False
    channel = bot.get_channel(room.channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(room.channel_id)
        except discord.HTTPException:
            return _warn_once(room.channel_id, "cannot see the channel")
    guild = getattr(channel, "guild", None)
    me = getattr(guild, "me", None)
    if me is not None and not (channel.permissions_for(me).send_messages and channel.permissions_for(me).embed_links):
        return _warn_once(room.channel_id, "missing Send Messages or Embed Links")
    names = {r.user_id: await display_name(bot, r.user_id, guild) for r in rows}
    from ..bot.views.card import PlayAgainView

    try:
        await channel.send(
            embed=build_card(room.mode, rows, names), view=PlayAgainView(), allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.Forbidden:
        return _warn_once(room.channel_id, "Discord refused the message")
    except discord.HTTPException as exc:
        log.warning("result card failed in channel %s: %s", room.channel_id, exc)
        return False
    return True


def _warn_once(channel_id: int, why: str) -> bool:
    if channel_id not in _warned:
        _warned.add(channel_id)
        log.warning("result card skipped in channel %s: %s (not logged again for this channel)", channel_id, why)
    return False
