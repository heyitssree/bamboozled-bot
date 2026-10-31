"""Wire protocol: JSON text frames, max 4 KB. Envelope {"v": 1, "t": TYPE, "id": client id, "seq": n, "d": {...}}.

Every client message has a strict model (unknown fields are rejected). Unknown message types are ignored.
"""
from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, StrictBool, StrictInt, StrictStr

VERSION = 1
MAX_FRAME_BYTES = 4096
MODES = ("bamboozled", "fff", "survival")


class FrameError(Exception):
    """A frame that cannot be used. `code` goes back to the client when the socket is still usable."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(code)
        self.code, self.message = code, message


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Auth(_M):
    access_token: StrictStr = Field(min_length=1, max_length=2048)
    instance_id: StrictStr = Field(min_length=1, max_length=128)


class Ready(_M):
    ready: StrictBool


class SetMode(_M):
    mode: Literal["bamboozled", "fff", "survival"]


class SetConfig(_M):
    rounds: Optional[StrictInt] = Field(default=None, ge=1, le=60)
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    category: Optional[StrictStr] = Field(default=None, max_length=40)


class Empty(_M):
    pass


class Answer(_M):
    index: StrictInt = Field(ge=0, le=3)


class PickTarget(_M):
    user_id: Optional[StrictInt] = Field(default=None, ge=0)


class PickRule(_M):
    rule_id: StrictInt = Field(ge=1, le=99)


class Monkey(_M):
    choice: Literal["belly", "tail"]


MODELS: dict[str, type[_M]] = {
    "AUTH": Auth, "READY": Ready, "SET_MODE": SetMode, "SET_CONFIG": SetConfig, "START": Empty,
    "ANSWER": Answer, "DRAW_CARD": Empty, "SPIN": Empty, "PICK_TARGET": PickTarget, "PICK_RULE": PickRule,
    "MONKEY": Monkey, "FORFEIT": Empty, "LEAVE": Empty, "REMATCH": Empty, "PING": Empty, "RESYNC": Empty,
}


class Parsed(BaseModel):
    t: str
    id: Optional[str]
    d: Any


def parse_frame(raw: str | bytes) -> Optional[Parsed]:
    """Return the parsed message, None for a type we do not know (ignored), or raise FrameError."""
    size = len(raw.encode() if isinstance(raw, str) else raw)
    if size > MAX_FRAME_BYTES:
        raise FrameError("frame_too_big", f"frames are limited to {MAX_FRAME_BYTES} bytes")
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise FrameError("bad_json", "that was not valid JSON") from None
    if not isinstance(obj, dict) or obj.get("v") != VERSION or not isinstance(obj.get("t"), str):
        raise FrameError("bad_frame", "expected an object with v=1 and a string t")
    msg_id = obj.get("id")
    if msg_id is not None and (not isinstance(msg_id, str) or len(msg_id) > 64):
        raise FrameError("bad_frame", "id must be a short string")
    model = MODELS.get(obj["t"])
    if model is None:
        return None
    try:
        data = model.model_validate(obj.get("d", {}))
    except ValidationError:
        raise FrameError("bad_payload", f"{obj['t']} has the wrong fields") from None
    return Parsed(t=obj["t"], id=msg_id, d=data)


def envelope(t: str, d: dict, seq: int, msg_id: Optional[str] = None) -> dict:
    out = {"v": VERSION, "t": t, "seq": seq, "d": d}
    if msg_id is not None:
        out["id"] = msg_id
    return out
