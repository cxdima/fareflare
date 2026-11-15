"""Which files of the built website are public, and how they are served.

One rule set for both places the files are served from: the application (any
deployment, and the fallback for paths CloudFront does not route to S3) and the S3
bucket CloudFront reads them from (``fareflare.publish_web``).
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

# Only packaged public assets are reachable. Never source maps, dotfiles, deployment
# configuration, HTML (pages are rendered per request) or a path outside the build root.
SUFFIXES = frozenset(
    {
        ".js",
        ".css",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".avif",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".webmanifest",
    }
)

# Python 3.12's built-in type table, which is all the Lambda image has, does not know
# these; without them browsers receive application/octet-stream.
MEDIA_TYPES = {
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}

FINGERPRINT = re.compile(r"[.-](?:[A-Z0-9]{8,}|[a-f0-9]{8,})\.[^.]+$")
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "public, max-age=3600"


def public_files(root: Path) -> dict[str, Path]:
    """Every servable file under ``root``, keyed by its URL path."""
    resolved = root.resolve()
    return {
        "/" + path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
        and (path.suffix.lower() in SUFFIXES or path.name == "3rdpartylicenses.txt")
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
        and path.resolve().is_relative_to(resolved)
    }


def media_type(path: Path) -> str | None:
    suffix = path.suffix.lower()
    return MEDIA_TYPES.get(suffix) or mimetypes.guess_type(path.name)[0]


def fingerprinted(path: Path) -> bool:
    """A name that changes with its content (`main-DANLJVR4.js`) can be cached forever."""
    return bool(FINGERPRINT.search(path.name))


def cache_control(path: Path) -> str:
    return IMMUTABLE if fingerprinted(path) else REVALIDATE
