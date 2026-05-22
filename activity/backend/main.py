from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from boli_client import award_boli
from config import settings
from db import close_session, init_db, record_results, record_session
from game_engine import BamboozledEngine
from models import GameConfig, GamePhase, Player
from question_service import fetch_question
from session_manager import SessionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("navi.activity.main")

app = FastAPI(title="Bamboozled Activity API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = SessionManager()
engine = BamboozledEngine()


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    logger.info("Bamboozled Activity backend started.")


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    guild_id: str
    channel_id: str
    host_id: str
    total_rounds: int = 10
    difficulty: str = "medium"
    category: Optional[str] = None
    time_per_question: int = 30


@app.post("/session/create")
async def create_session(req: CreateSessionRequest) -> dict:
    session_id = str(uuid.uuid4())
    config = GameConfig(
        total_rounds=max(1, min(20, req.total_rounds)),
        difficulty=req.difficulty if req.difficulty in ("easy", "medium", "hard") else "medium",
        category=req.category,
        time_per_question=max(10, min(60, req.time_per_question)),
    )
    await manager.create_session(
        session_id=session_id,
        guild_id=req.guild_id,
        channel_id=req.channel_id,
        host_id=req.host_id,
        config=config,
    )
    await record_session(
        session_id=session_id,
        guild_id=req.guild_id,
        channel_id=req.channel_id,
        host_id=req.host_id,
        total_rounds=config.total_rounds,
        difficulty=config.difficulty,
    )
    return {"session_id": session_id}


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_sessions": manager.active_session_count(),
    }


# ---------------------------------------------------------------------------
# OAuth2 callback — exchanges Discord code for access token
# ---------------------------------------------------------------------------

class OAuthCallbackRequest(BaseModel):
    code: str


@app.post("/oauth/callback")
async def oauth_callback(req: OAuthCallbackRequest) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": settings.DISCORD_CLIENT_ID,
                "client_secret": settings.DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": req.code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="OAuth exchange failed.")
        token_data = resp.json()
    return {"access_token": token_data.get("access_token")}


# ---------------------------------------------------------------------------
# WebSocket — main game loop
# ---------------------------------------------------------------------------

@app.websocket("/ws/{session_id}/{player_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str, player_id: str) -> None:
    await ws.accept()

    state = await manager.get_state(session_id)
    if state is None:
        await ws.close(code=4004, reason="Session not found.")
        return

    # Mid-game reconnect
    if player_id in state.players:
        await manager.reconnect_player(session_id, player_id, ws)
        await manager.broadcast(session_id, {"type": "STATE_UPDATE", "state": state.to_dict()})
    # else: PLAYER_JOIN message must arrive first

    try:
        while True:
            raw = await ws.receive_text()
            import json
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            msg_type = msg.get("type")
            state = await manager.get_state(session_id)
            if state is None:
                break

            # ------------------------------------------------------------------
            if msg_type == "PLAYER_JOIN":
                if state.phase != GamePhase.LOBBY:
                    continue
                player = Player(
                    discord_id=player_id,
                    username=msg.get("username", player_id),
                    avatar_url=msg.get("avatar_url", ""),
                )
                await manager.join_session(session_id, player, ws)
                state = await manager.get_state(session_id)
                await manager.broadcast(
                    session_id, {"type": "STATE_UPDATE", "state": state.to_dict()}
                )

            # ------------------------------------------------------------------
            elif msg_type == "START_GAME":
                if player_id != state.host_id or state.phase != GamePhase.LOBBY:
                    continue
                if len([p for p in state.players.values() if p.is_connected]) < 2:
                    await manager.send_to_player(
                        session_id, player_id,
                        {"type": "ERROR", "message": "Need at least 2 players to start."},
                    )
                    continue

                state.phase = GamePhase.WHEEL
                connected = [pid for pid in state.join_order if state.players[pid].is_connected]
                state.current_player_id = connected[0] if connected else None
                await manager.update_state(session_id, state)
                await _spin_wheel_and_broadcast(session_id, state)

            # ------------------------------------------------------------------
            elif msg_type == "WHEEL_ACK":
                if state.phase != GamePhase.WHEEL:
                    continue
                # Host (or current player) ACKs the wheel — apply effects and fetch question
                state = await engine.apply_wheel_effects(state)
                question = await fetch_question(
                    difficulty=state.config.difficulty,
                )
                state.current_question = question
                state.phase = GamePhase.QUESTION
                state.answers_this_round = {}
                await manager.update_state(session_id, state)
                await manager.broadcast(
                    session_id, {"type": "STATE_UPDATE", "state": state.to_dict()}
                )

            # ------------------------------------------------------------------
            elif msg_type == "ANSWER_SUBMITTED":
                if state.phase != GamePhase.QUESTION:
                    continue
                if player_id != state.current_player_id:
                    continue
                answer_index = int(msg.get("answer_index", -1))
                result = await engine.process_answer(state, player_id, answer_index)
                state.phase = GamePhase.REVEAL
                await manager.update_state(session_id, state)

                # Send targeted sound cue
                sound = "correct" if result.is_correct else "wrong"
                if state.wheel_result and state.wheel_result.outcome.value == "GOLDEN_MONKEY" and result.is_correct:
                    sound = "golden_monkey"
                elif state.wheel_result and state.wheel_result.outcome.value == "BAMBOOZLE" and not result.is_correct:
                    sound = "bamboozle"
                await manager.broadcast(session_id, {"type": "SOUND_CUE", "sound": sound})

                # If a card was applied, show it
                if result.card_applied:
                    state.phase = GamePhase.CARD
                    await manager.update_state(session_id, state)

                await manager.broadcast(
                    session_id, {"type": "STATE_UPDATE", "state": state.to_dict()}
                )

            # ------------------------------------------------------------------
            elif msg_type == "CARD_ACK":
                if state.phase != GamePhase.CARD:
                    continue
                state.phase = GamePhase.REVEAL
                await manager.update_state(session_id, state)
                await manager.broadcast(
                    session_id, {"type": "STATE_UPDATE", "state": state.to_dict()}
                )

            # ------------------------------------------------------------------
            elif msg_type == "NEXT_TURN":
                # Host or current player advances to next turn after reveal
                if state.phase not in (GamePhase.REVEAL, GamePhase.CARD):
                    continue
                if player_id not in (state.host_id, state.current_player_id):
                    continue

                state = await engine.advance_turn(state)
                game_over = await engine.check_win(state)

                if game_over:
                    await _handle_game_over(session_id, state)
                else:
                    state.phase = GamePhase.WHEEL
                    await manager.update_state(session_id, state)
                    await _spin_wheel_and_broadcast(session_id, state)

    except WebSocketDisconnect:
        await manager.disconnect_player(session_id, player_id)
        state = await manager.get_state(session_id)
        if state:
            await manager.broadcast(
                session_id, {"type": "STATE_UPDATE", "state": state.to_dict()}
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _spin_wheel_and_broadcast(session_id: str, state) -> None:
    wheel_result = await engine.spin_wheel(state)
    state.wheel_result = wheel_result
    await manager.update_state(session_id, state)
    await manager.broadcast(session_id, {"type": "SOUND_CUE", "sound": "wheel_spin"})

    # Map outcome to sound
    outcome_sounds = {
        "GOLDEN_MONKEY": "golden_monkey",
        "MYSTIC_MIST": "mist",
        "SOMBRERO": "sombrero",
        "BAMBOOZLE": "bamboozle",
    }
    outcome_sound = outcome_sounds.get(wheel_result.outcome.value)
    if outcome_sound:
        await manager.broadcast(session_id, {"type": "SOUND_CUE", "sound": outcome_sound})

    await manager.broadcast(
        session_id, {"type": "STATE_UPDATE", "state": state.to_dict()}
    )


async def _handle_game_over(session_id: str, state) -> None:
    state.phase = GamePhase.ENDED
    boli_awards = engine.calculate_boli(state)

    sorted_players = sorted(
        state.players.values(), key=lambda p: p.score, reverse=True
    )
    results = [
        {
            "discord_id": p.discord_id,
            "username": p.username,
            "final_score": p.score,
            "rank": i + 1,
            "boli_awarded": boli_awards.get(p.discord_id, 0),
        }
        for i, p in enumerate(sorted_players)
    ]

    await manager.update_state(session_id, state)
    await manager.broadcast(session_id, {"type": "SOUND_CUE", "sound": "game_over"})
    await manager.broadcast(
        session_id,
        {
            "type": "GAME_OVER",
            "results": results,
            "boli_awards": boli_awards,
            "state": state.to_dict(),
        },
    )

    # Persist and award Boli
    await record_results(session_id, results)
    await close_session(session_id)
    await award_boli(session_id, boli_awards)
    await manager.end_session(session_id)
