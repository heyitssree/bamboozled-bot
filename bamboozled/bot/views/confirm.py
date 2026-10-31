"""A Confirm / Cancel prompt that only the person who asked can answer, and that expires."""

from __future__ import annotations

from typing import Optional

import discord


class ConfirmView(discord.ui.View):
    def __init__(self, user_id: int, *, timeout: float = 60, confirm_label: str = "Yes, do it", danger: bool = True):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.confirmed: Optional[bool] = None
        self.interaction: Optional[discord.Interaction] = None
        self.confirm_btn.label = confirm_label
        self.confirm_btn.style = discord.ButtonStyle.danger if danger else discord.ButtonStyle.primary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This prompt belongs to someone else.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        self.confirmed, self.interaction = True, interaction
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        self.confirmed, self.interaction = False, interaction
        self.stop()

    async def on_timeout(self) -> None:
        self.confirmed = None
