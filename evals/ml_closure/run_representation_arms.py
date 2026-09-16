"""Generate label-blind R/F/E outputs from one official acquisition snapshot."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from milai.application.formation_recollection import recollect_with_formation
from milai.domain.formation_artifact import FormationArtifactSidecarV01
from milai.domain.formation_state import FormationStateChangeSidecarV01
from milai.domain.requirement_state import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "var/ml_closure/ml-closure-20260830-001"
RAW = ROOT / "evals/datasets/ml_closure/sealed-validation.raw.json"
BASELINE = RUN_DIR / "checkpoints/c0-candidate-r-unscored.json"
FORMATION = RUN_DIR / "checkpoints/c1-v02-sealed-unscored.json"
OUTPUT = RUN_DIR / "checkpoints/c2-rfe-unscored.json"


class RepresentationArmError(RuntimeError):
    """A frozen input identity or matched-arm contract drifted."""


def execute() -> dict[str, Any]:
    if OUTPUT.exists():
        raise RepresentationArmError("C2_RFE_OUTPUT_ALREADY_EXISTS")
    raw = _object(RAW)
    baseline = _object(BASELINE)
    formation = _object(FORMATION)
    _verify_digest(baseline, "result_digest")
    _verify_digest(formation, "output_digest")
    if baseline.get("status") != "PASS_C0_CANDIDATE_R_REPRODUCTION":
        raise RepresentationArmError("CANDIDATE_R_BASELINE_NOT_PASS")
    if baseline.get("raw_sha256") != formation.get("raw_sha256"):
        raise RepresentationArmError("R_F_RAW_SNAPSHOT_DRIFT")

    raw_by_id = {
        str(item["conversation_id"]): item
        for item in cast(list[dict[str, Any]], raw["conversations"])
    }
    baseline_by_id = {
        str(item["conversation_id"]): item
        for item in cast(list[dict[str, Any]], baseline["rows"])
    }
    formation_by_id = {
        str(item["conversation_id"]): item
        for item in cast(list[dict[str, Any]], formation["rows"])
    }
    if not (
        set(raw_by_id) == set(baseline_by_id) == set(formation_by_id)
        and len(raw_by_id) == 60
    ):
        raise RepresentationArmError("C2_RFE_CASE_IDENTITY_DRIFT")

    arms: dict[str, list[dict[str, Any]]] = {"R": [], "F": [], "E": []}
    for conversation_id in sorted(raw_by_id):
        conversation = raw_by_id[conversation_id]
        query = cast(list[dict[str, Any]], conversation["queries"])[0]
        raw_row = baseline_by_id[conversation_id]
        formation_row = formation_by_id[conversation_id]
        formation_sidecar = FormationArtifactSidecarV01.model_validate(
            formation_row["formation"]
        )
        state_sidecar = FormationStateChangeSidecarV01.model_validate(
            formation_row["state_changes"]
        )
        common = {
            "conversation_id": conversation_id,
            "query_id": query["query_id"],
            "stratum": query["stratum"],
        }
        arms["R"].append(
            {
                **common,
                "accepted_evidence_ids": raw_row["accepted_evidence_ids"],
                "complete": raw_row["status"] == "HIT",
                "status": raw_row["status"],
                "formed_evidence_ids": [],
                "raw_fallback_evidence_ids": raw_row["accepted_evidence_ids"],
            }
        )
        for arm, representation in (
            ("F", "FORMED_PLUS_RAW"),
            ("E", "FORMED_ONLY"),
        ):
            result = recollect_with_formation(
                query=str(query["question"]),
                formation=formation_sidecar,
                state_changes=state_sidecar,
                source_records=cast(list[dict[str, Any]], conversation["turns"]),
                raw_candidate_evidence_ids=cast(
                    list[str], raw_row["accepted_evidence_ids"]
                ),
                representation=representation,  # type: ignore[arg-type]
            )
            arms[arm].append(
                {
                    **common,
                    "accepted_evidence_ids": list(result.accepted_evidence_ids),
                    "complete": result.complete,
                    "status": "HIT" if result.complete else "ABSTAINED",
                    "required_facets": list(result.required_facets),
                    "covered_facets": list(result.covered_facets),
                    "formed_evidence_ids": list(result.formed_evidence_ids),
                    "raw_fallback_evidence_ids": list(
                        result.raw_fallback_evidence_ids
                    ),
                }
            )

    output: dict[str, Any] = {
        "schema": "milai.ml-closure.rfe-unscored.v0.1",
        "arms": arms,
        "matched_identity": {
            "raw_sha256": baseline["raw_sha256"],
            "candidate_r_output_digest": baseline["output_digest"],
            "formation_output_digest": formation["output_digest"],
            "query_order": [item["query_id"] for item in arms["R"]],
            "candidate_ceiling": 24,
            "hydration_ceiling": 12,
            "official_actions_per_query": 1,
            "model_calls_per_query": 0,
            "reader_calls_per_query": 0,
        },
        "implementation": {
            "R": "POST /v1/memory/resolve",
            "F": "runtime formation_recollection + Raw fallback",
            "E": "runtime formation_recollection, Raw fallback disabled",
            "eval_owned_retrieval": False,
        },
        "query_visible_to_formation": False,
        "labels_visible_to_arms": False,
        "formal_holdout_used": False,
    }
    output["output_digest"] = canonical_sha256(output)
    _write_exclusive(OUTPUT, output)
    return output


def _verify_digest(value: dict[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != canonical_sha256(material):
        raise RepresentationArmError(f"DIGEST_INVALID:{field}")


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RepresentationArmError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


if __name__ == "__main__":
    result = execute()
    print(result["output_digest"])
