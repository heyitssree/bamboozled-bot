"""/stats and /leaderboard (read-only; names are looked up when shown and never stored)."""

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from ...db.repos import stats as stats_repo
from ...services.names import safe_name
from ..leaderboards import TITLES, LeaderboardView, build_pages, fetch_rows

MODE_CHOICES = [
    app_commands.Choice(name="Bamboozled", value="bamboozled"),
    app_commands.Choice(name="Fastest Fingers First", value="fff"),
    app_commands.Choice(name="Survival", value="survival"),
]
SCOPE_CHOICES = [app_commands.Choice(name="This server", value="server"), app_commands.Choice(name="Everywhere", value="global")]


async def stats_embed(bot, user: discord.abc.User, mode: Optional[str], *, opted_out: bool) -> Optional[discord.Embed]:
    """None when there is nothing to show (no games, or the person opted out)."""
    if opted_out:
        return None
    modes = [mode] if mode else ["bamboozled", "fff", "survival"]
    rows = {m: await stats_repo.player_stats(user.id, m) for m in modes}
    if not any(rows.values()):
        return None
    embed = discord.Embed(title=f"📊 Stats — {safe_name(user.display_name)}", color=discord.Color.blue())
    for m, row in rows.items():
        title = TITLES[m][0]
        if not row:
            embed.add_field(name=title, value="No games yet.", inline=False)
        elif m == "survival":
            embed.add_field(name=title, value=f"🎮 {row['games']} runs · 🔥 best streak **{row['best_streak']}**", inline=False)
        else:
            rate = f"{row['wins'] / row['games'] * 100:.0f}%" if row["games"] else "0%"
            embed.add_field(
                name=title,
                value=f"🎮 {row['games']} games · 🏆 {row['wins']} wins ({rate}) · "
                f"⭐ best {row['best_score']:,} · total {row['total_score']:,}",
                inline=False,
            )
    return embed


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Show your stats, or another player's")
    @app_commands.describe(user="Whose stats (default: you)", mode="One game, or all of them")
    @app_commands.choices(mode=MODE_CHOICES)
    async def stats(
        self, interaction: discord.Interaction, user: Optional[discord.Member] = None, mode: Optional[str] = None
    ) -> None:
        target = user or interaction.user
        embed = await stats_embed(self.bot, target, mode, opted_out=self.bot.ctx.privacy.is_opted_out(target.id))
        if embed is None:
            await interaction.response.send_message(f"No stats found for {safe_name(target.display_name)}.", ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Top players in this server or everywhere")
    @app_commands.describe(mode="Which game", scope="This server or everywhere")
    @app_commands.choices(mode=MODE_CHOICES, scope=SCOPE_CHOICES)
    async def leaderboard(self, interaction: discord.Interaction, mode: str = "bamboozled", scope: str = "server") -> None:
        await interaction.response.defer(thinking=True)
        global_scope = scope == "global" or not interaction.guild_id
        rows = await fetch_rows(
            self.bot,
            mode,
            None if global_scope else interaction.guild_id,
            interaction.guild,
            opted_out=self.bot.ctx.privacy.is_opted_out,
        )
        pages = build_pages(mode, rows, "Everywhere" if global_scope else "This server")
        if len(pages) == 1:
            await interaction.followup.send(embed=pages[0])
        else:
            await interaction.followup.send(embed=pages[0], view=LeaderboardView(pages))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
