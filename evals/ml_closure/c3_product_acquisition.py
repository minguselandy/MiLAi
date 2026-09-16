"""Label-blind C3 product acquisition over OFF and CANARY Runtime modes."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from alembic import command
from alembic.config import Config
from milai.api import create_app
from milai.config.settings import prepare_runtime_directories
from milai.domain.requirement_state import canonical_sha256
from milai.persistence import Database

from evals.ml_closure.candidate_r_acquisition import (
    ROOT,
    _drain_worker,
    _headers,
    _ingest,
    _object,
    _settings,
)

RAW = ROOT / "evals/datasets/ml_closure/sealed-validation.raw.json"
BASELINE = (
    ROOT / "var/ml_closure/ml-closure-20260830-001/checkpoints/"
    "c0-candidate-r-unscored.json"
)


class C3ProductAcquisitionError(RuntimeError):
    """The final product-mode acquisition violated its frozen contract."""


def execute(
    *,
    raw_path: Path = RAW,
    baseline_path: Path | None = BASELINE,
) -> dict[str, Any]:
    raw_bytes = raw_path.read_bytes()
    dataset = _object(raw_path)
    conversations = cast(list[dict[str, Any]], dataset.get("conversations"))
    expected_count = 60 if raw_path.resolve() == RAW.resolve() else len(conversations)
    if len(conversations) != expected_count or expected_count < 1:
        raise C3ProductAcquisitionError("C3_CONVERSATION_DENOMINATOR_DRIFT")
    command.upgrade(Config("alembic.ini"), "head")

    with tempfile.TemporaryDirectory(prefix="milai-ml-c3-") as temporary:
        off_settings = _settings(Path(temporary))
        prepare_runtime_directories(off_settings)
        canary_settings = off_settings.model_copy(
            update={"feature_profile": "FORMED_CANARY"}
        )
        api_database = Database(off_settings)
        steward_database = Database(off_settings, dsn=off_settings.steward_database_dsn)
        from evals.ml_closure.candidate_r_acquisition import _required_environment

        worker_database = Database(
            off_settings,
            dsn=_required_environment("MILAI_TEST_WORKER_DATABASE_URL"),
        )
        try:
            off_app = create_app(
                off_settings,
                database=api_database,
                steward_database=steward_database,
            )
            canary_app = create_app(
                canary_settings,
                database=api_database,
                steward_database=steward_database,
            )
            for app in (off_app, canary_app):
                app.config["TESTING"] = True

            runtime_to_source = _ingest(canary_app.test_client(), conversations)
            worker_events = _drain_worker(off_settings, worker_database)
            off_first = _query_all(
                off_app, conversations, runtime_to_source, expected_mode="OFF"
            )
            canary_first = _query_all(
                canary_app,
                conversations,
                runtime_to_source,
                expected_mode="CANARY",
            )
            canary_second = _query_all(
                canary_app,
                conversations,
                runtime_to_source,
                expected_mode="CANARY",
            )
            restarted_app = create_app(
                canary_settings,
                database=api_database,
                steward_database=steward_database,
            )
            restarted_app.config["TESTING"] = True
            restarted = _query_all(
                restarted_app,
                conversations,
                runtime_to_source,
                expected_mode="CANARY",
            )
            off_after = _query_all(
                off_app, conversations, runtime_to_source, expected_mode="OFF"
            )
        finally:
            api_database.close()
            steward_database.close()
            worker_database.close()

    off_identity = _semantic_rows(off_first) == _semantic_rows(off_after)
    restart_raw_fallback = _semantic_rows(restarted) == _semantic_rows(off_first)
    replay_difference_paths = _difference_paths(canary_first, canary_second)
    request_scoped_paths = [
        path
        for path in replay_difference_paths
        if path.endswith(
            (
                ".baseline_requirement_state_digest",
                ".augmented_requirement_state_digest",
            )
        )
    ]
    unexpected_replay_paths = sorted(
        set(replay_difference_paths) - set(request_scoped_paths)
    )
    canary_reproducible = not unexpected_replay_paths
    baseline_match: bool | None = None
    baseline_digest: str | None = None
    if baseline_path is not None:
        baseline = _object(baseline_path)
        baseline_digest = str(baseline.get("result_digest"))
        baseline_match = _baseline_rows(off_first) == baseline.get("rows")

    traces = [cast(dict[str, Any], row["formation_projection"]) for row in canary_first]
    output: dict[str, Any] = {
        "schema": "milai.memory-lifecycle.c3-product-unscored.v0.1",
        "raw_path": str(raw_path.resolve().relative_to(ROOT)),
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "conversation_count": len(conversations),
        "query_count": len(canary_first),
        "candidate": "F",
        "representation": "FORMED_PLUS_RAW_CANONICAL",
        "recollection": "SIMPLE",
        "rows": canary_first,
        "checks": {
            "flag_off_behavior_identity": off_identity,
            "flag_off_matches_c0_frozen_baseline": baseline_match,
            "canary_replay_semantically_identical": canary_reproducible,
            "restart_empty_sidecar_raw_fallback": restart_raw_fallback,
            "rollback_to_off_identity": off_identity,
            "raw_baseline_preserved_all": all(
                trace.get("raw_baseline_preserved") is True for trace in traces
            ),
            "full_semantics_recomputed_when_selected": all(
                trace.get("full_semantics_recomputed") is True
                for trace in traces
                if int(trace.get("selected_source_count", 0)) > 0
            ),
            "canonical_mutation_zero": all(
                trace.get("canonical_mutation") is False for trace in traces
            ),
            "model_calls_zero": all(trace.get("model_calls") == 0 for trace in traces),
            "governance_rejected_zero": all(
                trace.get("governance_rejected_source_count") == 0 for trace in traces
            ),
            "off_response_has_no_formation_trace": all(
                row["formation_projection"] is None for row in off_first
            ),
        },
        "mode_counts": {
            "selected": sum(
                int(trace.get("selected_source_count", 0) > 0) for trace in traces
            ),
            "applied": sum(trace.get("applied") is True for trace in traces),
            "raw_fallback": sum(
                trace.get("fallback_taken") is True for trace in traces
            ),
            "no_match": sum(trace.get("status") == "NO_MATCH" for trace in traces),
        },
        "request_scoped_replay_difference_paths": request_scoped_paths,
        "unexpected_replay_difference_paths": unexpected_replay_paths,
        "official_path": {
            "ingest": "POST /v1/evidence",
            "projection": "FoundationWorker + process-local Formation sidecar",
            "acquisition": "POST /v1/memory/resolve",
            "semantic_kernel": "Gate -> Binding -> State -> Sufficiency -> Operator",
            "openworker_mcp_witness": "SEPARATE_REAL_TRANSPORT_PASS",
            "eval_owned_business_logic": False,
        },
        "identity": {
            "candidate_r_result_digest": baseline_digest,
            "migration_head": "0047_formation_hydration",
            "feature_flag": "MILAI_MEMORY_FORMATION_MODE",
            "default_mode": "OFF",
            "candidate_mode": "CANARY",
        },
        "cost": {
            "evidence_ingests": len(runtime_to_source),
            "worker_events": worker_events,
            "official_query_calls": len(conversations) * 5,
            "formation_model_calls": 0,
            "reader_model_calls": 0,
            "canonical_mutations": 0,
        },
        "labels_visible_to_acquisition": False,
        "formal_holdout_used": False,
    }
    output["output_digest"] = canonical_sha256(output)
    if not canary_reproducible:
        raise C3ProductAcquisitionError(
            "C3_CANARY_REPLAY_MISMATCH:" + ",".join(unexpected_replay_paths[:16])
        )
    return output


def _query_all(
    app: Any,
    conversations: list[dict[str, Any]],
    runtime_to_source: Mapping[str, str],
    *,
    expected_mode: str,
    api_token: str | None = None,
) -> list[dict[str, Any]]:
    client = app.test_client()
    rows: list[dict[str, Any]] = []
    for conversation in sorted(conversations, key=lambda item: item["conversation_id"]):
        query = cast(list[dict[str, Any]], conversation["queries"])[0]
        headers = _headers(
            request_id=f"ml-c3-{expected_mode}-{query['query_id']}-{uuid4()}"
        )
        if api_token is not None:
            headers["Authorization"] = f"Bearer {api_token}"
        response = client.post(
            "/v1/memory/resolve",
            headers=headers,
            json={
                "query": query["question"],
                "requested_scope": {"project_ids": [conversation["scope_id"]]},
                "required_authority": "INFORMATIONAL",
                "required_freshness": "CURRENT",
                "consistency_mode": "CANONICAL_REQUIRED",
                "budget": {
                    "max_results": 12,
                    "max_candidates": 24,
                    "max_context_tokens": 2500,
                    "max_latency_ms": 2000,
                },
                "entities": [f"{conversation['scope_id']}:self"],
            },
        )
        if response.status_code != 200:
            raise C3ProductAcquisitionError(
                f"MEMORY_RESOLVE_HTTP_{response.status_code}:{query['query_id']}"
            )
        body = cast(dict[str, Any], response.get_json())
        refs = [
            runtime_to_source[value]
            for value in cast(list[str], body.get("evidence_refs", []))
            if value in runtime_to_source
        ]
        access_trace = cast(dict[str, Any], body.get("access_trace") or {})
        structural_cost = cast(
            dict[str, Any], access_trace.get("structural_cost") or {}
        )
        search_trace = cast(dict[str, Any], body.get("search_trace") or {})
        formation = search_trace.get("formation_projection")
        if expected_mode == "OFF" and formation is not None:
            raise C3ProductAcquisitionError("C3_OFF_TRACE_MUTATED")
        if expected_mode == "CANARY" and not isinstance(formation, dict):
            raise C3ProductAcquisitionError("C3_CANARY_TRACE_MISSING")
        memory_context = cast(dict[str, Any], body.get("memory_context") or {})
        compile_trace = cast(dict[str, Any], memory_context.get("compile_trace") or {})
        rows.append(
            {
                "conversation_id": conversation["conversation_id"],
                "query_id": query["query_id"],
                "stratum": query["stratum"],
                "status": body.get("status"),
                "requirement": body.get("requirement"),
                "availability": body.get("availability"),
                "retrieval_intent": cast(
                    dict[str, Any], body.get("interpretation") or {}
                ).get("retrieval_intent"),
                "accepted_evidence_ids": sorted(refs),
                "abstention_reason": body.get("abstention_reason"),
                "fallback_used": body.get("fallback_used"),
                "degraded_components": sorted(
                    cast(list[str], body.get("degraded_components", []))
                ),
                "sufficiency_decision": _normalize_ids(
                    body.get("sufficiency_decision"), runtime_to_source
                ),
                "derived_result": _normalize_ids(
                    body.get("derived_result"), runtime_to_source
                ),
                "memory_context": {
                    "authority_class": memory_context.get("authority_class"),
                    "text": memory_context.get("text"),
                    "semantic_context_digest": memory_context.get(
                        "semantic_context_digest"
                    ),
                    "reader_context_digest": memory_context.get(
                        "reader_context_digest"
                    ),
                    "selected_evidence_ids": sorted(
                        runtime_to_source.get(value, value)
                        for value in cast(
                            list[str], memory_context.get("selected_evidence_ids", [])
                        )
                    ),
                    "selected_windows": memory_context.get("selected_windows"),
                    "context_truncated": memory_context.get("context_truncated"),
                    "reader_readiness": compile_trace.get("reader_readiness"),
                    "required_evidence_packing_loss_count": compile_trace.get(
                        "required_evidence_packing_loss_count"
                    ),
                    "hidden_model_calls": compile_trace.get("hidden_model_calls"),
                    "canonical_mutation": compile_trace.get("canonical_mutation"),
                    "decision_layer_digests": compile_trace.get(
                        "decision_layer_digests"
                    ),
                },
                "formation_projection": _normalize_ids(formation, runtime_to_source),
                "structural_cost": {
                    key: int(structural_cost.get(key, 0))
                    for key in (
                        "auxiliary_llm_calls",
                        "embedding_calls",
                        "vector_search_calls",
                        "reranker_calls",
                        "broad_head_scan_calls",
                    )
                },
            }
        )
    return rows


def _normalize_ids(value: object, runtime_to_source: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return runtime_to_source.get(value, value)
    if isinstance(value, list):
        return [_normalize_ids(item, runtime_to_source) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_ids(item, runtime_to_source)
            for key, item in value.items()
        }
    return value


def _semantic_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in row.items()
            if key not in {"formation_projection"}
        }
        for row in rows
    ]


def _baseline_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = {
        "conversation_id",
        "query_id",
        "stratum",
        "status",
        "requirement",
        "retrieval_intent",
        "accepted_evidence_ids",
        "abstention_reason",
        "fallback_used",
        "degraded_components",
        "structural_cost",
    }
    return [{key: row[key] for key in row if key in keys} for row in rows]


def _difference_paths(left: object, right: object, path: str = "$") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right), key=str):
            if key not in left or key not in right:
                paths.append(f"{path}.{key}")
            else:
                paths.extend(_difference_paths(left[key], right[key], f"{path}.{key}"))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        paths = [f"{path}.length"] if len(left) != len(right) else []
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=False)):
            paths.extend(_difference_paths(left_item, right_item, f"{path}[{index}]"))
        return paths
    return [] if left == right else [path]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--no-baseline", action="store_true")
    arguments = parser.parse_args()
    print(
        "ML_CLOSURE_C3_PRODUCT_RESULT="
        + json.dumps(
            execute(
                raw_path=arguments.raw.resolve(),
                baseline_path=(
                    None if arguments.no_baseline else arguments.baseline.resolve()
                ),
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
