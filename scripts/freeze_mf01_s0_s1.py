#!/usr/bin/env python3
"""Seal MF-01 S0 actual paths and S1 labels; never start the S2 effect."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.domain.requirement_state import canonical_sha256

from evals.mf01.labels import (
    BASE_LABELS,
    RAW_SNAPSHOT,
    SUPPLEMENT,
    build_label_seal,
)

RUN_LOCK = ROOT / "var/mf01/run-lock.json"
RUN_ID = "mf01-s0-s1-formation-audit-design-20260830-001"
PRODUCT_BASELINE = Path("var/dg12/product/core-baseline-e2e.json")

STAGE_PATHS = (
    "runtime/src/milai/application/evidence.py",
    "runtime/src/milai/application/episodes.py",
    "runtime/src/milai/application/evidence_semantics.py",
    "runtime/src/milai/application/derivation.py",
    "runtime/src/milai/application/proposals.py",
    "runtime/src/milai/domain/temporal_proof.py",
    "runtime/src/milai/workers/main.py",
    "runtime/src/milai/persistence/evidence_repository.py",
    "runtime/src/milai/persistence/canonical_repository.py",
    "runtime/src/milai/persistence/projection_repository.py",
    "runtime/src/milai/persistence/retrieval_repository.py",
    "runtime/migrations/versions/0015_governed_proposals_and_complete_history.py",
    "runtime/migrations/versions/0033_dg15_projection_pipeline.py",
    "runtime/migrations/versions/0044_dg17_evidence_dense_projection.py",
)
BOUND_PATHS = (
    str(RAW_SNAPSHOT),
    str(BASE_LABELS),
    str(SUPPLEMENT),
    "evals/mf01/labels.py",
    "scripts/freeze_mf01_s0_s1.py",
    "tests/test_mf01_s0_s1_design.py",
    *STAGE_PATHS,
    "runtime/.env.example",
    "runtime/compose.yaml",
    "runtime/pyproject.toml",
    str(PRODUCT_BASELINE),
    "MiLAi_Memory_Lifecycle_项目级架构与主程序_MASTER.md",
    "MiLAi_MF-01_Formation_First-Loss_Audit_GOALS.md",
)


class MF01FreezeError(RuntimeError):
    """The observation-only S0-S1 contract cannot be sealed safely."""


def stage_availability_map() -> list[dict[str, Any]]:
    """Describe current product capabilities without simulating missing stages."""

    return [
        {
            "stage": "F00_RAW_EVIDENCE_CAPTURED",
            "availability": "IMPLEMENTED",
            "owner": "EvidenceService.ingest",
            "paths": [
                "runtime/src/milai/application/evidence.py",
                "runtime/src/milai/persistence/evidence_repository.py",
            ],
            "machine_fact": "typed Evidence plus blob and outbox capture exists",
        },
        {
            "stage": "F10_EPISODE_FORMED",
            "availability": "NOT_IMPLEMENTED",
            "owner": None,
            "paths": ["runtime/src/milai/application/episodes.py"],
            "machine_fact": (
                "EpisodeService creates and settles caller-defined capture containers; "
                "it does not derive semantic episode boundaries"
            ),
            "adjacent_non_equivalent_capability": "EpisodeService.create/settle",
        },
        {
            "stage": "F20_MENTION_FORMED",
            "availability": "NOT_IMPLEMENTED",
            "owner": None,
            "paths": ["runtime/src/milai/application/evidence_semantics.py"],
            "machine_fact": (
                "Evidence spans are projected only during query-local recollection; no "
                "formation-time mention artifact exists"
            ),
            "adjacent_non_equivalent_capability": "project_evidence_spans",
        },
        {
            "stage": "F30_IDENTITY_RESOLVED",
            "availability": "NOT_IMPLEMENTED",
            "owner": None,
            "paths": [
                "runtime/src/milai/application/evidence_semantics.py",
                "runtime/src/milai/domain/temporal_proof.py",
            ],
            "machine_fact": (
                "query-time interpretation and event dedup identities exist; no "
                "formation-time entity/event identity sidecar exists"
            ),
            "adjacent_non_equivalent_capability": (
                "interpret_evidence_spans/build_event_identity_v01"
            ),
        },
        {
            "stage": "F40_EVENT_TIME_GROUNDED",
            "availability": "NOT_IMPLEMENTED",
            "owner": None,
            "paths": ["runtime/src/milai/application/evidence_semantics.py"],
            "machine_fact": (
                "event time is resolved query-locally with source time kept separate; no "
                "formation-time grounded time artifact exists"
            ),
            "adjacent_non_equivalent_capability": "interpret_evidence_spans",
        },
        {
            "stage": "F50_STATE_OR_CHANGE_FORMED",
            "availability": "NOT_IMPLEMENTED",
            "owner": None,
            "paths": ["runtime/src/milai/application/derivation.py"],
            "machine_fact": (
                "DeriveAndDiagnose classifies an already schema-validated caller patch; "
                "it does not extract state or change from Evidence"
            ),
            "adjacent_non_equivalent_capability": "DeriveAndDiagnose.derive",
        },
        {
            "stage": "F60_PROPOSAL_EMITTED",
            "availability": "IMPLEMENTED_EXPLICIT_CALLER_ONLY",
            "owner": "ProposalService.create",
            "paths": [
                "runtime/src/milai/application/proposals.py",
                "runtime/src/milai/persistence/canonical_repository.py",
            ],
            "machine_fact": (
                "typed governed proposals are durable when an authorized caller supplies "
                "the complete ProposalCreateRequest"
            ),
        },
        {
            "stage": "F70_CANONICAL_DISPOSITION",
            "availability": "IMPLEMENTED_GOVERNED",
            "owner": "ProposalService.review/CanonicalRepository.review_proposal",
            "paths": [
                "runtime/src/milai/application/proposals.py",
                "runtime/migrations/versions/0015_governed_proposals_and_complete_history.py",
            ],
            "machine_fact": (
                "Steward review owns canonical ClaimVersion/OpenIssue disposition; automatic "
                "commit remains disabled"
            ),
        },
        {
            "stage": "F80_RETRIEVAL_PROJECTION_BUILT",
            "availability": "IMPLEMENTED_RAW_AND_CANONICAL_READ_PATHS",
            "owner": "FoundationWorker/RetrievalRepository",
            "paths": [
                "runtime/src/milai/workers/main.py",
                "runtime/src/milai/persistence/projection_repository.py",
                "runtime/src/milai/persistence/retrieval_repository.py",
                "runtime/migrations/versions/0033_dg15_projection_pipeline.py",
                "runtime/migrations/versions/0044_dg17_evidence_dense_projection.py",
            ],
            "machine_fact": (
                "raw Evidence FTS/vector projections and governed canonical retrieval paths "
                "exist with watermarks and runtime gates"
            ),
        },
    ]


def freeze(path: Path = RUN_LOCK) -> dict[str, Any]:
    if path.exists():
        raise MF01FreezeError("MF01_RUN_LOCK_ALREADY_EXISTS")
    _verify_expected_symbols()
    seal = build_label_seal(ROOT)
    if not seal.adequate_for_s2_entry_review:
        raise MF01FreezeError("MF01_INSUFFICIENT_LIFECYCLE_LABELS")
    stage_map = stage_availability_map()
    if [item["stage"] for item in stage_map] != [
        "F00_RAW_EVIDENCE_CAPTURED",
        "F10_EPISODE_FORMED",
        "F20_MENTION_FORMED",
        "F30_IDENTITY_RESOLVED",
        "F40_EVENT_TIME_GROUNDED",
        "F50_STATE_OR_CHANGE_FORMED",
        "F60_PROPOSAL_EMITTED",
        "F70_CANONICAL_DISPOSITION",
        "F80_RETRIEVAL_PROJECTION_BUILT",
    ]:
        raise MF01FreezeError("MF01_STAGE_MAP_DRIFT")
    product_baseline = _object(ROOT / PRODUCT_BASELINE)
    if product_baseline.get("status") != "PASS":
        raise MF01FreezeError("MF01_PRODUCT_BASELINE_NOT_PASS")

    material: dict[str, Any] = {
        "schema": "milai.mf01.s0-s1.run-lock.v0.1",
        "goal_id": "MF-01",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "execution_authority": "MILA-ML-MASTER@1.1",
        "architecture_baseline": "MILA-ML-ARCH@1.0",
        "scope": {
            "authorized_stages": ["S0_ACTUAL_PATH_FREEZE", "S1_LABEL_SEAL"],
            "S2_passive_trace": "NOT_STARTED_NOT_AUTHORIZED_BY_CURRENT_MASTER_STATE",
            "S3_first_loss_score": "NOT_STARTED",
            "S4_terminal": "NOT_STARTED",
            "effect_run": False,
        },
        "S0_actual_path_freeze": {
            "status": "SEALED",
            "stage_availability": stage_map,
            "legal_trace_outcomes": [
                "SURVIVED",
                "FIRST_LOSS",
                "NOT_APPLICABLE",
                "NOT_IMPLEMENTED",
                "AUTHORIZED_REJECTION",
            ],
            "missing_stages_simulated": False,
            "product_behavior_changed": False,
            "product_output_baseline": {
                **_identity(ROOT / PRODUCT_BASELINE),
                "use": "REFERENCE_PRE_AUDIT_PRODUCT_OUTPUT",
                "fresh_behavior_equivalence_required_before_S2": True,
            },
        },
        "S1_label_seal": {
            "status": "SEALED",
            "label_schema": seal.schema_version,
            "label_seal_digest": seal.seal_digest,
            "label_count": seal.label_count,
            "case_count": seal.case_count,
            "counts_by_kind": seal.counts_by_kind,
            "counts_by_origin": seal.counts_by_origin,
            "scope_coverage": seal.scope_coverage,
            "determinability": seal.determinability,
            "local_label_and_snapshot_gate": "PASS",
            "adequate_for_S2_entry_review": seal.adequate_for_s2_entry_review,
            "allowed_analysis_unit": "SEALED_SOURCE_GROUNDED_OBLIGATION_ONLY",
            "scorer_opened": False,
        },
        "S2_entry_gates": {
            "label_adequacy": "PASS",
            "evidence_snapshot_sealed": True,
            "product_output_baseline_sealed": True,
            "passive_trace_hook_implemented": False,
            "trace_hook_behavior_equivalence_smoke": "PENDING_NOT_STARTED",
            "current_master_authorization": "S0_S1_ONLY",
            "effect_authorized": False,
        },
        "bound_identities": [_identity(ROOT / value) for value in BOUND_PATHS],
        "safety": {
            "formal_holdout_used": False,
            "introduced_provider_calls": 0,
            "canonical_mutations_caused_by_audit": 0,
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
            "trace_artifact_written": False,
            "results_artifact_written": False,
            "terminal_artifact_written": False,
        },
        "next_authorized_action": (
            "PAUSE_BEFORE_S2_UNTIL_MASTER_AUTHORIZES_AND_BEHAVIOR_EQUIVALENCE_HOOK_GATE_PASSES"
        ),
    }
    material["lock_digest"] = canonical_sha256(material)
    _write_exclusive(path, material)
    return material


def validate(path: Path = RUN_LOCK) -> dict[str, Any]:
    lock = _object(path)
    material = dict(lock)
    observed = material.pop("lock_digest", None)
    if observed != canonical_sha256(material):
        raise MF01FreezeError("MF01_RUN_LOCK_DIGEST_MISMATCH")
    for identity in lock.get("bound_identities", []):
        expected = _object_value(identity, "bound identity")
        if _identity(ROOT / str(expected["path"])) != expected:
            raise MF01FreezeError(f"MF01_BOUND_IDENTITY_DRIFT:{expected['path']}")
    seal = build_label_seal(ROOT)
    sealed = _object_value(lock.get("S1_label_seal"), "S1 label seal")
    if seal.seal_digest != sealed.get("label_seal_digest"):
        raise MF01FreezeError("MF01_LABEL_SEAL_REPLAY_DRIFT")
    return {
        "valid": True,
        "scope": "S0_S1_ONLY",
        "label_count": seal.label_count,
        "label_seal_digest": seal.seal_digest,
        "lock_digest": lock["lock_digest"],
        "effect_started": False,
    }


def _verify_expected_symbols() -> None:
    checks = {
        "runtime/src/milai/application/evidence.py": (
            "class EvidenceService",
            "def ingest(",
        ),
        "runtime/src/milai/application/episodes.py": (
            "class EpisodeService",
            "def create(",
            "def settle(",
        ),
        "runtime/src/milai/application/derivation.py": (
            "class DeriveAndDiagnose",
            "Classify an already schema-validated candidate",
        ),
        "runtime/src/milai/application/proposals.py": (
            "class ProposalService",
            "def create(",
            "def review(",
        ),
        "runtime/src/milai/workers/main.py": (
            "class FoundationWorker",
            "def _process(",
        ),
        "runtime/src/milai/persistence/retrieval_repository.py": (
            "def canonical_search(",
            "def recent_canonical_candidates(",
        ),
    }
    for relative, symbols in checks.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for symbol in symbols:
            if symbol not in text:
                raise MF01FreezeError(f"MF01_EXPECTED_SYMBOL_MISSING:{relative}:{symbol}")


def _identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MF01FreezeError(f"MF01_BOUND_PATH_MISSING:{path}")
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "size": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _object_value(value, str(path))


def _object_value(value: object, source: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MF01FreezeError(f"MF01_JSON_OBJECT_REQUIRED:{source}")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "validate"))
    args = parser.parse_args()
    output = freeze() if args.command == "freeze" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
