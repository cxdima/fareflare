"""Show what a Google Flights link holds and what Fareflare makes of it. Offline.

    PYTHONPATH=src .venv/bin/python scripts/decode_link.py 'https://www.google.com/travel/flights/booking?tfs=...'
    PYTHONPATH=src .venv/bin/python scripts/decode_link.py tests/fixtures/selected_city_safari.json

The argument is a link, or a file holding one (a fixture's ``url``, or plain text).
Prints the query parameters, every field of the ``tfs`` itinerary token (named where
Fareflare reads it, numbered where it does not) and of the ``tfu`` token, then whether
the importer accepts the link and whether the collector can price it. Shared ``/s/``
links are not followed: open one and paste the full address it leads to.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from fareflare.links import import_link
from fareflare.public_quotes import supported_target
from fareflare.search_links import SearchMessage

Field = tuple[int, int, int | bytes]


def _varint(data: bytes, position: int) -> tuple[int, int]:
    result = shift = 0
    while position < len(data) and shift < 64:
        byte = data[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, position
        shift += 7
    raise ValueError("bad varint")


def fields(data: bytes) -> list[Field]:
    """Every (number, wire type, value) of a protobuf message; ValueError if it is not one."""
    found: list[Field] = []
    position = 0
    while position < len(data):
        key, position = _varint(data, position)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, position = _varint(data, position)
        elif wire in (1, 2, 5):
            length = {1: 8, 5: 4}.get(wire)
            if length is None:
                length, position = _varint(data, position)
            value, position = data[position : position + length], position + length
        else:
            raise ValueError(f"wire type {wire}")
        if number == 0 or position > len(data):
            raise ValueError("truncated")
        found.append((number, wire, value))
    return found


def _text(value: bytes) -> str | None:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text if text.isprintable() else None


def _base64_message(text: str) -> bytes | None:
    """The message a long base64 text field encodes (tfu nests one), if it does."""
    if not re.fullmatch(r"[A-Za-z0-9+/_-]{16,}={0,2}", text):
        return None
    try:
        raw = base64.urlsafe_b64decode(text.replace("+", "-").replace("/", "_") + "==")
        return raw if fields(raw) else None
    except (ValueError, binascii.Error):
        return None


def show(data: bytes, descriptor: Any, depth: int = 1) -> None:
    pad = "  " * depth
    for number, wire, value in fields(data):
        field = descriptor.fields_by_number.get(number) if descriptor else None
        label = f"{field.name} ({number})" if field else f"field {number}"
        unread = "" if field or not descriptor else "  <- not read by Fareflare"
        if isinstance(value, int):
            signed = value - (1 << 64) if value >= 1 << 63 else value
            print(f"{pad}{label}: {signed}{unread}")
        elif wire != 2:
            print(f"{pad}{label}: 0x{value.hex()}{unread}")
        elif field is not None and field.message_type is not None:
            print(f"{pad}{label}:")
            show(value, field.message_type, depth + 1)
        elif (text := _text(value)) is not None:
            print(f"{pad}{label}: {text!r}{unread}")
            if field is None and (inner := _base64_message(text)) is not None:
                show(inner, None, depth + 1)
        else:
            try:
                fields(value)
            except ValueError:
                print(f"{pad}{label}: 0x{value.hex()}{unread}")
            else:
                print(f"{pad}{label}:{unread}")
                show(value, None, depth + 1)


def token(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def refusal(exc: ValueError) -> str:
    """The refusal as people see it, plus its finer cause where the exception names one."""
    named = [
        f"{name}={getattr(exc, name)}"
        for name in ("reason", "check", "code")
        if getattr(exc, name, None)
    ]
    return f"{type(exc).__name__}: {exc}" + (f" [{', '.join(named)}]" if named else "")


def main(argument: str) -> int:
    path = Path(argument)
    url = argument
    if not argument.startswith("http") and path.is_file():
        raw = path.read_text().strip()
        url = json.loads(raw)["url"] if raw.startswith("{") else raw
    parts = urlsplit(url)
    print(f"{parts.scheme}://{parts.netloc}{parts.path}")
    params = parse_qsl(parts.query, keep_blank_values=True)
    for name, value in params:
        print(f"  {name} = {value if name not in ('tfs', 'tfu') else f'<{len(value)} chars>'}")
    for name, value in params:
        if name in ("tfs", "tfu"):
            print(f"{name}:")
            try:
                show(token(value), SearchMessage.DESCRIPTOR if name == "tfs" else None)
            except (ValueError, binascii.Error) as exc:
                print(f"  cannot decode: {exc}")
    try:
        target = import_link(url, allow_search=True)
    except ValueError as exc:
        print("importer: refused,", refusal(exc))
        return 1
    flights = " / ".join(
        segment["date"]
        + " "
        + " ".join(
            f"{leg['origin']}-{leg['destination']} {leg['airline'] or ''}{leg['number'] or ''}"
            for leg in segment["legs"]
        )
        for segment in target["segments"]
    )
    print(f"importer: accepted {target.get('kind', 'itinerary')} {target['id'][:8]}: {flights}")
    print(
        f"  adults={target['adults']} cabin={target['cabin']} currency={target['currency']} "
        f"market={target['market']} url params={sorted(target['provider_query'])}"
    )
    try:
        supported_target(target)
    except ValueError as exc:
        print("collector: cannot price it,", refusal(exc))
        return 1
    print("collector: can price it")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
