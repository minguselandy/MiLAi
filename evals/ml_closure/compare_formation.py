"""One matched sealed score for V01 versus the frozen V02 treatment."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from milai.domain.requirement_state import canonical_sha256

from evals.ml_closure.score import score


def _paired_bootstrap(
    baseline: dict[str, Any], treatment: dict[str, Any], *, samples: int = 10_000
) -> dict[str, float | int]:
    left = {
        row["conversation_id"]: float(row["direct_accuracy"])
        for row in baseline["per_conversation"]
    }
    right = {
        row["conversation_id"]: float(row["direct_accuracy"])
        for row in treatment["per_conversation"]
    }
    if left.keys() != right.keys() or not left:
        raise ValueError("FORMATION_PAIRED_ROWS_MISMATCH")
    deltas = [right[key] - left[key] for key in sorted(left)]
    generator = random.Random(20260830)
    boot = sorted(
        sum(deltas[generator.randrange(len(deltas))] for _ in deltas) / len(deltas)
        for _ in range(samples)
    )
    return {
        "paired_conversations": len(deltas),
        "samples": samples,
        "seed": 20260830,
        "mean_delta": sum(deltas) / len(deltas),
        "ci_lower": boot[int(samples * 0.025)],
        "ci_upper": boot[int(samples * 0.975)],
    }


def compare(
    raw: Path,
    labels: Path,
    baseline_output: Path,
    treatment_output: Path,
) -> dict[str, Any]:
    baseline = score(raw, labels, baseline_output)
    treatment = score(raw, labels, treatment_output)
    bootstrap = _paired_bootstrap(baseline, treatment)
    metrics = treatment["metrics"]
    checks = {
        "semantic_macro_f1": metrics["SemanticFormationMacroF1"] >= 0.85,
        "minimum_component_f1": metrics["MinimumComponentF1"] >= 0.75,
        "raw_span_grounding_exact": metrics["RawSpanGroundingExactness"] == 1.0,
        "source_event_time_separated": metrics["SourceEventTimeSeparationAccuracy"]
        == 1.0,
        "ambiguous_time_preserved": metrics["AmbiguousTimePreservation"] == 1.0,
        "assistant_contamination_zero": metrics["AssistantContamination"] == 0,
        "unsupported_identity_merge_zero": metrics["UnsupportedIdentityMerge"] == 0,
        "distinct_event_collapse_zero": metrics["DistinctEventCollapse"] == 0,
        "query_dependent_input_zero": metrics["QueryDependentFormationInput"] == 0,
        "absolute_delta_at_least_005": bootstrap["mean_delta"] >= 0.05,
        "paired_bootstrap_lower_positive": bootstrap["ci_lower"] > 0,
        "md02_v02_boundary_forbidden": treatment["episode_boundary_policy"]
        == "MF02_V01_UNCHANGED_MD02_V02_FORBIDDEN",
    }
    result: dict[str, Any] = {
        "schema": "milai.memory-lifecycle-formation-matched-effect.v0.1",
        "baseline": baseline,
        "treatment": treatment,
        "delta": {
            name: treatment["metrics"][name] - baseline["metrics"][name]
            for name in (
                "SemanticFormationMacroF1",
                "MinimumComponentF1",
                "EntityMentionF1",
                "IdentityPairwiseF1",
                "EventMentionF1",
                "EventIdentityPairwiseF1",
                "OccurrenceTimeF1",
                "StateAssertionF1",
                "TransitionRelationMacroF1",
            )
        },
        "paired_bootstrap": bootstrap,
        "checks": checks,
        "status": "PASS_C1_FORMATION_GENERALIZATION"
        if all(checks.values())
        else "MISS_C1_FORMATION_GENERALIZATION",
        "sealed_retuning_permitted": False,
        "formal_holdout_used": False,
    }
    result["result_digest"] = canonical_sha256(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(
        args.raw.resolve(),
        args.labels.resolve(),
        args.baseline.resolve(),
        args.treatment.resolve(),
    )
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "baseline_macro_f1": result["baseline"]["metrics"][
                    "SemanticFormationMacroF1"
                ],
                "treatment_macro_f1": result["treatment"]["metrics"][
                    "SemanticFormationMacroF1"
                ],
                "minimum_component_f1": result["treatment"]["metrics"][
                    "MinimumComponentF1"
                ],
                "bootstrap": result["paired_bootstrap"],
                "checks": result["checks"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
