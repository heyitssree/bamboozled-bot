"""/play: launch the Activity from this channel."""

import discord
from discord import app_commands
from discord.ext import commands

from ..views.card import launch


class PlayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="play", description="Launch Bamboozled in a voice channel")
    async def play(self, interaction: discord.Interaction) -> None:
        if self.bot.ctx.settings.get("system.killswitch"):
            await interaction.response.send_message("Bamboozled is closed for maintenance. Try again shortly.", ephemeral=True)
            return
        await launch(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayCog(bot))
