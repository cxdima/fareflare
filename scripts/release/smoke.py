"""Post-release smoke test against the live site with a throwaway account that is deleted.

The throwaway address is on the SES mailbox simulator, so any mail the release sends
to it is accepted without touching a real inbox or the sending reputation. It takes
about two minutes (it waits out the sign-up limit once). The last line is
``FAILURES: none`` or the failed checks; exits 1 on any failure.

    .venv/bin/python scripts/release/smoke.py > .fareflare/release-<sha>/smoke.log

When a release changes what a check expects, change the check in the same commit.
"""

import argparse
import base64
import hashlib
import hmac
import http.cookiejar
import json
import secrets
import struct
import sys
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
parser.add_argument("--base", default="https://fareflare.dev", help="the site to check")
BASE = parser.parse_args().base.rstrip("/")
jar = http.cookiejar.CookieJar()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)
failures = []


def call(method, path, body=None, csrf=None):
    headers = {"User-Agent": "release-smoke-check", "Origin": BASE}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        response = opener.open(request, timeout=40)
    except urllib.error.HTTPError as error:
        response = error
    raw = response.read()
    kind = response.headers.get("content-type", "")
    parsed = json.loads(raw) if kind.startswith("application/json") and raw else None
    return response.status, response.headers, parsed, raw


def expect(label, condition, detail=""):
    print(("ok   " if condition else "FAIL ") + label + (" " + str(detail) if detail else ""))
    if not condition:
        failures.append(label)


def totp(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return str((struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**6).zfill(6)


for path, kind in [
    ("/", "text/html"),
    ("/login", "text/html"),
    ("/register", "text/html"),
    ("/forgot-password", "text/html"),
    ("/reset-password", "text/html"),
    ("/recover", "text/html"),
    ("/app", "text/html"),
    ("/privacy", "text/html"),
    ("/guides", "text/html"),
    ("/status", "text/html"),
    ("/assets/social.jpg", "image/jpeg"),
    ("/assets/art/paper-plane.webp", "image/webp"),
    ("/robots.txt", "text/plain"),
]:
    status, headers, _, raw = call("GET", path)
    expect(
        f"GET {path}",
        status == 200 and headers.get("content-type", "").startswith(kind),
        f"{status} {headers.get('content-type')} {len(raw)}b",
    )

status, headers, _, raw = call("GET", "/privacy")
expect(
    "privacy page describes account email and passkeys",
    b"emails you only to confirm" in raw and b"Passkeys are stored" in raw,
)
status, headers, config, _ = call("GET", "/v1/config")
expect(
    "config: open sign-up with email",
    status == 200 and config["registration_mode"] == "open" and config.get("email_enabled") is True,
    config,
)
expect(
    "config: the shortest check interval is ten minutes",
    config["limits"]["min_interval_seconds"] == 600,
    config.get("limits"),
)
status, _, content, _ = call("GET", "/site-content.json")
guides = json.dumps(content) if status == 200 else ""
expect(
    "guides state the ten-minute interval and the fixed 15-minute retry",
    "interval of 10 minutes" in guides
    and "tried again 15 minutes later" in guides
    and "backoff" not in guides,
    status,
)
status, headers, _, _ = call("GET", "/.well-known/change-password")
expect(
    "change-password redirect",
    status == 302 and headers.get("location") == "/app#settings?section=security",
    headers.get("location"),
)
status, _, body, _ = call("GET", "/.well-known/passkey-endpoints")
expect(
    "passkey endpoints for password managers",
    status == 200 and body.get("enroll", "").startswith(BASE + "/app"),
    body,
)
status, _, body, _ = call("GET", "/v1/account")
expect("signed-out account read is refused", status == 401, status)
status, _, body, _ = call("POST", "/auth/passkey/options", {})
rp = (body or {}).get("options", {}).get("rpId")
expect(
    "passkey sign-in options name fareflare.dev",
    status == 200 and rp == "fareflare.dev" and body.get("challenge_id"),
    f"{status} {rp}",
)

address = f"success+release-{secrets.token_hex(5)}@simulator.amazonses.com"
first, second = secrets.token_urlsafe(24), secrets.token_urlsafe(6)[:8]
status, _, body, _ = call("POST", "/auth/register", {"email": "not an address", "password": first})
expect(
    "a bad address is refused plainly",
    status == 422 and "Enter an email address" in str(body),
    f"{status} {body}",
)
status, _, body, _ = call("POST", "/auth/register", {"username": address, "password": first})
expect("the old sign-up shape is refused", status == 422, status)
status, _, body, _ = call("POST", "/auth/register", {"email": address, "password": "Password123!"})
expect(
    "a common password is refused", status == 422 and "most common" in str(body), f"{status} {body}"
)
status, _, body, _ = call("POST", "/auth/register", {"email": address, "password": "7-chars"})
expect(
    "a 7-character password is refused with the new rule",
    status == 422 and "8–128 characters" in str(body),
    f"{status} {body}",
)
time.sleep(61)  # Three refused sign-ups used this minute's per-address allowance.
status, _, created, _ = call("POST", "/auth/register", {"email": address, "password": first})
expect(
    "sign up with an email address",
    status == 201
    and created["account"]["email"] == address
    and created["account"]["email_verified"] is False,
    f"{status} {created}",
)
if status != 201:
    sys.exit(1)
csrf = created["csrf_token"]
expect("sign-up gives no recovery codes", "recovery_code" not in created)
password = first
try:
    status, _, body, _ = call("GET", "/v1/account")
    expect("session cookie works", status == 200 and body["account"]["email"] == address, status)
    status, _, body, _ = call("GET", "/v1/monitors?limit=100")
    expect("flights list", status == 200 and body["items"] == [], status)
    status, _, body, _ = call("GET", "/v1/telegram")
    expect("telegram status", status == 200 and "connected" in body, body)
    status, _, body, _ = call("GET", "/v1/preferences/telegram-templates")
    expect(
        "message styles are compact, detailed and custom, compact by default",
        status == 200
        and [item["value"] for item in body["styles"]] == ["compact", "detailed", "custom"]
        and body["default_style"] == "compact",
        status,
    )
    status, _, body, _ = call("POST", "/v1/preferences/telegram-preview?message=new_low", {}, csrf)
    expect(
        "a new account's alert is three lines with a $ price",
        status == 200
        and body["text"].startswith("\U0001f525 New low \u00b7 $191 (was $199)")
        and "USD" not in body["text"]
        and len(body["lines"]) == 3,
        f"{status} {body.get('text') if body else ''}",
    )
    status, _, body, _ = call(
        "POST", "/v1/preferences/telegram-preview?message=flight_list", {}, csrf
    )
    expect(
        "the flight list is one line per flight with the low marked",
        status == 200
        and "at the low" in body["text"]
        and "(low $219)" in body["text"]
        and len(body["lines"]) == 4,
        f"{status} {body.get('text') if body else ''}",
    )
    status, _, body, _ = call("GET", "/v1/preferences/telegram-templates")
    expect(
        "the catalog names the switches, previews and samples",
        status == 200
        and len(body["switches"]) == 4
        and [item["value"] for item in body["samples"]]
        == ["one_way", "round_trip", "untimed", "late"]
        and body["previews"][-1]["value"] == "flight_list",
        status,
    )
    status, _, body, _ = call(
        "POST",
        "/v1/preferences/telegram-preview?message=flight_list",
        {"telegram_list_order": "price"},
        csrf,
    )
    lines = body["text"].split("\n") if status == 200 else []
    expect(
        "a list ordered by price starts with the cheapest flight",
        status == 200 and len(lines) == 4 and "UA 414" in lines[1] and "at the low" in lines[1],
        f"{status} {lines}",
    )
    status, _, body, _ = call(
        "POST", "/v1/preferences/telegram-preview?sample=round_trip", {}, csrf
    )
    expect(
        "the round-trip sample is priced for two and shows the return",
        status == 200
        and "$382 for 2 adults" in body["text"]
        and "\u21a9" in body["text"]
        and len(body["lines"]) == 4
        and body["hints"] == [],
        f"{status} {body.get('text') if body else ''}",
    )
    status, _, body, _ = call("POST", "/v1/preferences/telegram-preview?sample=late", {}, csrf)
    expect(
        "a late alert says when its price was checked",
        status == 200 and body["text"].split("\n")[-1].startswith("Checked "),
        f"{status} {body.get('text') if body else ''}",
    )
    status, _, body, _ = call(
        "POST",
        "/v1/preferences/telegram-preview",
        {
            "telegram_style": "custom",
            "telegram_templates": {"new_low": "{weekday} {days_until} {stops} {cabin}"},
        },
        csrf,
    )
    expect(
        "wording without the price or the flight is rendered and remarked on",
        status == 200
        and body["text"].endswith("in 112 days Nonstop Economy")
        and len(body["hints"]) == 2,
        f"{status} {body}",
    )
    status, _, body, _ = call("GET", "/v1/preferences")
    expect(
        "previews saved nothing and the list order defaults to departure",
        status == 200
        and body["telegram_list_order"] == "departure"
        and body["telegram_style"] == "compact",
        f"{status} {body}",
    )
    status, _, body, _ = call("PUT", "/v1/preferences", {"telegram_style": "classic"}, csrf)
    expect("the removed style is refused", status == 422, status)
    status, _, body, _ = call("GET", "/v1/admin/gate")
    expect("an ordinary account does not see the admin panel", status == 404, status)
    status, _, body, _ = call("GET", "/v1/admin/overview")
    expect("nor its data", status == 404, status)
    status, _, body, _ = call("GET", "/v1/account/security")
    expect(
        "security summary",
        status == 200
        and body["two_factor"]["enabled"] is False
        and body["passkeys"] == []
        and body["email_enabled"] is True,
        body,
    )
    status, _, body, _ = call("POST", "/auth/email/resend", {}, csrf)
    expect("confirmation email accepted for sending", status == 202, status)
    status, _, body, _ = call("POST", "/auth/passkeys/options", {}, csrf)
    expect("adding a passkey without the password is refused", status == 422, status)
    status, _, body, _ = call("POST", "/auth/passkeys/options", {"password": first}, csrf)
    expect(
        "passkey registration options name fareflare.dev",
        status == 200 and body["options"]["rp"]["id"] == "fareflare.dev",
        status,
    )
    status, _, body, _ = call(
        "POST", "/auth/password", {"current_password": second, "new_password": second}, csrf
    )
    expect(
        "wrong current password is 403, not 401",
        status == 403 and body["detail"] == "That password is not correct",
        status,
    )
    status, _, body, _ = call(
        "POST", "/auth/password", {"current_password": first, "new_password": second}
    )
    expect("password change without CSRF is refused", status == 403, status)
    status, _, body, _ = call(
        "POST", "/auth/password", {"current_password": first, "new_password": second}, csrf
    )
    expect("password changed", status == 200 and body == {"changed": True}, status)
    password = second

    status, _, setup, _ = call("POST", "/auth/two-factor/setup", {"password": second}, csrf)
    expect(
        "two-step setup gives a secret and an otpauth link",
        status == 200 and setup["uri"].startswith("otpauth://totp/"),
        status,
    )
    step = int(time.time()) // 30
    status, _, body, _ = call(
        "POST", "/auth/two-factor/enable", {"code": totp(setup["secret"], step)}, csrf
    )
    backup = (body or {}).get("backup_codes", [])
    expect(
        "two-step sign-in turned on with backup codes",
        status == 200 and len(backup) >= 8,
        f"{status} {len(backup)}",
    )

    time.sleep(21)
    jar.clear()
    status, _, body, _ = call(
        "POST", "/auth/login", {"username": address.upper(), "password": first}
    )
    expect("old password no longer signs in", status == 401, status)
    status, headers, body, _ = call(
        "POST", "/auth/login", {"username": address.upper(), "password": second}
    )
    expect(
        "password sign-in asks for the code, without a session",
        status == 200
        and body.get("two_factor_required") is True
        and "set-cookie" not in {k.lower() for k in headers},
        body,
    )
    status, _, refused, _ = call(
        "POST",
        "/auth/login/two-factor",
        {
            "token": body["token"],
            "code": "000000"
            if totp(setup["secret"], int(time.time()) // 30) != "000000"
            else "111111",
        },
    )
    expect("a wrong code is refused", status == 401, status)
    status, _, signed, _ = call(
        "POST", "/auth/login/two-factor", {"token": body["token"], "code": backup[0]}
    )
    expect(
        "a backup code completes sign-in",
        status == 200 and signed["account"]["email"] == address,
        status,
    )
    csrf = signed["csrf_token"]
    status, _, body, _ = call("GET", "/v1/account/security")
    expect(
        "one backup code used",
        status == 200
        and body["two_factor"]["enabled"] is True
        and body["two_factor"]["backup_codes_left"] == len(backup) - 1,
        body.get("two_factor"),
    )
    status, _, body, _ = call("POST", "/auth/sign-out-everywhere", {"password": second}, csrf)
    expect(
        "sign out everywhere keeps this browser signed in",
        status == 200 and body.get("csrf_token"),
        status,
    )
    csrf = body["csrf_token"]
    status, _, body, _ = call("GET", "/v1/account")
    expect("still signed in after signing out elsewhere", status == 200, status)
finally:
    status, _, body, _ = call(
        "DELETE", "/v1/account", {"password": first if password == second else second}, csrf
    )
    expect("deleting with the wrong password is 403", status == 403, status)
    status, _, body, _ = call("DELETE", "/v1/account", {"password": password}, csrf)
    expect("throwaway account deleted", status == 200, f"{status} {body}")
    status, _, body, _ = call("GET", "/v1/account")
    expect("deleted account is signed out", status == 401, status)

print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
