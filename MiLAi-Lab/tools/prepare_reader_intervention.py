"""Bind saved and source-reviewed choices to the same real pools and Reader.

Preparation consumes offline review metadata. Prediction receives only source
locations and selected indices through the existing comparison runner. No labels,
reference answers or corrected evidence are added to the Reader's inputs.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.evidence_replay import _copied_bank
from prepare_evidence_value_transitions import contains, coverage, pack_intervals
from run_learned_value_comparison import source_context_indices


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def prepare(protocol: dict, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    base = Path(protocol["artifact_base"])
    runtime = {
        key: copy.deepcopy(protocol[key])
        for key in ("name", "settings", "questions", "methods", "scope")
    }
    runtime["prepared_inputs"] = {}
    inventory = []
    for qid in protocol["questions"]:
        reviewed = read_json(Path(protocol["prepared_inputs"][qid]))
        source_execution = resolve_path(base, reviewed["source_execution"])
        source = Path(read_json(source_execution / "protocol.json")["source_run"])
        settings = read_json(source / "actual-config.json")
        materials = read_json(source / "native/longmemeval" / qid / "answer/retrieval.json")[
            "materials"
        ]
        candidates = source_context_indices(materials)
        state = next(
            row
            for row in reviewed["states"]
            if row["condition"] == protocol["reviewed_conditions"][qid]
        )
        # All arms open whole real contexts; change only which contexts are chosen.
        if set(state["expand_context"]) != set(state["indices"]):
            raise ValueError("This comparison requires whole-context reviewed selections")
        required = coverage(state["source_intervals"])
        pool_spans = coverage(
            span for i in candidates for span in pack_intervals(materials[i], True)
        )
        bridge = output / "inputs" / f"{qid}.json"
        write_json(bridge, {"source_execution": str(source_execution)})
        runtime["prepared_inputs"][qid] = str(bridge.resolve())
        for arm in protocol["methods"]:
            arm_root = output / "execution" / arm
            if arm == "reviewed":
                # Common retrieval order removes a separate ordering intervention.
                indices = sorted(state["indices"])
                decision = {
                    "selected_indices": indices,
                    "diagnostic_only": True,
                    "reviewed_condition": state["condition"],
                    "controller_cost": "Author source review, not a deployable policy",
                }
            else:
                original = (
                    Path(protocol["saved_selection_root"]) / arm / "selections" / f"{qid}.json"
                )
                saved = read_json(original)
                indices = saved["selected_indices"]
                decision = {
                    "selected_indices": indices,
                    "reused_selection": str(original),
                    "inherited_selection_cost": {
                        key: saved[key]
                        for key in (
                            "total_selection_wall_seconds",
                            "total_selection_cpu_seconds",
                            "source_contexts_opened_for_selection",
                        )
                    },
                }
            if not set(indices) <= set(candidates):
                raise ValueError(f"{qid}/{arm}: choice is outside the saved candidate contexts")
            delivered = coverage(
                span for i in indices for span in pack_intervals(materials[i], True)
            )
            inventory.append(
                {
                    "question_id": qid,
                    "arm": arm,
                    "candidate_contexts": len(candidates),
                    "selected_contexts": len(indices),
                    "reviewed_support_in_pool": contains(pool_spans, required),
                    "reviewed_support_delivered": contains(delivered, required),
                    "support_scope": "Reviewed sufficient set; not all equivalent proofs",
                }
            )
            write_json(arm_root / "selections" / f"{qid}.json", decision)
            bank_id = settings["alignment_bank_ids"][qid]
            _copied_bank(
                source / "banks" / bank_id / "memory.sqlite",
                arm_root / "banks" / qid / "memory.sqlite",
            )
    write_json(output / "protocol.json", runtime)
    write_json(output / "intervention.json", protocol)
    write_json(output / "inventory.json", inventory)
    return runtime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(read_json(args.protocol), args.output.resolve())


if __name__ == "__main__":
    main()
