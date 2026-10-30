"""
quiz_stats.py
Shared leaderboard command cog for all quiz game modes.

Command:
    /quizstats mode:<fff|survival|bamboozled> scope:<server|global>

Displays paginated leaderboard (10 per page) from the appropriate table.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import escape_markdown, escape_mentions

from bamboozled.db.repos import stats as stats_repo
from bamboozled.services.names import display_name

logger = logging.getLogger("bamboozled.quiz_stats")

_PAGE_SIZE = 10
_MEDALS = ["🥇", "🥈", "🥉"]


# ---------------------------------------------------------------------------
# Paginated embed view
# ---------------------------------------------------------------------------


class LeaderboardView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed]):
        super().__init__(timeout=120)
        self.pages = pages
        self.current = 0
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1

    @discord.ui.button(label="◄ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        self.current = max(0, self.current - 1)
        self._update_buttons()
        try:
            await interaction.response.edit_message(embed=self.pages[self.current], view=self)
        except discord.HTTPException as exc:
            logger.debug("LeaderboardView prev_btn edit failed: %s", exc)

    @discord.ui.button(label="Next ►", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_buttons()
        try:
            await interaction.response.edit_message(embed=self.pages[self.current], view=self)
        except discord.HTTPException as exc:
            logger.debug("LeaderboardView next_btn edit failed: %s", exc)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


async def _fetch(fn, guild_id: int, global_scope: bool, bot, guild) -> list[dict]:
    """Run a board query and attach display names (resolved now, never stored)."""
    try:
        rows = await fn(None if global_scope else guild_id)
    except Exception as exc:
        logger.warning("quiz_stats: leaderboard fetch failed: %s", exc)
        return []
    for row in rows:
        row["username"] = escape_mentions(escape_markdown(await display_name(bot, row["user_id"], guild)))
    return rows


# ---------------------------------------------------------------------------
# Embed builders
# ---------------------------------------------------------------------------


def _build_fff_pages(rows: list[dict], scope_label: str) -> list[discord.Embed]:
    if not rows:
        embed = discord.Embed(
            title=f"⚡ Fastest Fingers First Leaderboard ({scope_label})",
            description="No games recorded yet. Play `/fff` to get on the board!",
            color=discord.Color.from_rgb(255, 200, 0),
        )
        return [embed]

    pages: list[discord.Embed] = []
    for page_start in range(0, len(rows), _PAGE_SIZE):
        page_rows = rows[page_start:page_start + _PAGE_SIZE]
        embed = discord.Embed(
            title=f"⚡ Fastest Fingers First Leaderboard ({scope_label})",
            color=discord.Color.from_rgb(255, 200, 0),
        )
        for i, row in enumerate(page_rows):
            rank = page_start + i + 1
            medal = _MEDALS[rank - 1] if rank <= 3 else f"#{rank}"
            avg_ms = row.get("avg_response_ms")
            speed_str = f" · ⚡ {avg_ms}ms avg" if avg_ms else ""
            embed.add_field(
                name=f"{medal} {row['username']}",
                value=(
                    f"✅ {row['correct_answers']}/{row['total_questions']} correct"
                    f"{speed_str}"
                ),
                inline=False,
            )
        total_pages = (len(rows) + _PAGE_SIZE - 1) // _PAGE_SIZE
        current_page = page_start // _PAGE_SIZE + 1
        embed.set_footer(text=f"Page {current_page}/{total_pages} · Ranked by correct answers, then speed")
        pages.append(embed)
    return pages


def _build_survival_pages(rows: list[dict], scope_label: str) -> list[discord.Embed]:
    if not rows:
        embed = discord.Embed(
            title=f"💀 Survival Mode Leaderboard ({scope_label})",
            description="No games recorded yet. Play `/survival` to get on the board!",
            color=discord.Color.from_rgb(220, 50, 50),
        )
        return [embed]

    pages: list[discord.Embed] = []
    for page_start in range(0, len(rows), _PAGE_SIZE):
        page_rows = rows[page_start:page_start + _PAGE_SIZE]
        embed = discord.Embed(
            title=f"💀 Survival Mode Leaderboard ({scope_label})",
            color=discord.Color.from_rgb(220, 50, 50),
        )
        for i, row in enumerate(page_rows):
            rank = page_start + i + 1
            medal = _MEDALS[rank - 1] if rank <= 3 else f"#{rank}"
            cat_str = f" · {row['category']}" if row.get("category") else ""
            embed.add_field(
                name=f"{medal} {row['username']}",
                value=(
                    f"🔥 Streak: **{row['streak']}** · {row['difficulty'].title()}{cat_str}"
                ),
                inline=False,
            )
        total_pages = (len(rows) + _PAGE_SIZE - 1) // _PAGE_SIZE
        current_page = page_start // _PAGE_SIZE + 1
        embed.set_footer(text=f"Page {current_page}/{total_pages} · Ranked by highest streak")
        pages.append(embed)
    return pages


def _build_bamboozled_pages(rows: list[dict], scope_label: str) -> list[discord.Embed]:
    if not rows:
        embed = discord.Embed(
            title=f"🎬 Bamboozled Leaderboard ({scope_label})",
            description="No Bamboozled scores recorded yet. Play `/bamboozled start` to get on the board!",
            color=discord.Color.orange(),
        )
        return [embed]

    pages: list[discord.Embed] = []
    for page_start in range(0, len(rows), _PAGE_SIZE):
        page_rows = rows[page_start:page_start + _PAGE_SIZE]
        embed = discord.Embed(
            title=f"🎬 Bamboozled Leaderboard ({scope_label})",
            color=discord.Color.orange(),
        )
        for i, row in enumerate(page_rows):
            rank = page_start + i + 1
            medal = _MEDALS[rank - 1] if rank <= 3 else f"#{rank}"
            games_played = row.get("games", 0) or 0
            win_rate = (
                f"{row['wins'] / games_played * 100:.0f}% win rate"
                if games_played > 0 else "0% win rate"
            )
            embed.add_field(
                name=f"{medal} {row['username']}",
                value=(
                    f"🏆 {row['wins']} wins · {win_rate} · "
                    f"🎮 {games_played} games played"
                ),
                inline=False,
            )
        total_pages = (len(rows) + _PAGE_SIZE - 1) // _PAGE_SIZE
        current_page = page_start // _PAGE_SIZE + 1
        embed.set_footer(text=f"Page {current_page}/{total_pages} · Ranked by games won")
        pages.append(embed)
    return pages


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class QuizStatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        logger.info("QuizStatsCog loaded.")

    async def cog_unload(self) -> None:
        logger.info("QuizStatsCog unloaded.")

    # ── /quizstats ────────────────────────────────────────────

    @app_commands.command(
        name="quizstats",
        description="View leaderboards for FFF, Survival, or Bamboozled quiz modes."
    )
    @app_commands.describe(
        mode="Which game mode to show stats for",
        scope="Server only, or global across all servers",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Fastest Fingers First (FFF)", value="fff"),
            app_commands.Choice(name="Survival Mode", value="survival"),
            app_commands.Choice(name="Bamboozled", value="bamboozled"),
        ],
        scope=[
            app_commands.Choice(name="This server", value="server"),
            app_commands.Choice(name="Global (all servers)", value="global"),
        ],
    )
    async def quizstats(
        self,
        interaction: discord.Interaction,
        mode: str,
        scope: str = "server",
    ) -> None:
        await interaction.response.defer(thinking=True)

        guild_id = interaction.guild_id or 0
        global_scope = scope == "global"
        scope_label = "Global" if global_scope else "This Server"

        if mode == "fff":
            rows = await _fetch(stats_repo.fff_board, guild_id, global_scope, self.bot, interaction.guild)
            pages = _build_fff_pages(rows, scope_label)
        elif mode == "survival":
            rows = await _fetch(stats_repo.survival_board, guild_id, global_scope, self.bot, interaction.guild)
            pages = _build_survival_pages(rows, scope_label)
        elif mode == "bamboozled":
            rows = await _fetch(stats_repo.bamboozled_board, guild_id, global_scope, self.bot, interaction.guild)
            pages = _build_bamboozled_pages(rows, scope_label)
        else:
            await interaction.followup.send("⚠️ Unknown mode.", ephemeral=True)
            return

        if len(pages) == 1:
            await interaction.followup.send(embed=pages[0])
        else:
            view = LeaderboardView(pages)
            await interaction.followup.send(embed=pages[0], view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuizStatsCog(bot))
