"""Enforcement points for the bot side: opted-out users, kill switch, admin rights."""

from __future__ import annotations

import discord

OPTED_OUT_TEXT = "You have opted out of Bamboozled, so I can't do that. Use `/privacy opt_in` to play again."
ALWAYS_ALLOWED = {"privacy", "help"}  # commands an opted-out user may still use
LEGACY_COMMANDS = {"bamboozled", "fff", "survival", "quizstats"}


def ctx_of(interaction: discord.Interaction):
    return interaction.client.ctx  # set by BamboozledBot


async def refuse_if_opted_out(interaction: discord.Interaction) -> bool:
    """For buttons and other components (slash commands are covered by the command tree check). True = refused."""
    if ctx_of(interaction).privacy.is_opted_out(interaction.user.id):
        await _say(interaction, OPTED_OUT_TEXT)
        return True
    return False


async def _say(interaction: discord.Interaction, text: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


async def is_admin(interaction: discord.Interaction) -> bool:
    """The application owner, or someone with the configured panel role. (The command also needs the Administrator
    permission by default, so it stays hidden from ordinary members.)"""
    user = interaction.user
    if await interaction.client.is_owner(user):
        return True
    role_id = ctx_of(interaction).settings.get("system.panel_role")
    return bool(role_id) and any(getattr(r, "id", None) == role_id for r in getattr(user, "roles", []))
