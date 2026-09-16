from __future__ import annotations

import math

import pytest

from milai.adapters import ProjectionIdentity, project_embedding_vector
from milai.application.evidence_dense import (
    EVIDENCE_TURN_EMBEDDING_INPUT_VERSION,
    evidence_turn_embedding_text,
    evidence_turn_projection_version,
)


def test_a6_embedding_projection_bounds_bytes_without_mutating_source() -> None:
    source = "界" * 20_000
    projected = evidence_turn_embedding_text(source)

    assert source == "界" * 20_000
    assert len(projected.encode("utf-8")) <= 32_768
    assert source.startswith(projected)
    assert projected.encode("utf-8").decode("utf-8") == projected


def test_a6_evidence_projection_identity_binds_model_and_input_version() -> None:
    identity = ProjectionIdentity(
        provider="fixture",
        model_id="fixture-128",
        source_dimensions=128,
        projection_dimensions=128,
        normalization="l2",
        code_version="projection-128/v1",
    )

    assert evidence_turn_projection_version(identity) == (
        f"{identity.key}:{EVIDENCE_TURN_EMBEDDING_INPUT_VERSION}"
    )


def test_a6_public_projection_matches_persisted_vector_contract() -> None:
    identity = ProjectionIdentity(
        provider="fixture",
        model_id="fixture-1024",
        source_dimensions=1024,
        projection_dimensions=128,
        normalization="source-l2+signed-projection-l2",
        code_version="projection-128/v1",
    )
    source = [float(index % 17 - 8) for index in range(1024)]

    projected = project_embedding_vector(source, identity)

    assert len(projected) == 128
    assert math.sqrt(sum(value * value for value in projected)) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="source dimension"):
        project_embedding_vector(source[:-1], identity)
