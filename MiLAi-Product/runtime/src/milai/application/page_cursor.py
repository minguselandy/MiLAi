"""Signed page positions bound to the current caller and query, never authority."""

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class PageCursor:
    def __init__(self, secret: str, namespace: str) -> None:
        self._key = hashlib.sha256(namespace.encode() + b":" + secret.encode()).digest()

    def decode(self, token: str | None, binding: object) -> dict[str, Any]:
        if token is None:
            return {}
        try:
            encoded, signature = token.split(".")
            expected = hmac.new(self._key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            payload = json.loads(base64.urlsafe_b64decode(encoded))
            if (payload["binding"] != hashlib.sha256(canonical_json(binding)).hexdigest()
                    or payload["expires"] < time.time()):
                raise ValueError("binding or expiry")
            return dict(payload)
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("invalid page cursor") from exc

    def encode(self, binding: object, position: dict[str, Any]) -> str:
        encoded = base64.urlsafe_b64encode(canonical_json({
            **position, "binding": hashlib.sha256(canonical_json(binding)).hexdigest(),
            "expires": position.get("expires", time.time() + 3600),
        })).decode()
        return encoded + "." + hmac.new(self._key, encoded.encode(), hashlib.sha256).hexdigest()
