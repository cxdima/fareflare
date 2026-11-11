"""A software passkey: real P-256 keys and signed WebAuthn responses, for tests."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

ONE_PASSWORD = bytes.fromhex("bada5566a7aa401fbd9645619a55120d")
_UP, _UV, _BE, _BS, _AT = 0x01, 0x04, 0x08, 0x10, 0x40


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class SoftPasskey:
    def __init__(self, origin: str, rp_id: str, aaguid: bytes = ONE_PASSWORD):
        self.origin, self.rp_id, self.aaguid = origin, rp_id, aaguid
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.user_handle: str | None = None
        self.sign_count = 0

    def _public_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,  # EC2
                3: -7,  # ES256
                -1: 1,  # P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin or self.origin}
        ).encode()

    def create(self, options: dict, origin: str | None = None, verified: bool = True) -> dict:
        self.user_handle = options["user"]["id"]
        flags = _UP | _AT | _BE | _BS | (_UV if verified else 0)
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([flags])
            + struct.pack(">I", self.sign_count)
            + self.aaguid
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._public_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(
                    self._client_data("webauthn.create", options["challenge"], origin)
                ),
                "attestationObject": b64(attestation),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    def get(self, options: dict, origin: str | None = None, verified: bool = True) -> dict:
        flags = _UP | _BE | _BS | (_UV if verified else 0)
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([flags])
            + struct.pack(">I", self.sign_count)
        )
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(auth_data),
                "signature": b64(signature),
                "userHandle": self.user_handle,
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }
