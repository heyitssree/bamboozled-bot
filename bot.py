"""Entry point for the Bamboozled Discord bot."""
import asyncio
import logging
import os
import signal
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from activity_launcher import register_activity_command
from bamboozled.db.connection import db_path
from bamboozled.db.migrate import migrate_async
from bamboozled.db.repos.legacy_text import get_orphaned_channels

load_dotenv()


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    # On by default for local runs; the container sets LOG_TO_FILE=0 and logs to stdout only.
    if os.getenv("LOG_TO_FILE", "1").lower() not in ("0", "false", "no", ""):
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "bamboozled.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


_setup_logging()
logger = logging.getLogger(__name__)
_TOKEN = os.getenv("DISCORD_TOKEN")

# Nothing the bot sends may ping @everyone or roles. Users are only pinged where a message names them on purpose.
SAFE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)


class BamboozledBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents, allowed_mentions=SAFE_MENTIONS)

    async def setup_hook(self):
        version = await migrate_async(db_path())
        logger.info("Database ready (schema version %d).", version)
        try:
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGTERM, lambda: asyncio.create_task(self.close())
            )
        except (NotImplementedError, RuntimeError):
            pass  # not supported on this platform; Ctrl+C still closes cleanly
        await self.load_extension("cogs.game")
        await self.load_extension("fastest_fingers")
        await self.load_extension("survival")
        await self.load_extension("quiz_stats")
        register_activity_command(self.tree)
        # Sync slash commands globally.
        # For faster dev iteration, replace with: await self.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))
        try:
            synced = await self.tree.sync()
            logger.info("Synced %d slash command(s).", len(synced))
        except discord.HTTPException as e:
            if e.code != 50240:
                raise
            # Discord has an Activity Entry Point command that must be included
            # in any bulk sync (error 50240). Fetch it and re-send manually.
            existing_raw = await self.http.get_global_commands(self.application_id)
            entry_points = [c for c in existing_raw if c.get("type") == 4]
            commands = self.tree.get_commands(guild=None)
            payload = [c.to_dict(self.tree) for c in commands] + entry_points
            result = await self.http.bulk_upsert_global_commands(self.application_id, payload=payload)
            logger.info(
                "Synced %d slash command(s) (Activity Entry Point preserved).",
                len(result) - len(entry_points),
            )

    async def on_ready(self):
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)

        # Announce orphaned games from before the last restart
        orphaned = await get_orphaned_channels()
        for cid_str in orphaned:
            cid = int(cid_str)
            channel = self.get_channel(cid)
            if channel:
                try:
                    await channel.send(
                        "⚠️ **The bot restarted mid-game.** "
                        "The previous Bamboozled game has been cancelled. "
                        "Use `/bamboozled join` to start a new one!"
                    )
                except discord.HTTPException:
                    logger.warning("Could not send restart notice to channel %s", cid)

        logger.info("Bamboozled bot is ready!")


def main():
    if not _TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN not set. Create a .env file with DISCORD_TOKEN=your_token_here"
        )
    bot = BamboozledBot()
    bot.run(_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
