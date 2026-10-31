"""/bamboozled-admin: owner (or the configured panel role) only."""

import io
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from ...db.connection import db_path
from ...settings import BY_KEY, SETTINGS, SettingError
from ..guards import ctx_of, is_admin
from ..views.panel import PanelView, show
from ..views.rooms import RoomsView, rooms_embed


class AdminGroup(app_commands.Group):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await is_admin(interaction):
            return True
        await interaction.response.send_message(
            "Only the bot's owner, or members with the admin role, can use this.", ephemeral=True
        )
        return False


async def key_autocomplete(_interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    needle = current.lower()
    return [
        app_commands.Choice(name=f"{s.key} ({s.label})"[:100], value=s.key)
        for s in SETTINGS
        if needle in s.key.lower() or needle in s.label.lower()
    ][:25]


def status_embed(ctx) -> discord.Embed:
    embed = discord.Embed(title="📟 Bamboozled status", color=discord.Color.green())
    up = ctx.uptime_s()
    embed.add_field(name="Uptime", value=f"{up // 3600}h {up % 3600 // 60}m")
    if ctx.manager is not None:
        snap = ctx.manager.snapshot()
        embed.add_field(name="Rooms / sockets now", value=f"{snap['rooms']} / {snap['sockets']}")
        embed.add_field(name="Active games", value=", ".join(f"{m}: {n}" for m, n in snap["by_mode"].items()))
    else:
        embed.add_field(name="Game server", value="not running in this process")
    health = getattr(ctx.authenticator, "health", {}) if ctx.authenticator else {}

    def line(name: str) -> str:
        if name not in health:
            return "no calls yet"
        when, result = health[name]
        return f"{result} (<t:{int(when)}:R>)"

    embed.add_field(name="Discord instance lookup", value=line("instance"), inline=False)
    embed.add_field(name="Discord token check", value=line("token"), inline=False)
    tv = ctx.trivia
    if tv is None:
        trivia = f"offline questions only (sources setting: {ctx.settings.get('trivia.sources')})"
        rejected = "0"
    else:
        trivia = "\n".join(f"{n}: {tv.health[n][1]} (<t:{int(tv.health[n][0])}:R>)" for n in tv.health) or "no calls yet"
        trivia += "\nserved: " + (", ".join(f"{k} {v}" for k, v in sorted(tv.served.items())) or "none yet")
        rejected = ", ".join(f"{k} {v}" for k, v in sorted(tv.rejections.by_source().items())) or "0"
    embed.add_field(name="Trivia sources", value=trivia, inline=False)
    embed.add_field(name="Safety rejections (since start)", value=rejected, inline=True)
    try:
        size = os.path.getsize(db_path())
        embed.add_field(name="Database size", value=f"{size / 1024:,.0f} KB", inline=True)
    except OSError:
        embed.add_field(name="Database size", value="unknown", inline=True)
    embed.add_field(name="Last backup / replication", value="not configured", inline=True)
    flags = [k for k in ("system.killswitch",) if ctx.settings.get(k)]
    if flags:
        embed.add_field(name="⚠️ Switched on", value=", ".join(flags), inline=False)
    return embed


class ImportModal(discord.ui.Modal, title="Import settings"):
    text = discord.ui.TextInput(label="Exported settings (JSON)", style=discord.TextStyle.paragraph, max_length=4000)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            keys = await self.ctx.import_settings(self.text.value, interaction.user.id)
        except SettingError as exc:
            await interaction.response.send_message(f"⚠️ {exc} Nothing was changed.", ephemeral=True)
            return
        await interaction.response.send_message(f"Imported {len(keys)} setting(s).", ephemeral=True)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    admin = AdminGroup(
        name="bamboozled-admin",
        description="Administer Bamboozled",
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    @admin.command(name="panel", description="Open the settings panel")
    async def panel(self, interaction: discord.Interaction) -> None:
        view = PanelView(self.bot.ctx, interaction.user.id)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

    @admin.command(name="set", description="Change a setting")
    @app_commands.describe(key="Which setting", value="The new value (on/off, a number, a choice, ids)")
    @app_commands.autocomplete(key=key_autocomplete)
    async def set_(self, interaction: discord.Interaction, key: str, value: str) -> None:
        ctx = ctx_of(interaction)
        try:
            new = await ctx.apply_setting(key, value, interaction.user.id)
        except KeyError:
            await interaction.response.send_message(
                f"There is no setting called `{key}`. Start typing to see the list.", ephemeral=True
            )
            return
        except SettingError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(f"`{key}` is now `{show(BY_KEY[key], new)}`.", ephemeral=True)

    @admin.command(name="get", description="Show a setting")
    @app_commands.autocomplete(key=key_autocomplete)
    async def get(self, interaction: discord.Interaction, key: str) -> None:
        ctx = ctx_of(interaction)
        if key not in BY_KEY:
            await interaction.response.send_message(f"There is no setting called `{key}`.", ephemeral=True)
            return
        spec = BY_KEY[key]
        mark = "" if ctx.settings.is_default(key) else f" (default: `{show(spec, spec.default)}`)"
        await interaction.response.send_message(
            f"**{spec.label}** `{key}` = `{show(spec, ctx.settings.get(key))}`{mark}\n{spec.help}", ephemeral=True
        )

    @admin.command(name="reset", description="Put a setting back to its default")
    @app_commands.autocomplete(key=key_autocomplete)
    async def reset(self, interaction: discord.Interaction, key: str) -> None:
        if key not in BY_KEY:
            await interaction.response.send_message(f"There is no setting called `{key}`.", ephemeral=True)
            return
        value = await ctx_of(interaction).reset_setting(key, interaction.user.id)
        await interaction.response.send_message(f"`{key}` is back to its default, `{show(BY_KEY[key], value)}`.", ephemeral=True)

    @admin.command(name="status", description="Uptime, rooms, Discord health, database size")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=status_embed(ctx_of(interaction)), ephemeral=True)

    @admin.command(name="rooms", description="List live rooms; close one or message its players")
    async def rooms(self, interaction: discord.Interaction) -> None:
        ctx = ctx_of(interaction)
        view = RoomsView(ctx, interaction.user.id)
        await interaction.response.send_message(embed=rooms_embed(ctx), view=view, ephemeral=True)

    @admin.command(name="export", description="Download the settings as JSON")
    async def export(self, interaction: discord.Interaction) -> None:
        data = ctx_of(interaction).settings.export_json().encode()
        await interaction.response.send_message(
            "Settings that differ from the defaults:",
            file=discord.File(io.BytesIO(data), filename="bamboozled-settings.json"),
            ephemeral=True,
        )

    @admin.command(name="import", description="Paste exported settings to apply them")
    async def import_(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ImportModal(ctx_of(interaction)))

    @admin.command(name="testing", description="Turn testing mode on or off for this server (nothing is recorded or posted)")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def testing(self, interaction: discord.Interaction, state: str) -> None:
        ctx = ctx_of(interaction)
        guilds = list(ctx.settings.get("system.testing_guilds"))
        gid: Optional[int] = interaction.guild_id
        if gid is None:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return
        if state == "on" and gid not in guilds:
            guilds.append(gid)
        elif state == "off" and gid in guilds:
            guilds.remove(gid)
        await ctx.apply_setting("system.testing_guilds", guilds, interaction.user.id)
        await interaction.response.send_message(
            "🧪 Testing mode is **on** for this server: games are not recorded and no result card is posted."
            if state == "on"
            else "Testing mode is **off** for this server: games record normally.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
