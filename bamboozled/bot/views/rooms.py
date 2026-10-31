"""Live rooms: list them, close one, or send its players a message."""

from __future__ import annotations

from typing import Optional

import discord

from ..guards import is_admin


def rooms_embed(ctx) -> discord.Embed:
    now = ctx.manager.clock_ms() if ctx.manager else 0
    rooms = ctx.manager.rooms_summary(now) if ctx.manager else []
    embed = discord.Embed(title="🎡 Live rooms", color=discord.Color.blurple())
    if ctx.manager is None:
        embed.description = "The game server is not running in this process."
    elif not rooms:
        embed.description = "No rooms right now."
    else:
        lines = []
        for r in rooms[:15]:
            watching = f" + {r['watching']} watching" if r["watching"] else ""
            lines.append(
                f"`{r['key'][:10]}…` {r['mode']} · {r['phase']} · {r['players']} playing{watching} · "
                f"{r['age_s'] // 60} min · server {r['guild_id']}"
            )
        embed.description = "\n".join(lines)
    return embed


class MessageModal(discord.ui.Modal, title="Message the players in this room"):
    text = discord.ui.TextInput(
        label="Message (shown to everyone in the room)", max_length=300, style=discord.TextStyle.paragraph
    )

    def __init__(self, ctx, key: str):
        super().__init__()
        self.ctx, self.key = ctx, key

    async def on_submit(self, interaction: discord.Interaction) -> None:
        sent = self.ctx.manager.admin_message(self.key, self.text.value)
        await interaction.response.send_message("Sent." if sent else "That room has already closed.", ephemeral=True)


class RoomsView(discord.ui.View):
    def __init__(self, ctx, user_id: int):
        super().__init__(timeout=300)
        self.ctx, self.user_id = ctx, user_id
        self.selected: Optional[str] = None
        self._build()

    def _build(self) -> None:
        self.clear_items()
        rooms = self.ctx.manager.rooms_summary(self.ctx.manager.clock_ms()) if self.ctx.manager else []
        if rooms:
            select = discord.ui.Select(
                placeholder="Choose a room…",
                row=0,
                options=[
                    discord.SelectOption(
                        label=f"{r['mode']} · {r['players']} playing · {r['key'][:40]}",
                        value=r["key"][:100],
                        default=r["key"] == self.selected,
                    )
                    for r in rooms[:25]
                ],
            )
            select.callback = self._pick
            self.add_item(select)
        close = discord.ui.Button(label="Close room", style=discord.ButtonStyle.danger, row=1, disabled=not self.selected)
        message = discord.ui.Button(label="Message…", style=discord.ButtonStyle.secondary, row=1, disabled=not self.selected)
        refresh = discord.ui.Button(label="Refresh", style=discord.ButtonStyle.secondary, row=1)
        close.callback, message.callback, refresh.callback = self._close, self._message, self._refresh
        for b in (close, message, refresh):
            self.add_item(b)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id or not await is_admin(interaction):
            await interaction.response.send_message("This belongs to someone else.", ephemeral=True)
            return False
        return True

    async def _redraw(self, interaction: discord.Interaction) -> None:
        self._build()
        await interaction.response.edit_message(embed=rooms_embed(self.ctx), view=self)

    async def _pick(self, interaction: discord.Interaction) -> None:
        self.selected = interaction.data["values"][0]
        await self._redraw(interaction)

    async def _close(self, interaction: discord.Interaction) -> None:
        self.ctx.manager.close_room(self.selected, "room_closed")
        self.selected = None
        await self._redraw(interaction)

    async def _message(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MessageModal(self.ctx, self.selected))

    async def _refresh(self, interaction: discord.Interaction) -> None:
        await self._redraw(interaction)
