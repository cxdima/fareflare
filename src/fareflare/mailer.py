"""Account email: password resets and address confirmation.

Production sends through Amazon SES. Local development writes each message to a
private file instead, so a reset link can be opened without any mail provider.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    html: str


class Mailer(Protocol):
    def send(self, message: Message) -> None: ...


class SesMailer:
    def __init__(self, sender: str, region: str = "us-east-1", client=None):
        if not sender or "@" not in sender:
            raise ValueError("Configure FAREFLARE_EMAIL_FROM with a sending address")
        if client is None:
            import boto3

            client = boto3.client("sesv2", region_name=region)
        self.sender, self.client = sender, client

    def send(self, message: Message) -> None:
        self.client.send_email(
            FromEmailAddress=self.sender,
            Destination={"ToAddresses": [message.to]},
            Content={
                "Simple": {
                    "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": message.text, "Charset": "UTF-8"},
                        "Html": {"Data": message.html, "Charset": "UTF-8"},
                    },
                }
            },
        )


class FileMailer:
    """Writes each message to ``<directory>/<n>.eml`` (mode 0600) for local use."""

    def __init__(self, directory: Path, sender: str = "Fareflare <no-reply@localhost>"):
        self.directory, self.sender = Path(directory), sender

    def send(self, message: Message) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        email = EmailMessage()
        email["From"], email["To"], email["Subject"] = self.sender, message.to, message.subject
        # 8-bit parts keep each link on one readable line in the file.
        email.set_content(message.text, cte="8bit")
        email.add_alternative(message.html, subtype="html", cte="8bit")
        # Time first so a directory listing reads in order; random so two at once never clash.
        path = self.directory / f"{time.time_ns()}-{secrets.token_hex(4)}.eml"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(email.as_string())
        # Local development only: say where the link went, as `make serve` has no inbox.
        print(f"Email to {message.to} written to {path}", flush=True)  # noqa: T201


class MemoryMailer:
    """Keeps messages in a list; used by tests."""

    def __init__(self):
        self.sent: list[Message] = []

    def send(self, message: Message) -> None:
        self.sent.append(message)


def mailer_from_env(environ: Mapping[str, str] | None = None) -> Mailer | None:
    values = os.environ if environ is None else environ
    kind = values.get("FAREFLARE_EMAIL", "").lower()
    if kind == "ses":
        return SesMailer(
            values.get("FAREFLARE_EMAIL_FROM", ""), region=values.get("AWS_REGION", "us-east-1")
        )
    if kind == "file":
        return FileMailer(Path(values.get("FAREFLARE_EMAIL_DIRECTORY", ".fareflare/outbox")))
    if kind in ("", "off"):
        return None
    raise ValueError("FAREFLARE_EMAIL must be ses, file or off")


def _render(product: str, heading: str, lines: list[str], action: str, link: str, after: str):
    text = "\n\n".join([heading, *lines, f"{action}: {link}", after, f"— {product}"])
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;font-size:16px;line-height:1.5;color:#4a465c">{escape(line)}</p>'
        for line in lines
    )
    html = (
        '<!doctype html><html><body style="margin:0;background:#f3f2ee;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif\">"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f3f2ee;padding:32px 16px"><tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:520px;background:#ffffff;border-radius:24px;padding:36px">'
        f'<tr><td><p style="margin:0 0 28px;font-weight:800;letter-spacing:-0.02em;'
        f'font-size:15px;color:#17141f;text-transform:uppercase">{escape(product)}</p>'
        f'<h1 style="margin:0 0 16px;font-size:28px;line-height:1.1;letter-spacing:-0.03em;'
        f'color:#17141f">{escape(heading)}</h1>{paragraphs}'
        f'<p style="margin:28px 0"><a href="{escape(link, quote=True)}" '
        'style="display:inline-block;padding:14px 26px;border-radius:999px;background:#17141f;'
        f'color:#ffffff;font-weight:700;text-decoration:none">{escape(action)}</a></p>'
        f'<p style="margin:0;font-size:14px;line-height:1.5;color:#5f5a76">{escape(after)}</p>'
        f'<p style="margin:20px 0 0;font-size:12px;line-height:1.5;color:#5f5a76;'
        f'word-break:break-all">{escape(link)}</p>'
        "</td></tr></table></td></tr></table></body></html>"
    )
    return text, html


def password_reset(product: str, to: str, link: str, minutes: int) -> Message:
    text, html = _render(
        product,
        "Reset your password",
        [
            f"Someone asked to reset the password for your {product} account.",
            f"The link works once and for {minutes} minutes.",
        ],
        "Choose a new password",
        link,
        "If you did not ask for this, ignore this email: your password stays the same.",
    )
    return Message(to, f"Reset your {product} password", text, html)


def security_notice(product: str, to: str, heading: str, lines: list[str], link: str) -> Message:
    text, html = _render(
        product,
        heading,
        lines,
        "Review your security settings",
        link,
        "You get this email for every change to how your account signs in.",
    )
    return Message(to, f"{heading} · {product}", text, html)


def email_confirmation(product: str, to: str, link: str) -> Message:
    text, html = _render(
        product,
        "Confirm your email",
        [
            f"Confirm this address to reset your {product} password by email if you ever need to.",
            "The link works for 24 hours.",
        ],
        "Confirm email",
        link,
        f"If you did not create a {product} account, ignore this email.",
    )
    return Message(to, f"Confirm your email for {product}", text, html)
