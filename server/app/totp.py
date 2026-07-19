"""Minimal RFC 6238 TOTP (SHA-1, 6 digits, 30 s) — stdlib only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int) -> str:
    pad = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(secret.upper() + pad)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify(secret: str, code: str, window: int = 1) -> bool:
    if not secret or not code:
        return False
    counter = int(time.time() // 30)
    for off in range(-window, window + 1):
        if hmac.compare_digest(_code(secret, counter + off), code.strip()):
            return True
    return False


def provisioning_uri(secret: str, username: str,
                     issuer: str = "shelly-pool-control") -> str:
    return (f"otpauth://totp/{issuer}:{username}?secret={secret}"
            f"&issuer={issuer}&algorithm=SHA1&digits=6&period=30")
