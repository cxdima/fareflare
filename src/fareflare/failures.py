"""Describe an unexpected error for operators without repeating its message.

Exception text from a browser, an HTTP client or a provider can carry URLs,
cookies, tokens or customer data, so it is never logged or stored. The error's
type and the places in this package it passed through are safe, and are usually
enough to find the fault.
"""

from __future__ import annotations

import traceback
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent
_MAX_FRAMES = 4


def describe_failure(error: BaseException) -> str:
    """``KeyError at public_quotes.py:98 verified_reading < service.py:641 collect_batch``."""
    frames = [
        frame
        for frame in traceback.extract_tb(error.__traceback__)
        if Path(frame.filename).resolve().parent == _PACKAGE
    ]
    trail = " < ".join(
        f"{Path(frame.filename).name}:{frame.lineno} {frame.name}"
        for frame in reversed(frames[-_MAX_FRAMES:])
    )
    name = type(error).__name__
    return f"{name} at {trail}" if trail else name
