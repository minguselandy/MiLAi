from __future__ import annotations

from dataclasses import dataclass

from evals.dg12.materialization_profile import (
    ReplayEmbeddingProvider,
    _worker_attribution,
    verify_environment_database,
)
from evals.dg12.stage_profile import (
    StageRecorder,
    _profile_summary,
    build_deep_anchor_profile,
)


def test_profile_summary_attributes_complete_wall_time_without_double_counting() -> (
    None
):
    recorder = StageRecorder()
    recorder.durations_ms.update(
        {
            "db_create_or_clone_ms": 10.0,
            "migration_ms": 20.0,
            "context_compile_ms": 5.0,
            "evidence_ms": 11.0,
            "proposal_ms": 12.0,
            "review_ms": 13.0,
            "fts_projection_ms": 14.0,
            "vector_projection_ms": 15.0,
        }
    )
    summary = _profile_summary(
        recorder=recorder,
        raw_trace={
            "total_runtime_ms": 90.0,
            "ingest_ms": 30.0,
            "retrieval_ms": 20.0,
            "paper_embedding_accounting": {"total_calls": 7},
            "retrieved_items": [],
        },
        wall_ms=100.0,
    )

    assert summary["attribution_ratio"] == 1.0
    assert summary["unattributed_ms"] == 0.0
    assert summary["top_level_non_overlapping"]["runtime_setup_ms"] == 5.0
    assert summary["top_level_non_overlapping"]["cleanup_ms"] == 10.0
    assert summary["nested_stage_metrics"]["embedding_logical_items"] == 7
    assert summary["nested_stage_metrics"]["fts_ms"] is None
    assert "fts_ms" in summary["unavailable_nested_metrics"]


@dataclass(frozen=True)
class _Identity:
    projection_dimensions: int = 2


def test_replay_embedding_requires_an_exact_precomputed_digest() -> None:
    import hashlib

    vector = [0.25, 0.75]
    provider = ReplayEmbeddingProvider(
        _Identity(), {hashlib.sha256(b"fragment").hexdigest(): vector}
    )

    assert provider.embed_many(["fragment"], 4) == [vector]
    assert provider.logical_hits == 1


def test_worker_attribution_keeps_nested_spans_non_overlapping() -> None:
    result = _worker_attribution(
        {
            "projection_drain_total_ms": 100.0,
            "embedding_warmup": {"duration_ms": 5.0},
            "stage_metrics": {
                "durations_ms": {
                    "purge_projection_ms": 4.0,
                    "fts_projection_ms": 30.0,
                    "vector_projection_ms": 50.0,
                    "worker_ping_ms": 1.0,
                    "projection_lease_ms": 2.0,
                    "fragment_derivation_ms": 3.0,
                    "embedding_inference_ms": 20.0,
                    "projection_write_ms": 60.0,
                    "projection_complete_ms": 4.0,
                }
            },
        }
    )

    assert result["projection_handler_total_ms"] == 84.0
    assert result["explained_projection_ms"] == 95.0
    assert result["projection_worker_unattributed_ms"] == 5.0
    assert result["explained_projection_ratio"] == 0.95
    assert result["projection_write_includes_index_maintenance"] is True


def test_materialization_database_environment_checks_every_role() -> None:
    name = "milai_eval_x"
    environment = {
        key: f"postgresql://role:secret@127.0.0.1:5432/{name}"
        for key in (
            "MILAI_DATABASE_URL",
            "MILAI_STEWARD_DATABASE_URL",
            "MILAI_WORKER_DATABASE_URL",
            "MILAI_MIGRATION_DATABASE_URL",
            "MILAI_AUDIT_DATABASE_URL",
        )
    }

    assert verify_environment_database(environment, name)
    environment["MILAI_WORKER_DATABASE_URL"] = environment[
        "MILAI_WORKER_DATABASE_URL"
    ].replace(name, "other")
    assert not verify_environment_database(environment, name)


def test_deep_anchor_profile_is_payload_free_and_non_overlapping() -> None:
    source = {
        "schema": "milai.dg12.eh02-persistent-product.v1",
        "status": "PASS",
        "records": [
            {
                "case_id": "private-case-one",
                "context": "private context must not escape",
                "ordinal": 1,
                "reuse_equivalent": True,
                "equivalence": {"context": True, "top_k": True},
                "reuse_retrieval_ms": 20.0,
                "reuse_product_usage": {
                    "stage_metrics": {
                        "counts": {
                            "fts_ms": 1,
                            "query_total_ms": 1,
                            "reranker_ms": 1,
                        },
                        "durations_ms": {
                            "fts_ms": 3.0,
                            "query_total_ms": 15.0,
                            "reranker_ms": 10.0,
                        },
                    }
                },
            },
            {
                "case_id": "private-case-two",
                "context": "another private context",
                "ordinal": 2,
                "reuse_equivalent": True,
                "equivalence": {"context": True, "top_k": True},
                "reuse_retrieval_ms": 30.0,
                "reuse_product_usage": {
                    "stage_metrics": {
                        "counts": {
                            "fts_ms": 1,
                            "query_total_ms": 1,
                            "recent_canonical_ms": 1,
                            "reranker_ms": 1,
                        },
                        "durations_ms": {
                            "fts_ms": 4.0,
                            "query_total_ms": 25.0,
                            "recent_canonical_ms": 5.0,
                            "reranker_ms": 12.0,
                        },
                    }
                },
            },
        ],
    }

    profile = build_deep_anchor_profile(source)

    assert profile["non_overlapping_accounting"] == {
        "outer_retrieval_ms": 50.0,
        "runtime_sibling_stage_ms": 34.0,
        "runtime_uninstrumented_ms": 6.0,
        "openworker_mcp_adapter_residual_ms": 10.0,
        "explained_ms": 50.0,
        "explained_ratio": 1.0,
        "runtime_nested_span_ratio": 0.85,
        "outer_residual_method": "outer_retrieval_ms - Runtime query_total_ms",
    }
    assert (
        profile["named_stage_distributions"]["recent_canonical_ms"]["total_ms"] == 5.0
    )
    rendered = __import__("json").dumps(profile)
    assert "private context" not in rendered
    assert "private-case-one" not in rendered
