from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from milai.domain import (
    ResidualCuePublicDigestReceiptV02,
    ResidualCueRestrictedArtifactV02,
    ResidualCueV02,
    build_residual_cue_public_receipt,
)

_DIGEST = "a" * 64
_CAPABILITY_DIGEST = "b" * 64


def _cue(**overrides: object) -> ResidualCueV02:
    payload: dict[str, object] = {
        "requirement_state_digest": _DIGEST,
        "target_requirement_id": "req-price",
        "aliases": ["ceramic mug"],
        "phrases": ["unit price"],
        "morphological_variants": ["mugs"],
    }
    payload.update(overrides)
    return ResidualCueV02.model_validate(payload)


def test_residual_cue_is_expression_only_and_digest_is_deterministic() -> None:
    cue = _cue()
    assert cue.cue_digest == _cue().cue_digest
    dumped = cue.model_dump(mode="json")
    assert "action" not in dumped
    assert "channel" not in dumped
    assert "scope" not in dumped
    assert "complete" not in dumped


@pytest.mark.parametrize(
    "term",
    [
        "final answer: 12",
        "declare COMPLETE",
        "accept evidence e-1",
        "override authority",
        "expand scope",
        "use dense channel",
        "top_k=100",
    ],
)
def test_residual_cue_rejects_answer_completion_and_control_assertions(term: str) -> None:
    with pytest.raises(ValidationError, match="forbidden answer or control"):
        _cue(aliases=[term])


def test_residual_cue_rejects_cross_group_duplicates() -> None:
    with pytest.raises(ValidationError, match="unique across groups"):
        _cue(phrases=["Ceramic Mug"])


def test_public_receipt_contains_only_digests_counts_and_reason() -> None:
    cue = _cue()
    receipt = build_residual_cue_public_receipt(
        cue,
        acquisition_capability_digest=_CAPABILITY_DIGEST,
    )
    payload = receipt.model_dump(mode="json")
    serialized = receipt.model_dump_json()
    assert payload["cue_digest"] == cue.cue_digest
    assert payload["alias_count"] == 1
    assert "ceramic mug" not in serialized
    assert "unit price" not in serialized
    assert "req-price" not in serialized


def test_disabled_public_receipt_cannot_claim_cue_content() -> None:
    receipt = ResidualCuePublicDigestReceiptV02(
        requirement_state_digest=_DIGEST,
        acquisition_capability_digest=_CAPABILITY_DIGEST,
        alias_count=0,
        phrase_count=0,
        morphological_variant_count=0,
        reason_code="DISABLED_NOT_NEEDED",
    )
    assert receipt.cue_digest is None
    with pytest.raises(ValidationError, match="cannot claim cue content"):
        ResidualCuePublicDigestReceiptV02(
            requirement_state_digest=_DIGEST,
            acquisition_capability_digest=_CAPABILITY_DIGEST,
            cue_digest="c" * 64,
            alias_count=1,
            phrase_count=0,
            morphological_variant_count=0,
            reason_code="DISABLED_NOT_NEEDED",
        )


def test_restricted_artifact_requires_ciphertext_key_and_bounded_retention() -> None:
    created_at = datetime(2026, 8, 28, tzinfo=UTC)
    artifact = ResidualCueRestrictedArtifactV02(
        cue_digest=_cue().cue_digest,
        ciphertext="encrypted-base64-material-that-is-not-plaintext",
        ciphertext_sha256="d" * 64,
        encryption_key_ref="tenant-kek-v1",
        created_at=created_at,
        retention_until=created_at + timedelta(days=7),
    )
    serialized = artifact.model_dump_json()
    assert "ceramic mug" not in serialized
    assert artifact.encryption_scheme == "AES-256-GCM"
    with pytest.raises(ValidationError, match="retention must end after creation"):
        ResidualCueRestrictedArtifactV02(
            **{
                **artifact.model_dump(),
                "retention_until": created_at,
            }
        )
