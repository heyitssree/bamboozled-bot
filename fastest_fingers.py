"""
fastest_fingers.py
Fastest Fingers First (FFF) — multiplayer, reaction-speed trivia cog.

Rules:
- 2–10 players join a persistent lobby (host presses Start; 10-min inactivity close)
- Questions fetched upfront from Open Trivia DB
- Per question: 10-second timer, A/B/C/D buttons, one answer per player
- Scoring: first correct = 100pts, subsequent correct = 75pts, wrong/no answer = 0
- AFK kick: 2 consecutive non-answers → removed from game
- Results (rank, points, correct answers, average response time) are recorded in the match tables
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bamboozled.bot.guards import refuse_if_opted_out
from bamboozled.services.names import safe_name
from bamboozled.db.repos.matches import ResultRow, ranked, record_match
from game_engine.trivia import fetch_question_any, shuffle_answers
from session_registry import (
    add_player,
    end_session,
    is_player_active,
    register_session,
    remove_player,
)

logger = logging.getLogger("bamboozled.fastest_fingers")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FFF_QUESTION_TIMEOUT = 10      # seconds per question
_FFF_LOBBY_INACTIVITY = 600     # 10 min → auto-disband if no start (Fix 3b)
_FFF_REVEAL_PAUSE = 3           # seconds between question reveal and next question
_FFF_MAX_PLAYERS = 10
_FFF_MIN_PLAYERS = 2
_FFF_AFK_KICK_THRESHOLD = 2    # consecutive non-answers before kick (Fix 4)

_FIRST_CORRECT_PTS = 100
_SUBSEQUENT_CORRECT_PTS = 75

_MEDALS = ["🥇", "🥈", "🥉"]
_ANSWER_LABELS = ["A", "B", "C", "D"]

# ---------------------------------------------------------------------------
# Category choices (Fix 1)
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
    # New: Trivia API categories
    app_commands.Choice(name="🎵 Music",                value="-1"),
    app_commands.Choice(name="🎬 Film & TV",            value="-2"),
    app_commands.Choice(name="🍕 Food & Drink",         value="-3"),
    app_commands.Choice(name="🌍 Society & Culture",    value="-4"),
]

_CAT_ID_TO_NAME: dict[int, str] = {int(c.value): c.name for c in _CATEGORY_CHOICES}

# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------


@dataclass
class FFFSession:
    session_id: str
    host_id: int
    channel_id: int       # thread ID once created
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
    afk_counts: dict[int, int] = field(default_factory=dict)     # Fix 4: AFK tracker
    correct: dict[int, int] = field(default_factory=dict)        # user_id → correct answers this game
    started_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: float = field(default_factory=time.time)      # Fix 3b: inactivity watch


# ---------------------------------------------------------------------------
# UI: Lobby view — Bamboozled-style persistent lobby (Fix 3b)
# ---------------------------------------------------------------------------


class FFFLobbyView(discord.ui.View):
    """Persistent lobby view. No timeout — host must Start or End Lobby.
    A background inactivity watcher auto-disbands after 10 min of no joins."""

    def __init__(self, session: FFFSession, cog: "FastestFingersCog"):
        super().__init__(timeout=None)   # Fix 3b: no auto-timeout
        self.session = session
        self.cog = cog

    # ── Lobby embed ──────────────────────────────────────────

    def lobby_embed(self) -> discord.Embed:
        session = self.session
        embed = discord.Embed(
            title="⚡ Fastest Fingers First — Lobby",
            color=discord.Color.from_rgb(255, 200, 0),
        )
        roster = "\n".join(
            f"{'👑' if uid == session.host_id else '🎮'} {name}"
            for uid, name in session.players.items()
        )
        embed.add_field(
            name=f"Players ({len(session.players)}/{_FFF_MAX_PLAYERS})",
            value=roster or "*No one yet — be the first!*",
            inline=False,
        )
        embed.set_footer(text="Host: press ⚡ Start when ready · Auto-closes after 10 min of inactivity")
        return embed

    # ── Buttons ───────────────────────────────────────────────

    @discord.ui.button(label="🟢 Join", style=discord.ButtonStyle.success, row=0)
    async def join_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        if await refuse_if_opted_out(interaction):                  # opted-out players cannot join (spec 10.3)
            return
        session = self.session
        uid = interaction.user.id

        if uid in session.players:
            await interaction.response.send_message("⚠️ You're already in this lobby!", ephemeral=True)
            return
        if len(session.players) >= _FFF_MAX_PLAYERS:
            await interaction.response.send_message(
                f"⚠️ This lobby is full ({_FFF_MAX_PLAYERS} players max)!", ephemeral=True
            )
            return
        existing = is_player_active(uid)
        if existing:
            await interaction.response.send_message(
                "⚠️ You're already in another active game session!", ephemeral=True
            )
            return

        session.players[uid] = safe_name(interaction.user.display_name)
        session.scores[uid] = 0
        session.last_activity = time.time()
        add_player(session.channel_id, uid)

        try:
            await interaction.response.edit_message(embed=self.lobby_embed(), view=self)
        except discord.HTTPException:
            await interaction.response.defer()
        await interaction.followup.send(
            f"🟢 **{safe_name(interaction.user.display_name)}** joined the lobby! "
            f"({len(session.players)}/{_FFF_MAX_PLAYERS} players)"
        )

    @discord.ui.button(label="👋 Leave", style=discord.ButtonStyle.secondary, row=0)
    async def leave_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        session = self.session
        uid = interaction.user.id

        if uid not in session.players:
            await interaction.response.send_message("⚠️ You're not in this lobby.", ephemeral=True)
            return

        pname = session.players.pop(uid)
        session.scores.pop(uid, None)
        remove_player(session.channel_id, uid)

        if not session.players:
            self.stop()
            end_session(session.channel_id)
            await interaction.response.edit_message(
                content="🛑 **Lobby closed** — all players left.",
                embed=None,
                view=None,
            )
            return

        host_msg = ""
        if uid == session.host_id:
            session.host_id = next(iter(session.players))
            host_msg = f" **{session.players[session.host_id]}** is now the host!"

        try:
            await interaction.response.edit_message(embed=self.lobby_embed(), view=self)
        except discord.HTTPException:
            await interaction.response.defer()
        await interaction.followup.send(f"👋 **{pname}** left the lobby.{host_msg}")

    @discord.ui.button(label="⚡ Start", style=discord.ButtonStyle.primary, row=1)
    async def start_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        session = self.session
        if interaction.user.id != session.host_id:
            await interaction.response.send_message(
                "⚠️ Only the host can start the game!", ephemeral=True
            )
            return
        if len(session.players) < _FFF_MIN_PLAYERS:
            await interaction.response.send_message(
                f"⚠️ Need at least {_FFF_MIN_PLAYERS} players to start!", ephemeral=True
            )
            return

        self.stop()
        self.cog._lobby_ready[session.session_id] = True
        await interaction.response.defer()

    @discord.ui.button(label="🛑 End Lobby", style=discord.ButtonStyle.danger, row=1)
    async def end_lobby_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        if interaction.user.id != self.session.host_id:
            await interaction.response.send_message(
                "⚠️ Only the host can end the lobby!", ephemeral=True
            )
            return
        self.stop()
        self.cog._lobby_ready[self.session.session_id] = "cancelled"
        await interaction.response.edit_message(
            content="🛑 **Lobby disbanded.** See you next time!",
            embed=None,
            view=None,
        )


# ---------------------------------------------------------------------------
# UI: Answer buttons (per-question) — includes Quit button (Fix 3a)
# ---------------------------------------------------------------------------

_QUIT_SENTINEL = -999  # used in answers_this_round to mark a quit


class AnswerView(discord.ui.View):
    """Shared answer view for a single FFF question.

    All registered players can click. Each player gets exactly one answer recorded.
    Clicking gives an ephemeral response. The public embed is updated when the
    timer expires or all players have answered/quit.
    """

    def __init__(self, session: FFFSession, answers: list[str]):
        super().__init__(timeout=float(_FFF_QUESTION_TIMEOUT))
        self.session = session
        self.answers = answers
        self._all_responded = asyncio.Event()

        for i, (label, answer) in enumerate(zip(_ANSWER_LABELS, answers)):
            btn = discord.ui.Button(
                label=f"{label}: {answer[:75]}",
                style=discord.ButtonStyle.primary,
                custom_id=f"fff_ans_{session.session_id}_{i}",
            )
            btn.callback = self._make_cb(i)
            self.add_item(btn)

        # Quit button (Fix 3a)
        quit_btn = discord.ui.Button(
            label="🚪 Quit Game",
            style=discord.ButtonStyle.danger,
            custom_id=f"fff_quit_{session.session_id}",
        )
        quit_btn.callback = self._quit_cb
        self.add_item(quit_btn)

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

            # Check if everyone (still in the game) has responded
            if set(self.session.answers_this_round.keys()) >= set(self.session.players.keys()):
                self._all_responded.set()

        return cb

    async def _quit_cb(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        if uid not in self.session.players:
            await interaction.response.send_message(
                "⚠️ You're not part of this game!", ephemeral=True
            )
            return
        if uid in self.session.answers_this_round:
            await interaction.response.send_message(
                "✅ Already responded this round!", ephemeral=True
            )
            return

        ts_ms = int(time.monotonic() * 1000)
        self.session.answers_this_round[uid] = (_QUIT_SENTINEL, ts_ms)
        await interaction.response.send_message(
            "🚪 **You quit the game.** Final scores will be shown at the end.", ephemeral=True
        )

        # Check if everyone responded
        if set(self.session.answers_this_round.keys()) >= set(self.session.players.keys()):
            self._all_responded.set()

    async def on_timeout(self) -> None:
        self._all_responded.set()
        self.stop()


# ---------------------------------------------------------------------------
# Embed builders
# ---------------------------------------------------------------------------


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
    quitters_this_round: list[int],
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
    if quitters_this_round:
        qnames = ", ".join(session.players.get(uid, str(uid)) for uid in quitters_this_round)
        embed.add_field(name="🚪 Left the game", value=qnames, inline=False)
    return embed


def _build_results_embed(session: FFFSession, total_q: int, early: bool = False) -> discord.Embed:
    sorted_players = sorted(session.players, key=lambda uid: session.scores.get(uid, 0), reverse=True)
    title = "⚡ Fastest Fingers First — Final Results"
    if early:
        title += " (Game Ended Early)"
    embed = discord.Embed(title=title, color=discord.Color.gold())
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


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _save_result(session: FFFSession, total_q: int) -> None:
    """Record the finished game: one match, a result per remaining player, stats updated in the same transaction."""
    scores = {uid: session.scores.get(uid, 0) for uid in session.players}
    if not scores:
        return
    rows = []
    for uid, rank in ranked(scores):
        times = session.response_times.get(uid, [])
        rows.append(ResultRow(
            uid, rank, scores[uid], session.correct.get(uid, 0),
            {"total_questions": total_q, "avg_response_ms": int(sum(times) / len(times)) if times else None},
        ))
    try:
        await record_match("fff", session.guild_id, rows, started_at=session.started_at.isoformat(),
                           rounds=total_q)
    except Exception as exc:
        logger.warning("FFF: failed to save results: %s", exc)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class FastestFingersCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # session_id → True (host pressed Start) | "cancelled" (host ended lobby)
        self._lobby_ready: dict[str, object] = {}

    async def cog_load(self) -> None:
        logger.info("FastestFingersCog loaded.")

    async def cog_unload(self) -> None:
        logger.info("FastestFingersCog unloaded.")

    # ── /fff ─────────────────────────────────────────────────

    @app_commands.command(name="fff", description="Start a Fastest Fingers First trivia game!")
    @app_commands.describe(
        questions="Number of questions (5–20, default 10)",
        category="Trivia category (optional — leave blank for all)",
        difficulty="Question difficulty",
    )
    @app_commands.choices(
        difficulty=[
            app_commands.Choice(name="Easy",   value="easy"),
            app_commands.Choice(name="Medium", value="medium"),
            app_commands.Choice(name="Hard",   value="hard"),
        ],
        category=_CATEGORY_CHOICES,   # Fix 1: dropdown choices
    )
    async def fff(
        self,
        interaction: discord.Interaction,
        questions: app_commands.Range[int, 5, 20] = 10,
        category: Optional[str] = None,   # stringified category ID or None
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

        # Resolve category (Fix 1)
        cat_id: Optional[int] = None
        cat_name: Optional[str] = None
        if category:
            cat_id = int(category)
            cat_name = _CAT_ID_TO_NAME.get(cat_id, f"Category {cat_id}")

        # Create thread
        timestamp = datetime.utcnow().strftime("%b %d %H:%M")
        try:
            announce_msg = await interaction.channel.send(
                f"⚡ **{safe_name(interaction.user.display_name)}** is starting **Fastest Fingers First!** "
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

        # Build session
        session_id = str(uuid.uuid4())
        session = FFFSession(
            session_id=session_id,
            host_id=interaction.user.id,
            channel_id=thread.id,
            guild_id=interaction.guild.id,
        )
        session.players[interaction.user.id] = safe_name(interaction.user.display_name)
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
        seen_questions: set[str] = set()
        try:
            async with asyncio.timeout(30):
                for _ in range(questions):
                    q, session_token = await fetch_question_any(
                        session_token=session_token,
                        difficulty=difficulty,
                        category=cat_id,
                        seen=seen_questions,
                    )
                    if q:
                        seen_questions.add(q["question"])
                        fetched_questions.append(q)
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning("FFF: question fetch error: %s", exc)

        if len(fetched_questions) < 3:
            end_session(thread.id)
            await thread.send(
                "⚠️ **Game cancelled** — couldn't fetch enough questions. "
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

        # Post lobby info and persistent view (Fix 3b)
        await thread.send(
            f"🎯 **{actual_q} questions** · Difficulty: **{difficulty.title()}**"
            + (f" · Category: **{cat_name}**" if cat_name else ""),
        )
        lobby_view = FFFLobbyView(session, self)
        lobby_msg = await thread.send(embed=lobby_view.lobby_embed(), view=lobby_view)
        await interaction.followup.send(
            f"⚡ Game lobby created! Head to {thread.mention} to join.", ephemeral=True
        )

        self._lobby_ready[session_id] = False

        # Wait for host to Start or End Lobby (Fix 3b — persistent lobby with inactivity watch)
        cancelled = False
        try:
            async with asyncio.timeout(_FFF_LOBBY_INACTIVITY):
                while True:
                    await asyncio.sleep(2)
                    status = self._lobby_ready.get(session_id)
                    if status is True:
                        break
                    if status == "cancelled":
                        cancelled = True
                        break
                    # Inactivity check
                    if time.time() - session.last_activity > _FFF_LOBBY_INACTIVITY:
                        cancelled = True
                        break
        except asyncio.TimeoutError:
            cancelled = len(session.players) < _FFF_MIN_PLAYERS  # auto-start only if enough players

        self._lobby_ready.pop(session_id, None)

        # Disable lobby buttons
        lobby_view.stop()
        for item in lobby_view.children:
            item.disabled = True
        try:
            await lobby_msg.edit(view=lobby_view)
        except discord.HTTPException:
            pass

        # Handle cancelled / not enough players
        if cancelled or len(session.players) < _FFF_MIN_PLAYERS:
            end_session(thread.id)
            msg = (
                "🛑 **Lobby ended.** " +
                ("Not enough players joined." if len(session.players) < _FFF_MIN_PLAYERS
                 else "Host ended the lobby.")
            )
            await thread.send(msg)
            await asyncio.sleep(5)
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

    # ── Inactivity watcher (Fix 3b) ───────────────────────────

    # Note: inactivity is handled inline in the lobby wait loop above.
    # No separate task needed because the timeout covers it.

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
            + f"\n\n*First correct answer = {_FIRST_CORRECT_PTS} pts · "
            f"subsequent correct = {_SUBSEQUENT_CORRECT_PTS} pts*\n"
            f"*Use 🚪 Quit Game at any time to exit.*"
        )
        await asyncio.sleep(3)

        q_start_ms = int(time.monotonic() * 1000)

        for q_index, question in enumerate(session.questions):
            # Stop if too few players remain
            if len(session.players) < 1:
                await thread.send("🛑 **All players have left — game over.**")
                break

            session.current_q_index = q_index
            session.answers_this_round.clear()
            session.first_correct_claimed = False

            answers, correct_idx = shuffle_answers(question)
            q_start_ms = int(time.monotonic() * 1000)

            embed = _build_question_embed(question, answers, q_index + 1, total_q)
            answer_view = AnswerView(session, answers)
            q_msg = await thread.send(embed=embed, view=answer_view)

            # Wait for timer or all players responded
            try:
                await asyncio.wait_for(
                    answer_view._all_responded.wait(), timeout=float(_FFF_QUESTION_TIMEOUT)
                )
            except asyncio.TimeoutError:
                pass

            answer_view.stop()
            for item in answer_view.children:
                item.disabled = True
            try:
                await q_msg.edit(view=answer_view)
            except discord.HTTPException:
                pass

            # Collect quitters this round
            quitters_this_round: list[int] = []
            for uid, (ans_idx, _ts) in session.answers_this_round.items():
                if ans_idx == _QUIT_SENTINEL and uid in session.players:
                    quitters_this_round.append(uid)

            # Score this round and track AFK (Fix 4)
            winners_this_round: list[int] = []
            for uid, (ans_idx, ts_ms) in sorted(
                session.answers_this_round.items(), key=lambda x: x[1][1]
            ):
                if uid not in session.players:
                    continue
                if ans_idx == _QUIT_SENTINEL:
                    continue
                if ans_idx == correct_idx:
                    response_ms = ts_ms - q_start_ms
                    session.response_times.setdefault(uid, []).append(response_ms)
                    session.correct[uid] = session.correct.get(uid, 0) + 1
                    if not session.first_correct_claimed:
                        session.scores[uid] = session.scores.get(uid, 0) + _FIRST_CORRECT_PTS
                        session.first_correct_claimed = True
                    else:
                        session.scores[uid] = session.scores.get(uid, 0) + _SUBSEQUENT_CORRECT_PTS
                    winners_this_round.append(uid)
                    session.afk_counts[uid] = 0   # reset AFK counter on any answer (Fix 4)
                else:
                    session.afk_counts[uid] = 0   # wrong answer still counts as "answered"

            # AFK tracking for players who didn't answer at all (Fix 4)
            answered_uids = set(session.answers_this_round.keys())
            for uid in list(session.players.keys()):
                if uid not in answered_uids:
                    session.afk_counts[uid] = session.afk_counts.get(uid, 0) + 1

            reveal_embed = _build_reveal_embed(
                question, answers, correct_idx, session, winners_this_round, quitters_this_round
            )
            await thread.send(embed=reveal_embed)

            # Remove quitters (Fix 3a)
            for uid in quitters_this_round:
                if uid in session.players:
                    name = session.players.pop(uid)
                    session.scores.pop(uid, None)
                    remove_player(session.channel_id, uid)
                    await thread.send(f"🚪 **{name}** left the game.")

            # AFK kick (Fix 4)
            for uid in list(session.players.keys()):
                if session.afk_counts.get(uid, 0) >= _FFF_AFK_KICK_THRESHOLD:
                    name = session.players.pop(uid)
                    session.scores.pop(uid, None)
                    remove_player(session.channel_id, uid)
                    session.afk_counts.pop(uid, None)
                    await thread.send(
                        f"💤 **{name}** has been removed for going AFK "
                        f"({_FFF_AFK_KICK_THRESHOLD} consecutive non-answers)."
                    )

            # Check if game should end early (not enough players for meaningful play)
            if len(session.players) < 1:
                await thread.send("🛑 **No players remaining — game over.**")
                break

            await asyncio.sleep(_FFF_REVEAL_PAUSE)

        # Game over — show results
        await asyncio.sleep(1)
        early = len(session.players) < 1
        results_embed = _build_results_embed(session, total_q, early=early)
        await thread.send(embed=results_embed)

        # Persist results
        await _save_result(session, total_q)

        # Fix 2: lock thread immediately after game ends
        await asyncio.sleep(3)
        try:
            await thread.edit(archived=True, locked=True)
        except discord.Forbidden:
            logger.warning("FFF: no permission to archive thread %d.", thread.id)
        except discord.HTTPException as exc:
            logger.warning("FFF: failed to archive thread: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FastestFingersCog(bot))
