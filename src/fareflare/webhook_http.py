"""Signed webhooks over HTTPS with public-address pinning and bounded I/O.

The transport never follows redirects, reads response bodies, or uses proxy
environment variables. Authentication follows the Standard Webhooks v1 format.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import http.client
import ipaddress
import math
import queue
import re
import secrets
import socket
import ssl
import threading
import time
from collections.abc import Mapping
from urllib.parse import quote, urlsplit, urlunsplit

_MAX_PAYLOAD = 65536
_MAX_URL = 2048
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_SIGNING_HEADERS = frozenset({"webhook-id", "webhook-timestamp", "webhook-signature"})
# Explicit transition/special ranges supplement Python's versioned is_global table.
_V4_SPECIAL = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",
        "100.64.0.0/10",
        "192.0.0.0/24",
        "192.88.99.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
_V6_UNICAST = ipaddress.ip_network("2000::/3")
_V6_SPECIAL = tuple(ipaddress.ip_network(network) for network in ("2001::/23", "2002::/16"))
# libc name resolution has no portable timeout. Hung lookups consume at most four
# daemon threads; they never hold the caller past its deadline or block shutdown.
_DNS_SLOTS = threading.BoundedSemaphore(4)


def _public_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(value)
        if (
            "%" in value
            or not address.is_global
            or address.is_multicast
            or address.is_reserved
            or address.is_loopback
            or address.is_link_local
        ):
            raise ValueError
        if isinstance(address, ipaddress.IPv4Address):
            if any(address in network for network in _V4_SPECIAL):
                raise ValueError from None
        elif address not in _V6_UNICAST or any(address in network for network in _V6_SPECIAL):
            raise ValueError
        return address
    except ValueError:
        raise ValueError("Webhook destination must use public internet addresses") from None


def normalize_webhook_url(url: str) -> str:
    """Validate syntax without network access; DNS is validated on every send."""
    try:
        if (
            not isinstance(url, str)
            or not 1 <= len(url) <= _MAX_URL
            or any(ord(character) <= 32 or ord(character) == 127 for character in url)
            or "\\" in url
            or "#" in url
        ):
            raise ValueError
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
            or parts.netloc.endswith(":")
        ):
            raise ValueError
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if not host or len(host) > 253 or "%" in host:
            raise ValueError
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or not all(_LABEL.fullmatch(label) for label in host.split(".")):
                raise ValueError from None
            # Reject ambiguous numeric address spellings (octal, dword, hex).
            if not any(character.isalpha() for character in host.split(".")[-1]):
                raise ValueError from None
        else:
            _public_address(str(literal))
            host = f"[{literal}]" if literal.version == 6 else str(literal)
        path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
        normalized = urlunsplit(("https", host, path, query, ""))
        if len(normalized) > _MAX_URL:
            raise ValueError
        return normalized
    except (ValueError, UnicodeError):
        raise ValueError("Webhook URL must be a public HTTPS URL on port 443") from None


def new_signing_secret() -> str:
    return "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def _secret_bytes(secret: str) -> bytes:
    try:
        if not isinstance(secret, str) or not secret.startswith("whsec_"):
            raise ValueError
        value = base64.b64decode(secret[6:], validate=True)
        if not 24 <= len(value) <= 64:
            raise ValueError
        return value
    except (ValueError, binascii.Error):
        raise ValueError("Invalid webhook signing secret") from None


def sign_webhook(secret: str, event_id: str, timestamp: int, payload: bytes) -> dict[str, str]:
    """Sign the exact transmitted bytes; reuse event_id across delivery retries."""
    if (
        not isinstance(event_id, str)
        or not _ID.fullmatch(event_id)
        or type(timestamp) is not int
        or not 0 <= timestamp <= 99999999999
        or not isinstance(payload, bytes)
        or len(payload) > _MAX_PAYLOAD
    ):
        raise ValueError("Invalid webhook signing input")
    signed = f"{event_id}.{timestamp}.".encode("ascii") + payload
    digest = hmac.new(_secret_bytes(secret), signed, hashlib.sha256).digest()
    return {
        "webhook-id": event_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": "v1," + base64.b64encode(digest).decode("ascii"),
    }


def verify_webhook(
    secret: str,
    payload: bytes,
    headers: Mapping[str, str],
    *,
    now: int | None = None,
    tolerance: int = 300,
) -> bool:
    """Authenticate bytes and time; receivers must also deduplicate webhook-id."""
    try:
        if type(tolerance) is not int or not 0 <= tolerance <= 3600:
            return False
        normalized = {key.lower(): value for key, value in headers.items()}
        timestamp_text = normalized["webhook-timestamp"]
        if not re.fullmatch(r"0|[1-9][0-9]{0,10}", timestamp_text):
            return False
        timestamp = int(timestamp_text)
        if abs((int(time.time()) if now is None else now) - timestamp) > tolerance:
            return False
        expected = sign_webhook(secret, normalized["webhook-id"], timestamp, payload)[
            "webhook-signature"
        ]
        signatures = normalized["webhook-signature"]
        if not isinstance(signatures, str) or len(signatures) > 1024 or not signatures.isascii():
            return False
        return any(hmac.compare_digest(expected, candidate) for candidate in signatures.split())
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def _resolve_addresses(host: str, timeout: float) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return (str(_public_address(str(literal))),)

    slots = _DNS_SLOTS
    if timeout <= 0 or not slots.acquire(blocking=False):
        raise TimeoutError("Webhook DNS unavailable")
    results: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            records = socket.getaddrinfo(
                host + ".", 443, socket.AF_UNSPEC, socket.SOCK_STREAM, socket.IPPROTO_TCP
            )
            results.put((True, records))
        except OSError:
            results.put((False, None))
        finally:
            slots.release()

    thread = threading.Thread(target=resolve, name="webhook-dns", daemon=True)
    try:
        thread.start()
    except RuntimeError:
        slots.release()
        raise OSError("Webhook DNS unavailable") from None
    try:
        success, records = results.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError("Webhook DNS timed out") from None
    if not success or not isinstance(records, list) or not records or len(records) > 64:
        raise OSError("Webhook DNS unavailable")
    addresses = []
    for family, kind, protocol, _, sockaddr in records:
        if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM:
            raise ValueError("Webhook DNS returned an unsupported address")
        if protocol != socket.IPPROTO_TCP or sockaddr[1] != 443:
            raise ValueError("Webhook DNS returned an unsupported address")
        addresses.append(str(_public_address(sockaddr[0])))
    return tuple(dict.fromkeys(addresses))


class WebhookHTTPTransport:
    """A fresh, IP-pinned HTTPS connection per attempt, with no connection pool."""

    def __init__(self, timeout: float = 10):
        if (
            not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 15
        ):
            raise ValueError("Webhook timeout must be between 0 and 15 seconds")
        self.timeout = float(timeout)
        self._context = ssl.create_default_context()
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2

    def send(self, url: str, payload: bytes, headers: dict[str, str]) -> bool:
        """Return true only for a timely 2xx; errors never reveal destination data."""
        started = time.monotonic()
        deadline = started + self.timeout
        connection = None
        current_socket: list[socket.socket] = []
        timer = None
        expired = threading.Event()

        def remaining() -> float:
            value = deadline - time.monotonic()
            if value <= 0 or expired.is_set():
                raise TimeoutError("Webhook deadline exceeded")
            return value

        def abort() -> None:
            expired.set()
            if current_socket:
                try:
                    current_socket[0].shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        try:
            normalized = normalize_webhook_url(url)
            if not isinstance(payload, bytes) or len(payload) > _MAX_PAYLOAD:
                return False
            safe_headers = {key.lower(): value for key, value in headers.items()}
            if set(safe_headers) != _SIGNING_HEADERS or any(
                not isinstance(value, str)
                or not value.isascii()
                or len(value) > 1024
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
                for value in safe_headers.values()
            ):
                return False
            parts = urlsplit(normalized)
            host = parts.hostname
            if host is None:  # normalize_webhook_url has already rejected this.
                return False
            addresses = _resolve_addresses(host, remaining())
            address = ipaddress.ip_address(addresses[0])
            family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
            raw = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            current_socket.append(raw)
            timer = threading.Timer(remaining(), abort)
            timer.daemon = True
            timer.start()
            raw.settimeout(remaining())
            # Numeric addresses are passed straight to the socket; no second DNS lookup.
            raw.connect((str(address), 443))
            secure = self._context.wrap_socket(
                raw, server_hostname=host, do_handshake_on_connect=False
            )
            current_socket[0] = secure
            secure.settimeout(remaining())
            secure.do_handshake()
            secure.settimeout(remaining())
            connection = http.client.HTTPSConnection(
                host, 443, timeout=remaining(), context=self._context
            )
            connection.sock = secure
            request_target = parts.path + ("?" + parts.query if parts.query else "")
            connection.request(
                "POST",
                request_target,
                body=payload,
                headers={
                    **safe_headers,
                    "Content-Type": "application/json",
                    "User-Agent": "Fareflare-Webhooks/1",
                    "Connection": "close",
                },
            )
            secure.settimeout(remaining())
            response = connection.getresponse()
            # http.client bounds status/header lines and header count. The body is
            # deliberately never read, regardless of declared or streamed size.
            success = 200 <= response.status < 300 and not expired.is_set()
            response.close()
            return success and time.monotonic() <= deadline
        except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
            return False
        finally:
            if timer is not None:
                timer.cancel()
            if connection is not None:
                connection.close()
            if current_socket:
                current_socket[0].close()
