"""
survival.py
Survival Mode — single-player, streak-based trivia until one wrong answer.

Rules:
- Single player only — starts immediately, no lobby
- Questions served one at a time with a 15-second timer each
- One wrong answer or timeout = game over; Give Up at any time
- No question cap — runs until death
- Score = streak (number of correct answers before dying)
- Boli formula: min(streak * multiplier, 200)
  multipliers: easy=2, medium=4, hard=7
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from game_engine.constants import NAVI_DB_PATH, SAFE_OPENTDB_CATEGORY_IDS
from game_engine.trivia import fetch_question, shuffle_answers
from session_registry import (
    add_player,
    end_session,
    is_player_active,
    register_session,
    remove_player,
)

logger = logging.getLogger("navi.survival")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SURVIVAL_TIMEOUT = 15          # seconds per question
_TIMER_UPDATE_INTERVAL = 5      # edit embed every N seconds to show countdown

_DIFFICULTY_MULTIPLIER: dict[str, int] = {
    "easy": 2,
    "medium": 4,
    "hard": 7,
}
_MAX_BOLI = 200

_ANSWER_LABELS = ["A", "B", "C", "D"]

# ---------------------------------------------------------------------------
# Category choices (Fix 1) — ordered list matching game_config_view.py
# ---------------------------------------------------------------------------

_CATEGORY_CHOICES = [
    app_commands.Choice(name="General Knowledge",       value="9"),
    app_commands.Choice(name="Science & Nature",        value="17"),
    app_commands.Choice(name="Computers",               value="18"),
    app_commands.Choice(name="Mathematics",             value="19"),
    app_commands.Choice(name="History",                 value="23"),
    app_commands.Choice(name="Geography",               value="22"),
    app_commands.Choice(name="Art",                     value="25"),
    app_commands.Choice(name="Animals",                 value="27"),
    app_commands.Choice(name="Sports",                  value="21"),
    app_commands.Choice(name="Mythology",               value="20"),
    app_commands.Choice(name="Vehicles",                value="28"),
    app_commands.Choice(name="Comics",                  value="29"),
    app_commands.Choice(name="Gadgets",                 value="30"),
    app_commands.Choice(name="Anime & Manga",           value="31"),
    app_commands.Choice(name="Cartoons & Animations",   value="32"),
]

# id → display name (for embed labels)
_CAT_ID_TO_NAME: dict[int, str] = {
    int(c.value): c.name for c in _CATEGORY_CHOICES
}


# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------


@dataclass
class SurvivalSession:
    session_id: str
    player_id: int
    username: str
    channel_id: int
    guild_id: int
    difficulty: str
    category_id: int | None   # numeric ID for fetch_question
    category_name: str | None  # display name
    streak: int = 0
    started_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# UI: Answer View (per question) — includes Give Up button (Fix 3a)
# ---------------------------------------------------------------------------


class SurvivalAnswerView(discord.ui.View):
    # Sentinel value set on selected_answer when player gives up
    GIVE_UP_SENTINEL = -999

    def __init__(self, player_id: int, answers: list[str], session: SurvivalSession):
        super().__init__(timeout=float(_SURVIVAL_TIMEOUT))
        self.player_id = player_id
        self.answers = answers
        self.selected_answer: Optional[int] = None
        self._answered = asyncio.Event()

        for i, (label, answer) in enumerate(zip(_ANSWER_LABELS, answers)):
            btn = discord.ui.Button(
                label=f"{label}: {answer[:75]}",
                style=discord.ButtonStyle.primary,
                custom_id=f"surv_ans_{session.session_id}_{i}",
            )
            btn.callback = self._make_cb(i)
            self.add_item(btn)

        # Give Up button (Fix 3a)
        give_up_btn = discord.ui.Button(
            label="🏳️ Give Up",
            style=discord.ButtonStyle.danger,
            custom_id=f"surv_giveup_{session.session_id}",
        )
        give_up_btn.callback = self._give_up_cb
        self.add_item(give_up_btn)

    def _make_cb(self, idx: int):
        async def cb(interaction: discord.Interaction) -> None:
            if interaction.user.id != self.player_id:
                await interaction.response.send_message(
                    "⚠️ This is not your game!", ephemeral=True
                )
                return
            if self.selected_answer is not None:
                await interaction.response.send_message(
                    "✅ Already locked in!", ephemeral=True
                )
                return
            self.selected_answer = idx
            # Disable all buttons immediately
            for item in self.children:
                item.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            except discord.HTTPException:
                await interaction.response.defer()
            self._answered.set()
            self.stop()

        return cb

    async def _give_up_cb(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "⚠️ This is not your game!", ephemeral=True
            )
            return
        if self.selected_answer is not None:
            await interaction.response.send_message(
                "✅ Already answered!", ephemeral=True
            )
            return
        self.selected_answer = self.GIVE_UP_SENTINEL
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            await interaction.response.defer()
        self._answered.set()
        self.stop()

    async def on_timeout(self) -> None:
        self._answered.set()
        self.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_question_embed(question: dict, answers: list[str], streak: int, timer_left: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"💀 Survival — Streak: {streak}",
        description=f"**{question['question']}**",
        color=discord.Color.from_rgb(220, 50, 50),
    )
    embed.add_field(
        name="Category",
        value=f"{question.get('category', 'Unknown')} · {question.get('difficulty', '?').title()}",
        inline=True,
    )
    embed.add_field(name="⏱️ Time Left", value=f"{timer_left}s", inline=True)
    answer_text = "\n".join(f"**{lbl}:** {ans}" for lbl, ans in zip(_ANSWER_LABELS, answers))
    embed.add_field(name="Choices", value=answer_text, inline=False)
    return embed


def _correct_embed(streak: int) -> discord.Embed:
    return discord.Embed(
        title="✅ Correct!",
        description=f"🔥 Streak: **{streak}**",
        color=discord.Color.green(),
    )


async def _build_death_embed(
    session: SurvivalSession,
    reason: str,
    boli: int,
    personal_best: int,
    is_new_pb: bool,
) -> discord.Embed:
    reason_text = {
        "wrong": "❌ Wrong answer",
        "timeout": "⏱️ Time ran out",
        "quit": "🏳️ Gave up",
        "error": "⚠️ Fetch error",
    }.get(reason, reason)

    title = "💀 GAME OVER"
    if is_new_pb:
        title += " — 🏆 New Personal Best!"

    embed = discord.Embed(
        title=title,
        color=discord.Color.from_rgb(40, 40, 40),
    )
    embed.add_field(name="Cause of Death", value=reason_text, inline=True)
    embed.add_field(name="🔥 Final Streak", value=str(session.streak), inline=True)
    embed.add_field(name="📊 Difficulty", value=session.difficulty.title(), inline=True)
    if session.category_name:
        embed.add_field(name="📚 Category", value=session.category_name, inline=True)
    embed.add_field(name="🍮 Boli Earned", value=f"+{boli}", inline=True)
    if not is_new_pb and personal_best > 0:
        embed.add_field(name="🏆 Your Best", value=str(personal_best), inline=True)
    elif is_new_pb:
        embed.add_field(name="🏆 Previous Best", value=str(personal_best) if personal_best > 0 else "—", inline=True)
    embed.set_footer(text=f"Game ID: {session.session_id[:8]}")
    return embed


async def _award_boli(user_id: int, username: str, amount: int, game_id: str) -> bool:
    """Award Boli to a user via the Navi DB external_boli_points table."""
    if not NAVI_DB_PATH:
        logger.warning("Survival Boli bridge: NAVI_DB_PATH not configured — skipping.")
        return False
    if not Path(NAVI_DB_PATH).exists():
        logger.warning("Survival Boli bridge: DB not found at %s.", NAVI_DB_PATH)
        return False
    try:
        async with aiosqlite.connect(NAVI_DB_PATH) as db:
            await db.execute(
                "INSERT INTO external_boli_points "
                "    (user_id, username, points, source_game, game_id) "
                "VALUES (?, ?, ?, 'survival', ?)",
                (user_id, username, amount, game_id),
            )
            await db.commit()
        logger.info("Survival Boli: +%d to user %d (%s)", amount, user_id, username)
        return True
    except Exception as exc:
        logger.warning("Survival Boli bridge failed: %s", exc)
        return False


async def _save_result_to_navi_db(session: SurvivalSession, boli: int) -> int:
    """Save result and return personal best streak (prior to this game, for comparison)."""
    if not NAVI_DB_PATH or not Path(NAVI_DB_PATH).exists():
        return 0
    cat_name = session.category_name
    try:
        async with aiosqlite.connect(NAVI_DB_PATH) as db:
            # Fetch previous best
            if cat_name:
                cursor = await db.execute(
                    "SELECT MAX(streak) FROM survival_scores "
                    "WHERE user_id = ? AND difficulty = ? AND category = ?",
                    (session.player_id, session.difficulty, cat_name),
                )
            else:
                cursor = await db.execute(
                    "SELECT MAX(streak) FROM survival_scores "
                    "WHERE user_id = ? AND difficulty = ? AND category IS NULL",
                    (session.player_id, session.difficulty),
                )
            row = await cursor.fetchone()
            prev_best = int(row[0]) if row and row[0] is not None else 0

            # Save this result
            game_id = f"surv_{session.session_id}"
            await db.execute(
                """
                INSERT OR IGNORE INTO survival_scores
                    (game_id, user_id, guild_id, username, streak, difficulty, category, boli_awarded)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (game_id, session.player_id, session.guild_id, session.username,
                 session.streak, session.difficulty, cat_name, boli),
            )
            await db.commit()
        return prev_best
    except Exception as exc:
        logger.warning("Survival: failed to save result: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class SurvivalCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        logger.info("SurvivalCog loaded.")

    async def cog_unload(self) -> None:
        logger.info("SurvivalCog unloaded.")

    # ── /survival ─────────────────────────────────────────────

    @app_commands.command(
        name="survival",
        description="Start a solo Survival trivia game — one wrong answer and it's over!"
    )
    @app_commands.describe(
        difficulty="Question difficulty (default: medium)",
        category="Trivia category (optional — leave blank for all)",
    )
    @app_commands.choices(
        difficulty=[
            app_commands.Choice(name="Easy",   value="easy"),
            app_commands.Choice(name="Medium", value="medium"),
            app_commands.Choice(name="Hard",   value="hard"),
        ],
        category=_CATEGORY_CHOICES,   # Fix 1: dropdown choices
    )
    async def survival(
        self,
        interaction: discord.Interaction,
        difficulty: str = "medium",
        category: Optional[str] = None,  # value is the stringified category ID, or None
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "⚠️ This command can only be used in a server.", ephemeral=True
            )
            return

        # Check if already in a game
        existing = is_player_active(interaction.user.id)
        if existing:
            await interaction.response.send_message(
                "⚠️ You're already in an active game session! Finish that one first.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        # Resolve category from choice value (Fix 1)
        cat_id: Optional[int] = None
        cat_name: Optional[str] = None
        if category:
            cat_id = int(category)
            cat_name = _CAT_ID_TO_NAME.get(cat_id, f"Category {cat_id}")

        # Create private thread
        timestamp = datetime.utcnow().strftime("%b %d %H:%M")
        username = interaction.user.display_name
        try:
            announce_msg = await interaction.channel.send(
                f"💀 **{username}** is entering **Survival Mode!** Wish them luck…"
            )
            thread = await announce_msg.create_thread(
                name=f"💀 Survival — {username} — {timestamp}",
                auto_archive_duration=60,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ I don't have permission to create threads in this channel.", ephemeral=True
            )
            return
        except discord.HTTPException as exc:
            logger.error("Survival: failed to create thread: %s", exc)
            await interaction.followup.send(
                "⚠️ Something went wrong creating the game thread. Try again.", ephemeral=True
            )
            return

        session_id = str(uuid.uuid4())
        session = SurvivalSession(
            session_id=session_id,
            player_id=interaction.user.id,
            username=username,
            channel_id=thread.id,
            guild_id=interaction.guild.id,
            difficulty=difficulty,
            category_id=cat_id,
            category_name=cat_name,
        )

        if not register_session(thread.id, "survival", interaction.user.id):
            await interaction.followup.send("⚠️ Could not register session.", ephemeral=True)
            return
        add_player(thread.id, interaction.user.id)

        await interaction.followup.send(
            f"💀 Survival Mode started! Head to {thread.mention}", ephemeral=True
        )

        # Run game in finally block to ensure cleanup
        try:
            await self._run_survival(thread, session, interaction.user, difficulty, cat_id, cat_name)
        finally:
            end_session(thread.id)

    # ── Game loop ─────────────────────────────────────────────

    async def _run_survival(
        self,
        thread: discord.Thread,
        session: SurvivalSession,
        player: discord.Member,
        difficulty: str,
        cat_id: Optional[int],
        cat_name: Optional[str],
    ) -> None:
        await thread.send(
            f"💀 **SURVIVAL MODE**\n"
            f"Player: **{session.username}** · Difficulty: **{difficulty.title()}**"
            + (f" · Category: **{cat_name}**" if cat_name else "")
            + f"\n\n*Answer correctly to survive. One mistake and it's OVER.*\n"
            f"⏱️ {_SURVIVAL_TIMEOUT}s per question. Click **🏳️ Give Up** to quit anytime."
        )
        await asyncio.sleep(2)

        session_token: Optional[str] = None
        death_reason = "unknown"

        while True:
            # Fetch next question
            try:
                question, session_token = await fetch_question(
                    session_token=session_token,
                    difficulty=difficulty,
                    category=cat_id,
                )
            except Exception as exc:
                logger.warning("Survival: fetch_question error: %s", exc)
                question = None

            if question is None:
                await thread.send(
                    "⚠️ Couldn't fetch a question — network issue. Ending game."
                )
                death_reason = "error"
                break

            answers, correct_idx = shuffle_answers(question)
            answer_view = SurvivalAnswerView(player.id, answers, session)
            embed = _build_question_embed(question, answers, session.streak, _SURVIVAL_TIMEOUT)
            q_msg = await thread.send(embed=embed, view=answer_view)

            # Launch a background task to update the timer every 5s
            timer_task = asyncio.create_task(
                self._update_timer(q_msg, question, answers, session, _SURVIVAL_TIMEOUT)
            )

            try:
                await asyncio.wait_for(
                    answer_view._answered.wait(), timeout=float(_SURVIVAL_TIMEOUT)
                )
            except asyncio.TimeoutError:
                timer_task.cancel()
                answer_view.stop()
                # Disable buttons on timeout
                for item in answer_view.children:
                    item.disabled = True
                try:
                    await q_msg.edit(view=answer_view)
                except discord.HTTPException:
                    pass
                death_reason = "timeout"
                break

            # Player answered or gave up
            timer_task.cancel()

            # ── Give Up (Fix 3a) ──────────────────────────────
            if answer_view.selected_answer == SurvivalAnswerView.GIVE_UP_SENTINEL:
                await thread.send(f"🏳️ **{session.username}** gave up. Respect.")
                death_reason = "quit"
                break

            if answer_view.selected_answer == correct_idx:
                session.streak += 1
                correct_embed = _correct_embed(session.streak)
                await thread.send(embed=correct_embed, delete_after=2)
                await asyncio.sleep(2)
            else:
                # Wrong answer — reveal correct
                correct_text = answers[correct_idx]
                for item in answer_view.children:
                    if isinstance(item, discord.ui.Button):
                        idx_str = item.custom_id.rsplit("_", 1)[-1]
                        try:
                            b_idx = int(idx_str)
                        except ValueError:
                            continue
                        item.disabled = True
                        if b_idx == correct_idx:
                            item.style = discord.ButtonStyle.success
                        elif (answer_view.selected_answer is not None
                              and b_idx == answer_view.selected_answer
                              and b_idx != correct_idx):
                            item.style = discord.ButtonStyle.danger
                try:
                    await q_msg.edit(view=answer_view)
                except discord.HTTPException:
                    pass
                await thread.send(
                    f"❌ Wrong! The correct answer was **{correct_text}**."
                )
                death_reason = "wrong"
                break

        # Compute Boli — 0 if player gave up voluntarily
        multiplier = _DIFFICULTY_MULTIPLIER.get(difficulty, 4)
        boli = 0 if death_reason == "quit" else min(session.streak * multiplier, _MAX_BOLI)

        # Save result and get personal best
        prev_best = await _save_result_to_navi_db(session, boli)
        is_new_pb = session.streak > prev_best and session.streak > 0 and death_reason != "quit"

        # Build and send death embed
        death_embed = await _build_death_embed(session, death_reason, boli, prev_best, is_new_pb)
        await thread.send(embed=death_embed)

        if boli > 0:
            game_id = f"surv_{session.session_id}"
            await _award_boli(session.player_id, session.username, boli, game_id)
            await thread.send(f"🍮 **+{boli} Boli** awarded to **{session.username}**!")

        # Fix 2: Lock thread immediately (read-only) after game ends
        await asyncio.sleep(3)
        try:
            await thread.edit(archived=True, locked=True)
        except discord.Forbidden:
            logger.warning("Survival: no permission to archive thread %d.", thread.id)
        except discord.HTTPException as exc:
            logger.warning("Survival: failed to archive thread: %s", exc)

    async def _update_timer(
        self,
        msg: discord.Message,
        question: dict,
        answers: list[str],
        session: SurvivalSession,
        total: int,
    ) -> None:
        """Edit the question embed every _TIMER_UPDATE_INTERVAL seconds to show countdown."""
        try:
            elapsed = 0
            while elapsed < total:
                await asyncio.sleep(_TIMER_UPDATE_INTERVAL)
                elapsed += _TIMER_UPDATE_INTERVAL
                remaining = max(0, total - elapsed)
                updated_embed = _build_question_embed(question, answers, session.streak, remaining)
                try:
                    await msg.edit(embed=updated_embed)
                except discord.HTTPException:
                    return  # message may have been updated already
        except asyncio.CancelledError:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SurvivalCog(bot))
