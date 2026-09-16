"""Label-blind Candidate R acquisition through the public runtime API."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from milai.adapters import DeterministicHashEmbedding, LocalContentAddressedBlobStore
from milai.api import create_app
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.domain.requirement_state import canonical_sha256
from milai.persistence import Database
from milai.persistence.projection_repository import ProjectionRepository
from milai.workers.main import FoundationWorker
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "evals/datasets/ml_closure/sealed-validation.raw.json"
TENANT_ID = UUID("22222222-2222-4222-8222-222222222222")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
API_TOKEN = "ml-closure-r-api-token-with-at-least-32-characters"
CAUSAL_SECRET = "ml-closure-r-causal-secret-with-at-least-32-characters"


class CandidateRAcquisitionError(RuntimeError):
    """The frozen raw input or official product acquisition diverged."""


def execute() -> dict[str, Any]:
    raw_bytes = RAW.read_bytes()
    dataset = _object(RAW)
    conversations = cast(list[dict[str, Any]], dataset.get("conversations"))
    if len(conversations) != 60:
        raise CandidateRAcquisitionError("CANDIDATE_R_CONVERSATION_DENOMINATOR_DRIFT")
    command.upgrade(Config("alembic.ini"), "head")
    with tempfile.TemporaryDirectory(prefix="milai-ml-r-") as temporary:
        settings = _settings(Path(temporary))
        prepare_runtime_directories(settings)
        api_database = Database(settings)
        steward_database = Database(settings, dsn=settings.steward_database_dsn)
        worker_database = Database(
            settings, dsn=_required_environment("MILAI_TEST_WORKER_DATABASE_URL")
        )
        try:
            app = create_app(
                settings,
                database=api_database,
                steward_database=steward_database,
            )
            app.config["TESTING"] = True
            client = app.test_client()
            runtime_to_source = _ingest(client, conversations)
            worker_events = _drain_worker(settings, worker_database)
            first = _query_all(app, conversations, runtime_to_source)
            second = _query_all(app, conversations, runtime_to_source)
        finally:
            api_database.close()
            steward_database.close()
            worker_database.close()

    reproducible = first == second
    output: dict[str, Any] = {
        "schema": "milai.ml-closure.candidate-r-unscored.v0.1",
        "arm": "R",
        "representation": "RAW_PLUS_CANONICAL",
        "recollection": "SIMPLE",
        "raw_path": str(RAW.relative_to(ROOT)),
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "conversation_count": len(conversations),
        "query_count": len(first),
        "rows": first,
        "baseline_replay_semantically_identical": reproducible,
        "official_path": {
            "ingest": "POST /v1/evidence",
            "projection": "FoundationWorker",
            "acquisition": "POST /v1/memory/resolve",
            "eval_owned_retrieval": False,
            "product_and_eval_acquisition_identical": True,
        },
        "ceilings": {
            "max_results": 12,
            "max_candidates": 24,
            "max_context_tokens": 2500,
            "max_latency_ms": 2000,
            "official_actions_per_query": 1,
            "hydrated_evidence_units": 12,
            "model_calls": 0,
            "reader_calls": 0,
        },
        "cost": {
            "evidence_ingests": len(runtime_to_source),
            "worker_events": worker_events,
            "official_query_calls": len(first) * 2,
            "model_calls": 0,
            "reader_calls": 0,
            "canonical_mutations": 0,
        },
        "formal_holdout_used": False,
        "labels_visible_to_acquisition": False,
    }
    output["output_digest"] = canonical_sha256(output)
    if not reproducible:
        raise CandidateRAcquisitionError("CANDIDATE_R_REPLAY_MISMATCH")
    return output


def _settings(blob_root: Path) -> RuntimeSettings:
    return RuntimeSettings(
        database_url=SecretStr(_required_environment("MILAI_TEST_API_DATABASE_URL")),
        steward_database_url=SecretStr(
            _required_environment("MILAI_TEST_STEWARD_DATABASE_URL")
        ),
        blob_root=blob_root / "blobs",
        tenant_id=TENANT_ID,
        local_actor_id=ACTOR_ID,
        api_token=SecretStr(API_TOKEN),
        causal_token_secret=SecretStr(CAUSAL_SECRET),
        worker_event_limit=10_000,
        worker_retry_delay_seconds=0,
        worker_max_attempts=1,
        retrieval_evidence_dense_enabled=False,
        retrieval_deterministic_recovery_enabled=False,
        retrieval_type_directed_acquisition_enabled=False,
        retrieval_reranker_provider="none",
    )


def _ingest(client: Any, conversations: list[dict[str, Any]]) -> dict[str, str]:
    runtime_to_source: dict[str, str] = {}
    for conversation in sorted(conversations, key=lambda item: item["conversation_id"]):
        turns = cast(list[dict[str, Any]], conversation["turns"])
        session_positions: dict[str, list[int]] = {}
        for index, turn in enumerate(turns):
            session_positions.setdefault(str(turn["session_id"]), []).append(index)
        for index, turn in enumerate(turns):
            positions = session_positions[str(turn["session_id"])]
            ordinal = positions.index(index)
            response = client.post(
                "/v1/evidence",
                headers=_headers(f"ml-r-ingest-{conversation['conversation_id']}-{index}"),
                json={
                    "source_type": "RUNTIME_OBSERVATION",
                    "source_ref": turn["source_ref"],
                    "subject_id": f"{conversation['scope_id']}:self",
                    "speaker": turn["speaker"],
                    "source_context": {
                        "session_id": turn["session_id"],
                        "turn_id": turn["evidence_id"],
                        "turn_ordinal": ordinal,
                        "round_id": f"{turn['session_id']}:round-{ordinal // 2}",
                        "round_ordinal": ordinal // 2,
                        "previous_turn_id": (
                            turns[positions[ordinal - 1]]["evidence_id"]
                            if ordinal > 0
                            else None
                        ),
                        "next_turn_id": (
                            turns[positions[ordinal + 1]]["evidence_id"]
                            if ordinal + 1 < len(positions)
                            else None
                        ),
                    },
                    "observed_at": turn["observed_at"],
                    "content": turn["content"],
                    "media_type": "text/plain; charset=utf-8",
                    "permission_snapshot": {
                        **cast(dict[str, Any], turn["permission_snapshot"]),
                        "project_ids": [conversation["scope_id"]],
                    },
                    "retention_state": turn["retention_state"],
                },
            )
            if response.status_code != 201:
                raise CandidateRAcquisitionError(
                    f"EVIDENCE_INGEST_HTTP_{response.status_code}:"
                    f"{conversation['conversation_id']}:{index}"
                )
            runtime_to_source[str(response.get_json()["evidence_id"])] = str(
                turn["evidence_id"]
            )
    return runtime_to_source


def _drain_worker(settings: RuntimeSettings, database: Database) -> int:
    worker = FoundationWorker(
        settings,
        database,
        repository=ProjectionRepository(database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(),
        worker_id="ml-closure-candidate-r",
    )
    processed = 0
    while True:
        batch = worker.run_once()
        processed += batch
        if batch == 0:
            return processed


def _query_all(
    app: Any,
    conversations: list[dict[str, Any]],
    runtime_to_source: Mapping[str, str],
) -> list[dict[str, Any]]:
    client = app.test_client()
    rows: list[dict[str, Any]] = []
    for conversation in sorted(conversations, key=lambda item: item["conversation_id"]):
        query = cast(list[dict[str, Any]], conversation["queries"])[0]
        response = client.post(
            "/v1/memory/resolve",
            headers=_headers(request_id=f"ml-r-{query['query_id']}-{uuid4()}"),
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
            raise CandidateRAcquisitionError(
                f"MEMORY_RESOLVE_HTTP_{response.status_code}:{query['query_id']}"
            )
        body = cast(dict[str, Any], response.get_json())
        refs = [
            runtime_to_source[value]
            for value in cast(list[str], body.get("evidence_refs", []))
            if value in runtime_to_source
        ]
        access_trace = cast(dict[str, Any], body.get("access_trace") or {})
        structural_cost = cast(dict[str, Any], access_trace.get("structural_cost") or {})
        rows.append(
            {
                "conversation_id": conversation["conversation_id"],
                "query_id": query["query_id"],
                "stratum": query["stratum"],
                "status": body.get("status"),
                "requirement": body.get("requirement"),
                "retrieval_intent": cast(
                    dict[str, Any], body.get("interpretation") or {}
                ).get("retrieval_intent"),
                "accepted_evidence_ids": sorted(refs),
                "abstention_reason": body.get("abstention_reason"),
                "fallback_used": body.get("fallback_used"),
                "degraded_components": sorted(
                    cast(list[str], body.get("degraded_components", []))
                ),
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


def _headers(key: str | None = None, request_id: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {API_TOKEN}"}
    if key is not None:
        result["Idempotency-Key"] = key
    if request_id is not None:
        result["X-Request-ID"] = request_id
    return result


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CandidateRAcquisitionError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise CandidateRAcquisitionError(f"{name}_MISSING")
    return value


if __name__ == "__main__":
    print(
        "ML_CLOSURE_CANDIDATE_R_RESULT="
        + json.dumps(execute(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
