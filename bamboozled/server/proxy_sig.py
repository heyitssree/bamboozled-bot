"""Optional second layer for REST calls: verify the signature Discord's proxy adds (Ed25519, PyNaCl).

UNVERIFIED ASSUMPTION: the signed message is `timestamp + payload`, as for Discord interactions. Confirm the real
header contract against Discord's current Activity documentation, and confirm that the headers arrive at all on REST
calls (they may not on the WebSocket upgrade), before turning `activity.require_proxy_signature` on (Phase 7).
"""
from __future__ import annotations

import time
from typing import Callable

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

MAX_AGE_S = 300


def verify(public_key_hex: str, signature_hex: str, timestamp: str, payload: bytes,
           now: Callable[[], float] = time.time) -> bool:
    try:
        if abs(now() - float(timestamp)) > MAX_AGE_S:
            return False
        VerifyKey(bytes.fromhex(public_key_hex)).verify(timestamp.encode() + payload, bytes.fromhex(signature_hex))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False
