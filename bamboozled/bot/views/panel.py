"""The interactive settings panel: pick a category, see each setting with its value and a marker when it differs from the
default, then toggle, edit in a modal, reset, or go back."""

from __future__ import annotations

from typing import Any, Optional

import discord

from ...settings import BY_KEY, CATEGORIES, SETTINGS, SettingError, Setting

CHANGED = "✱"


def show(spec: Setting, value: Any) -> str:
    if spec.kind == "bool":
        return "on" if value else "off"
    if spec.kind == "id_list":
        return ", ".join(str(v) for v in value) if value else "none"
    if spec.kind == "role":
        return f"<@&{value}>" if value else "none"
    return str(value)


def editable_text(spec: Setting, value: Any) -> str:
    if spec.kind == "id_list":
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def overview_embed(settings) -> discord.Embed:
    embed = discord.Embed(
        title="⚙️ Bamboozled settings",
        color=discord.Color.blurple(),
        description="Pick a category below. A setting changed from its default is marked " + CHANGED + ".",
    )
    for cat in CATEGORIES:
        specs = [s for s in SETTINGS if s.category == cat and not s.hidden]
        changed = sum(1 for s in specs if not settings.is_default(s.key))
        embed.add_field(
            name=cat, value=f"{len(specs)} setting(s)" + (f" · {CHANGED} {changed} changed" if changed else ""), inline=True
        )
    return embed


def category_embed(settings, category: str, selected: Optional[str]) -> discord.Embed:
    embed = discord.Embed(title=f"⚙️ {category}", color=discord.Color.blurple())
    lines = []
    for spec in (s for s in SETTINGS if s.category == category and not s.hidden):
        value = settings.get(spec.key)
        mark = f" {CHANGED} *(default: {show(spec, spec.default)})*" if not settings.is_default(spec.key) else ""
        pointer = "▶ " if spec.key == selected else ""
        lines.append(
            f"{pointer}**{spec.label}**: `{show(spec, value)}`{mark}\n　`{spec.key}`" + (f" · {spec.help}" if spec.help else "")
        )
    embed.description = "\n".join(lines) or "Nothing to show here."
    if selected:
        embed.set_footer(text="Use the buttons to change the selected setting.")
    return embed


class EditModal(discord.ui.Modal):
    def __init__(self, panel: "PanelView", spec: Setting):
        super().__init__(title=spec.label[:45])
        self.panel, self.spec = panel, spec
        hint = {
            "int": f"A whole number from {spec.min} to {spec.max}",
            "choice": "One of: " + ", ".join(spec.choices),
            "id_list": "Ids separated by commas (empty = none)",
            "role": "A role id, or 'none'",
            "bool": "on or off",
        }[spec.kind]
        self.value = discord.ui.TextInput(
            label=hint[:45],
            default=editable_text(spec, panel.ctx.settings.get(spec.key)) or None,
            required=spec.kind not in ("id_list", "role"),
            max_length=400,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.panel.ctx.apply_setting(self.spec.key, self.value.value, interaction.user.id)
        except SettingError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return
        await self.panel.refresh(interaction)


class PanelView(discord.ui.View):
    def __init__(self, ctx, user_id: int):
        super().__init__(timeout=300)
        self.ctx, self.user_id = ctx, user_id
        self.category: Optional[str] = None
        self.selected: Optional[str] = None
        self._build()

    # ───── building the controls for the current state ─────
    def _build(self) -> None:
        self.clear_items()
        cat_select = discord.ui.Select(
            placeholder="Choose a category…",
            row=0,
            options=[discord.SelectOption(label=c, value=c, default=c == self.category) for c in CATEGORIES],
        )
        cat_select.callback = self._on_category
        self.add_item(cat_select)
        if self.category is None:
            return
        specs = [s for s in SETTINGS if s.category == self.category and not s.hidden]
        pick = discord.ui.Select(
            placeholder="Choose a setting…",
            row=1,
            options=[
                discord.SelectOption(
                    label=s.label[:100],
                    value=s.key,
                    description=f"now: {show(s, self.ctx.settings.get(s.key))}"[:100],
                    default=s.key == self.selected,
                )
                for s in specs
            ],
        )
        pick.callback = self._on_setting
        self.add_item(pick)
        spec = BY_KEY.get(self.selected) if self.selected else None
        toggle = discord.ui.Button(
            label="Toggle", style=discord.ButtonStyle.primary, row=2, disabled=not (spec and spec.kind == "bool")
        )
        edit = discord.ui.Button(
            label="Edit…", style=discord.ButtonStyle.secondary, row=2, disabled=not (spec and spec.kind != "bool")
        )
        reset = discord.ui.Button(
            label="Reset",
            style=discord.ButtonStyle.secondary,
            row=2,
            disabled=not (spec and not self.ctx.settings.is_default(spec.key)),
        )
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=2)
        toggle.callback, edit.callback, reset.callback, back.callback = self._toggle, self._edit, self._reset, self._back
        for b in (toggle, edit, reset, back):
            self.add_item(b)

    def embed(self) -> discord.Embed:
        return (
            overview_embed(self.ctx.settings)
            if self.category is None
            else category_embed(self.ctx.settings, self.category, self.selected)
        )

    async def refresh(self, interaction: discord.Interaction) -> None:
        self._build()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This panel belongs to someone else. Run `/bamboozled-admin panel` for your own.", ephemeral=True
            )
            return False
        return True

    # ───── callbacks ─────
    async def _on_category(self, interaction: discord.Interaction) -> None:
        self.category, self.selected = interaction.data["values"][0], None
        await self.refresh(interaction)

    async def _on_setting(self, interaction: discord.Interaction) -> None:
        self.selected = interaction.data["values"][0]
        await self.refresh(interaction)

    async def _toggle(self, interaction: discord.Interaction) -> None:
        await self.ctx.apply_setting(self.selected, not self.ctx.settings.get(self.selected), interaction.user.id)
        await self.refresh(interaction)

    async def _edit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(EditModal(self, BY_KEY[self.selected]))

    async def _reset(self, interaction: discord.Interaction) -> None:
        await self.ctx.reset_setting(self.selected, interaction.user.id)
        await self.refresh(interaction)

    async def _back(self, interaction: discord.Interaction) -> None:
        self.category, self.selected = None, None
        await self.refresh(interaction)
