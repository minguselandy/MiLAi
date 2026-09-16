from __future__ import annotations

import ast
from pathlib import Path

import pytest
from evals.dg24.contracts import InputOnlyCaseManifestV01, run_synthetic_matrix
from evals.dg24.freeze import build_audit_cap_registry
from evals.dg24.product import _repository_semantics
from milai.domain.retrieval_audit import (
    ProductRetrievalTraceV01,
    RetrievalAuditReason,
    canonical_sha256,
    semantic_sha256,
)
from milai.observability.retrieval_audit import (
    ProductRetrievalAuditObserver,
    RepositoryCallObservation,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def test_dg24_canonical_digest_is_key_order_stable() -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256(
        {"a": 1, "b": 2}
    )


def test_dg24_behavior_digest_excludes_characterization_not_policy() -> None:
    baseline = {
        "candidate": "e-1",
        "latency_ms": 1.0,
        "created_at": "2026-08-29T00:00:00Z",
        "stage": {"total_ms": 2.0},
    }
    characterized = {
        "candidate": "e-1",
        "latency_ms": 99.0,
        "created_at": "2026-08-30T00:00:00Z",
        "stage": {"total_ms": 200.0},
    }
    assert semantic_sha256(baseline) == semantic_sha256(characterized)
    assert semantic_sha256({"search_deadline_ms": 100}) != semantic_sha256(
        {"search_deadline_ms": 200}
    )


def test_dg24_input_only_manifest_rejects_order_drift_and_extra_fields() -> None:
    request = {
        "case_id": "case-a",
        "request_payload_digest": "0" * 64,
        "query_text": "where",
        "source_snapshot_ref": "snapshot-a",
        "tenant_scope_digest": "1" * 64,
    }
    with pytest.raises(ValidationError):
        InputOnlyCaseManifestV01.model_validate(
            {
                "schema_version": "input-only-case-manifest-v0.1",
                "case_order": ["case-b"],
                "requests": [request],
                "forbidden_fields_absent": {"gold_label": True},
            }
        )
    with pytest.raises(ValidationError):
        InputOnlyCaseManifestV01.model_validate(
            {
                "schema_version": "input-only-case-manifest-v0.1",
                "case_order": ["case-a"],
                "requests": [{**request, "expected_answer": "forbidden"}],
                "forbidden_fields_absent": {"gold_label": True},
            }
        )


def test_dg24_product_trace_rejects_gold_before_other_validation() -> None:
    with pytest.raises(ValidationError, match="gold fields are forbidden"):
        ProductRetrievalTraceV01.model_validate({"expected_answer": "forbidden"})


def test_dg24_reason_registry_rejects_free_text_primary_reason() -> None:
    with pytest.raises(ValueError):
        RetrievalAuditReason("looks approximately wrong")


def test_dg24_synthetic_matrix_covers_rediscovery_and_reason_families() -> None:
    report = run_synthetic_matrix()
    records = {item["case_id"]: item for item in report["records"]}

    assert report["hard_gate"]["passed"] is True
    assert len(records) >= 16
    assert records["drop-then-rediscovery"][
        "first_irrecoverable_loss_stage"
    ] is None
    assert records["dedup-loses-answer-span"][
        "first_irrecoverable_loss_stage"
    ] == "S21"


def test_dg24_runtime_has_no_scorer_only_imports() -> None:
    forbidden = ("evals.dg24.gold_registry", "evals.dg24.proof_registry", "evals.dg24.scorer")
    findings: list[str] = []
    for path in sorted((ROOT / "runtime/src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                findings.extend(
                    alias.name
                    for alias in node.names
                    if alias.name.startswith(forbidden)
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith(forbidden)
            ):
                findings.append(node.module)
    assert findings == []


def test_dg24_repository_call_set_gate_is_not_trace_payload_identity() -> None:
    baseline = ProductRetrievalAuditObserver(enabled=False)
    traced = ProductRetrievalAuditObserver(enabled=True)
    baseline.repository_calls.append(
        RepositoryCallObservation(
            ordinal=1,
            method="record_trace",
            input_digest="b" * 64,
            query_digest=None,
            query_summary=None,
            limit=None,
            output_items=(),
            output_digest="a" * 64,
        )
    )
    traced.repository_calls.append(
        RepositoryCallObservation(
            ordinal=1,
            method="record_trace",
            input_digest="c" * 64,
            query_digest=None,
            query_summary=None,
            limit=None,
            output_items=(),
            output_digest="a" * 64,
        )
    )

    assert _repository_semantics(baseline) == _repository_semantics(traced)


def test_dg24_audit_caps_respect_each_official_repository_ceiling() -> None:
    registry = build_audit_cap_registry()
    channels = registry["channels"]

    assert channels["FTS_RAW"]["m_audit"] == 64
    assert channels["EVIDENCE_DENSE"]["verified_official_ceiling"] == 30
    assert channels["EVIDENCE_DENSE"]["m_audit"] == 30
    assert channels["SOURCE_OBSERVED_RANGE_SCAN"]["m_audit"] == 64
