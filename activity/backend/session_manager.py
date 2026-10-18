from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket

from models import GameConfig, GamePhase, GameState, Player

logger = logging.getLogger("bamboozled.activity.sessions")


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, GameState] = {}
        self._connections: dict[str, dict[str, WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        session_id: str,
        guild_id: str,
        channel_id: str,
        host_id: str,
        config: GameConfig,
    ) -> GameState:
        async with self._lock:
            state = GameState(
                session_id=session_id,
                guild_id=guild_id,
                channel_id=channel_id,
                phase=GamePhase.LOBBY,
                players={},
                join_order=[],
                host_id=host_id,
                current_question=None,
                current_player_id=None,
                wheel_result=None,
                active_card=None,
                mist_active=False,
                mist_turns_remaining=0,
                round_number=1,
                config=config,
                answers_this_round={},
            )
            self._sessions[session_id] = state
            self._connections[session_id] = {}
            logger.info("Session %s created by host %s", session_id, host_id)
            return state

    async def join_session(
        self,
        session_id: str,
        player: Player,
        ws: WebSocket,
    ) -> bool:
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                logger.warning("join_session: unknown session %s", session_id)
                return False
            if state.phase != GamePhase.LOBBY:
                logger.warning(
                    "join_session: session %s not in LOBBY phase (%s)",
                    session_id,
                    state.phase,
                )
                return False

            pid = player.discord_id
            if pid not in state.players:
                state.players[pid] = player
                state.join_order.append(pid)
            else:
                # Reconnect: mark as connected and update ws
                state.players[pid].is_connected = True

            self._connections[session_id][pid] = ws
            logger.info("Player %s joined session %s", pid, session_id)
            return True

    async def reconnect_player(
        self,
        session_id: str,
        player_id: str,
        ws: WebSocket,
    ) -> bool:
        """Re-attach a websocket for a player who already joined (mid-game reconnect)."""
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None or player_id not in state.players:
                return False
            state.players[player_id].is_connected = True
            self._connections[session_id][player_id] = ws
            logger.info("Player %s reconnected to session %s", player_id, session_id)
            return True

    async def disconnect_player(self, session_id: str, player_id: str) -> None:
        async with self._lock:
            state = self._sessions.get(session_id)
            if state and player_id in state.players:
                state.players[player_id].is_connected = False
            conns = self._connections.get(session_id, {})
            conns.pop(player_id, None)
            logger.info("Player %s disconnected from session %s", player_id, session_id)

    async def broadcast(self, session_id: str, event: dict) -> None:
        conns = dict(self._connections.get(session_id, {}))
        dead: list[str] = []
        payload = json.dumps(event)
        for pid, ws in conns.items():
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(pid)
        for pid in dead:
            await self.disconnect_player(session_id, pid)

    async def send_to_player(
        self,
        session_id: str,
        player_id: str,
        event: dict,
    ) -> None:
        ws = self._connections.get(session_id, {}).get(player_id)
        if ws:
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                await self.disconnect_player(session_id, player_id)

    async def get_state(self, session_id: str) -> Optional[GameState]:
        return self._sessions.get(session_id)

    async def update_state(self, session_id: str, new_state: GameState) -> None:
        async with self._lock:
            self._sessions[session_id] = new_state

    async def end_session(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)
            self._connections.pop(session_id, None)
        logger.info("Session %s ended and removed.", session_id)

    def active_session_count(self) -> int:
        return len(self._sessions)
