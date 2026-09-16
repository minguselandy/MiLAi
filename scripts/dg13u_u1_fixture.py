from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TypedDict

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_FIXTURE = ROOT / "contracts/agent/v1/dg13u-u1-candidate-fixture.json"
CANDIDATE_SHA256 = "47175b17cdc8444955d28cf3ec2f6d96964faf2099decf34bd317cf7729bb555"

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
_EXPECTED_CANDIDATE: dict[str, Any] = {
    "schema": "milai.dg13u.u1-candidate-fixture.v1",
    "status": "U1_CANDIDATE_OWNER_ACCEPTANCE_REQUIRED",
    "data_boundary": "SYNTHETIC_OR_INDEPENDENTLY_DEIDENTIFIED",
    "formal_evaluation_input": False,
    "families": [
        {
            "project": "orchid-release",
            "state_key": "release.target",
            "claim_type": "PROJECT_STATE",
            "aliases": ["current release target", "当前发布目标"],
        },
        {
            "project": "orchid-release",
            "state_key": "release.database",
            "claim_type": "PROJECT_CONFIG",
            "aliases": [
                "current release database",
                "current release config",
                "当前发布数据库",
                "当前发布配置",
            ],
        },
        {
            "project": "orchid-release",
            "state_key": "release.decision",
            "claim_type": "PROJECT_DECISION",
            "aliases": ["current governed release decision", "当前受治理的发布决定"],
        },
    ],
}

_CURRENT_VALUES = {
    "release.target": "rc-2026.08-u1",
    "release.database": "postgresql-18-u1",
    "release.decision": "proceed-after-governance-pass",
}


class FixtureReceipt(TypedDict):
    schema: str
    status: str
    candidate_fixture_sha256: str
    run_id_sha256: str
    data_boundary: str
    formal_evaluation_input: bool
    writer_roles: list[str]
    families: list[dict[str, Any]]
    negative_setups: dict[str, dict[str, Any]]
    mutations: list[dict[str, Any]]


class CleanupReceipt(TypedDict):
    schema: str
    status: str
    run_id_sha256: str
    canonical_claims_deleted: bool
    evidence_revocations: int
    receipts: list[dict[str, Any]]


class FixtureContractError(RuntimeError):
    """The frozen candidate or fixture invocation is not executable as declared."""


class FixtureSeedError(FixtureContractError):
    """A controlled mutation failed after zero or more mutation receipts existed."""

    def __init__(self, code: str, partial_receipt: dict[str, Any]) -> None:
        super().__init__(code)
        self.code = code
        self.partial_receipt = partial_receipt


@dataclass(frozen=True, slots=True)
class StateFamily:
    project: str
    state_key: str
    claim_type: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixtureOptions:
    wrong_scope: bool = False
    open_issue: bool = False
    revoke: bool = False
    state_change: bool = False


class CanonicalFixtureWriter(Protocol):
    """Role-separated adapter over existing controlled Runtime/MCP write paths."""

    def capture_as_submitter(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def propose_as_submitter(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def review_as_steward(
        self, proposal_id: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...

    def revoke_as_operator(
        self, evidence_id: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_candidate_families() -> tuple[StateFamily, ...]:
    if _sha256_file(CANDIDATE_FIXTURE) != CANDIDATE_SHA256:
        raise FixtureContractError("candidate fixture SHA-256 mismatch")
    try:
        candidate = json.loads(CANDIDATE_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureContractError("candidate fixture is unreadable") from exc
    if candidate != _EXPECTED_CANDIDATE:
        raise FixtureContractError(
            "candidate fixture exact three-family contract mismatch"
        )
    return tuple(
        StateFamily(
            project=str(item["project"]),
            state_key=str(item["state_key"]),
            claim_type=str(item["claim_type"]),
            aliases=tuple(str(alias) for alias in item["aliases"]),
        )
        for item in candidate["families"]
    )


def _identifier(result: Mapping[str, Any], key: str, code: str) -> str:
    value = result.get(key)
    if not isinstance(value, str) or not value or len(value) > 512:
        raise FixtureContractError(code)
    return value


def _replayed(result: Mapping[str, Any]) -> bool:
    value = result.get("replayed", False)
    if not isinstance(value, bool):
        raise FixtureContractError("mutation replay field is invalid")
    return value


def _partial_receipt(
    run_id_sha256: str, mutations: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema": "milai.dg13u.u1-fixture-partial.v1",
        "status": "PARTIAL",
        "candidate_fixture_sha256": CANDIDATE_SHA256,
        "run_id_sha256": run_id_sha256,
        "mutations": list(mutations),
    }


def _validate_invocation(run_id: str, observed_at: str) -> None:
    if _RUN_ID.fullmatch(run_id) is None:
        raise FixtureContractError("run_id must be a bounded synthetic identifier")
    try:
        observed = datetime.fromisoformat(observed_at)
    except ValueError as exc:
        raise FixtureContractError("observed_at must be ISO-8601") from exc
    if observed.utcoffset() is None:
        raise FixtureContractError("observed_at must include a timezone offset")


def _capture(
    writer: CanonicalFixtureWriter,
    *,
    run_id: str,
    run_id_sha256: str,
    observed_at: str,
    label: str,
    subject_id: str,
    content: str,
    mutations: list[dict[str, Any]],
) -> str:
    payload = {
        "operation_id": f"dg13u-u1-{run_id}-{label}-evidence",
        "source_type": "RUNTIME_OBSERVATION",
        "source_ref": f"dg13u-u1://{run_id_sha256[:16]}/{label}",
        "subject_id": subject_id,
        "observed_at": observed_at,
        "content": content,
        "data_classification": "SYNTHETIC",
        "permission_snapshot": {"readable": True, "scope": "synthetic-dg13u-u1"},
        "retention_state": "READABLE",
        "confirmation": "CAPTURE",
    }
    try:
        result = writer.capture_as_submitter(payload)
        evidence_id = _identifier(result, "evidence_id", "EVIDENCE_ID_MISSING")
        mutation = {
            "kind": "EVIDENCE_CAPTURE",
            "role": "submitter",
            "evidence_id": evidence_id,
            "outbox_id": _identifier(result, "outbox_id", "EVIDENCE_OUTBOX_ID_MISSING"),
            "replayed": _replayed(result),
        }
    except Exception as exc:
        if isinstance(exc, FixtureSeedError):
            raise
        raise FixtureSeedError(
            "EVIDENCE_CAPTURE_FAILED", _partial_receipt(run_id_sha256, mutations)
        ) from exc
    mutations.append(mutation)
    return evidence_id


def _propose_and_review(
    writer: CanonicalFixtureWriter,
    *,
    run_id: str,
    run_id_sha256: str,
    label: str,
    proposal: dict[str, Any],
    review_reason: str,
    mutations: list[dict[str, Any]],
) -> Mapping[str, Any]:
    proposal_payload = {
        "operation_id": f"dg13u-u1-{run_id}-{label}-proposal",
        "proposal": proposal,
        "confirmation": "SUBMIT",
    }
    try:
        proposed = writer.propose_as_submitter(proposal_payload)
        proposal_id = _identifier(proposed, "proposal_id", "PROPOSAL_ID_MISSING")
        proposal_mutation = {
            "kind": "PROPOSAL_CREATE",
            "role": "submitter",
            "proposal_id": proposal_id,
            "replayed": _replayed(proposed),
        }
    except Exception as exc:
        raise FixtureSeedError(
            "PROPOSAL_CREATE_FAILED", _partial_receipt(run_id_sha256, mutations)
        ) from exc
    mutations.append(proposal_mutation)
    review_payload = {
        "operation_id": f"dg13u-u1-{run_id}-{label}-review",
        "decision": "APPROVE",
        "policy_version": "dg13u-u1-synthetic-fixture-v1",
        "reason_code": review_reason,
    }
    try:
        reviewed = writer.review_as_steward(proposal_id, review_payload)
        review_mutation: dict[str, Any] = {
            "kind": "PROPOSAL_REVIEW",
            "role": "steward",
            "proposal_id": proposal_id,
            "claim_id": _identifier(reviewed, "claim_id", "REVIEW_CLAIM_ID_MISSING"),
            "outbox_id": _identifier(reviewed, "outbox_id", "REVIEW_OUTBOX_ID_MISSING"),
            "replayed": _replayed(reviewed),
        }
        if reviewed.get("claim_version_id") is not None:
            review_mutation["claim_version_id"] = _identifier(
                reviewed, "claim_version_id", "REVIEW_VERSION_ID_INVALID"
            )
    except Exception as exc:
        raise FixtureSeedError(
            "PROPOSAL_REVIEW_FAILED", _partial_receipt(run_id_sha256, mutations)
        ) from exc
    mutations.append(review_mutation)
    return reviewed


def _create_claim(
    writer: CanonicalFixtureWriter,
    family: StateFamily,
    *,
    run_id: str,
    run_id_sha256: str,
    observed_at: str,
    label: str,
    subject_id: str,
    scope_project: str,
    value: str,
    mutations: list[dict[str, Any]],
) -> dict[str, Any]:
    claim_payload = {"state_key": family.state_key, "value": value}
    evidence_id = _capture(
        writer,
        run_id=run_id,
        run_id_sha256=run_id_sha256,
        observed_at=observed_at,
        label=label,
        subject_id=subject_id,
        content=f"Synthetic {family.state_key} is {value}",
        mutations=mutations,
    )
    proposal = {
        "operation": "CREATE",
        "proposed_patch": {
            "subject_id": subject_id,
            "predicate": family.state_key,
            "claim_type": family.claim_type,
            "payload": claim_payload,
            "authority": "INFORMATIONAL",
            "confidence": 1.0,
        },
        "supporting_evidence_refs": [evidence_id],
        "scope_predicate": {"project_ids": [scope_project]},
        "requested_authority": "INFORMATIONAL",
        "derivation_policy_id": "dg13u-u1-deterministic-fixture-v1",
        "model_id": "deterministic-synthetic-fixture",
        "template_id": "v1",
        "derivation_snapshot": {
            "input_snapshot_sha256": _digest(
                {
                    "evidence_id": evidence_id,
                    "family": family.state_key,
                    "payload": claim_payload,
                    "scope": scope_project,
                }
            )
        },
    }
    reviewed = _propose_and_review(
        writer,
        run_id=run_id,
        run_id_sha256=run_id_sha256,
        label=label,
        proposal=proposal,
        review_reason="SYNTHETIC_FIXTURE_OBSERVATION_VERIFIED",
        mutations=mutations,
    )
    return {
        "project": family.project,
        "state_key": family.state_key,
        "claim_type": family.claim_type,
        "evidence_id": evidence_id,
        "claim_id": _identifier(reviewed, "claim_id", "REVIEW_CLAIM_ID_MISSING"),
        "claim_version_id": _identifier(
            reviewed, "claim_version_id", "REVIEW_VERSION_ID_MISSING"
        ),
        "payload_sha256": _digest(claim_payload),
        "scope_sha256": _digest({"project_ids": [scope_project]}),
    }


def _seed_open_issue(
    writer: CanonicalFixtureWriter,
    family: StateFamily,
    current: dict[str, Any],
    *,
    run_id: str,
    run_id_sha256: str,
    observed_at: str,
    mutations: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence_id = _capture(
        writer,
        run_id=run_id,
        run_id_sha256=run_id_sha256,
        observed_at=observed_at,
        label="open-issue",
        subject_id=family.project,
        content="Synthetic governed decision conflicts with the current decision",
        mutations=mutations,
    )
    proposal = {
        "target_claim_id": current["claim_id"],
        "operation": "CONTRADICT",
        "expected_version_id": current["claim_version_id"],
        "proposed_patch": {},
        "contradicting_evidence_refs": [evidence_id],
        "scope_predicate": {"project_ids": [family.project]},
        "requested_authority": "INFORMATIONAL",
        "derivation_policy_id": "dg13u-u1-deterministic-fixture-v1",
        "model_id": "deterministic-synthetic-fixture",
        "template_id": "v1",
        "derivation_snapshot": {
            "input_snapshot_sha256": _digest(
                {
                    "evidence_id": evidence_id,
                    "target_claim_id": current["claim_id"],
                    "operation": "CONTRADICT",
                }
            )
        },
    }
    reviewed = _propose_and_review(
        writer,
        run_id=run_id,
        run_id_sha256=run_id_sha256,
        label="open-issue",
        proposal=proposal,
        review_reason="SYNTHETIC_CONFLICT_CONFIRMED",
        mutations=mutations,
    )
    return {
        "state_key": family.state_key,
        "claim_id": current["claim_id"],
        "head_claim_version_id": current["claim_version_id"],
        "conflicting_evidence_id": evidence_id,
        "open_issue_id": _identifier(
            reviewed, "open_issue_id", "OPEN_ISSUE_ID_MISSING"
        ),
    }


def _seed_state_change(
    writer: CanonicalFixtureWriter,
    family: StateFamily,
    current: dict[str, Any],
    *,
    run_id: str,
    run_id_sha256: str,
    observed_at: str,
    mutations: list[dict[str, Any]],
) -> dict[str, Any]:
    changed_payload = {"state_key": family.state_key, "value": "ga-2026.08-u1"}
    evidence_id = _capture(
        writer,
        run_id=run_id,
        run_id_sha256=run_id_sha256,
        observed_at=observed_at,
        label="state-change",
        subject_id=family.project,
        content="Synthetic release target advanced to ga-2026.08-u1",
        mutations=mutations,
    )
    proposal = {
        "target_claim_id": current["claim_id"],
        "operation": "SUPERSEDE",
        "expected_version_id": current["claim_version_id"],
        "proposed_patch": {
            "payload": changed_payload,
            "authority": "INFORMATIONAL",
            "confidence": 1.0,
        },
        "supporting_evidence_refs": [evidence_id],
        "scope_predicate": {"project_ids": [family.project]},
        "requested_authority": "INFORMATIONAL",
        "derivation_policy_id": "dg13u-u1-deterministic-fixture-v1",
        "model_id": "deterministic-synthetic-fixture",
        "template_id": "v1",
        "derivation_snapshot": {
            "input_snapshot_sha256": _digest(
                {
                    "evidence_id": evidence_id,
                    "target_claim_id": current["claim_id"],
                    "payload": changed_payload,
                }
            )
        },
    }
    reviewed = _propose_and_review(
        writer,
        run_id=run_id,
        run_id_sha256=run_id_sha256,
        label="state-change",
        proposal=proposal,
        review_reason="SYNTHETIC_STATE_CHANGE_VERIFIED",
        mutations=mutations,
    )
    prior_version = str(current["claim_version_id"])
    current_version = _identifier(
        reviewed, "claim_version_id", "STATE_CHANGE_VERSION_ID_MISSING"
    )
    current["claim_version_id"] = current_version
    current["payload_sha256"] = _digest(changed_payload)
    return {
        "state_key": family.state_key,
        "claim_id": current["claim_id"],
        "prior_claim_version_id": prior_version,
        "current_claim_version_id": current_version,
        "supporting_evidence_id": evidence_id,
        "payload_sha256": _digest(changed_payload),
    }


def _revoke(
    writer: CanonicalFixtureWriter,
    evidence_id: str,
    *,
    run_id: str,
    run_id_sha256: str,
    label: str,
    mutations: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "operation_id": f"dg13u-u1-{run_id}-{label}-revoke",
        "reason_code": "SOURCE_REMOVED",
        "confirmation": "REVOKE",
    }
    try:
        result = writer.revoke_as_operator(evidence_id, payload)
        block_status = result.get("canonical_block_status")
        if block_status != "APPLIED":
            raise FixtureContractError("REVOCATION_DID_NOT_APPLY_CANONICAL_BLOCK")
        receipt = {
            "kind": "EVIDENCE_REVOKE",
            "role": "operator",
            "evidence_id": evidence_id,
            "deletion_request_id": _identifier(
                result, "deletion_request_id", "DELETION_REQUEST_ID_MISSING"
            ),
            "canonical_block_status": block_status,
            "replayed": _replayed(result),
        }
    except Exception as exc:
        raise FixtureSeedError(
            "EVIDENCE_REVOKE_FAILED", _partial_receipt(run_id_sha256, mutations)
        ) from exc
    mutations.append(receipt)
    return receipt


def seed_u1_canonical_fixture(
    writer: CanonicalFixtureWriter,
    *,
    run_id: str,
    observed_at: str,
    options: FixtureOptions | None = None,
) -> FixtureReceipt:
    """Seed the exact U1 families only through controlled role-separated writes."""

    families = load_candidate_families()
    _validate_invocation(run_id, observed_at)
    options = options or FixtureOptions()
    run_id_sha256 = hashlib.sha256(run_id.encode()).hexdigest()
    mutations: list[dict[str, Any]] = []
    seeded = [
        _create_claim(
            writer,
            family,
            run_id=run_id,
            run_id_sha256=run_id_sha256,
            observed_at=observed_at,
            label=family.state_key.replace(".", "-"),
            subject_id=family.project,
            scope_project=family.project,
            value=_CURRENT_VALUES[family.state_key],
            mutations=mutations,
        )
        for family in families
    ]
    by_key = {item["state_key"]: item for item in seeded}
    family_by_key = {family.state_key: family for family in families}
    negative_setups: dict[str, dict[str, Any]] = {}

    if options.wrong_scope:
        wrong = _create_claim(
            writer,
            family_by_key["release.target"],
            run_id=run_id,
            run_id_sha256=run_id_sha256,
            observed_at=observed_at,
            label="wrong-scope",
            subject_id=f"orchid-release-wrong-scope-{run_id_sha256[:12]}",
            scope_project="outside-orchid-release",
            value="wrong-scope-synthetic-target",
            mutations=mutations,
        )
        negative_setups["wrong_scope"] = {
            "state_key": wrong["state_key"],
            "claim_id": wrong["claim_id"],
            "claim_version_id": wrong["claim_version_id"],
            "evidence_id": wrong["evidence_id"],
            "scope_sha256": wrong["scope_sha256"],
        }
    if options.open_issue:
        negative_setups["open_issue"] = _seed_open_issue(
            writer,
            family_by_key["release.decision"],
            by_key["release.decision"],
            run_id=run_id,
            run_id_sha256=run_id_sha256,
            observed_at=observed_at,
            mutations=mutations,
        )
    if options.state_change:
        negative_setups["state_change"] = _seed_state_change(
            writer,
            family_by_key["release.target"],
            by_key["release.target"],
            run_id=run_id,
            run_id_sha256=run_id_sha256,
            observed_at=observed_at,
            mutations=mutations,
        )
    if options.revoke:
        revoke_receipt = _revoke(
            writer,
            str(by_key["release.database"]["evidence_id"]),
            run_id=run_id,
            run_id_sha256=run_id_sha256,
            label="negative",
            mutations=mutations,
        )
        negative_setups["revoke"] = {
            "state_key": "release.database",
            "claim_id": by_key["release.database"]["claim_id"],
            "evidence_id": revoke_receipt["evidence_id"],
            "deletion_request_id": revoke_receipt["deletion_request_id"],
            "canonical_block_status": revoke_receipt["canonical_block_status"],
        }

    observed_roles = {str(item["role"]) for item in mutations}
    roles = [
        role for role in ("submitter", "steward", "operator") if role in observed_roles
    ]
    return {
        "schema": "milai.dg13u.u1-canonical-fixture.v1",
        "status": "SEEDED",
        "candidate_fixture_sha256": CANDIDATE_SHA256,
        "run_id_sha256": run_id_sha256,
        "data_boundary": "SYNTHETIC",
        "formal_evaluation_input": False,
        "writer_roles": roles,
        "families": seeded,
        "negative_setups": negative_setups,
        "mutations": mutations,
    }


def apply_u1_state_change(
    writer: CanonicalFixtureWriter,
    seeded: Mapping[str, Any],
    *,
    run_id: str,
    observed_at: str,
) -> FixtureReceipt:
    """Apply the U1 target SUPERSEDE after a caller has warmed the current slot.

    The returned receipt is a new object containing both the original controlled
    writes and the post-warm mutation.  This keeps cleanup complete without
    mutating the caller's prior evidence snapshot.
    """

    load_candidate_families()  # revalidate the exact candidate before any write
    _validate_invocation(run_id, observed_at)
    run_id_sha256 = hashlib.sha256(run_id.encode()).hexdigest()
    required = {
        "schema",
        "status",
        "candidate_fixture_sha256",
        "run_id_sha256",
        "data_boundary",
        "formal_evaluation_input",
        "writer_roles",
        "families",
        "negative_setups",
        "mutations",
    }
    if (
        set(seeded) != required
        or seeded.get("schema") != "milai.dg13u.u1-canonical-fixture.v1"
        or seeded.get("status") != "SEEDED"
        or seeded.get("candidate_fixture_sha256") != CANDIDATE_SHA256
        or seeded.get("run_id_sha256") != run_id_sha256
        or seeded.get("data_boundary") != "SYNTHETIC"
        or seeded.get("formal_evaluation_input") is not False
    ):
        raise FixtureContractError("STATE_CHANGE_SEEDED_RECEIPT_INVALID")
    families = seeded.get("families")
    negative_setups = seeded.get("negative_setups")
    mutations = seeded.get("mutations")
    roles = seeded.get("writer_roles")
    if (
        not isinstance(families, list)
        or len(families) != 3
        or not isinstance(negative_setups, Mapping)
        or "state_change" in negative_setups
        or not isinstance(mutations, list)
        or not isinstance(roles, list)
        or any(not isinstance(role, str) for role in roles)
    ):
        raise FixtureContractError("STATE_CHANGE_SEEDED_RECEIPT_INVALID")

    updated = copy.deepcopy(dict(seeded))
    updated_families = updated["families"]
    target_rows = [
        row
        for row in updated_families
        if isinstance(row, dict) and row.get("state_key") == "release.target"
    ]
    if len(target_rows) != 1 or not {
        "claim_id",
        "claim_version_id",
        "payload_sha256",
    }.issubset(target_rows[0]):
        raise FixtureContractError("STATE_CHANGE_TARGET_BINDING_INVALID")
    target_family = next(
        family
        for family in load_candidate_families()
        if family.state_key == "release.target"
    )
    updated_mutations = updated["mutations"]
    state_change = _seed_state_change(
        writer,
        target_family,
        target_rows[0],
        run_id=run_id,
        run_id_sha256=run_id_sha256,
        observed_at=observed_at,
        mutations=updated_mutations,
    )
    updated["negative_setups"]["state_change"] = state_change
    observed_roles = {str(item["role"]) for item in updated_mutations}
    updated["writer_roles"] = [
        role for role in ("submitter", "steward", "operator") if role in observed_roles
    ]
    return FixtureReceipt(**updated)


def cleanup_u1_canonical_fixture(
    writer: CanonicalFixtureWriter,
    seeded: Mapping[str, Any],
    *,
    run_id: str,
) -> CleanupReceipt:
    """Fail closed by revoking every still-live Evidence created by one seed receipt."""

    if seeded.get("schema") != "milai.dg13u.u1-canonical-fixture.v1":
        raise FixtureContractError("cleanup requires a U1 canonical fixture receipt")
    expected_run_digest = hashlib.sha256(run_id.encode()).hexdigest()
    if seeded.get("run_id_sha256") != expected_run_digest:
        raise FixtureContractError("cleanup run identity mismatch")
    raw_mutations = seeded.get("mutations")
    if not isinstance(raw_mutations, list) or not all(
        isinstance(item, Mapping) for item in raw_mutations
    ):
        raise FixtureContractError("cleanup mutation receipt is invalid")
    evidence_ids = [
        str(item["evidence_id"])
        for item in raw_mutations
        if item.get("kind") == "EVIDENCE_CAPTURE"
        and isinstance(item.get("evidence_id"), str)
    ]
    already_revoked = {
        str(item["evidence_id"])
        for item in raw_mutations
        if item.get("kind") == "EVIDENCE_REVOKE"
        and isinstance(item.get("evidence_id"), str)
    }
    if not evidence_ids or len(evidence_ids) != len(set(evidence_ids)):
        raise FixtureContractError("cleanup Evidence identity set is invalid")
    cleanup_mutations: list[dict[str, Any]] = []
    for index, evidence_id in enumerate(evidence_ids, start=1):
        if evidence_id in already_revoked:
            continue
        _revoke(
            writer,
            evidence_id,
            run_id=run_id,
            run_id_sha256=expected_run_digest,
            label=f"cleanup-{index}",
            mutations=cleanup_mutations,
        )
    return {
        "schema": "milai.dg13u.u1-canonical-fixture-cleanup.v1",
        "status": "CLEANUP_REQUESTED",
        "run_id_sha256": expected_run_digest,
        "canonical_claims_deleted": False,
        "evidence_revocations": len(cleanup_mutations),
        "receipts": cleanup_mutations,
    }
