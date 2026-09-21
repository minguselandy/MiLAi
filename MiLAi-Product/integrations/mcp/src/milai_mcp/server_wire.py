"""MCP wire identity primitives."""

from __future__ import annotations

import hashlib
import json


def _wire_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
