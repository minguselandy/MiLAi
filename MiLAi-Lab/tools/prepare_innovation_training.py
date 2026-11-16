"""Export matched representation targets from explicitly reviewed source references.

This prepares supervised examples; it does not train a model, infer correctness
from committed edits, or turn development examples into a held-out evaluation.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from milai_lab.methods.semantic_delta import compile_delta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in args.references.read_text().splitlines() if line.strip()]
    exports: dict[str, list[dict[str, Any]]] = {name: [] for name in (
        "ordinary_operations", "conversion_quality", "relation_consequence", "semantic_delta")}
    for row in rows:
        proposals = compile_delta(row["delta_target"], row["mapping"])
        plain = copy.deepcopy(proposals)
        for proposal in plain:
            proposal.pop("support_groups", None)
            for clause in proposal.get("clauses", []):
                # These references use independent content nodes; the full
                # conditional rule is also one of the shared factual clauses.
                if clause.pop("conditions"):
                    raise ValueError("Reference requires an explicit plain-text condition target")
        common = {key: row[key] for key in ("example_id", "input", "review", "provenance")}
        targets = {
            "ordinary_operations": {"proposals": plain},
            "conversion_quality": {"proposals": plain},
            "relation_consequence": {"proposals": proposals},
            "semantic_delta": row["delta_target"],
        }
        for name, target in targets.items():
            exports[name].append({**common, "objective": name, "target": target,
                **({"quality_feedback": row["quality_feedback"]}
                   if name != "ordinary_operations" else {}),
                **({"consequence_targets": row["consequence_targets"]}
                   if name in {"relation_consequence", "semantic_delta"} else {})})
    for name, samples in exports.items():
        (args.output / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in samples))
    (args.output / "preparation.json").write_text(json.dumps({
        "references": str(args.references), "reference_examples": len(rows),
        "source_chains": len({row["provenance"]["owner"] for row in rows}),
        "references_with_consequence_targets": sum(
            bool(row["consequence_targets"]) for row in rows),
        "conditions": list(exports), "parameter_updates": 0, "metered_teacher_http_calls": 0,
        "reference_authoring_cost": "Assistant authoring/review work is not separately metered "
                                    "by the experiment ledger; it is not zero cost.",
        "status": "DATA_PREPARATION_ONLY", "split": "exposed_author_development",
        "training_budget": "Not allocated; match trained tokens, steps and parameters before use.",
        "plain_condition": "Same factual clauses and explicit rule text, without auxiliary graph.",
    }, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
