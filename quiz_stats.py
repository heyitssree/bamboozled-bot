"""/quizstats: an alias of /leaderboard, kept for one release after the cutover and then deleted."""

import discord
from discord import app_commands
from discord.ext import commands

from bamboozled.bot.leaderboards import LeaderboardView, build_pages, fetch_rows


class QuizStatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="quizstats", description="Old name of /leaderboard (it will be removed soon).")
    @app_commands.describe(mode="Which game mode to show stats for", scope="Server only, or global across all servers")
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
    async def quizstats(self, interaction: discord.Interaction, mode: str, scope: str = "server") -> None:
        await interaction.response.defer(thinking=True)
        global_scope = scope == "global" or not interaction.guild_id
        rows = await fetch_rows(
            self.bot,
            mode,
            None if global_scope else interaction.guild_id,
            interaction.guild,
            opted_out=self.bot.ctx.privacy.is_opted_out,
        )
        pages = build_pages(mode, rows, "Global" if global_scope else "This Server")
        await interaction.followup.send(embed=pages[0], view=LeaderboardView(pages) if len(pages) > 1 else discord.utils.MISSING)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuizStatsCog(bot))
