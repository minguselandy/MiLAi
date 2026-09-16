"""Exercise Formation-to-Canonical evolution against an isolated database.

The harness owns no evolution behavior.  It forms source-grounded sidecars,
passes them through the runtime bridge and public HTTP API, and scores the
persisted Canonical effects against predeclared expectations.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
from alembic import command
from alembic.config import Config
from milai.api import create_app
from milai.application.formation_evolution_bridge import (
    EvolutionCurrentClaimV01,
    FormationEvolutionBridgeError,
    map_state_artifact_to_proposal,
)
from milai.application.formation_engine import DEFAULT_FORMATION_ENGINE
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.persistence import Database
from pydantic import SecretStr

TENANT_ID = "11111111-1111-4111-8111-111111111111"
ACTOR_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
API_TOKEN = "ml-closure-api-token-with-at-least-32-characters"
SUBMITTER_TOKEN = "ml-closure-submitter-token-with-at-least-32-characters"
REVIEWER_TOKEN = "ml-closure-reviewer-token-with-at-least-32-characters"
OBSERVED_AT = "2026-08-16T11:00:00+08:00"


class ReplayFailure(RuntimeError):
    """The isolated replay diverged from its declared semantic expectation."""


class EvolutionReplay:
    def __init__(self, client: Any, owner_dsn: str) -> None:
        self.client = client
        self.owner_dsn = owner_dsn
        self.cases: list[dict[str, Any]] = []
        self.provenance_failures = 0
        self.model_calls = 0

    def execute(self) -> dict[str, Any]:
        residence = self._residence_lifecycle("scope-residence")
        temporary = self._temporary_lifecycle("scope-temporary")
        allergy = self._allergy_lifecycle("scope-allergy")
        unsupported = self._unsupported_and_cross_scope(residence["claim_id"])
        database_checks = self._database_checks(
            residence=residence,
            temporary=temporary,
            allergy=allergy,
        )

        operation_correct = sum(
            item["expected_operation"] == item["observed_operation"]
            for item in self.cases
        )
        disposition_correct = sum(bool(item["disposition_correct"]) for item in self.cases)
        hard_gates = {
            "UnsupportedCanonicalPromotion": unsupported["unsupported_promotions"],
            "WrongTransitionDisposition": len(self.cases) - operation_correct,
            "MissingProvenanceClosure": self.provenance_failures
            + database_checks["ungrounded_versions"],
            "ValidTimeMisassignment": temporary["valid_time_misassignments"],
            "RevocationSupportLeak": residence["revocation_support_leak"],
            "RollbackReplayMismatch": residence["rollback_replay_mismatch"],
            "CrossScopeIdentityLink": unsupported["cross_scope_links"]
            + database_checks["cross_scope_grounding_links"],
        }
        metrics = {
            "ExpectedOperationAccuracy": operation_correct / len(self.cases),
            "ExpectedReviewDispositionAccuracy": disposition_correct / len(self.cases),
            "CanonicalCurrentStateAccuracy": min(
                residence["current_state_accuracy"],
                temporary["current_state_accuracy"],
                allergy["current_state_accuracy"],
            ),
            "ValidTimeAccuracy": 1.0
            if temporary["valid_time_misassignments"] == 0
            else 0.0,
            "VersionTransitionAccuracy": database_checks["transition_accuracy"],
            "Conflict/OpenIssuePreservation": residence["conflict_preservation"],
            "RollbackReplayEquivalence": 1.0
            if residence["rollback_replay_mismatch"] == 0
            else 0.0,
        }
        passed = (
            all(value == 0 for value in hard_gates.values())
            and all(value == 1.0 for value in metrics.values())
            and self.model_calls == 0
        )
        return {
            "schema": "milai.ml-closure.evolution-replay.v0.1",
            "status": "PASS_C1_GOVERNED_EVOLUTION" if passed else "NEEDS_REPAIR",
            "metrics": metrics,
            "hard_gates": hard_gates,
            "operation_cases": self.cases,
            "coverage": {
                "operations": sorted({item["observed_operation"] for item in self.cases}),
                "current_and_historical_reads": True,
                "conflict_open_issue": True,
                "revoke_block_fresh_reground": True,
                "stale_review_transaction_rollback": True,
                "idempotent_proposal_and_review_replay": True,
                "rollback_replay_probe": residence["rollback_probe"],
                "model_calls": self.model_calls,
            },
            "database_checks": database_checks,
            "formal_holdout_used": False,
            "canonical_mutation_scope": "fresh_ephemeral_database_only",
        }

    def _residence_lifecycle(self, scope: str) -> dict[str, Any]:
        created = self._apply_formed(
            "residence-create", scope, "I live in Shanghai.", "CREATE", None
        )
        claim_id = UUID(created["review"]["claim_id"])

        # Two candidates share one observed head.  One commits and the other
        # proves that a stale review rolls back without changing Canonical state.
        observed = self._current(claim_id)
        first_support = self._prepare_formed(
            "residence-support", scope, "I live in Shanghai.", "SUPPORT", observed
        )
        stale_support = self._prepare_formed(
            "residence-stale", scope, "I live in Shanghai.", "SUPPORT", observed
        )
        support_review = self._review(first_support, expected="APPLIED")
        self._finish_case(first_support, support_review, expected="APPLIED")
        before_stale = self._claim_snapshot(claim_id)
        stale_response = self.client.post(
            f"/v1/proposals/{stale_support['proposal']['proposal_id']}/review",
            headers=self._profile_headers(REVIEWER_TOKEN, stale_support["review_key"]),
            json=stale_support["review_payload"],
        )
        stale_rolled_back = (
            stale_response.status_code == 409
            and stale_response.get_json()["error"]["code"] == "VERSION_CONFLICT"
            and before_stale == self._claim_snapshot(claim_id)
        )
        self._finish_case(
            stale_support,
            None,
            expected="VERSION_CONFLICT_ROLLBACK",
            disposition_correct=stale_rolled_back,
        )

        replay_proposal = self.client.post(
            "/v1/proposals",
            headers=self._profile_headers(SUBMITTER_TOKEN, first_support["proposal_key"]),
            json=first_support["proposal_payload"],
        )
        before_replay = self._claim_snapshot(claim_id)
        replay_review = self.client.post(
            f"/v1/proposals/{first_support['proposal']['proposal_id']}/review",
            headers=self._profile_headers(REVIEWER_TOKEN, first_support["review_key"]),
            json=first_support["review_payload"],
        )
        after_replay = self._claim_snapshot(claim_id)
        replay_probe = {
            "proposal_http": replay_proposal.status_code,
            "proposal_replayed": replay_proposal.get_json().get("replayed"),
            "review_http": replay_review.status_code,
            "review_replayed": replay_review.get_json().get("replayed"),
            "canonical_snapshot_equal": before_replay == after_replay,
        }
        replay_equivalent = (
            replay_probe["proposal_http"] == 200
            and replay_probe["proposal_replayed"] is True
            and replay_probe["review_http"] == 200
            and replay_probe["review_replayed"] is True
            and replay_probe["canonical_snapshot_equal"] is True
        )

        moved = self._apply_formed(
            "residence-supercede",
            scope,
            "On August 12, 2026, I moved from Shanghai to Hangzhou for my new job.",
            "SUPERSEDE",
            self._current(claim_id),
        )
        move_evidence_id = moved["evidence_id"]
        revoked = self.client.post(
            f"/v1/evidence/{move_evidence_id}/revoke",
            headers=self._headers(f"revoke-{uuid4()}"),
            json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
        )
        blocked = self._claim_json(claim_id)
        blocked_correct = (
            revoked.status_code == 202
            and blocked["effective_status"] == "BLOCKED"
            and blocked["has_live_block"] is True
        )

        regrounded = self._apply_formed(
            "residence-reground",
            scope,
            "I live in Hangzhou.",
            "REGROUND",
            self._current(claim_id),
        )
        restored = self._claim_json(claim_id)
        restored_correct = (
            restored["payload"] == {"location": "Hangzhou"}
            and restored["effective_status"] == "EFFECTIVE"
            and restored["has_live_block"] is False
            and regrounded["review"]["claim_version_id"]
            != moved["review"]["claim_version_id"]
        )

        conflict = self._apply_formed(
            "residence-conflict",
            scope,
            "I live in Beijing.",
            "CONTRADICT",
            self._current(claim_id),
            disposition="OPEN_ISSUE",
        )
        issue_id = conflict["review"].get("open_issue_id")
        issue = self.client.get(
            f"/v1/open-issues/{issue_id}", headers=self._headers()
        )
        after_conflict = self._claim_json(claim_id)
        issue_json = issue.get_json() if issue.status_code == 200 else {}
        branches = {
            item["relation_type"] for item in issue_json.get("branches", [])
        }
        conflict_preservation = float(
            issue.status_code == 200
            and issue_json.get("status") == "OPEN"
            and branches == {"SUPPORT_BRANCH", "CONTRADICT_BRANCH"}
            and after_conflict["claim_version_id"]
            == regrounded["review"]["claim_version_id"]
            and after_conflict["effective_status"] == "CONFLICTED"
        )
        versions = self._versions(claim_id)
        historical_correct = [item["payload"] for item in versions] == [
            {"location": "Shanghai"},
            {"location": "Shanghai"},
            {"location": "Hangzhou"},
            {"location": "Hangzhou"},
        ]
        return {
            "claim_id": claim_id,
            "current_state_accuracy": float(
                restored_correct and historical_correct and conflict_preservation == 1.0
            ),
            "conflict_preservation": conflict_preservation,
            "revocation_support_leak": 0 if blocked_correct and restored_correct else 1,
            "rollback_replay_mismatch": 0
            if stale_rolled_back and replay_equivalent
            else 1,
            "rollback_probe": {
                "stale_review_rolled_back": stale_rolled_back,
                **replay_probe,
            },
        }

    def _temporary_lifecycle(self, scope: str) -> dict[str, Any]:
        first = self._apply_formed(
            "temporary-create",
            scope,
            "Until September 5, 2026, I am staying in Suzhou for a conference.",
            "CREATE",
            None,
        )
        claim_id = UUID(first["review"]["claim_id"])
        second = self._apply_formed(
            "temporary-contextualize",
            scope,
            "Until September 12, 2026, I am staying in Nanjing for training.",
            "CONTEXTUALIZE",
            self._current(claim_id),
        )
        versions = self._versions(claim_id)
        expected_times = [first["valid_time"], second["valid_time"]]
        mismatches = 0
        for version, expected in zip(versions, expected_times, strict=True):
            if expected is None:
                mismatches += 1
                continue
            if not (
                self._same_instant(version["valid_time_from"], expected["start"])
                and self._same_instant(version["valid_time_to"], expected["end"])
            ):
                mismatches += 1
        current = self._claim_json(claim_id)
        state_correct = (
            current["payload"] == {"location": "Nanjing"}
            and [item["payload"] for item in versions]
            == [{"location": "Suzhou"}, {"location": "Nanjing"}]
        )
        return {
            "claim_id": claim_id,
            "current_state_accuracy": float(state_correct),
            "valid_time_misassignments": mismatches,
        }

    def _allergy_lifecycle(self, scope: str) -> dict[str, Any]:
        created = self._apply_formed(
            "allergy-create", scope, "I am allergic to peanuts.", "CREATE", None
        )
        claim_id = UUID(created["review"]["claim_id"])
        weakened = self._apply_formed(
            "allergy-weaken",
            scope,
            "That peanuts allergy was incorrect; I revoke it.",
            "WEAKEN",
            self._current(claim_id),
        )
        current = self._claim_json(claim_id)
        versions = self._versions(claim_id)
        correct = (
            weakened["review"]["claim_version_id"] == current["claim_version_id"]
            and current["payload"] == {"item": "peanuts"}
            and current["epistemic_status"] == "CHALLENGED"
            and [item["payload"] for item in versions]
            == [{"item": "peanuts"}, {"item": "peanuts"}]
        )
        return {"claim_id": claim_id, "current_state_accuracy": float(correct)}

    def _unsupported_and_cross_scope(self, residence_claim_id: UUID) -> dict[str, int]:
        intent = self._capture(
            "query-local-intent", "scope-intent", "I am planning to visit Kyoto."
        )
        bundle = self._form(intent)
        assertion = bundle.state_changes.assertions[0]
        request = map_state_artifact_to_proposal(
            assertion,
            transition=bundle.state_changes.transitions[0],
            governed_evidence_ref=UUID(intent["evidence_id"]),
            scope_predicate={"project_ids": ["scope-intent"]},
        )
        unsupported_promotions = 0 if request is None else 1

        cross = self._capture(
            "cross-scope", "scope-other", "I live in Hangzhou."
        )
        cross_bundle = self._form(cross)
        before = self._proposal_count()
        rejected = False
        try:
            map_state_artifact_to_proposal(
                cross_bundle.state_changes.assertions[0],
                transition=cross_bundle.state_changes.transitions[0],
                current_claim=self._current(residence_claim_id),
                governed_evidence_ref=UUID(cross["evidence_id"]),
                scope_predicate={"project_ids": ["scope-other"]},
            )
        except FormationEvolutionBridgeError as error:
            rejected = str(error) == "FORMATION_CURRENT_CLAIM_IDENTITY_MISMATCH"
        cross_scope_links = 0 if rejected and before == self._proposal_count() else 1
        return {
            "unsupported_promotions": unsupported_promotions,
            "cross_scope_links": cross_scope_links,
        }

    def _prepare_formed(
        self,
        case_id: str,
        scope: str,
        content: str,
        expected_operation: str,
        current: EvolutionCurrentClaimV01 | None,
    ) -> dict[str, Any]:
        evidence = self._capture(case_id, scope, content)
        bundle = self._form(evidence)
        self.model_calls += bundle.formation.model_calls
        if len(bundle.state_changes.assertions) != 1:
            raise ReplayFailure(f"{case_id}: expected one state assertion")
        assertion = bundle.state_changes.assertions[0]
        transition = bundle.state_changes.transitions[0]
        request = map_state_artifact_to_proposal(
            assertion,
            transition=transition,
            current_claim=current,
            governed_evidence_ref=UUID(evidence["evidence_id"]),
            scope_predicate={"project_ids": [scope]},
        )
        if request is None:
            raise ReplayFailure(f"{case_id}: governed artifact was suppressed")
        proposal_key = f"proposal-{case_id}-{uuid4()}"
        proposal_payload = request.model_dump(mode="json", exclude_none=True)
        proposal_response = self.client.post(
            "/v1/proposals",
            headers=self._profile_headers(SUBMITTER_TOKEN, proposal_key),
            json=proposal_payload,
        )
        if proposal_response.status_code != 201:
            raise ReplayFailure(
                f"{case_id}: proposal HTTP {proposal_response.status_code} "
                f"{self._error_code(proposal_response)}"
            )
        proposal = proposal_response.get_json()
        stored = self.client.get(
            f"/v1/proposals/{proposal['proposal_id']}", headers=self._headers()
        )
        if stored.status_code != 200:
            raise ReplayFailure(f"{case_id}: stored proposal unavailable")
        snapshot = stored.get_json().get("derivation_snapshot", {})
        source_span = snapshot.get("source_span", {}) if isinstance(snapshot, dict) else {}
        refs = (
            stored.get_json().get("contradicting_evidence_refs", [])
            if request.operation == "CONTRADICT"
            else stored.get_json().get("supporting_evidence_refs", [])
        )
        if not (
            snapshot.get("formation_artifact_digest") == assertion.artifact_digest
            and snapshot.get("canonical_commit_authorized") is False
            and source_span.get("source_evidence_id") == evidence["evidence_id"]
            and evidence["evidence_id"] in refs
        ):
            self.provenance_failures += 1
        review_key = f"review-{case_id}-{uuid4()}"
        return {
            "case_id": case_id,
            "expected_operation": expected_operation,
            "observed_operation": request.operation,
            "evidence_id": evidence["evidence_id"],
            "proposal": proposal,
            "proposal_key": proposal_key,
            "proposal_payload": proposal_payload,
            "review_key": review_key,
            "review_payload": {
                "decision": "APPROVE",
                "policy_version": "ml-closure-evolution-v0.1",
                "reason_code": "GROUNDED_LIFECYCLE_REPLAY_VERIFIED",
            },
            "policy_correct": proposal.get("commit_policy_decision") == "USER_REVIEW",
            "valid_time": (
                assertion.valid_time.model_dump(mode="json")
                if assertion.valid_time is not None
                else None
            ),
        }

    def _apply_formed(
        self,
        case_id: str,
        scope: str,
        content: str,
        expected_operation: str,
        current: EvolutionCurrentClaimV01 | None,
        *,
        disposition: str = "APPLIED",
    ) -> dict[str, Any]:
        prepared = self._prepare_formed(
            case_id, scope, content, expected_operation, current
        )
        reviewed = self._review(prepared, expected=disposition)
        self._finish_case(prepared, reviewed, expected=disposition)
        prepared["review"] = reviewed
        return prepared

    def _review(self, prepared: dict[str, Any], *, expected: str) -> dict[str, Any]:
        response = self.client.post(
            f"/v1/proposals/{prepared['proposal']['proposal_id']}/review",
            headers=self._profile_headers(REVIEWER_TOKEN, prepared["review_key"]),
            json=prepared["review_payload"],
        )
        if response.status_code != 200:
            raise ReplayFailure(
                f"{prepared['case_id']}: review HTTP {response.status_code} "
                f"{self._error_code(response)}"
            )
        result = cast(dict[str, Any], response.get_json())
        if expected == "OPEN_ISSUE" and not result.get("open_issue_id"):
            raise ReplayFailure(f"{prepared['case_id']}: OpenIssue was not created")
        return result

    def _finish_case(
        self,
        prepared: dict[str, Any],
        reviewed: dict[str, Any] | None,
        *,
        expected: str,
        disposition_correct: bool | None = None,
    ) -> None:
        if disposition_correct is None:
            stored = self.client.get(
                f"/v1/proposals/{prepared['proposal']['proposal_id']}",
                headers=self._headers(),
            )
            stored_status = stored.get_json().get("status") if stored.status_code == 200 else None
            disposition_correct = bool(
                prepared["policy_correct"]
                and stored_status == "APPLIED"
                and reviewed is not None
                and reviewed.get("decision") == "APPROVE"
                and (
                    expected != "OPEN_ISSUE" or reviewed.get("open_issue_id") is not None
                )
            )
        self.cases.append(
            {
                "case_id": prepared["case_id"],
                "expected_operation": prepared["expected_operation"],
                "observed_operation": prepared["observed_operation"],
                "expected_disposition": expected,
                "disposition_correct": disposition_correct,
            }
        )

    def _capture(self, case_id: str, scope: str, content: str) -> dict[str, str]:
        source_ref = f"ml-closure://{case_id}/{uuid4()}"
        response = self.client.post(
            "/v1/evidence",
            headers=self._profile_headers(
                SUBMITTER_TOKEN, f"evidence-{case_id}-{uuid4()}"
            ),
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": source_ref,
                "subject_id": f"{scope}:self",
                "observed_at": OBSERVED_AT,
                "content": content,
                "media_type": "text/plain",
                "permission_snapshot": {"readable": True, "scope": scope},
                "retention_state": "READABLE",
            },
        )
        if response.status_code != 201:
            raise ReplayFailure(
                f"{case_id}: evidence HTTP {response.status_code} {self._error_code(response)}"
            )
        return {
            "evidence_id": response.get_json()["evidence_id"],
            "source_ref": source_ref,
            "scope_id": scope,
            "content": content,
            "observed_at": OBSERVED_AT,
        }

    @staticmethod
    def _form(evidence: dict[str, str]) -> Any:
        return DEFAULT_FORMATION_ENGINE.build(
            [
                {
                    **evidence,
                    "speaker": "user",
                    "permission_snapshot": {"readable": True},
                    "retention_state": "READABLE",
                    "access_decision": "ALLOWED",
                }
            ]
        ).generalized

    def _current(self, claim_id: UUID) -> EvolutionCurrentClaimV01:
        item = self._claim_json(claim_id)
        return EvolutionCurrentClaimV01(
            claim_id=claim_id,
            claim_version_id=UUID(item["claim_version_id"]),
            subject_id=item["subject_id"],
            predicate=item["predicate"],
            payload=item["payload"],
            effective_status=item["effective_status"],
        )

    def _claim_json(self, claim_id: UUID) -> dict[str, Any]:
        response = self.client.get(f"/v1/claims/{claim_id}", headers=self._headers())
        if response.status_code != 200:
            raise ReplayFailure(f"claim {claim_id} unavailable")
        return cast(dict[str, Any], response.get_json())

    def _versions(self, claim_id: UUID) -> list[dict[str, Any]]:
        response = self.client.get(
            f"/v1/claims/{claim_id}/versions", headers=self._headers()
        )
        if response.status_code != 200:
            raise ReplayFailure(f"versions for {claim_id} unavailable")
        payload = cast(dict[str, Any], response.get_json())
        return cast(list[dict[str, Any]], payload["versions"])

    def _claim_snapshot(self, claim_id: UUID) -> dict[str, Any]:
        current = self._claim_json(claim_id)
        return {
            "current": {
                key: current[key]
                for key in (
                    "subject_id",
                    "predicate",
                    "payload",
                    "version_number",
                    "effective_status",
                    "has_live_grounding",
                    "has_live_block",
                    "has_live_open_issue",
                )
            },
            "versions": [
                {
                    key: item[key]
                    for key in (
                        "version_number",
                        "payload",
                        "scope_predicate",
                        "valid_time_from",
                        "valid_time_to",
                        "lifecycle",
                        "epistemic_status",
                        "freshness",
                    )
                }
                for item in self._versions(claim_id)
            ],
        }

    def _database_checks(
        self,
        *,
        residence: dict[str, Any],
        temporary: dict[str, Any],
        allergy: dict[str, Any],
    ) -> dict[str, Any]:
        expected = {
            residence["claim_id"]: ["CREATE", "SUPPORT", "SUPERSEDE", "REGROUND"],
            temporary["claim_id"]: ["CREATE", "CONTEXTUALIZE"],
            allergy["claim_id"]: ["CREATE", "WEAKEN"],
        }
        observed: dict[str, list[str]] = {}
        with psycopg.connect(self.owner_dsn) as connection:
            for claim_id, expected_types in expected.items():
                rows = connection.execute(
                    """
                    SELECT transition_type
                    FROM milai.version_transition
                    WHERE claim_id = %s
                    ORDER BY canonical_commit_seq
                    """,
                    (claim_id,),
                ).fetchall()
                observed[str(claim_id)] = [str(row[0]) for row in rows]
                if observed[str(claim_id)] != expected_types:
                    continue
            ungrounded_row = connection.execute(
                """
                SELECT count(*)
                FROM milai.claim_version version
                WHERE NOT EXISTS (
                  SELECT 1 FROM milai.grounding_relation relation
                  WHERE relation.claim_version_id = version.claim_version_id
                    AND relation.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
                )
                """
            ).fetchone()
            cross_scope_row = connection.execute(
                """
                SELECT count(*)
                FROM milai.grounding_relation relation
                JOIN milai.claim_version version
                  ON version.claim_version_id = relation.claim_version_id
                JOIN milai.claim claim ON claim.claim_id = version.claim_id
                JOIN milai.evidence_record evidence
                  ON evidence.evidence_id = relation.evidence_id
                WHERE evidence.subject_id IS DISTINCT FROM claim.subject_id
                """
            ).fetchone()
            migration_head_row = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            if (
                ungrounded_row is None
                or cross_scope_row is None
                or migration_head_row is None
            ):
                raise ReplayFailure("database aggregate query returned no row")
            ungrounded = ungrounded_row[0]
            cross_scope = cross_scope_row[0]
            migration_head = migration_head_row[0]
        transition_accuracy = sum(
            observed[str(claim_id)] == expected_types
            for claim_id, expected_types in expected.items()
        ) / len(expected)
        return {
            "transition_accuracy": transition_accuracy,
            "observed_transition_types": sorted(observed.values()),
            "ungrounded_versions": int(ungrounded),
            "cross_scope_grounding_links": int(cross_scope),
            "migration_head": str(migration_head),
        }

    def _proposal_count(self) -> int:
        with psycopg.connect(self.owner_dsn) as connection:
            row = connection.execute(
                "SELECT count(*) FROM milai.operation_proposal"
            ).fetchone()
        if row is None:
            raise ReplayFailure("proposal count returned no row")
        return int(row[0])

    @staticmethod
    def _same_instant(left: str | None, right: str | None) -> bool:
        if left is None or right is None:
            return left == right
        return datetime.fromisoformat(left) == datetime.fromisoformat(right)

    @staticmethod
    def _headers(key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {API_TOKEN}"}
        if key is not None:
            headers["Idempotency-Key"] = key
        return headers

    @staticmethod
    def _profile_headers(token: str, key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {token}"}
        if key is not None:
            headers["Idempotency-Key"] = key
        return headers

    @staticmethod
    def _error_code(response: Any) -> str:
        value = response.get_json(silent=True)
        if isinstance(value, dict) and isinstance(value.get("error"), dict):
            return str(value["error"].get("code", "UNKNOWN"))
        return "UNKNOWN"


def execute() -> dict[str, Any]:
    owner_dsn = _required_environment("MILAI_MIGRATION_DATABASE_URL")
    command.upgrade(Config("alembic.ini"), "head")
    with tempfile.TemporaryDirectory(prefix="milai-ml-closure-") as temporary:
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
                "ml-closure-causal-secret-at-least-32-characters"
            ),
            agent_submitter_token=SecretStr(SUBMITTER_TOKEN),
            agent_reviewer_token=SecretStr(REVIEWER_TOKEN),
        )
        prepare_runtime_directories(settings)
        database = Database(settings)
        steward_database = Database(settings, dsn=settings.steward_database_dsn)
        try:
            app = create_app(
                settings, database=database, steward_database=steward_database
            )
            app.config["TESTING"] = True
            result = EvolutionReplay(app.test_client(), owner_dsn).execute()
        finally:
            database.close()
            steward_database.close()
    return result


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ReplayFailure(f"{name}_MISSING")
    return value


if __name__ == "__main__":
    print(
        "ML_CLOSURE_EVOLUTION_RESULT="
        + json.dumps(execute(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
