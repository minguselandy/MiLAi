"""One fresh-database, non-holdout lifecycle integration validation.

The fixture intentionally reuses opened integration patterns.  It is a product
closure witness, not new generalization evidence and not a formal holdout.
All memory behavior is exercised through Runtime services and public HTTP APIs;
this module owns only fixture construction and scoring.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from flask import Flask
from milai.api import create_app
from milai.application.formation_projection import FormationProjectionStore
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.domain.requirement_state import canonical_sha256
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import Database, SessionContext
from pydantic import SecretStr

from evals.ml_closure.c3_product_acquisition import (
    _query_all,
    _semantic_rows,
)
from evals.ml_closure.candidate_r_acquisition import _drain_worker
from evals.ml_closure.evolution_replay import (
    ACTOR_ID,
    API_TOKEN,
    OBSERVED_AT,
    REVIEWER_TOKEN,
    SUBMITTER_TOKEN,
    TENANT_ID,
    EvolutionReplay,
    ReplayFailure,
)
from evals.ml_closure.score_c3_product import (
    _operator_correct,
    _reader_grounding_violation,
)


class C4LifecycleFailure(RuntimeError):
    """The fresh lifecycle witness failed an explicit product invariant."""


class C4LifecycleReplay(EvolutionReplay):
    def __init__(
        self,
        *,
        canary_app: Flask,
        off_app: Flask,
        owner_dsn: str,
        settings: RuntimeSettings,
        worker_database: Database,
    ) -> None:
        super().__init__(canary_app.test_client(), owner_dsn)
        self.canary_app = canary_app
        self.off_app = off_app
        self.settings = settings
        self.worker_database = worker_database
        self.captured: dict[str, str] = {}
        self.capture_count = 0

    def execute(self) -> dict[str, Any]:
        write_started = perf_counter()
        evolution = super().execute()
        if evolution.get("status") != "PASS_C1_GOVERNED_EVOLUTION":
            raise C4LifecycleFailure("C4_EVOLUTION_REPLAY_NOT_PASS")
        deletion_replay = self._deletion_replay()
        conversations, labels = _read_fixture()
        runtime_to_source = _ingest_read_fixture(self.client, conversations)
        worker_events = _drain_worker(self.settings, self.worker_database)
        write_seconds = perf_counter() - write_started

        query_started = perf_counter()
        off_first = _query_all(
            self.off_app,
            conversations,
            runtime_to_source,
            expected_mode="OFF",
            api_token=API_TOKEN,
        )
        canary = _query_all(
            self.canary_app,
            conversations,
            runtime_to_source,
            expected_mode="CANARY",
            api_token=API_TOKEN,
        )
        off_after = _query_all(
            self.off_app,
            conversations,
            runtime_to_source,
            expected_mode="OFF",
            api_token=API_TOKEN,
        )
        restarted_app = create_app(
            self.settings,
            database=self.canary_app.extensions["milai.database"],
            steward_database=self.canary_app.extensions["milai.steward_database"],
        )
        restarted_app.config["TESTING"] = True
        restarted = _query_all(
            restarted_app,
            conversations,
            runtime_to_source,
            expected_mode="CANARY",
            api_token=API_TOKEN,
        )
        revocation_projection = self._revocation_projection_witness()
        query_seconds = perf_counter() - query_started

        read_score = _score_read_fixture(
            conversations=conversations,
            labels=labels,
            canary_rows=canary,
            baseline_rows=off_first,
        )
        off_identity = _semantic_rows(off_first) == _semantic_rows(off_after)
        restart_fallback = _semantic_rows(restarted) == _semantic_rows(off_first)
        metrics = {
            "DirectFormationFidelity": read_score["exact_case_rate"],
            "CanonicalCurrentStateAccuracy": evolution["metrics"][
                "CanonicalCurrentStateAccuracy"
            ],
            "ValidBindingRecall": read_score["valid_binding_recall"],
            "AcceptedBindingPrecision": read_score["accepted_binding_precision"],
            "OperatorReadyRate": read_score["operator_ready_rate"],
            "TemporalCompletenessRate": read_score["temporal_completeness_rate"],
            "FinalAnswerCorrectness": read_score["operator_result_accuracy"],
            "WrongCOMPLETE": read_score["wrong_complete"],
            "CorrectCaseRegression": read_score["correct_case_regression"],
            "AuthorityScopeViolation": read_score["authority_scope_violation"],
            "ReaderGroundingViolation": read_score["reader_grounding_violation"],
        }
        gates = {
            "governed_evolution_pass": evolution["status"]
            == "PASS_C1_GOVERNED_EVOLUTION",
            "canonical_hard_gates_zero": all(
                value == 0 for value in evolution["hard_gates"].values()
            ),
            "formation_fidelity_one": metrics["DirectFormationFidelity"] == 1.0,
            "canonical_current_state_one": metrics[
                "CanonicalCurrentStateAccuracy"
            ]
            == 1.0,
            "binding_recall_one": metrics["ValidBindingRecall"] == 1.0,
            "binding_precision_one": metrics["AcceptedBindingPrecision"] == 1.0,
            "operator_ready_one": metrics["OperatorReadyRate"] == 1.0,
            "temporal_completeness_one": metrics["TemporalCompletenessRate"] == 1.0,
            "final_answer_correctness_one": metrics["FinalAnswerCorrectness"] == 1.0,
            "wrong_complete_zero": metrics["WrongCOMPLETE"] == 0,
            "correct_case_regression_zero": metrics["CorrectCaseRegression"] == 0,
            "authority_scope_violation_zero": metrics["AuthorityScopeViolation"] == 0,
            "reader_grounding_violation_zero": metrics[
                "ReaderGroundingViolation"
            ]
            == 0,
            "deletion_replay_idempotent": deletion_replay["status"] == "PASS",
            "revoked_projection_blocked_and_rebuilt": revocation_projection["status"]
            == "PASS",
            "off_identity": off_identity,
            "restart_empty_sidecar_raw_fallback": restart_fallback,
        }
        result: dict[str, Any] = {
            "schema": "milai.memory-lifecycle.c4-lifecycle-validation.v0.1",
            "status": "PASS_C4_NON_HOLDOUT_LIFECYCLE"
            if all(gates.values())
            else "NEEDS_REPAIR_C4_NON_HOLDOUT_LIFECYCLE",
            "fixture_class": "OPENED_INTERNAL_INTEGRATION_PATTERNS_NOT_GENERALIZATION",
            "formal_holdout_used": False,
            "selected_candidate": "CANDIDATE_F",
            "official_boundaries": {
                "evidence": "POST /v1/evidence",
                "proposal": "POST /v1/proposals",
                "review": "POST /v1/proposals/{id}/review",
                "revoke": "POST /v1/evidence/{id}/revoke",
                "read": "POST /v1/memory/resolve",
                "eval_owned_business_logic": False,
            },
            "coverage": {
                **evolution["coverage"],
                "formation": True,
                "projection_freshness_and_rebuild": True,
                "current_historical_query": True,
                "multi_session_identity_query": True,
                "temporal_query": True,
                "preference_temporary_state_query": True,
                "binding_sufficiency_operator": True,
                "context_reader": True,
                "correction_replay": True,
                "deletion_replay": True,
                "flag_off_rollback": True,
            },
            "evolution": {
                "metrics": evolution["metrics"],
                "hard_gates": evolution["hard_gates"],
                "database_checks": evolution["database_checks"],
                "operation_case_count": len(evolution["operation_cases"]),
            },
            "read_path": read_score,
            "deletion_replay": deletion_replay,
            "revocation_projection": revocation_projection,
            "metrics": metrics,
            "gates": gates,
            "cost": {
                "write_time_seconds": write_seconds,
                "query_time_seconds": query_seconds,
                "evidence_ingests": self.capture_count + len(runtime_to_source),
                "canonical_operation_cases": len(evolution["operation_cases"]),
                "worker_events": worker_events,
                "official_query_calls": len(conversations) * 4 + 1,
                "formation_model_calls": self.model_calls,
                "reader_model_calls": 0,
            },
            "feature_flag": {
                "name": "MILAI_MEMORY_FORMATION_MODE",
                "candidate_mode": "CANARY",
                "default_mode": "OFF",
                "durable_projection": False,
                "rollback": "PASS" if off_identity and restart_fallback else "FAIL",
            },
        }
        result["output_digest"] = canonical_sha256(result)
        return result

    def _capture(self, case_id: str, scope: str, content: str) -> dict[str, str]:
        source_ref = f"ml-closure-c4://{case_id}/{uuid4()}"
        turn_id = f"{case_id}:turn-0"
        response = self.client.post(
            "/v1/evidence",
            headers=self._profile_headers(
                SUBMITTER_TOKEN, f"evidence-c4-{case_id}-{uuid4()}"
            ),
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": source_ref,
                "subject_id": f"{scope}:self",
                "speaker": "user",
                "source_context": {
                    "session_id": f"{case_id}:session",
                    "turn_id": turn_id,
                    "turn_ordinal": 0,
                    "round_id": f"{case_id}:round-0",
                    "round_ordinal": 0,
                },
                "observed_at": OBSERVED_AT,
                "content": content,
                "media_type": "text/plain",
                "permission_snapshot": {
                    "readable": True,
                    "scope": scope,
                    "project_ids": [scope],
                },
                "retention_state": "READABLE",
            },
        )
        if response.status_code != 201:
            raise ReplayFailure(
                f"{case_id}: evidence HTTP {response.status_code} "
                f"{self._error_code(response)}"
            )
        evidence_id = str(response.get_json()["evidence_id"])
        self.captured[case_id] = evidence_id
        self.capture_count += 1
        return {
            "evidence_id": evidence_id,
            "source_ref": source_ref,
            "scope_id": scope,
            "content": content,
            "observed_at": OBSERVED_AT,
        }

    def _deletion_replay(self) -> dict[str, Any]:
        evidence = self._capture(
            "deletion-replay",
            "scope-deletion-replay",
            "I keep a temporary deletion replay marker.",
        )
        key = f"c4-delete-replay-{uuid4()}"
        payload = {"reason_code": "USER_REQUEST", "confirmation": "REVOKE"}
        first = self.client.post(
            f"/v1/evidence/{evidence['evidence_id']}/revoke",
            headers=self._headers(key),
            json=payload,
        )
        second = self.client.post(
            f"/v1/evidence/{evidence['evidence_id']}/revoke",
            headers=self._headers(key),
            json=payload,
        )
        first_body = cast(dict[str, Any], first.get_json(silent=True) or {})
        second_body = cast(dict[str, Any], second.get_json(silent=True) or {})
        passed = (
            first.status_code == 202
            and second.status_code == 200
            and second_body.get("replayed") is True
            and first_body.get("deletion_request_id")
            == second_body.get("deletion_request_id")
        )
        return {
            "status": "PASS" if passed else "FAIL",
            "first_http": first.status_code,
            "replay_http": second.status_code,
            "replayed": second_body.get("replayed"),
            "same_deletion_request": first_body.get("deletion_request_id")
            == second_body.get("deletion_request_id"),
        }

    def _revocation_projection_witness(self) -> dict[str, Any]:
        revoked_id = self.captured["residence-supercede"]
        request = RetrievalRequest(
            route="L1",
            query="Where do I currently live?",
            requested_scope={"project_ids": ["scope-residence"]},
            entities=["scope-residence:self"],
            as_of=datetime.now(UTC),
            system_as_of=datetime.now(UTC),
        )
        projection = cast(
            FormationProjectionStore,
            self.canary_app.extensions["milai.formation_projection"],
        )
        selected = projection.select(
            SessionContext(UUID(TENANT_ID), UUID(ACTOR_ID)), request
        )
        response = self.client.post(
            "/v1/memory/resolve",
            headers=self._headers(f"c4-revocation-query-{uuid4()}"),
            json={
                "query": request.query,
                "requested_scope": request.requested_scope,
                "required_authority": "INFORMATIONAL",
                "required_freshness": "CURRENT",
                "consistency_mode": "CANONICAL_REQUIRED",
                "budget": {
                    "max_results": 12,
                    "max_candidates": 24,
                    "max_context_tokens": 2500,
                    "max_latency_ms": 2000,
                },
                "entities": request.entities,
            },
        )
        body = cast(dict[str, Any], response.get_json(silent=True) or {})
        trace = cast(
            dict[str, Any],
            cast(dict[str, Any], body.get("search_trace") or {}).get(
                "formation_projection"
            )
            or {},
        )
        evidence_refs = set(cast(list[str], body.get("evidence_refs") or []))
        passed = (
            response.status_code == 200
            and revoked_id not in selected.evidence_ids
            and revoked_id not in evidence_refs
            and (selected.build_epoch or 0) >= 2
            and selected.source_watermark_digest != ""
            and trace.get("source_watermark_digest") is not None
            and trace.get("access_snapshot_digest") is not None
            and trace.get("governance_rejected_source_count") == 0
        )
        return {
            "status": "PASS" if passed else "FAIL",
            "http_status": response.status_code,
            "revoked_selected": revoked_id in selected.evidence_ids,
            "revoked_returned": revoked_id in evidence_refs,
            "build_epoch": selected.build_epoch,
            "source_watermark_bound": selected.source_watermark_digest != "",
            "access_snapshot_bound": trace.get("access_snapshot_digest") is not None,
            "governance_rejected_source_count": trace.get(
                "governance_rejected_source_count"
            ),
        }


def _score_read_fixture(
    *,
    conversations: list[dict[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
    canary_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = {str(row["query_id"]): row for row in canary_rows}
    baseline = {str(row["query_id"]): row for row in baseline_rows}
    by_conversation = {
        str(conversation["conversation_id"]): conversation
        for conversation in conversations
    }
    valid = accepted = expected_total = operator_ready = exact_cases = 0
    wrong_complete = reader_violation = authority_violation = 0
    baseline_exact: set[str] = set()
    candidate_exact: set[str] = set()
    temporal_complete = 0
    summaries: list[dict[str, Any]] = []
    for query_id in sorted(labels):
        label = labels[query_id]
        row = rows[query_id]
        baseline_row = baseline[query_id]
        conversation = by_conversation[str(row["conversation_id"])]
        expected = set(cast(list[str], label["expected_bindings"]))
        actual = set(cast(list[str], row["accepted_evidence_ids"]))
        baseline_actual = set(
            cast(list[str], baseline_row["accepted_evidence_ids"])
        )
        true_positive = actual & expected
        extra = actual - expected
        missing = expected - actual
        exact = not extra and not missing
        operator_correct = _operator_correct(row, label)
        context_violation = _reader_grounding_violation(
            row,
            accepted=actual,
            turns=cast(list[dict[str, Any]], conversation["turns"]),
            expected_complete=True,
        )
        sufficiency = cast(dict[str, Any], row.get("sufficiency_decision") or {})
        declared_complete = (
            row.get("status") == "HIT"
            and sufficiency.get("status") == "COMPLETE"
            and not cast(list[object], sufficiency.get("missing_slots") or [])
        )
        wrong = declared_complete and (not exact or not operator_correct)
        valid += len(true_positive)
        accepted += len(actual)
        expected_total += len(expected)
        operator_ready += int(operator_correct)
        exact_cases += int(exact and operator_correct and not context_violation)
        wrong_complete += int(wrong)
        reader_violation += int(context_violation)
        authority_violation += len(extra)
        if exact:
            candidate_exact.add(query_id)
        if baseline_actual == expected:
            baseline_exact.add(query_id)
        if label["expected_operator"] == "TEMPORAL_ORDER":
            temporal_complete += int(exact and operator_correct)
        summaries.append(
            {
                "query_id": query_id,
                "stratum": row["stratum"],
                "expected_binding_count": len(expected),
                "accepted_binding_count": len(actual),
                "missing_binding_count": len(missing),
                "extra_binding_count": len(extra),
                "operator_correct": operator_correct,
                "reader_grounding_violation": context_violation,
            }
        )
    count = len(labels)
    return {
        "query_count": count,
        "expected_binding_count": expected_total,
        "accepted_binding_count": accepted,
        "valid_binding_count": valid,
        "valid_binding_recall": valid / expected_total,
        "accepted_binding_precision": valid / accepted if accepted else 1.0,
        "exact_case_rate": exact_cases / count,
        "operator_ready_rate": operator_ready / count,
        "operator_result_accuracy": operator_ready / count,
        "temporal_completeness_rate": float(temporal_complete),
        "wrong_complete": wrong_complete,
        "correct_case_regression": len(baseline_exact - candidate_exact),
        "authority_scope_violation": authority_violation,
        "reader_grounding_violation": reader_violation,
        "queries": summaries,
    }


def _ingest_read_fixture(
    client: Any, conversations: list[dict[str, Any]]
) -> dict[str, str]:
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
                headers={
                    "Authorization": f"Bearer {API_TOKEN}",
                    "Idempotency-Key": (
                        f"ml-c4-ingest-{conversation['conversation_id']}-{index}"
                    ),
                },
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
                raise C4LifecycleFailure(
                    f"C4_EVIDENCE_INGEST_HTTP_{response.status_code}:"
                    f"{conversation['conversation_id']}:{index}"
                )
            runtime_to_source[str(response.get_json()["evidence_id"])] = str(
                turn["evidence_id"]
            )
    return runtime_to_source


def _read_fixture() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    definitions = [
        (
            "c4-read-current-history",
            "CURRENT_HISTORICAL",
            [
                "I live in Riga.",
                "I noted the location you supplied.",
                "On January 10, 2026, I moved from Riga to Vilnius.",
                "I understand that this updates the earlier location.",
            ],
            "What location or allergy state is current after my latest change?",
            "LOOKUP_CURRENT_WITH_HISTORY",
            "Vilnius",
        ),
        (
            "c4-read-multi-session",
            "ENTITY_IDENTITY_MULTI_SESSION",
            [
                "My colleague Alex Morgan and I attended the Atlas workshop on February 3, 2026.",
                "Thanks for distinguishing the person and event.",
                "Morgan and I attended that same Atlas workshop on February 3, 2026; my dentist Alex Rivera attended a different Atlas workshop on February 18, 2026.",
                "I will not merge the two people or the two workshops.",
            ],
            "Did my colleague and my dentist attend the same Atlas workshop?",
            "COMPARE_EVENT_IDENTITY",
            {"same_event": False},
        ),
        (
            "c4-read-temporal",
            "EVENT_TIME_ORDER",
            [
                "I attended the Orion workshop on March 2, 2026.",
                "I noted the event date from your statement.",
                "Two days after the Orion workshop, I visited the Orion museum. For clarity, I attended that same Orion workshop on March 2, 2026.",
                "I will keep the occurrence date separate from message time.",
            ],
            "Which happened first, the workshop or the visit, and when was the visit?",
            "TEMPORAL_ORDER",
            {"visit_date": "2026-03-04T00:00:00+00:00"},
        ),
        (
            "c4-read-composed",
            "PREFERENCE_TEMPORARY_STATE",
            [
                "I prefer aisle seats over window seats.",
                "I noted the preference as user-supplied.",
                "Until October 10, 2026, I am staying in Bath while finishing a course.",
                "An intent or temporary state is not a permanent fact.",
            ],
            "What preference and short-lived plan or constraint should be recalled?",
            "COMPOSE_STATE",
            {
                "preference": "aisle seats",
                "temporary_location": {"location": "Bath"},
            },
        ),
    ]
    conversations: list[dict[str, Any]] = []
    labels: dict[str, dict[str, Any]] = {}
    for offset, definition in enumerate(definitions):
        conversation_id, stratum, contents, question, operator, state = definition
        scope = f"scope:{conversation_id}"
        turns: list[dict[str, Any]] = []
        for index, content in enumerate(contents):
            session = f"{conversation_id}:session-{index // 2}"
            evidence_id = f"{conversation_id}:e{index}"
            turns.append(
                {
                    "evidence_id": evidence_id,
                    "session_id": session,
                    "speaker": "user" if index % 2 == 0 else "assistant",
                    "source_ref": f"ml-closure-c4://{conversation_id}/{evidence_id}",
                    "observed_at": (
                        datetime(2026, 8, 20 + offset, 8 + index, tzinfo=UTC).isoformat()
                    ),
                    "content": content,
                    "permission_snapshot": {"readable": True},
                    "retention_state": "READABLE",
                    "revoked_at": None,
                    "access_decision": "ALLOWED",
                    "scope_id": scope,
                }
            )
        query_id = f"{conversation_id}:q0"
        conversations.append(
            {
                "conversation_id": conversation_id,
                "scope_id": scope,
                "turns": turns,
                "queries": [
                    {
                        "query_id": query_id,
                        "question": question,
                        "stratum": stratum,
                    }
                ],
            }
        )
        expected_bindings = [
            f"{conversation_id}:e0",
            f"{conversation_id}:e2",
        ]
        labels[query_id] = {
            "expected_bindings": expected_bindings,
            "proof_obligations": expected_bindings,
            "expected_complete": True,
            "expected_operator": operator,
            "expected_current_state": state,
        }
    return conversations, labels


def execute() -> dict[str, Any]:
    owner_dsn = _required_environment("MILAI_MIGRATION_DATABASE_URL")
    command.upgrade(Config("alembic.ini"), "head")
    with tempfile.TemporaryDirectory(prefix="milai-ml-c4-") as temporary:
        settings = RuntimeSettings(
            database_url=SecretStr(
                _required_environment("MILAI_TEST_API_DATABASE_URL")
            ),
            steward_database_url=SecretStr(
                _required_environment("MILAI_TEST_STEWARD_DATABASE_URL")
            ),
            blob_root=Path(temporary) / "blobs",
            tenant_id=UUID(TENANT_ID),
            local_actor_id=UUID(ACTOR_ID),
            api_token=SecretStr(API_TOKEN),
            causal_token_secret=SecretStr(
                "ml-closure-c4-causal-secret-at-least-32-characters"
            ),
            agent_submitter_token=SecretStr(SUBMITTER_TOKEN),
            agent_reviewer_token=SecretStr(REVIEWER_TOKEN),
            feature_profile="FORMED_CANARY",
            worker_event_limit=10_000,
            worker_retry_delay_seconds=0,
            worker_max_attempts=1,
            retrieval_evidence_dense_enabled=False,
            retrieval_deterministic_recovery_enabled=False,
            retrieval_type_directed_acquisition_enabled=False,
            retrieval_reranker_provider="none",
        )
        prepare_runtime_directories(settings)
        api_database = Database(settings)
        steward_database = Database(settings, dsn=settings.steward_database_dsn)
        worker_database = Database(
            settings,
            dsn=_required_environment("MILAI_TEST_WORKER_DATABASE_URL"),
        )
        try:
            canary_app = create_app(
                settings,
                database=api_database,
                steward_database=steward_database,
            )
            off_app = create_app(
                settings.model_copy(update={"feature_profile": "BASELINE"}),
                database=api_database,
                steward_database=steward_database,
            )
            for app in (canary_app, off_app):
                app.config["TESTING"] = True
            result = C4LifecycleReplay(
                canary_app=canary_app,
                off_app=off_app,
                owner_dsn=owner_dsn,
                settings=settings,
                worker_database=worker_database,
            ).execute()
        finally:
            api_database.close()
            steward_database.close()
            worker_database.close()
    return result


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise C4LifecycleFailure(f"{name}_MISSING")
    return value


if __name__ == "__main__":
    print(
        "ML_CLOSURE_C4_LIFECYCLE_RESULT="
        + json.dumps(execute(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
