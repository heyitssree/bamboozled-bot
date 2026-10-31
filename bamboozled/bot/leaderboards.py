"""Leaderboard and stats embeds. Names are resolved when shown and escaped; opted-out players never appear."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord.utils import escape_markdown, escape_mentions

from ..db.repos import stats as stats_repo
from ..services.names import display_name

log = logging.getLogger("bamboozled.leaderboards")
PAGE_SIZE = 10
MEDALS = ["🥇", "🥈", "🥉"]
TITLES = {
    "fff": ("⚡ Fastest Fingers First", discord.Color.from_rgb(255, 200, 0)),
    "survival": ("💀 Survival Mode", discord.Color.from_rgb(220, 50, 50)),
    "bamboozled": ("🎬 Bamboozled", discord.Color.orange()),
}
BOARDS = {"bamboozled": stats_repo.bamboozled_board, "fff": stats_repo.fff_board, "survival": stats_repo.survival_board}


class LeaderboardView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed]):
        super().__init__(timeout=120)
        self.pages, self.current = pages, 0
        self._buttons()

    def _buttons(self) -> None:
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1

    async def _go(self, interaction: discord.Interaction, step: int) -> None:
        self.current = max(0, min(len(self.pages) - 1, self.current + step))
        self._buttons()
        try:
            await interaction.response.edit_message(embed=self.pages[self.current], view=self)
        except discord.HTTPException as exc:
            log.debug("leaderboard page edit failed: %s", exc)

    @discord.ui.button(label="◄ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await self._go(interaction, -1)

    @discord.ui.button(label="Next ►", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await self._go(interaction, 1)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


def row_text(mode: str, row: dict) -> str:
    if mode == "bamboozled":
        games = row.get("games") or 0
        rate = f"{row['wins'] / games * 100:.0f}% win rate" if games else "0% win rate"
        return f"🏆 {row['wins']} wins · {rate} · 🎮 {games} games · ⭐ {row['total_score']:,} pts"
    if mode == "fff":
        speed = f" · ⚡ {row['avg_response_ms']}ms avg" if row.get("avg_response_ms") else ""
        return f"✅ {row['correct_answers']}/{row['total_questions']} correct{speed}"
    cat = f" · {row['category']}" if row.get("category") else ""
    return f"🔥 Streak: **{row['streak']}** · {str(row['difficulty']).title()}{cat}"


def build_pages(mode: str, rows: list[dict], scope_label: str) -> list[discord.Embed]:
    title, color = TITLES[mode]
    if not rows:
        return [
            discord.Embed(
                title=f"{title} Leaderboard ({scope_label})",
                color=color,
                description="Nothing here yet. Launch the Activity with `/play` to get on the board!",
            )
        ]
    total = (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE
    pages = []
    for start in range(0, len(rows), PAGE_SIZE):
        embed = discord.Embed(title=f"{title} Leaderboard ({scope_label})", color=color)
        for i, row in enumerate(rows[start : start + PAGE_SIZE]):
            rank = start + i + 1
            embed.add_field(
                name=f"{MEDALS[rank - 1] if rank <= 3 else f'#{rank}'} {row['username']}", value=row_text(mode, row), inline=False
            )
        embed.set_footer(text=f"Page {start // PAGE_SIZE + 1}/{total}")
        pages.append(embed)
    return pages


async def fetch_rows(bot, mode: str, guild_id: Optional[int], guild, *, opted_out) -> list[dict]:
    """Board rows with display names attached now (never stored) and opted-out players removed."""
    rows = await BOARDS[mode](guild_id)
    rows = [r for r in rows if not opted_out(r["user_id"])]
    for row in rows:
        row["username"] = escape_mentions(escape_markdown(await display_name(bot, row["user_id"], guild)))
    return rows
