"""The 'Play again' button on a result card. Persistent (fixed custom_id), so it keeps working after a restart."""

from __future__ import annotations

import discord

from ..guards import refuse_if_opted_out


class PlayAgainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Play again", emoji="🎡", style=discord.ButtonStyle.primary, custom_id="bamboozled:play_again")
    async def play_again(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        if await refuse_if_opted_out(interaction):
            return
        if interaction.client.ctx.settings.get("system.killswitch"):
            await interaction.response.send_message("Bamboozled is closed for maintenance. Try again shortly.", ephemeral=True)
            return
        await launch(interaction)


async def launch(interaction: discord.Interaction) -> None:
    """Launch the Activity from this interaction, or tell the person how if Discord will not let us."""
    try:
        await interaction.response.launch_activity()
    except (AttributeError, TypeError, discord.HTTPException):
        text = "Open the **App Launcher** (the rocket icon next to the message box) and pick **Bamboozled**."
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
