"""What makes a new password too easy to guess, beyond its length.

NIST SP 800-63B (section 3.1.1.2) asks a service to refuse passwords that are
commonly used, already breached, built from the account's or the service's own
name, or simple runs such as ``aaaaaaaa`` and ``12345678``. The local rules here
need no network; the breach check asks Have I Been Pwned without ever sending
the password.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Iterable, Mapping

import httpx

log = logging.getLogger(__name__)

COMMON = "This is one of the most common passwords, so attackers try it first. Choose another."
PATTERN = "Avoid runs and repeats like 12345678 or aaaaaaaa. Choose another."
PERSONAL = "Your email address or Fareflare's name makes up most of this password. Choose another."
BREACHED = "This password has appeared in a data breach, so attackers try it early. Choose another."

# The roots of the most-used passwords. With only digits or symbols around them
# (Password1!, 2024dragon) they are just as predictable, so the root is compared.
_COMMON_ROOTS = frozenset(
    [
        "password",
        "passw0rd",
        "p@ssword",
        "p@ssw0rd",
        "pass",
        "passwd",
        "qwerty",
        "qwertyuiop",
        "qwertz",
        "azerty",
        "asdfgh",
        "asdfghjkl",
        "zxcvbn",
        "zxcvbnm",
        "letmein",
        "welcome",
        "iloveyou",
        "loveyou",
        "admin",
        "administrator",
        "root",
        "login",
        "user",
        "guest",
        "test",
        "changeme",
        "default",
        "secret",
        "access",
        "master",
        "monkey",
        "dragon",
        "football",
        "baseball",
        "basketball",
        "soccer",
        "hockey",
        "sunshine",
        "princess",
        "shadow",
        "superman",
        "batman",
        "spiderman",
        "trustno",
        "trustno1",
        "whatever",
        "starwars",
        "pokemon",
        "charlie",
        "michael",
        "jordan",
        "jennifer",
        "jessica",
        "ashley",
        "daniel",
        "thomas",
        "robert",
        "matthew",
        "anthony",
        "andrew",
        "joshua",
        "michelle",
        "nicole",
        "hannah",
        "buster",
        "tigger",
        "ginger",
        "pepper",
        "cookie",
        "chocolate",
        "summer",
        "winter",
        "spring",
        "autumn",
        "flower",
        "freedom",
        "computer",
        "internet",
        "matrix",
        "mustang",
        "harley",
        "ranger",
        "hunter",
        "killer",
        "liverpool",
        "chelsea",
        "arsenal",
        "samsung",
        "google",
        "facebook",
        "hello",
        "hellohello",
        "abc",
        "abcd",
        "abcdef",
        "iloveu",
        "fuckyou",
        "blink",
        "qazwsx",
        "qwer",
        "asdf",
        "zaq",
        "zaq12wsx",
        "1q2w3e",
        "1q2w3e4r",
        "1qaz2wsx",
        "q1w2e3r4",
        "fareflare",
        "flight",
        "flights",
        "travel",
        "airplane",
        "holiday",
        "vacation",
    ]
)

# Keyboard rows and alphabets, read either way; a password inside one is a run.
_RUNS = (
    "1234567890",
    "0987654321",
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
    "!@#$%^&*()",
    "abcdefghijklmnopqrstuvwxyz",
)


def _plain(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _is_run(value: str) -> bool:
    if len(value) < 6:
        return False
    return any(value in run or value in run[::-1] for run in _RUNS)


def weakness(password: str, context: Iterable[str] = ()) -> str | None:
    """The reason a new password is easy to guess, or None. ``context`` holds words
    an attacker would try first for this account: its email address, its username
    and the service's name."""
    lowered = password.lower()
    plain = _plain(password)
    root = re.sub(r"^[\d\W_]+|[\d\W_]+$", "", lowered)
    if lowered in _COMMON_ROOTS or root in _COMMON_ROOTS or plain in _COMMON_ROOTS:
        return COMMON
    if (
        len(set(lowered)) <= 2
        or re.fullmatch(r"(.{1,4})\1+", lowered)
        or _is_run(lowered)
        or _is_run(plain)
    ):
        return PATTERN
    for word in context:
        for piece in {_plain(word), _plain(word.partition("@")[0])}:
            if len(piece) >= 4 and piece in plain and len(plain) - len(piece) < 6:
                return PERSONAL
    return None


class BreachedPasswords:
    """Have I Been Pwned's Pwned Passwords range API.

    Only the first five characters of the password's SHA-1 leave the service
    (k-anonymity), and padded answers hide how many suffixes matched. If the
    service cannot be reached, the password is allowed: an outage must not stop
    sign-up, and the local rules in ``weakness`` still apply.
    """

    URL = "https://api.pwnedpasswords.com/range/"

    def __init__(self, transport: httpx.BaseTransport | None = None, timeout: float = 2.0):
        self.transport, self.timeout = transport, timeout

    def __call__(self, password: str) -> bool:
        # SHA-1 is the API's lookup key, not how Fareflare stores passwords.
        digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = client.get(
                    self.URL + prefix,
                    headers={"Add-Padding": "true", "User-Agent": "Fareflare-password-check"},
                )
            response.raise_for_status()
        except httpx.HTTPError:
            log.warning("The breached-password check could not be reached")
            return False
        for line in response.text[:2_000_000].splitlines():
            found, _, count = line.partition(":")
            if found.strip() == suffix and count.strip().isdigit() and int(count) > 0:
                return True
        return False


def breach_check_from_env(environ: Mapping[str, str] | None = None) -> BreachedPasswords | None:
    """The breach check unless ``FAREFLARE_PASSWORD_BREACH_CHECK`` is ``off``."""
    values = os.environ if environ is None else environ
    setting = values.get("FAREFLARE_PASSWORD_BREACH_CHECK", "on").lower()
    if setting not in ("on", "off"):
        raise ValueError("FAREFLARE_PASSWORD_BREACH_CHECK must be on or off")
    return BreachedPasswords() if setting == "on" else None
