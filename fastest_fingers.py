"""
fastest_fingers.py
Fastest Fingers First (FFF) — multiplayer, reaction-speed trivia cog.

Rules:
- 2–8 players join a lobby (60-second join window)
- Questions fetched upfront from Open Trivia DB
- Per question: 10-second timer, A/B/C/D buttons, one answer per player
- Scoring: first correct = 100pts, subsequent correct = 75pts, wrong/no answer = 0
- Boli: 1st = 50, 2nd = 30, 3rd = 15, any finisher = 5
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

logger = logging.getLogger("navi.fastest_fingers")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FFF_QUESTION_TIMEOUT = 10      # seconds per question
_FFF_LOBBY_TIMEOUT = 60         # seconds lobby stays open
_FFF_REVEAL_PAUSE = 3           # seconds between question reveal and next question
_FFF_ARCHIVE_DELAY = 120        # seconds before archiving the thread after game ends

_BOLI_PLACEMENT = {1: 50, 2: 30, 3: 15}
_BOLI_PARTICIPATION = 5          # for all non-placed finishers

_FIRST_CORRECT_PTS = 100
_SUBSEQUENT_CORRECT_PTS = 75

_MEDALS = ["🥇", "🥈", "🥉"]
_ANSWER_LABELS = ["A", "B", "C", "D"]

# ---------------------------------------------------------------------------
# Open Trivia DB category map (id → name) — subset that is SFW
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, int] = {
    "general": 9,
    "science & nature": 17,
    "computers": 18,
    "mathematics": 19,
    "mythology": 20,
    "geography": 22,
    "history": 23,
    "art": 25,
    "animals": 27,
    "vehicles": 28,
    "comics": 29,
    "gadgets": 30,
    "anime & manga": 31,
    "cartoon & animations": 32,
}

# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------


@dataclass
class FFFSession:
    session_id: str
    host_id: int
    channel_id: int
    guild_id: int
    players: dict[int, str] = field(default_factory=dict)        # user_id → username
    scores: dict[int, int] = field(default_factory=dict)         # user_id → score
    questions: list[dict] = field(default_factory=list)          # pre-fetched questions
    current_q_index: int = 0
    answers_this_round: dict[int, tuple[int, int]] = field(default_factory=dict)
    # user_id → (answer_index, timestamp_ms)
    first_correct_claimed: bool = False
    response_times: dict[int, list[int]] = field(default_factory=dict)
    # user_id → list of ms taken to answer correctly
    started_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# UI: Lobby buttons
# ---------------------------------------------------------------------------


class LobbyView(discord.ui.View):
    def __init__(self, session: FFFSession, cog: "FastestFingersCog"):
        super().__init__(timeout=float(_FFF_LOBBY_TIMEOUT))
        self.session = session
        self.cog = cog
        self._start_btn_ref: Optional[discord.ui.Button] = None

    def _build(self) -> None:
        """Rebuild buttons; call after mutating session.players."""
        self.clear_items()

        join_btn = discord.ui.Button(
            label="🟢 Join",
            style=discord.ButtonStyle.success,
            custom_id=f"fff_join_{self.session.session_id}",
        )
        join_btn.callback = self._join_cb
        self.add_item(join_btn)

        can_start = len(self.session.players) >= 2
        start_btn = discord.ui.Button(
            label="⚡ Start",
            style=discord.ButtonStyle.primary,
            disabled=not can_start,
            custom_id=f"fff_start_{self.session.session_id}",
        )
        start_btn.callback = self._start_cb
        self._start_btn_ref = start_btn
        self.add_item(start_btn)

    async def _join_cb(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        if uid in self.session.players:
            await interaction.response.send_message("⚠️ You're already in this game!", ephemeral=True)
            return
        if len(self.session.players) >= 8:
            await interaction.response.send_message("⚠️ This lobby is full (8 players max)!", ephemeral=True)
            return
        existing = is_player_active(uid)
        if existing:
            await interaction.response.send_message(
                "⚠️ You're already in another active game session!", ephemeral=True
            )
            return

        self.session.players[uid] = interaction.user.display_name
        self.session.scores[uid] = 0
        add_player(self.session.channel_id, uid)
        self._build()

        embed = _build_lobby_embed(self.session)
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.HTTPException:
            await interaction.response.send_message(
                f"🎮 **{interaction.user.display_name}** joined the lobby!", ephemeral=True
            )

    async def _start_cb(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.host_id:
            await interaction.response.send_message(
                "⚠️ Only the host can start the game!", ephemeral=True
            )
            return
        if len(self.session.players) < 2:
            await interaction.response.send_message(
                "⚠️ Need at least 2 players to start!", ephemeral=True
            )
            return
        self.stop()
        await interaction.response.defer()
        # Signal the lobby waiter
        self.cog._lobby_ready[self.session.session_id] = True

    async def on_timeout(self) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# UI: Answer buttons (per-question)
# ---------------------------------------------------------------------------


class AnswerView(discord.ui.View):
    """Shared answer view for a single FFF question.

    All registered players can click. Each player gets exactly one answer recorded.
    Clicking gives an ephemeral "Locked in!" response — the public embed is NOT
    updated until the 10s timer expires or all players have answered.
    """

    def __init__(self, session: FFFSession, answers: list[str]):
        super().__init__(timeout=float(_FFF_QUESTION_TIMEOUT))
        self.session = session
        self.answers = answers
        self._all_answered = asyncio.Event()

        for i, (label, answer) in enumerate(zip(_ANSWER_LABELS, answers)):
            btn = discord.ui.Button(
                label=f"{label}: {answer[:75]}",
                style=discord.ButtonStyle.primary,
                custom_id=f"fff_ans_{session.session_id}_{i}",
            )
            btn.callback = self._make_cb(i)
            self.add_item(btn)

    def _make_cb(self, idx: int):
        async def cb(interaction: discord.Interaction) -> None:
            uid = interaction.user.id
            if uid not in self.session.players:
                await interaction.response.send_message(
                    "⚠️ You're not part of this game!", ephemeral=True
                )
                return
            if uid in self.session.answers_this_round:
                await interaction.response.send_message(
                    "✅ You've already locked in your answer!", ephemeral=True
                )
                return

            ts_ms = int(time.monotonic() * 1000)
            self.session.answers_this_round[uid] = (idx, ts_ms)

            await interaction.response.send_message("🔒 **Locked in!** Waiting for others…", ephemeral=True)

            if len(self.session.answers_this_round) >= len(self.session.players):
                self._all_answered.set()

        return cb

    async def on_timeout(self) -> None:
        self._all_answered.set()
        self.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_lobby_embed(session: FFFSession) -> discord.Embed:
    embed = discord.Embed(
        title="⚡ Fastest Fingers First — Lobby",
        description=(
            "Click **🟢 Join** to enter the game. "
            f"The host can **⚡ Start** once 2+ players have joined.\n\n"
            f"⏰ Lobby auto-starts in **{_FFF_LOBBY_TIMEOUT}s** if 2+ players have joined."
        ),
        color=discord.Color.from_rgb(255, 200, 0),
    )
    if session.players:
        roster = "\n".join(
            f"{'👑' if uid == session.host_id else '🎮'} {name}"
            for uid, name in session.players.items()
        )
        embed.add_field(name=f"Players ({len(session.players)}/8)", value=roster, inline=False)
    else:
        embed.add_field(name="Players", value="*No one yet — be the first!*", inline=False)
    return embed


def _build_question_embed(
    question: dict,
    answers: list[str],
    q_num: int,
    total: int,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"❓ Question {q_num}/{total}",
        description=f"**{question['question']}**",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Category",
        value=f"{question.get('category', 'Unknown')} · {question.get('difficulty', '?').title()}",
        inline=True,
    )
    embed.add_field(name="⏱️ Timer", value=f"{_FFF_QUESTION_TIMEOUT}s", inline=True)
    answer_text = "\n".join(f"**{lbl}:** {ans}" for lbl, ans in zip(_ANSWER_LABELS, answers))
    embed.add_field(name="Choices", value=answer_text, inline=False)
    return embed


def _build_reveal_embed(
    question: dict,
    answers: list[str],
    correct_idx: int,
    session: FFFSession,
    winners_this_round: list[int],
) -> discord.Embed:
    correct_text = answers[correct_idx]
    embed = discord.Embed(
        title="✅ Round Result",
        description=f"The correct answer was **{correct_text}**",
        color=discord.Color.green(),
    )
    if winners_this_round:
        winner_names = ", ".join(session.players[uid] for uid in winners_this_round if uid in session.players)
        embed.add_field(name="🎯 Got it right", value=winner_names, inline=False)
    else:
        embed.add_field(name="🎯 Got it right", value="*Nobody — tough question!*", inline=False)
    return embed


def _build_results_embed(session: FFFSession, total_q: int) -> discord.Embed:
    sorted_players = sorted(session.players, key=lambda uid: session.scores.get(uid, 0), reverse=True)
    embed = discord.Embed(
        title="⚡ Fastest Fingers First — Final Results",
        color=discord.Color.gold(),
    )
    for i, uid in enumerate(sorted_players):
        medal = _MEDALS[i] if i < 3 else f"#{i+1}"
        name = session.players[uid]
        score = session.scores.get(uid, 0)
        embed.add_field(
            name=f"{medal} {name}",
            value=f"**{score} pts**",
            inline=False,
        )
    embed.set_footer(text=f"Game ID: {session.session_id[:8]} · {total_q} questions")
    return embed


async def _award_boli(user_id: int, username: str, amount: int, game_id: str) -> bool:
    """Award Boli to a user via the Navi DB (external_boli_points table)."""
    if not NAVI_DB_PATH:
        logger.warning("FFF Boli bridge: NAVI_DB_PATH not configured — skipping.")
        return False
    if not Path(NAVI_DB_PATH).exists():
        logger.warning("FFF Boli bridge: DB not found at %s.", NAVI_DB_PATH)
        return False
    try:
        async with aiosqlite.connect(NAVI_DB_PATH) as db:
            await db.execute(
                "INSERT INTO external_boli_points "
                "    (user_id, username, points, source_game, game_id) "
                "VALUES (?, ?, ?, 'fff', ?)",
                (user_id, username, amount, game_id),
            )
            await db.commit()
        logger.info("FFF Boli: +%d to user %d (%s)", amount, user_id, username)
        return True
    except Exception as exc:
        logger.warning("FFF Boli bridge failed: %s", exc)
        return False


async def _save_result_to_navi_db(session: FFFSession, total_q: int) -> None:
    """Save FFF game results to the Navi DB (fff_scores table)."""
    if not NAVI_DB_PATH:
        return
    if not Path(NAVI_DB_PATH).exists():
        return

    sorted_players = sorted(session.players, key=lambda uid: session.scores.get(uid, 0), reverse=True)
    try:
        async with aiosqlite.connect(NAVI_DB_PATH) as db:
            for uid in sorted_players:
                correct = session.scores.get(uid, 0) // _SUBSEQUENT_CORRECT_PTS  # approximate
                times = session.response_times.get(uid, [])
                avg_ms = int(sum(times) / len(times)) if times else None
                game_id = f"fff_{session.session_id}_{uid}"
                boli = _BOLI_PLACEMENT.get(sorted_players.index(uid) + 1, _BOLI_PARTICIPATION)

                await db.execute(
                    """
                    INSERT OR IGNORE INTO fff_scores
                        (game_id, user_id, guild_id, username, correct_answers,
                         total_questions, avg_response_ms, boli_awarded)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (game_id, uid, session.guild_id, session.players[uid],
                     correct, total_q, avg_ms, boli),
                )
            await db.commit()
    except Exception as exc:
        logger.warning("FFF: failed to save results to Navi DB: %s", exc)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class FastestFingersCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # session_id → bool (True = host pressed Start early)
        self._lobby_ready: dict[str, bool] = {}

    async def cog_load(self) -> None:
        logger.info("FastestFingersCog loaded.")

    async def cog_unload(self) -> None:
        logger.info("FastestFingersCog unloaded.")

    # ── /fff ─────────────────────────────────────────────────

    @app_commands.command(name="fff", description="Start a Fastest Fingers First trivia game!")
    @app_commands.describe(
        questions="Number of questions (5–20, default 10)",
        category="Trivia category (optional)",
        difficulty="Question difficulty",
    )
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="Easy", value="easy"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="Hard", value="hard"),
    ])
    async def fff(
        self,
        interaction: discord.Interaction,
        questions: app_commands.Range[int, 5, 20] = 10,
        category: Optional[str] = None,
        difficulty: str = "medium",
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "⚠️ This command can only be used in a server.", ephemeral=True
            )
            return

        # Check if invoker is already in a game
        existing = is_player_active(interaction.user.id)
        if existing:
            await interaction.response.send_message(
                "⚠️ You're already in an active game session! Finish that one first.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        # Create thread
        timestamp = datetime.utcnow().strftime("%b %d %H:%M")
        try:
            announce_msg = await interaction.channel.send(
                f"⚡ **{interaction.user.display_name}** is starting **Fastest Fingers First!** "
                f"Join using the button below."
            )
            thread = await announce_msg.create_thread(
                name=f"⚡ Fastest Fingers — {timestamp}",
                auto_archive_duration=60,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ I don't have permission to create threads in this channel.", ephemeral=True
            )
            return
        except discord.HTTPException as exc:
            logger.error("FFF: failed to create thread: %s", exc)
            await interaction.followup.send(
                "⚠️ Something went wrong creating the game thread. Try again.", ephemeral=True
            )
            return

        # Resolve category
        cat_id: Optional[int] = None
        cat_name: Optional[str] = None
        if category:
            cat_lower = category.lower().strip()
            cat_id = _CATEGORY_MAP.get(cat_lower)
            if cat_id is None:
                # Try partial match
                for k, v in _CATEGORY_MAP.items():
                    if cat_lower in k:
                        cat_id = v
                        cat_name = k.title()
                        break
            else:
                cat_name = category.title()

        # Build session
        session_id = str(uuid.uuid4())
        session = FFFSession(
            session_id=session_id,
            host_id=interaction.user.id,
            channel_id=thread.id,
            guild_id=interaction.guild.id,
        )
        session.players[interaction.user.id] = interaction.user.display_name
        session.scores[interaction.user.id] = 0

        if not register_session(thread.id, "fff", interaction.user.id):
            await interaction.followup.send(
                "⚠️ A game is already running in this thread.", ephemeral=True
            )
            return

        add_player(thread.id, interaction.user.id)

        # Fetch questions upfront (before lobby closes to avoid mid-game latency)
        fetched_questions: list[dict] = []
        session_token: Optional[str] = None
        try:
            async with asyncio.timeout(30):
                for _ in range(questions):
                    q, session_token = await fetch_question(
                        session_token=session_token,
                        difficulty=difficulty,
                        category=cat_id,
                    )
                    if q:
                        fetched_questions.append(q)
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning("FFF: question fetch error: %s", exc)

        if len(fetched_questions) < 3:
            end_session(thread.id)
            await thread.send(
                "⚠️ **Game cancelled** — couldn't fetch enough questions from Open Trivia DB. "
                "Try again in a moment."
            )
            try:
                await thread.edit(archived=True, locked=True)
            except Exception:
                pass
            await interaction.followup.send("⚠️ Game cancelled — not enough questions available.", ephemeral=True)
            return

        session.questions = fetched_questions
        actual_q = len(fetched_questions)

        # Post lobby in thread
        lobby_view = LobbyView(session, self)
        lobby_view._build()
        lobby_embed = _build_lobby_embed(session)
        await thread.send(
            f"🎯 **{actual_q} questions** · Difficulty: **{difficulty.title()}**"
            + (f" · Category: **{cat_name or category}**" if cat_name or category else ""),
        )
        lobby_msg = await thread.send(embed=lobby_embed, view=lobby_view)
        await interaction.followup.send(
            f"⚡ Game lobby created! Head to {thread.mention} to join.", ephemeral=True
        )

        self._lobby_ready[session_id] = False

        # Wait for lobby: 60s timeout or host presses Start
        lobby_ended = False
        try:
            async with asyncio.timeout(_FFF_LOBBY_TIMEOUT):
                while True:
                    await asyncio.sleep(1)
                    if self._lobby_ready.get(session_id):
                        lobby_ended = True
                        break
        except asyncio.TimeoutError:
            lobby_ended = True  # auto-start if enough players

        lobby_view.stop()
        self._lobby_ready.pop(session_id, None)

        # Disable lobby buttons
        for item in lobby_view.children:
            item.disabled = True
        try:
            await lobby_msg.edit(view=lobby_view)
        except discord.HTTPException:
            pass

        # Check player count
        if len(session.players) < 2:
            end_session(thread.id)
            await thread.send(
                "⚠️ **Game cancelled** — not enough players joined (need at least 2).\n"
                "Use `/fff` to start a new lobby."
            )
            await asyncio.sleep(10)
            try:
                await thread.edit(archived=True, locked=True)
            except Exception:
                pass
            return

        # Run the game
        try:
            await self._run_game(thread, session, actual_q, difficulty, cat_name)
        finally:
            end_session(thread.id)

    # ── Game loop ─────────────────────────────────────────────

    async def _run_game(
        self,
        thread: discord.Thread,
        session: FFFSession,
        total_q: int,
        difficulty: str,
        cat_name: Optional[str],
    ) -> None:
        player_names = ", ".join(session.players.values())
        await thread.send(
            f"⚡ **FASTEST FINGERS FIRST BEGINS!**\n"
            f"Players: **{player_names}**\n"
            f"**{total_q} questions · {difficulty.title()}**"
            + (f" · Category: {cat_name}" if cat_name else "")
            + f"\n\n*First correct answer = {_FIRST_CORRECT_PTS} pts · subsequent correct = {_SUBSEQUENT_CORRECT_PTS} pts*"
        )
        await asyncio.sleep(3)

        # Track question start time per question for response time calculation
        q_start_ms = int(time.monotonic() * 1000)

        for q_index, question in enumerate(session.questions):
            session.current_q_index = q_index
            session.answers_this_round.clear()
            session.first_correct_claimed = False

            answers, correct_idx = shuffle_answers(question)
            q_start_ms = int(time.monotonic() * 1000)

            embed = _build_question_embed(question, answers, q_index + 1, total_q)
            answer_view = AnswerView(session, answers)
            q_msg = await thread.send(embed=embed, view=answer_view)

            # Wait for 10s or all players answered
            try:
                await asyncio.wait_for(answer_view._all_answered.wait(), timeout=float(_FFF_QUESTION_TIMEOUT))
            except asyncio.TimeoutError:
                pass

            answer_view.stop()
            # Disable buttons
            for item in answer_view.children:
                item.disabled = True
            try:
                await q_msg.edit(view=answer_view)
            except discord.HTTPException:
                pass

            # Score this round
            winners_this_round: list[int] = []
            for uid, (ans_idx, ts_ms) in sorted(
                session.answers_this_round.items(), key=lambda x: x[1][1]
            ):
                if ans_idx == correct_idx:
                    response_ms = ts_ms - q_start_ms
                    session.response_times.setdefault(uid, []).append(response_ms)
                    if not session.first_correct_claimed:
                        session.scores[uid] = session.scores.get(uid, 0) + _FIRST_CORRECT_PTS
                        session.first_correct_claimed = True
                    else:
                        session.scores[uid] = session.scores.get(uid, 0) + _SUBSEQUENT_CORRECT_PTS
                    winners_this_round.append(uid)

            reveal_embed = _build_reveal_embed(question, answers, correct_idx, session, winners_this_round)
            await thread.send(embed=reveal_embed)
            await asyncio.sleep(_FFF_REVEAL_PAUSE)

        # Game over — show results
        await asyncio.sleep(1)
        results_embed = _build_results_embed(session, total_q)
        await thread.send(embed=results_embed)

        # Award Boli
        sorted_players = sorted(session.players, key=lambda uid: session.scores.get(uid, 0), reverse=True)
        boli_embed = discord.Embed(
            title="🍮 Boli Points Awarded",
            color=discord.Color.gold(),
        )
        boli_tasks = []
        for i, uid in enumerate(sorted_players):
            placement = i + 1
            boli = _BOLI_PLACEMENT.get(placement, _BOLI_PARTICIPATION)
            name = session.players[uid]
            medal = _MEDALS[i] if i < 3 else f"#{placement}"
            boli_embed.add_field(
                name=f"{medal} {name}",
                value=f"+{boli} Boli",
                inline=False,
            )
            boli_tasks.append(_award_boli(uid, name, boli, f"fff_{session.session_id}_{uid}"))

        if boli_tasks:
            await asyncio.gather(*boli_tasks, return_exceptions=True)

        await thread.send(embed=boli_embed)

        # Persist results
        await _save_result_to_navi_db(session, total_q)

        # Archive after delay
        await asyncio.sleep(_FFF_ARCHIVE_DELAY)
        try:
            await thread.edit(archived=True, locked=True)
        except discord.Forbidden:
            logger.warning("FFF: no permission to archive thread %d.", thread.id)
        except discord.HTTPException as exc:
            logger.warning("FFF: failed to archive thread: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FastestFingersCog(bot))
