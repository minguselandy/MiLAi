from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from uuid import UUID


class CausalTokenError(ValueError):
    """A causal token is malformed, forged, or belongs to another tenant."""


@dataclass(frozen=True, slots=True)
class CausalPosition:
    tenant_id: UUID
    minimum_outbox_sequence: int


class CausalTokenCodec:
    """Issue tenant-bound, opaque HMAC tokens for an Outbox position."""

    VERSION = 1

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("causal token secret must contain at least 32 characters")
        self._key = hashlib.sha256(b"milai-causal-token-v1\x00" + secret.encode("utf-8")).digest()

    def issue(self, tenant_id: UUID, minimum_outbox_sequence: int) -> str:
        if minimum_outbox_sequence < 1:
            raise ValueError("minimum_outbox_sequence must be positive")
        payload = json.dumps(
            {
                "minimum_outbox_sequence": minimum_outbox_sequence,
                "tenant_id": str(tenant_id),
                "version": self.VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        encoded = _encode(payload)
        signature = _encode(hmac.digest(self._key, encoded.encode("ascii"), "sha256"))
        return f"{encoded}.{signature}"

    def decode(self, token: str, expected_tenant_id: UUID) -> CausalPosition:
        encoded, separator, supplied_signature = token.partition(".")
        if separator != "." or not encoded or not supplied_signature or len(token) > 512:
            raise CausalTokenError("invalid causal token")
        expected_signature = _encode(hmac.digest(self._key, encoded.encode("ascii"), "sha256"))
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise CausalTokenError("invalid causal token")
        try:
            value = json.loads(_decode(encoded))
            if not isinstance(value, dict) or set(value) != {
                "minimum_outbox_sequence",
                "tenant_id",
                "version",
            }:
                raise ValueError
            tenant_id = UUID(str(value["tenant_id"]))
            sequence = value["minimum_outbox_sequence"]
            if (
                value["version"] != self.VERSION
                or isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence < 1
            ):
                raise ValueError
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CausalTokenError("invalid causal token") from exc
        if tenant_id != expected_tenant_id:
            raise CausalTokenError("causal token tenant mismatch")
        return CausalPosition(tenant_id, sequence)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)
