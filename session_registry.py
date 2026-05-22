"""
session_registry.py
Tracks all active game sessions across all modes (bamboozled, fff, survival).
Prevents duplicate sessions in the same thread and prevents a player
from being in two games simultaneously.

Sessions are transient — they do not survive bot restarts, which is acceptable.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Literal

logger = logging.getLogger("navi.session_registry")

GameMode = Literal["bamboozled", "fff", "survival"]

# channel_id → session metadata dict
_active_sessions: dict[int, dict] = {}

# user_id → channel_id they are currently active in
_player_sessions: dict[int, int] = {}

# Single lock protecting all dict mutations
_lock = threading.Lock()


def register_session(channel_id: int, mode: GameMode, host_id: int) -> bool:
    """Register a new game session for a channel.

    Returns True on success, False if the channel already has an active session.
    """
    with _lock:
        if channel_id in _active_sessions:
            logger.debug(
                "register_session: channel %d already has an active %s session.",
                channel_id, _active_sessions[channel_id].get("mode"),
            )
            return False
        _active_sessions[channel_id] = {
            "channel_id": channel_id,
            "mode": mode,
            "host_id": host_id,
            "players": set(),
            "started_at": datetime.utcnow(),
        }
        logger.debug("register_session: %s session started in channel %d.", mode, channel_id)
        return True


def add_player(channel_id: int, user_id: int) -> bool:
    """Add a player to an existing session.

    Returns False if the user is already in *any* active session.
    """
    with _lock:
        if user_id in _player_sessions:
            existing_channel = _player_sessions[user_id]
            logger.debug(
                "add_player: user %d already in session for channel %d.",
                user_id, existing_channel,
            )
            return False
        session = _active_sessions.get(channel_id)
        if session is None:
            logger.debug("add_player: no session found for channel %d.", channel_id)
            return False
        session["players"].add(user_id)
        _player_sessions[user_id] = channel_id
        logger.debug("add_player: user %d added to channel %d.", user_id, channel_id)
        return True


def remove_player(channel_id: int, user_id: int) -> None:
    """Remove a player from a session (e.g. they left mid-game)."""
    with _lock:
        session = _active_sessions.get(channel_id)
        if session is not None:
            session["players"].discard(user_id)
        _player_sessions.pop(user_id, None)
        logger.debug("remove_player: user %d removed from channel %d.", user_id, channel_id)


def end_session(channel_id: int) -> None:
    """Fully clean up a session.

    Must be called when a game ends or errors out.
    Clears both _active_sessions and all player entries for this channel.
    """
    with _lock:
        session = _active_sessions.pop(channel_id, None)
        if session is not None:
            for uid in list(session.get("players", set())):
                _player_sessions.pop(uid, None)
            logger.debug(
                "end_session: %s session in channel %d cleaned up.",
                session.get("mode"), channel_id,
            )
        else:
            logger.debug("end_session: no session found for channel %d (already cleaned).", channel_id)


def get_session(channel_id: int) -> dict | None:
    """Return session metadata or None if no session exists for the channel."""
    with _lock:
        return _active_sessions.get(channel_id)


def is_player_active(user_id: int) -> int | None:
    """Return the channel_id if the user is in an active session, else None."""
    with _lock:
        return _player_sessions.get(user_id)
