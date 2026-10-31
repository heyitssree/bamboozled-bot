"""/privacy status | opt_out | opt_in (spec 10.3). Everything here is ephemeral."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..views.confirm import ConfirmView

log = logging.getLogger("bamboozled.privacy")

EXPLAIN = (
    "**Opting out** deletes your results and stats and stops you joining games, boards and result cards.\n"
    "Bamboozled never saved your name or picture (they are looked up from Discord when shown), so only your Discord id "
    "and your results are removed.\n"
    "Backups and replicas age out within **72 hours** and logs within **14 days**.\n"
    "You can opt back in later with `/privacy opt_in`, after a short wait. "
    "Nothing is restored: your next game starts a fresh profile."
)


class PrivacyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    privacy = app_commands.Group(name="privacy", description="What Bamboozled keeps about you, and how to leave")

    @privacy.command(name="status", description="Are you in or out?")
    async def status(self, interaction: discord.Interaction) -> None:
        st = await self.bot.ctx.privacy.status(interaction.user.id)
        if st.status == "in":
            text = "You are **in**. Bamboozled keeps your Discord id and your results, nothing else."
        else:
            text = f"You are **opted out**. You can opt back in <t:{st.can_opt_in_at}:R> with `/privacy opt_in`."
        await interaction.response.send_message(text, ephemeral=True)

    @privacy.command(name="opt_out", description="Delete my results and stop me joining games")
    async def opt_out(self, interaction: discord.Interaction) -> None:
        priv = self.bot.ctx.privacy
        if priv.is_opted_out(interaction.user.id):
            await interaction.response.send_message("You are already opted out.", ephemeral=True)
            return
        if self.bot.ctx.settings.get("privacy.block_during_game") and priv.in_running_game(interaction.user.id):
            await interaction.response.send_message(
                "You are in a game that is still running. Finish it or leave it, then try again.", ephemeral=True
            )
            return
        view = ConfirmView(interaction.user.id, timeout=60, confirm_label="Yes, delete and opt out")
        await interaction.response.send_message(f"{EXPLAIN}\n\n**Press Confirm within 60 seconds.**", view=view, ephemeral=True)
        await view.wait()
        if view.confirmed is not True:
            text = (
                "Cancelled. Nothing was deleted."
                if view.confirmed is False
                else "That took too long, so nothing was deleted. Run `/privacy opt_out` again if you still want to."
            )
            if view.interaction is not None:
                await view.interaction.response.edit_message(content=text, view=None)
            else:
                await interaction.edit_original_response(content=text, view=None)
            return
        result = await priv.opt_out(interaction.user.id)
        if result.outcome == "in_game":  # started a game between asking and confirming
            text = "You are in a game that is still running. Finish it or leave it, then try again."
        elif result.outcome == "already":
            text = "You are already opted out."
        else:
            p = result.purged or {}
            log.info("user opted out (deleted %s)", p)
            text = (
                "Done. You are opted out and your results were deleted "
                f"({p.get('match_results', 0)} result(s), {p.get('stats', 0)} stat line(s)). "
                "Backups age out within 72 hours and logs within 14 days."
            )
        await view.interaction.response.edit_message(content=text, view=None)

    @privacy.command(name="opt_in", description="Come back")
    async def opt_in(self, interaction: discord.Interaction) -> None:
        result = await self.bot.ctx.privacy.opt_in(interaction.user.id)
        if result.outcome == "cooldown":
            text = f"You can opt back in <t:{result.retry_at}:R>. This short wait stops opt-in and opt-out flip-flopping."
        elif result.outcome == "already":
            text = "You are already in."
        else:
            text = "Welcome back! Nothing was restored: your next game starts a fresh profile."
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PrivacyCog(bot))
