from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from milai.application.retrieval_audit_probe import (
    OfficialRetrievalAuditProbeExecutor,
)
from milai.domain.acquisition import AcquisitionPlan, AcquisitionProbe
from milai.domain.retrieval import QueryPlan
from milai.observability.retrieval_audit import (
    AuditRecordingRepository,
    ProductRetrievalAuditObserver,
    _channel_disposition_semantics,
    _repository_call_semantics,
)
from milai.persistence import SessionContext


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.result = [
            {
                "evidence_id": "e-1",
                "source_ref": "session-1:turn-1",
                "content_hash": "a" * 64,
                "content": "stable retrieval evidence",
                "observed_at": "2026-08-29T00:00:00+00:00",
                "relevance_score": 1.0,
            }
        ]

    def search_fts(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append((args, kwargs))
        return self.result

    def search_evidence(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append((args, kwargs))
        return self.result


class _Embedding:
    def embed(self, text: str) -> list[float]:
        raise AssertionError(f"FTS audit must not embed: {text}")


def test_dg24_repository_proxy_preserves_return_identity_and_call_shape() -> None:
    repository = _Repository()
    observer = ProductRetrievalAuditObserver(enabled=True)
    proxy = AuditRecordingRepository(repository, observer)

    result = proxy.search_fts("query", limit=8, statement_timeout_ms=200)

    assert result is repository.result
    assert repository.calls == [(("query",), {"limit": 8, "statement_timeout_ms": 200})]
    assert [item.method for item in observer.repository_calls] == ["search_fts"]


def test_dg24_repository_timeout_normalization_retains_disposition() -> None:
    first = _repository_call_semantics(
        "search_fts", {"kwargs": {"statement_timeout_ms": 100}}
    )
    second = _repository_call_semantics(
        "search_fts", {"kwargs": {"statement_timeout_ms": 900}}
    )
    exhausted = _repository_call_semantics(
        "search_fts", {"kwargs": {"statement_timeout_ms": 0}}
    )

    assert first == second
    assert first != exhausted


def test_dg24_repository_semantics_mask_wall_clock_but_not_snapshot_as_of() -> None:
    baseline_args: list[Any] = [
        "principal",
        [],
        "INFORMATIONAL",
        {},
        "2026-08-01T00:00:00+00:00",
        "ACTIVE",
        [],
        "CURRENT",
        0.0,
        "2026-08-29T01:00:00+00:00",
    ]
    traced_args = [*baseline_args]
    traced_args[9] = "2026-08-29T01:00:01+00:00"
    baseline = _repository_call_semantics(
        "gate_and_hydrate", {"args": baseline_args, "kwargs": {}}
    )
    traced = _repository_call_semantics(
        "gate_and_hydrate", {"args": traced_args, "kwargs": {}}
    )

    assert baseline == traced
    changed_snapshot = [*traced_args]
    changed_snapshot[4] = "2026-08-02T00:00:00+00:00"
    assert baseline != _repository_call_semantics(
        "gate_and_hydrate", {"args": changed_snapshot, "kwargs": {}}
    )


def test_dg24_channel_semantics_ignore_probe_identity_and_latency_only() -> None:
    baseline = SimpleNamespace(
        probe_id="wall-clock-derived-a",
        requirement_id="req-1",
        channel="FTS_RAW",
        status="EXECUTED",
        reason_code="EXECUTED",
        raw_candidate_count=3,
        selected_candidate_count=2,
        excluded_seen_candidate_count=0,
        repeated_region_count=0,
        new_region_count=2,
        latency_ms=1.0,
    )
    traced = SimpleNamespace(**vars(baseline))
    traced.probe_id = "wall-clock-derived-b"
    traced.latency_ms = 999.0

    assert _channel_disposition_semantics(baseline) == _channel_disposition_semantics(
        traced
    )
    traced.selected_candidate_count = 1
    assert _channel_disposition_semantics(baseline) != _channel_disposition_semantics(
        traced
    )


def test_dg24_official_probe_derives_cuts_and_types_above_cap_unavailable() -> None:
    repository = _Repository()
    executor = OfficialRetrievalAuditProbeExecutor(
        repository,
        cast(Any, _Embedding()),
    )
    probe = AcquisitionProbe(
        probe_id="probe-1",
        requirement_slot="req-1",
        channel="FTS_RAW",
        lexical_terms=["stable", "evidence"],
        temporal_axis="NONE",
        candidate_limit=16,
        expansion_policy="NONE",
    )
    trace = executor.execute_probe(
        run_identity="audit-run",
        product_seal_digest="b" * 64,
        request_identity="request-1",
        requirement_id="req-1",
        channel="FTS_RAW",
        probe=probe,
        query_plan=cast(QueryPlan, object()),
        acquisition_plan=cast(AcquisitionPlan, object()),
        context=SessionContext(UUID(int=1), UUID(int=2)),
        requested_scope={"namespace": "case-1"},
        as_of=datetime(2026, 8, 29, tzinfo=UTC),
        requested_audit_cap=16,
        snapshot_identity="snapshot-1",
        scope_digest="c" * 64,
        policy_digest="d" * 64,
        index_identity="index-1",
    )
    views = {item["cutoff"]: item for item in trace.offline_cut_views}

    assert len(repository.calls) == 1
    assert views[8]["status"] == "AVAILABLE"
    assert views[16]["status"] == "AVAILABLE"
    assert views[32]["status"] == "EXCEEDS_VERIFIED_OFFICIAL_AUDIT_CAP"
    assert views[64]["occurrence_ids"] == []
    assert len({item["source_wide_result_digest"] for item in views.values()}) == 1
