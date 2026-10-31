"""The Discord bot. In the single process it shares a Context with the game server."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..context import Context
from .guards import ALWAYS_ALLOWED, LEGACY_COMMANDS, OPTED_OUT_TEXT

log = logging.getLogger("bamboozled.bot")

# Nothing the bot sends may ping @everyone or roles. Users are only pinged where a message names them on purpose.
SAFE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)
NEW_EXTENSIONS = [
    "bamboozled.bot.cogs.play",
    "bamboozled.bot.cogs.stats",
    "bamboozled.bot.cogs.privacy",
    "bamboozled.bot.cogs.help",
    "bamboozled.bot.cogs.admin",
]
LEGACY_EXTENSIONS = ["cogs.game", "fastest_fingers", "survival", "quiz_stats"]


class GuardedTree(app_commands.CommandTree):
    """Every slash command passes through here first: opted-out users are refused (except /privacy and /help), and the
    legacy text commands disappear for everyone while feature.text_mode is off."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        ctx: Context = interaction.client.ctx
        command = interaction.command
        name = (command.root_parent or command).name if command else ""
        if name in LEGACY_COMMANDS and not ctx.settings.get("feature.text_mode"):
            await interaction.response.send_message(
                "The old text games are retired. Use `/play` to launch Bamboozled.", ephemeral=True
            )
            return False
        if ctx.privacy.is_opted_out(interaction.user.id) and name not in ALWAYS_ALLOWED:
            await interaction.response.send_message(OPTED_OUT_TEXT, ephemeral=True)
            return False
        return True


class BamboozledBot(commands.Bot):
    def __init__(self, ctx: Optional[Context] = None):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents, allowed_mentions=SAFE_MENTIONS, tree_cls=GuardedTree)
        self.ctx = ctx or Context.create()
        self.ctx.bot = self
        self.ctx.on_setting_changed.append(self._setting_changed)

    async def setup_hook(self):
        await self.ctx.init()
        try:
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(self.close()))
        except (NotImplementedError, RuntimeError):
            pass  # not supported on this platform; Ctrl+C still closes cleanly
        for ext in NEW_EXTENSIONS:
            await self.load_extension(ext)
        if self.ctx.settings.get("feature.text_mode"):
            await self._load_legacy()
        from .views.card import PlayAgainView

        self.add_view(PlayAgainView())  # so 'Play again' still works on cards posted before a restart
        await self.sync_commands()

    # ───────────── the legacy text games, switchable at run time ─────────────
    async def _load_legacy(self) -> None:
        for ext in LEGACY_EXTENSIONS:
            if ext not in self.extensions:
                await self.load_extension(ext)

    async def _unload_legacy(self) -> None:
        for ext in LEGACY_EXTENSIONS:
            if ext in self.extensions:
                await self.unload_extension(ext)

    async def _setting_changed(self, key: str, value) -> None:
        if key == "feature.text_mode":
            await (self._load_legacy() if value else self._unload_legacy())
            await self.sync_commands()

    async def sync_commands(self) -> None:
        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash command(s).", len(synced))
        except discord.HTTPException as e:
            if e.code != 50240:
                raise
            # Discord has an Activity Entry Point command that must be included in any bulk sync (error 50240).
            existing = await self.http.get_global_commands(self.application_id)
            entry_points = [c for c in existing if c.get("type") == 4]
            payload = [c.to_dict(self.tree) for c in self.tree.get_commands(guild=None)] + entry_points
            result = await self.http.bulk_upsert_global_commands(self.application_id, payload=payload)
            log.info("Synced %d slash command(s) (Activity Entry Point preserved).", len(result) - len(entry_points))

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        from ..db.repos.legacy_text import get_orphaned_channels

        for cid_str in await get_orphaned_channels():
            channel = self.get_channel(int(cid_str))
            if channel:
                try:
                    await channel.send(
                        "⚠️ **The bot restarted mid-game.** The previous Bamboozled game has been cancelled. "
                        "Use `/play` to start a new one!"
                    )
                except discord.HTTPException:
                    log.warning("Could not send restart notice to channel %s", cid_str)
        log.info("Bamboozled bot is ready!")
