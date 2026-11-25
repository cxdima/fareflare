"""Check the API image through the Lambda runtime emulator before it is pushed.

No AWS access: the table is never created, so pages that need it are not checked
here (``GET /v1/status`` is covered by the smoke check after the release).

    .venv/bin/python scripts/release/verify_api.py fareflare-api:<sha>

Starts the image on 127.0.0.1:9000, checks pages, files, content types, security
headers, the public configuration and the warm-up ping, then removes the container.
The last line is ``FAILURES: none`` or the failed checks; exits 1 on any failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request

URL = "http://127.0.0.1:9000/2015-03-31/functions/function/invocations"
CONTAINER = "fareflare-verify-api"
ENVIRONMENT = {
    "FAREFLARE_PUBLIC_URL": "https://fareflare.dev",
    "FAREFLARE_TABLE": "gfpt-next-verify",  # Needs the fareflare-/gfpt-next- prefix.
    "AWS_ACCESS_KEY_ID": "dummy",
    "AWS_SECRET_ACCESS_KEY": "dummy",
    "AWS_DEFAULT_REGION": "us-east-1",
    "FAREFLARE_EMAIL": "ses",
    "FAREFLARE_EMAIL_FROM": "Fareflare <no-reply@fareflare.dev>",
}
# Path, status, content type. The host is fareflare.dev: localhost gets 400.
PAGES = [
    ("/", 200, "text/html"),
    ("/v1/config", 200, "application/json"),
    ("/login", 200, "text/html"),
    ("/register", 200, "text/html"),
    ("/app", 200, "text/html"),
    ("/assets/social.jpg", 200, "image/jpeg"),
    ("/assets/art/paper-plane.webp", 200, "image/webp"),
    ("/forgot-password", 200, "text/html"),
    ("/reset-password", 200, "text/html"),
    ("/.well-known/passkey-endpoints", 200, "application/json"),
    ("/.well-known/change-password", 302, ""),
    ("/privacy", 200, "text/html"),
    ("/status", 200, "text/html"),
    ("/v1/account", 401, "application/json"),
    ("/v1/admin/gate", 401, "application/json"),
    ("/v1/admin/overview", 401, "application/json"),
    ("/llms.txt", 200, "text/markdown"),
    ("/.well-known/security.txt", 200, "text/plain"),
    ("/favicon.ico", 200, "image/x-icon"),
    ("/apple-touch-icon.png", 200, "image/png"),
    ("/site.webmanifest", 200, "application/manifest+json"),
]
HSTS = "max-age=31536000; includeSubDomains"
failures: list[str] = []


def post(payload: dict) -> dict:
    request = urllib.request.Request(URL, data=json.dumps(payload).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def invoke(path: str) -> dict:
    return post(
        {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": path,
            "rawQueryString": "",
            "headers": {"host": "fareflare.dev", "accept": "*/*", "user-agent": "image-verify"},
            "requestContext": {
                "accountId": "000000000000",
                "apiId": "verify",
                "domainName": "fareflare.dev",
                "http": {
                    "method": "GET",
                    "path": path,
                    "protocol": "HTTP/1.1",
                    "sourceIp": "127.0.0.1",
                    "userAgent": "image-verify",
                },
                "requestId": "verify",
                "routeKey": "$default",
                "stage": "$default",
                "time": "10/Nov/2026:00:00:00 +0000",
                "timeEpoch": int(time.time() * 1000),
            },
            "isBase64Encoded": False,
        }
    )


def check(label: str, ok: bool, detail: object = "") -> None:
    print(("ok   " if ok else "FAIL ") + label + (f" {detail}" if detail != "" else ""))
    if not ok:
        failures.append(label)


def verify() -> None:
    for _ in range(40):
        try:
            invoke("/v1/config")
            break
        except OSError:
            time.sleep(0.5)
    else:
        check("the emulator answers", False)
        return
    for path, status, kind in PAGES:
        result = invoke(path)
        headers = {key.lower(): value for key, value in result.get("headers", {}).items()}
        content = headers.get("content-type", "")
        body = result.get("body", "")
        note = body[:90] if content.startswith("application/json") else headers.get("location", "")
        check(
            f"GET {path}",
            result.get("statusCode") == status and content.startswith(kind),
            f"{result.get('statusCode')} {content} {len(body)}b {note}".rstrip(),
        )
    config = json.loads(invoke("/v1/config")["body"])
    check(
        "config: open sign-up with email",
        config.get("email_enabled") is True and config.get("registration_mode") == "open",
        f"email_enabled={config.get('email_enabled')} mode={config.get('registration_mode')}",
    )
    for path in ("/", "/login", "/v1/config", "/no-such-page"):
        headers = {k.lower(): v for k, v in invoke(path).get("headers", {}).items()}
        check(
            f"nosniff and HSTS on {path}",
            headers.get("x-content-type-options") == "nosniff"
            and headers.get("strict-transport-security") == HSTS,
        )
    warm = post({"fareflare": "warm-up"})
    check("warm-up ping", warm == {"warm": True}, warm)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("image", help="the API image to check, such as fareflare-api:<sha>")
    image = parser.parse_args().image
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
    command = ["docker", "run", "-d", "--name", CONTAINER, "--platform", "linux/arm64"]
    command += ["-p", "9000:8080"]
    for key, value in ENVIRONMENT.items():
        command += ["-e", f"{key}={value}"]
    subprocess.run([*command, image], capture_output=True, check=True)
    try:
        verify()
    finally:
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
    print("FAILURES:", " ".join(failures) or "none")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
