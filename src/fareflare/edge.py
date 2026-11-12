"""The visitor's address, whether or not CloudFront is in front.

With the CDN on, API Gateway's source address is a CloudFront edge, so per-address
limits would put every visitor of one edge in the same bucket. CloudFront names the
visitor in ``CloudFront-Viewer-Address``, but anyone can send that header straight to
the origin, so it is believed only with the secret CloudFront adds to every request it
forwards (``X-Fareflare-Edge``, from ``FAREFLARE_EDGE_SECRET``). Without both, the
address is API Gateway's own record of who connected.
"""

from __future__ import annotations

import hmac
import ipaddress
import os

from starlette.requests import HTTPConnection


def edge_secret() -> str:
    return os.environ.get("FAREFLARE_EDGE_SECRET", "")


def client_address(request: HTTPConnection, secret: str | None = None) -> str:
    connected = request.client.host if request.client else "unknown"
    secret = edge_secret() if secret is None else secret
    supplied = request.headers.get("x-fareflare-edge", "")
    if len(secret) < 32 or not hmac.compare_digest(supplied.encode(), secret.encode()):
        return connected
    # "192.0.2.4:46532" or "2001:db8::1:46532": the port follows the last colon.
    viewer, _, port = request.headers.get("cloudfront-viewer-address", "").rpartition(":")
    if not port.isdigit():
        return connected
    try:
        return str(ipaddress.ip_address(viewer.strip("[]")))
    except ValueError:
        return connected
