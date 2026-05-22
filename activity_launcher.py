"""
activity_launcher.py
Registers the /bamboozled-activity slash command on the bot's CommandTree.
Works with both discord.Client + CommandTree (Navi) and commands.Bot setups.

Usage (discord.Client pattern — Navi bot.py):
    from bamboozled.activity_launcher import register_activity_command
    register_activity_command(tree)   # call before tree.sync()
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import discord
import httpx
from discord import app_commands

logger = logging.getLogger("navi.activity.launcher")


def register_activity_command(tree: app_commands.CommandTree) -> None:
    """Register /bamboozled-activity on the given CommandTree."""

    @tree.command(
        name="bamboozled-activity",
        description="Launch Bamboozled as a Discord Activity in your voice channel",
    )
    @app_commands.describe(
        rounds="Number of rounds (5–20, default 10)",
        difficulty="Question difficulty: easy, medium, or hard",
        category="Trivia category (optional)",
    )
    @app_commands.choices(
        difficulty=[
            app_commands.Choice(name="Easy", value="easy"),
            app_commands.Choice(name="Medium", value="medium"),
            app_commands.Choice(name="Hard", value="hard"),
        ]
    )
    async def launch_activity(
        interaction: discord.Interaction,
        rounds: int = 10,
        difficulty: str = "medium",
        category: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        activity_backend_url = os.getenv("ACTIVITY_BACKEND_URL", "")
        discord_application_id = os.getenv("DISCORD_APPLICATION_ID", "")

        if not activity_backend_url:
            await interaction.followup.send(
                "⚠️ Bamboozled Activity backend is not configured. "
                "Ask an admin to set `ACTIVITY_BACKEND_URL`.",
                ephemeral=True,
            )
            return

        if not discord_application_id:
            await interaction.followup.send(
                "⚠️ `DISCORD_APPLICATION_ID` is not configured. Ask an admin to set it.",
                ephemeral=True,
            )
            return

        rounds = max(5, min(20, rounds))
        guild_id = str(interaction.guild_id) if interaction.guild_id else "0"
        channel_id = str(interaction.channel_id) if interaction.channel_id else "0"
        host_id = str(interaction.user.id)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{activity_backend_url}/session/create",
                    json={
                        "guild_id": guild_id,
                        "channel_id": channel_id,
                        "host_id": host_id,
                        "total_rounds": rounds,
                        "difficulty": difficulty,
                        "category": category,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Session creation failed: HTTP %d", exc.response.status_code)
            await interaction.followup.send(
                "❌ Failed to create game session. The Activity backend returned an error.",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("Session creation failed: %s", exc)
            await interaction.followup.send(
                "❌ Could not reach the Bamboozled Activity backend. Is it running?",
                ephemeral=True,
            )
            return

        session_id: str = data["session_id"]

        # Discord Activity launch URL format:
        # https://discord.com/activities/{APPLICATION_ID}?session_id={session_id}
        activity_url = (
            f"https://discord.com/activities/{discord_application_id}"
            f"?session_id={session_id}"
        )

        embed = discord.Embed(
            title="🎪 Bamboozled Activity",
            description=(
                f"**{rounds} rounds** · Difficulty: **{difficulty.capitalize()}**"
                f"{f' · Category: {category}' if category else ''}\n\n"
                "Click the button below to join the Activity in your voice channel!"
            ),
            color=0x9B59B6,
        )
        embed.set_footer(text=f"Session: {session_id[:8]}…")

        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="🚀 Launch Bamboozled",
                url=activity_url,
                style=discord.ButtonStyle.link,
            )
        )

        await interaction.followup.send(embed=embed, view=view)
        logger.info(
            "Activity session %s launched by %s in guild %s",
            session_id,
            interaction.user,
            guild_id,
        )
