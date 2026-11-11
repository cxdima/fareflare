"""Time-based one-time codes (RFC 6238) and single-use backup codes for two-step sign-in.

Codes are six digits on a 30-second step, the shape every authenticator app and
password manager (1Password included) reads from an ``otpauth://`` link.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct
from urllib.parse import quote, urlencode

STEP_SECONDS = 30
DIGITS = 6
# One step either side absorbs a clock that is up to half a minute off.
WINDOW = 1
BACKUP_CODE_COUNT = 10
# No 0/O or 1/I/L: a code read from paper must not be ambiguous.
_BACKUP_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
_CODE = re.compile(r"\d{6}\Z")
_BACKUP = re.compile(r"[2-9a-hjkmnp-z]{4}-?[2-9a-hjkmnp-z]{4}\Z")


def new_secret() -> str:
    """A 160-bit secret in unpadded base32, as RFC 4226 recommends."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def matching_step(secret: str, code: str, now: float, after_step: int = -1) -> int | None:
    """The step a code belongs to, or None. A step at or before ``after_step`` was
    already used, so the same code cannot sign in twice."""
    if not isinstance(code, str):
        return None
    code = code.replace(" ", "")
    if not _CODE.fullmatch(code):
        return None
    current = int(now) // STEP_SECONDS
    for step in range(current - WINDOW, current + WINDOW + 1):
        if step > after_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}", safe="@:")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def new_backup_codes() -> list[str]:
    codes = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(8))
        codes.append(raw[:4] + "-" + raw[4:])
    return codes


def backup_digest(code: str) -> str | None:
    """The stored form of a backup code, tolerant of case, spaces and a missing hyphen."""
    if not isinstance(code, str):
        return None
    normalized = code.strip().lower().replace(" ", "")
    if not _BACKUP.fullmatch(normalized):
        return None
    normalized = normalized.replace("-", "")
    return hashlib.sha256(("fareflare-backup-v1:" + normalized).encode()).hexdigest()
