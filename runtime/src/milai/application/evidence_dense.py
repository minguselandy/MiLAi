"""Versioned, bounded embedding projection for lossless Raw Evidence turns."""

from __future__ import annotations

from milai.adapters import ProjectionIdentity

EVIDENCE_TURN_EMBEDDING_INPUT_VERSION = "evidence-turn-utf8-prefix-32768-v1"
_MAX_EMBEDDING_BYTES = 32_768


def evidence_turn_embedding_text(content: str) -> str:
    """Bound only the derived embedding input; never mutate stored Evidence."""

    encoded = content.encode("utf-8")
    if len(encoded) <= _MAX_EMBEDDING_BYTES:
        return content
    return encoded[:_MAX_EMBEDDING_BYTES].decode("utf-8", errors="ignore")


def evidence_turn_projection_version(identity: ProjectionIdentity) -> str:
    return f"{identity.key}:{EVIDENCE_TURN_EMBEDDING_INPUT_VERSION}"


__all__ = [
    "EVIDENCE_TURN_EMBEDDING_INPUT_VERSION",
    "evidence_turn_embedding_text",
    "evidence_turn_projection_version",
]
