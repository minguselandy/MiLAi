"""Compatibility exports for deterministic domain serialization."""

from __future__ import annotations

from milai.domain.action_identity import canonical_json, canonical_sha256

sha256 = canonical_sha256


__all__ = ["canonical_json", "sha256"]
