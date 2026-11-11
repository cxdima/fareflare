"""Passkeys (WebAuthn): add one while signed in, then sign in with it alone.

Every passkey is discoverable and requires user verification, so signing in with
one proves both possession and the person (a fingerprint, face or device PIN). It
therefore stands in for the password and any second step together.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from fareflare.store import Conflict, Document, Store

CHALLENGE_SECONDS = 300
MAX_PASSKEYS = 10
# Names for well-known passkey providers, so the list says "1Password", not a UUID.
# Source: the community-maintained passkey AAGUID list (passkeydeveloper/passkey-authenticator-aaguids).
PROVIDERS = {
    "bada5566-a7aa-401f-bd96-45619a55120d": "1Password",
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "iCloud Keychain",
    "dd4ec289-e01d-41c9-bb89-70fa845d4bf2": "iCloud Keychain",
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome on Mac",
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden",
    "531126d6-e717-415c-9320-3d9aa6981239": "Dashlane",
    "b84e4048-15dc-4dd0-8640-f4f60813c8af": "NordPass",
    "0ea242b4-43c4-4a1b-8b17-dd6d0b6baec6": "Keeper",
    "f3809540-7f14-49c1-a8b3-8f813b225541": "Enpass",
    "53414d53-554e-4700-0000-000000000000": "Samsung Pass",
}


class PasskeyRejected(ValueError):
    """A passkey ceremony failed; the message never says which check failed."""


def _key(credential_id: bytes) -> str:
    return "passkey:" + hashlib.sha256(credential_id).hexdigest()


def provider_name(aaguid: str) -> str:
    return PROVIDERS.get(aaguid, "Passkey")


class Passkeys:
    def __init__(
        self,
        store: Store,
        public_url: str,
        product_name: str,
        clock: Callable[[], float] = time.time,
    ):
        self.store, self.clock, self.product_name = store, clock, product_name
        self.origin = public_url.rstrip("/")
        self.rp_id = urlsplit(self.origin).hostname or "localhost"

    def _now(self) -> int:
        return int(self.clock())

    def _challenge(self, purpose: str, tenant: str | None) -> tuple[str, bytes]:
        identifier, challenge = secrets.token_urlsafe(24), secrets.token_bytes(32)
        expires = self._now() + CHALLENGE_SECONDS
        self.store.commit(
            [
                Document(
                    "webauthn-challenge:" + identifier,
                    "webauthn_challenges",
                    {
                        "purpose": purpose,
                        "tenant": tenant,
                        "challenge": bytes_to_base64url(challenge),
                        "expires_at": expires,
                        "used": False,
                    },
                    expires_at=expires,
                )
            ]
        )
        return identifier, challenge

    def _consume(self, identifier: object, purpose: str, tenant: str | None) -> bytes:
        """A challenge works once, for its own purpose and account, within five minutes."""
        if not isinstance(identifier, str) or not 16 <= len(identifier) <= 64:
            raise PasskeyRejected("This passkey request expired. Try again.")
        document = self.store.get("webauthn-challenge:" + identifier)
        if (
            not document
            or document.data["used"]
            or document.data["purpose"] != purpose
            or document.data["tenant"] != tenant
            or document.data["expires_at"] <= self._now()
        ):
            raise PasskeyRejected("This passkey request expired. Try again.")
        try:
            self.store.commit([document.update({**document.data, "used": True})])
        except Conflict:
            raise PasskeyRejected("This passkey request expired. Try again.") from None
        return base64url_to_bytes(document.data["challenge"])

    # Adding a passkey, while signed in.

    def registration_options(self, account: Document) -> tuple[dict, str | None]:
        """Options for navigator.credentials.create(), and a new user handle if the
        account has none yet (the caller saves it with the account)."""
        user_handle = account.data.get("webauthn_user_id")
        new_handle = None
        if not user_handle:
            user_handle = new_handle = bytes_to_base64url(secrets.token_bytes(32))
        identifier, challenge = self._challenge("register", account.data["id"])
        existing = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(item["credential_id"]))
            for item in self.list(account)
        ]
        options = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=self.product_name,
            user_name=account.data.get("email") or account.data["username"],
            user_id=base64url_to_bytes(user_handle),
            challenge=challenge,
            timeout=CHALLENGE_SECONDS * 1000,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                require_resident_key=True,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=existing,
        )
        return {
            "challenge_id": identifier,
            "options": json.loads(options_to_json(options)),
        }, new_handle

    def register(
        self, account: Document, challenge_id: object, credential: object, name: object
    ) -> tuple[Document, Document]:
        """Verify a new passkey. Returns the passkey and the account, both to be committed."""
        tenant = account.data["id"]
        challenge = self._consume(challenge_id, "register", tenant)
        if len(account.data.get("passkey_ids", [])) >= MAX_PASSKEYS:
            raise ValueError(f"You can keep up to {MAX_PASSKEYS} passkeys. Remove one first.")
        if not isinstance(credential, dict):
            raise PasskeyRejected("The passkey could not be added. Try again.")
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origin,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, KeyError, TypeError):
            raise PasskeyRejected("The passkey could not be added. Try again.") from None
        key = _key(verified.credential_id)
        if self.store.get(key):
            raise PasskeyRejected("This passkey is already added.")
        label = (
            name.strip()
            if isinstance(name, str) and name.strip()
            else provider_name(verified.aaguid)
        )
        if len(label) > 60 or any(ord(character) < 32 for character in label):
            raise ValueError("Use a name of up to 60 characters")
        transports = [
            value
            for value in (credential.get("response", {}) or {}).get("transports", []) or []
            if value in {item.value for item in AuthenticatorTransport}
        ]
        passkey = Document(
            key,
            "passkeys:" + tenant,
            {
                "tenant": tenant,
                "credential_id": bytes_to_base64url(verified.credential_id),
                "public_key": bytes_to_base64url(verified.credential_public_key),
                "sign_count": verified.sign_count,
                "aaguid": verified.aaguid,
                "name": label,
                "transports": transports,
                "backed_up": verified.credential_backed_up,
                "created_at": self._now(),
                "last_used_at": None,
                "removed": False,
            },
            due=self._now(),
        )
        updated = account.update(
            {**account.data, "passkey_ids": [*account.data.get("passkey_ids", []), key]}
        )
        return passkey, updated

    def list(self, account: Document) -> list[dict]:
        items = []
        for key in account.data.get("passkey_ids", []):
            document = self.store.get(key)
            if (
                document
                and not document.data["removed"]
                and document.data["tenant"] == account.data["id"]
            ):
                items.append(self._public(document))
        return items

    @staticmethod
    def _public(document: Document) -> dict:
        data = document.data
        return {
            "id": document.key.removeprefix("passkey:"),
            "credential_id": data["credential_id"],
            "name": data["name"],
            "provider": provider_name(data["aaguid"]),
            "synced": bool(data.get("backed_up")),
            "created_at": data["created_at"],
            "last_used_at": data.get("last_used_at"),
        }

    def _owned(self, account: Document, identifier: object) -> Document:
        if not isinstance(identifier, str) or len(identifier) != 64:
            raise ValueError("Passkey not found")
        key = "passkey:" + identifier
        document = self.store.get(key)
        if (
            not document
            or document.data["removed"]
            or document.data["tenant"] != account.data["id"]
            or key not in account.data.get("passkey_ids", [])
        ):
            raise ValueError("Passkey not found")
        return document

    def rename(self, account: Document, identifier: object, name: object) -> dict:
        document = self._owned(account, identifier)
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 60
            or any(ord(character) < 32 for character in name)
        ):
            raise ValueError("Use a name of up to 60 characters")
        updated = document.update({**document.data, "name": name.strip()})
        self.store.commit([updated])
        return self._public(updated)

    def remove(self, account: Document, identifier: object) -> tuple[Document, Document]:
        document = self._owned(account, identifier)
        return document.update({**document.data, "removed": True}), account.update(
            {
                **account.data,
                "passkey_ids": [key for key in account.data["passkey_ids"] if key != document.key],
            }
        )

    # Signing in with a passkey.

    def authentication_options(self) -> dict:
        identifier, challenge = self._challenge("login", None)
        options = generate_authentication_options(
            rp_id=self.rp_id,
            challenge=challenge,
            timeout=CHALLENGE_SECONDS * 1000,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return {"challenge_id": identifier, "options": json.loads(options_to_json(options))}

    def authenticate(
        self,
        challenge_id: object,
        credential: object,
        account_for: Callable[[str], Document | None],
    ) -> tuple[Document, Document]:
        """Verify a sign-in. Returns the account and the passkey with its new use recorded."""
        challenge = self._consume(challenge_id, "login", None)
        rejected = PasskeyRejected("That passkey is not recognized. Try another sign-in method.")
        if not isinstance(credential, dict) or not isinstance(credential.get("rawId"), str):
            raise rejected
        try:
            raw_id = base64url_to_bytes(credential["rawId"])
        except (ValueError, TypeError):
            raise rejected from None
        document = self.store.get(_key(raw_id))
        if not document or document.data["removed"]:
            raise rejected
        account = account_for(document.data["tenant"])
        if account is None or document.key not in account.data.get("passkey_ids", []):
            raise rejected
        handle = (credential.get("response") or {}).get("userHandle")
        if handle and handle != account.data.get("webauthn_user_id"):
            raise rejected
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origin,
                credential_public_key=base64url_to_bytes(document.data["public_key"]),
                credential_current_sign_count=document.data["sign_count"],
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, KeyError, TypeError):
            raise rejected from None
        used = document.update(
            {
                **document.data,
                "sign_count": verified.new_sign_count,
                "backed_up": verified.credential_backed_up,
                "last_used_at": self._now(),
            }
        )
        return account, used
