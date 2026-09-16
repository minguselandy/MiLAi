from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-22"
CANDIDATE = "candidate.1"
QUALITY_CONTRACT = ROOT / "docs/contracts/DG-10-quality-acceptance.yaml"
QUALITY_CONTRACT_SHA256 = (
    "50599ac26f478370f85655df8acaa4b278d7ea3e94aba4938110474b1fcf9f51"
)
QUALITY_REPORT = (
    ROOT
    / "docs/reports/DG-10-quality-calibration-assessment-candidate.1-2026-08-22.json"
)
QUALITY_REPORT_SHA256 = (
    "4df3da78254f356d77f687c2acfa66d6dd7a9a8fdeffc880903253057e6d31a9"
)
THREE_ARM_REPORT = (
    ROOT / "docs/reports/DG-10-benchmark-three-arm-dev-candidate.3-2026-08-22.json"
)
THREE_ARM_REPORT_SHA256 = (
    "6c7b2261e82bbbbc417f371983fbdea921e1f7f123f394c705cfd7091f5ee10e"
)
THREE_ARM_SIDECAR = (
    ROOT.parent / "evidence/dg10-benchmark-three-arm-dev/"
    "dg10-three-arm-dev-2026-08-22-56aac96f7c4f.raw.json"
)
THREE_ARM_SIDECAR_SHA256 = (
    "6d564fd8c1272f37799bd0c9f282512342a72d0cbcc7f2d21534ec8b19a85fcd"
)
RUBRIC = ROOT / "docs/contracts/DG-10-tier2-blinded-audit-rubric.md"
RUBRIC_SHA256 = "209e246042e90110cfee9aca57ae647bd77b397984665de682b5a4d05d81361e"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-tier2-blinded-audit-package-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = ROOT.parent / "evidence/dg10-tier2-blinded-audit"
ARMS = ("NO_MEMORY", "NAIVE_RAG", "MILAI_MCP")
ANSWER_IDS = ("A", "B", "C")
TIER2_CASES = (
    "longmemeval:118b2229",
    "longmemeval:18bc8abd",
    "longmemeval:19b5f2b3",
    "longmemeval:75832dbd",
    "longmemeval:88432d0a_abs",
    "longmemeval:ac031881",
    "longmemeval:b0479f84",
    "longmemeval:b759caee",
    "longmemeval:e61a7584",
    "longmemeval:ef66a6e5",
    "longmemeval:gpt4_ec93e27f",
    "longmemeval:gpt4_f49edff3",
)


class Tier2PackageError(RuntimeError):
    pass


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _json_sha256(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )


def _load_bound(path: Path, expected_sha256: str) -> dict[str, Any]:
    actual = _sha256_file(path)
    if actual != expected_sha256:
        raise Tier2PackageError(
            f"bound input drift: {path.name}: expected={expected_sha256} actual={actual}"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Tier2PackageError(f"bound input is not an object: {path.name}")
    return value


def _write_new(path: Path, raw: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)
    return {
        "filename": path.name,
        "sha256": _sha256_bytes(raw),
        "size": len(raw),
        "mode": "0600",
    }


def _records_by_case(
    sidecar: Mapping[str, Any],
) -> dict[str, dict[str, Mapping[str, Any]]]:
    records = sidecar.get("records")
    if not isinstance(records, list) or len(records) != 150:
        raise Tier2PackageError("three-arm raw denominator drift")
    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise Tier2PackageError("three-arm raw record is not an object")
        case_id = str(raw["case_id"])
        arm = str(raw["arm"])
        if arm not in ARMS:
            raise Tier2PackageError("unknown arm in three-arm sidecar")
        arms = grouped.setdefault(case_id, {})
        if arm in arms:
            raise Tier2PackageError("duplicate case/arm record")
        arms[arm] = raw
    for case_id in TIER2_CASES:
        if set(grouped.get(case_id, {})) != set(ARMS):
            raise Tier2PackageError(f"Tier-2 case arm denominator drift: {case_id}")
    return grouped


def _permutation(seed: bytes, case_id: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            ARMS,
            key=lambda arm: (
                hashlib.sha256(
                    seed + b"\0" + case_id.encode() + b"\0" + arm.encode()
                ).digest(),
                arm,
            ),
        )
    )


def _scan_blind_payload(value: object, *, allow_evidence: bool) -> None:
    forbidden_keys = {
        "arm",
        "arms",
        "execution_order",
        "input_tokens",
        "output_tokens",
        "model_rounds",
        "mcp_rounds",
        "exact_match",
        "normalized_f1",
        "deterministic_score",
    }
    if not allow_evidence:
        forbidden_keys |= {"memory_context", "retrieved_evidence_ids"}

    def walk(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key in forbidden_keys:
                    raise Tier2PackageError(
                        f"blind payload contains forbidden key: {key}"
                    )
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)
        elif isinstance(item, str) and item in ARMS:
            raise Tier2PackageError("blind payload contains an arm identity value")

    walk(value)


def build_packages(
    sidecar: Mapping[str, Any], *, seed: bytes, run_id: str, created_at: str
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    if len(seed) != 32:
        raise Tier2PackageError("randomization seed must contain exactly 32 bytes")
    grouped = _records_by_case(sidecar)
    blind_cases: list[dict[str, Any]] = []
    reveal_cases: list[dict[str, Any]] = []
    manifest_cases: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    adjudication_rows: list[dict[str, Any]] = []

    for ordinal, case_id in enumerate(TIER2_CASES, start=1):
        records = grouped[case_id]
        first = records[ARMS[0]]
        question = first["question"]
        gold_answers = first["gold_answers"]
        category = first["category"]
        if not isinstance(question, str) or not isinstance(gold_answers, list):
            raise Tier2PackageError("question/reference contract drift")
        for record in records.values():
            if (
                record.get("question") != question
                or record.get("gold_answers") != gold_answers
                or record.get("category") != category
            ):
                raise Tier2PackageError("case-internal question/reference drift")

        order = _permutation(seed, case_id)
        aliases = dict(zip(ANSWER_IDS, order, strict=True))
        audit_case_id = f"DG10-T2-{ordinal:02d}"
        answers: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        mapping: list[dict[str, str]] = []
        for answer_id in ANSWER_IDS:
            arm = aliases[answer_id]
            record = records[arm]
            answer_text = record.get("parsed_answer")
            memory_context = record.get("memory_context")
            evidence_ids = record.get("retrieved_evidence_ids")
            if (
                not isinstance(answer_text, str)
                or not isinstance(memory_context, str)
                or not isinstance(evidence_ids, list)
            ):
                raise Tier2PackageError("answer/evidence contract drift")
            answers.append({"answer_id": answer_id, "answer_text": answer_text})
            evidence.append(
                {
                    "answer_id": answer_id,
                    "bounded_evidence_text": (
                        memory_context if memory_context else "[none supplied]"
                    ),
                    "evidence_ids": list(evidence_ids),
                }
            )
            mapping.append({"answer_id": answer_id, "arm_identity": arm})
            annotation_rows.append(
                {
                    "audit_case_id": audit_case_id,
                    "answer_id": answer_id,
                    "answer_correctness": None,
                    "uncertainty_calibration": None,
                    "preference_rank": None,
                    "reason_codes": [],
                    "tie_reason_code": None,
                    "redacted_note": None,
                }
            )
            adjudication_rows.append(
                {
                    "audit_case_id": audit_case_id,
                    "answer_id": answer_id,
                    "conflict_fields": [],
                    "adjudicated_answer_correctness": None,
                    "adjudicated_support_status": None,
                    "adjudicated_uncertainty_calibration": None,
                    "adjudicated_preference_rank": None,
                    "reason_codes": [],
                    "redacted_note": None,
                }
            )
        blind_cases.append(
            {
                "audit_case_id": audit_case_id,
                "source_case_id": case_id,
                "stratum": category,
                "question": question,
                "reference_answers": gold_answers,
                "answers": answers,
            }
        )
        reveal_cases.append(
            {
                "audit_case_id": audit_case_id,
                "source_case_id": case_id,
                "answer_evidence": evidence,
            }
        )
        manifest_cases.append(
            {
                "audit_case_id": audit_case_id,
                "source_case_id": case_id,
                "answer_mapping": mapping,
            }
        )

    seed_commitment = _sha256_bytes(seed)
    blind_package = {
        "schema": "milai.dg10.tier2-blind-package.v1",
        "protocol": "DG10_TIER2_BLINDED_HUMAN_AUDIT_V1",
        "run_id": run_id,
        "created_at": created_at,
        "stage": "FIRST_PASS",
        "status": "READY_FOR_TWO_INDEPENDENT_HUMAN_ANNOTATORS",
        "public_dev_data_only": True,
        "test_labels_or_outputs_included": False,
        "randomization_seed_sha256_commitment": seed_commitment,
        "rubric_sha256": RUBRIC_SHA256,
        "instructions": {
            "annotators_required": 2,
            "work_independently": True,
            "do_not_open_before_first_pass_lock": "evidence-reveal-package.json",
            "do_not_open_until_adjudication_complete": "randomization-manifest.json",
            "allowed_answer_correctness": [
                "CORRECT",
                "PARTIALLY_CORRECT",
                "INCORRECT",
                "AMBIGUOUS_REFERENCE",
            ],
            "allowed_uncertainty_calibration": [
                "APPROPRIATE",
                "OVERCONFIDENT",
                "UNNECESSARILY_ABSTAINED",
            ],
            "allowed_reason_codes": [
                "LATEST_STATE",
                "TEMPORAL_ORDER",
                "ENTITY_MISMATCH",
                "MISSING_DETAIL",
                "EXTRA_UNSUPPORTED_DETAIL",
                "REFERENCE_AMBIGUITY",
                "OTHER_REDACTED_NOTE",
            ],
        },
        "case_count": len(blind_cases),
        "answer_count": len(annotation_rows),
        "cases": blind_cases,
    }
    evidence_reveal = {
        "schema": "milai.dg10.tier2-evidence-reveal-package.v1",
        "protocol": "DG10_TIER2_BLINDED_HUMAN_AUDIT_V1",
        "run_id": run_id,
        "created_at": created_at,
        "stage": "SUPPORT_ADJUDICATION_AFTER_FIRST_PASS_LOCK",
        "status": "SEALED_UNTIL_BOTH_FIRST_PASS_FILES_ARE_HASH_LOCKED",
        "allowed_support_status": [
            "SUPPORTED",
            "UNSUPPORTED",
            "CONFLICTING",
            "NOT_ASSESSABLE",
        ],
        "cases": reveal_cases,
    }
    manifest = {
        "schema": "milai.dg10.tier2-randomization-manifest.v1",
        "protocol": "DG10_TIER2_BLINDED_HUMAN_AUDIT_V1",
        "run_id": run_id,
        "created_at": created_at,
        "classification": "WITHHOLD_FROM_ANNOTATORS_AND_ADJUDICATOR_UNTIL_ALL_LABELS_LOCKED",
        "seed_hex": seed.hex(),
        "seed_sha256_commitment": seed_commitment,
        "permutation_algorithm": "SHA256(seed_bytes || NUL || case_id || NUL || arm_identity), ascending digest",
        "cases": manifest_cases,
    }
    annotation_template = {
        "schema": "milai.dg10.tier2-independent-annotation.v1",
        "protocol": "DG10_TIER2_BLINDED_HUMAN_AUDIT_V1",
        "run_id": run_id,
        "annotator_pseudonym": None,
        "human_attestation": None,
        "independent_work_attestation": None,
        "blind_package_sha256": "POPULATED_IN_PACKAGE_INDEX",
        "first_pass_locked_at": None,
        "first_pass_rows": annotation_rows,
        "evidence_reveal_opened_at": None,
        "support_rows": [
            {
                "audit_case_id": row["audit_case_id"],
                "answer_id": row["answer_id"],
                "support_status": None,
                "reason_codes": [],
                "redacted_note": None,
            }
            for row in annotation_rows
        ],
        "completed_at": None,
        "signature_or_receipt": None,
    }
    adjudication_template = {
        "schema": "milai.dg10.tier2-conflict-adjudication.v1",
        "protocol": "DG10_TIER2_BLINDED_HUMAN_AUDIT_V1",
        "run_id": run_id,
        "adjudicator_pseudonym": None,
        "human_attestation": None,
        "annotator_1_sha256": None,
        "annotator_2_sha256": None,
        "conflict_count": None,
        "rows": adjudication_rows,
        "completed_at": None,
        "signature_or_receipt": None,
    }
    _scan_blind_payload(blind_package, allow_evidence=False)
    _scan_blind_payload(evidence_reveal, allow_evidence=True)
    _scan_blind_payload(annotation_template, allow_evidence=False)
    _scan_blind_payload(adjudication_template, allow_evidence=False)
    return (
        blind_package,
        evidence_reveal,
        manifest,
        annotation_template,
        adjudication_template,
    )


def _validate_bound_contracts(
    quality_report: Mapping[str, Any], three_arm_report: Mapping[str, Any]
) -> None:
    tier2 = quality_report.get("tier_2_manifest")
    if (
        not isinstance(tier2, dict)
        or tuple(tier2.get("case_ids", [])) != TIER2_CASES
        or tier2.get("case_ids_sha256")
        != "286fcfb4fad5bc3eb6a909cc31eb33eba00b4414a5a5db499789398fcaa3628b"
        or tier2.get("rubric_sha256") != RUBRIC_SHA256
        or tier2.get("human_annotations_present") is not False
    ):
        raise Tier2PackageError("frozen Tier-2 manifest drift")
    sidecar = three_arm_report.get("repo_external_sidecar")
    if (
        not isinstance(sidecar, dict)
        or sidecar.get("sha256") != THREE_ARM_SIDECAR_SHA256
        or sidecar.get("mode") != "0600"
    ):
        raise Tier2PackageError("three-arm sidecar binding drift")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the frozen DG-10 Tier-2 blind package"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument(
        "--seed-hex",
        help="exactly 64 hex characters; omit for a fresh cryptographic seed",
    )
    args = parser.parse_args()

    _ = _sha256_file(QUALITY_CONTRACT)
    if _ != QUALITY_CONTRACT_SHA256:
        raise Tier2PackageError("quality contract drift")
    if _sha256_file(RUBRIC) != RUBRIC_SHA256:
        raise Tier2PackageError("Tier-2 rubric drift")
    quality_report = _load_bound(QUALITY_REPORT, QUALITY_REPORT_SHA256)
    three_arm_report = _load_bound(THREE_ARM_REPORT, THREE_ARM_REPORT_SHA256)
    sidecar = _load_bound(THREE_ARM_SIDECAR, THREE_ARM_SIDECAR_SHA256)
    _validate_bound_contracts(quality_report, three_arm_report)

    if args.seed_hex is None:
        seed = secrets.token_bytes(32)
    else:
        try:
            seed = bytes.fromhex(args.seed_hex)
        except ValueError as exc:
            raise Tier2PackageError("--seed-hex is not valid hex") from exc
        if len(seed) != 32 or args.seed_hex.lower() != seed.hex():
            raise Tier2PackageError(
                "--seed-hex must be exactly 64 lowercase hex characters"
            )
    created_at = datetime.now(UTC).isoformat()
    run_id = f"dg10-tier2-blind-{DATE}-{uuid4().hex[:12]}"
    package_values = build_packages(
        sidecar, seed=seed, run_id=run_id, created_at=created_at
    )
    names = (
        "blind-package.json",
        "evidence-reveal-package.json",
        "randomization-manifest.json",
        "independent-annotation-template.json",
        "conflict-adjudication-template.json",
    )
    capture_directory = args.capture_directory.resolve() / run_id
    captures: dict[str, Any] = {}
    for name, value in zip(names, package_values, strict=True):
        captures[name] = _write_new(capture_directory / name, _json_bytes(value))

    blind_sha = captures["blind-package.json"]["sha256"]
    annotation_index = {
        "schema": "milai.dg10.tier2-package-index.v1",
        "run_id": run_id,
        "created_at": created_at,
        "blind_package_sha256": blind_sha,
        "randomization_manifest_sha256": captures["randomization-manifest.json"][
            "sha256"
        ],
        "files": captures,
        "workflow": [
            "Give blind-package.json and independent-annotation-template.json separately to two independent human annotators.",
            "Hash-lock both first-pass files before releasing evidence-reveal-package.json.",
            "Hash-lock both completed support files, compute conflicts, and give only conflict rows to a third human adjudicator.",
            "Keep randomization-manifest.json sealed until adjudication is complete; then aggregate and reveal arm identities.",
        ],
    }
    captures["package-index.json"] = _write_new(
        capture_directory / "package-index.json", _json_bytes(annotation_index)
    )

    report = {
        "schema": "milai.dg10.tier2-blinded-audit-package-receipt.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "created_at": created_at,
        "run_id": run_id,
        "status": "PACKAGE_READY_AUDIT_NOT_STARTED_WAITING_FOR_HUMANS",
        "quality_outcome": "BELOW_TARGET_UNCHANGED",
        "test_access_authorized": False,
        "test_labels_or_outputs_opened": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "inputs": {
            "quality_contract_sha256": QUALITY_CONTRACT_SHA256,
            "quality_report_sha256": QUALITY_REPORT_SHA256,
            "three_arm_report_sha256": THREE_ARM_REPORT_SHA256,
            "three_arm_raw_sidecar_sha256": THREE_ARM_SIDECAR_SHA256,
            "rubric_sha256": RUBRIC_SHA256,
            "tier2_case_ids_sha256": "286fcfb4fad5bc3eb6a909cc31eb33eba00b4414a5a5db499789398fcaa3628b",
        },
        "package": {
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "directory_id": run_id,
            "files": captures,
            "case_count": 12,
            "answer_count": 36,
            "randomization_seed_sha256_commitment": _sha256_bytes(seed),
            "arm_identity_absent_from_blind_and_reveal_packages": True,
            "tokens_scores_execution_order_absent_from_blind_package": True,
            "raw_public_dev_questions_answers_evidence_repo_external_only": True,
        },
        "human_requirements": {
            "independent_annotators_required": 2,
            "independent_annotators_completed": 0,
            "third_human_adjudicator_required_on_conflict": True,
            "adjudication_completed": False,
            "codex_is_human_annotator": False,
            "same_vllm_is_human_annotator": False,
        },
        "gate_results": {
            "blind_package_generated": "PASS",
            "randomization_manifest_hash_bound": "PASS",
            "first_pass_evidence_separation": "PASS",
            "arm_mapping_withheld": "PASS",
            "human_audit": "NOT_STARTED_EXTERNAL_HUMANS_REQUIRED",
            "tier2_complete": "NO",
        },
        "release_effect": {
            "may_override_tier1_below_target": False,
            "may_authorize_test": False,
            "may_support_local_candidate_claim": False,
        },
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise Tier2PackageError(f"refusing to overwrite report: {output}")
    output.write_bytes(_json_bytes(report))
    os.chmod(output, 0o600)
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(output),
                "sha256": _sha256_file(output),
                "capture_directory": str(capture_directory),
                "package_index_sha256": captures["package-index.json"]["sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
