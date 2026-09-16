"""Lean DG-30 admission and rollback evaluation for the repaired read path."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from milai.application.decision_boundary import decide_deterministic_boundary
from milai.domain.requirement_state import canonical_sha256

from evals.dg28.formation_consumption import (
    execute_formation_consumption_replay,
    score_formation_consumption_replay,
)
from evals.dg28.lite_effect import execute_lite_effect, score_lite_effect

DG27_RECEIPT = Path(
    "var/dg27/v05/dg27-v05-mf03-replay-20260830-001/receipt.json"
)
DG28_LITE_RECEIPT = Path(
    "var/dg28/lite/dg28-lite-lexical-union-20260830-001/receipt.json"
)
MF03_RECEIPT = Path(
    "var/mf03/mf03-formation-sidecar-20260830-004/receipt.json"
)
DG28_FORMATION_RECEIPT = Path(
    "var/dg28/formation/dg28-formation-consumption-20260830-002/receipt.json"
)


class DG30IntegrationError(RuntimeError):
    """A predecessor or behavior-equivalence check drifted."""


def evaluate_read_path_integration(root: Path) -> dict[str, Any]:
    """Recompute admitted effects and prove the default-off rollback path."""

    root = root.resolve()
    predecessors = {
        "DG27": _object(root / DG27_RECEIPT),
        "DG28_LITE": _object(root / DG28_LITE_RECEIPT),
        "MF03": _object(root / MF03_RECEIPT),
        "DG28_FORMATION": _object(root / DG28_FORMATION_RECEIPT),
    }
    expected = {
        "DG27": "PASS_DECISION_BOUNDARY_REPAIRED",
        "DG28_LITE": "PASS_DG28_LITE_RETRIEVAL_GAIN",
        "MF03": "PASS_MF03_FORMATION_IDENTITY_TIME",
        "DG28_FORMATION": "PASS_DG28_FORMATION_CONSUMPTION_CLOSURE",
    }
    if any(predecessors[key].get("status") != status for key, status in expected.items()):
        raise DG30IntegrationError("DG30_PREDECESSOR_NOT_ADMISSIBLE")

    lite_unscored = execute_lite_effect(root)
    lite_score = score_lite_effect(root, lite_unscored)
    formed_unscored = execute_formation_consumption_replay(root)
    formed_score = score_formation_consumption_replay(root, formed_unscored)
    rollback_equivalent = (
        canonical_sha256(lite_unscored["treatment"])
        == canonical_sha256(formed_unscored["baseline"])
    )
    default_formation_events = inspect.signature(
        decide_deterministic_boundary
    ).parameters["formation_events"].default
    checks = {
        "dg27_boundary_admitted": predecessors["DG27"]["status"]
        == expected["DG27"],
        "deterministic_channel_union_admitted": lite_score["status"]
        == expected["DG28_LITE"],
        "formation_sidecar_admitted": predecessors["MF03"]["status"]
        == expected["MF03"],
        "formation_consumption_admitted": formed_score["status"]
        == expected["DG28_FORMATION"],
        "all_target_bindings_closed": formed_score["treatment"][
            "target_binding_groups"
        ]
        == 7,
        "accepted_binding_precision_one": formed_score["treatment"][
            "accepted_binding_precision"
        ]
        == 1.0,
        "wrong_complete_zero": formed_score["treatment"]["wrong_complete"] == 0,
        "rollback_equivalent": rollback_equivalent,
        "formation_default_off": default_formation_events == (),
        "dg29_excluded": formed_score["dg29_refinding_entry"] is False,
        "formal_holdout_untouched": not formed_unscored["formal_holdout_used"],
    }
    passed = all(checks.values())
    output: dict[str, Any] = {
        "schema": "milai.dg30.read-path-integration-result.v0.1",
        "status": "PASS_READ_PATH_INTEGRATION" if passed else "NEEDS_REPAIR",
        "admitted_components": [
            "DECISION_BOUNDARY_V02",
            "FTS_RAW_ENRICHED_IDENTITY_UNION",
            "MF03_EVENT_IDENTITY_TIME_SIDECAR",
        ],
        "excluded_components": [
            "DG26_STATEVIEW_RERANKER",
            "DG27_GENERATIVE_INTERPRETATION",
            "DG29_ACTIVE_REFINDING",
            "MODEL_ACTION_RANKING",
        ],
        "checks": checks,
        "metrics": {
            "target_candidate_groups": formed_score["treatment"][
                "target_candidate_groups"
            ],
            "target_binding_groups": formed_score["treatment"][
                "target_binding_groups"
            ],
            "accepted_binding_precision": formed_score["treatment"][
                "accepted_binding_precision"
            ],
            "wrong_complete": formed_score["treatment"]["wrong_complete"],
            "query_time_model_calls": formed_unscored["cost"]["model_calls"],
            "additional_refinding_rounds": 0,
        },
        "implementation_rollback": {
            "default": "FORMATION_EVENTS_EMPTY",
            "equivalent_to_dg28_lite": rollback_equivalent,
        },
        "dg29_disposition": "NOT_ENTERED_NO_REFINDING_OPPORTUNITY",
        "release_ready": False,
        "release_blockers": [
            "FORMAL_HOLDOUT_NOT_AUTHORIZED",
            "READER_ANSWER_EFFECT_NOT_RERUN_IN_DG30",
            "EXPERIMENTAL_FEATURES_DEFAULT_OFF",
        ],
        "formal_holdout_used": False,
        "canonical_mutations": 0,
        "reader_calls": 0,
        "model_calls": 0,
    }
    output["result_digest"] = canonical_sha256(output)
    return output


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG30IntegrationError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


__all__ = ["DG30IntegrationError", "evaluate_read_path_integration"]
