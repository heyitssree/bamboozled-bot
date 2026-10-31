"""/help: what the Activity is and how to start it, with a screenshot."""

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

ASSET = Path(__file__).resolve().parents[1] / "assets" / "help.png"


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="What Bamboozled is and how to start a game")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🎡 Bamboozled",
            color=discord.Color.orange(),
            description=(
                "Chaos trivia for your voice channel. Everything happens in a window inside Discord.\n\n"
                "**How to start:** join a voice channel, then type `/play` or open the **App Launcher** "
                "(the rocket icon) and pick Bamboozled. "
                "Everyone in the call can join the same game."
            ),
        )
        embed.add_field(
            name="Three games",
            inline=False,
            value=(
                "🎡 **Bamboozled**: take turns answering, draw cards, spin the wheel, survive the Mist.\n"
                "⚡ **Fastest Fingers First**: everyone answers at once; the fastest correct answer scores most.\n"
                "💀 **Survival**: keep your streak alive; one wrong answer ends your run."
            ),
        )
        embed.add_field(
            name="Commands",
            inline=False,
            value=(
                "`/play` start a game · `/stats` your numbers · `/leaderboard` the top players · "
                "`/privacy` see what is kept about you, or opt out"
            ),
        )
        embed.set_footer(text="Bamboozled keeps only your Discord id and your results, never your name or picture.")
        kwargs = {}
        if ASSET.is_file():
            embed.set_image(url="attachment://help.png")
            kwargs["file"] = discord.File(ASSET, filename="help.png")
        await interaction.response.send_message(embed=embed, ephemeral=True, **kwargs)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
