"""Group actual DEV trajectory endpoints for method-hidden source-grounded review."""
from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def group_endpoints(methods: dict[str, list[dict[str, Any]]], width: int = 2
                    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Align native tasks, retaining distinct trajectories even when action IDs are equal."""
    if not methods or width < 1:
        raise ValueError("Require methods and a positive fixed review group width")
    names = list(methods)
    anchor = methods[names[0]]
    identities = [(c["family"], c["native_control"]["native_question_id"]) for c in anchor]
    if len(identities) != len(set(identities)):
        raise ValueError("Each method must have one actual endpoint per native source/task")
    for cases in methods.values():
        if [(c["family"], c["native_control"]["native_question_id"]) for c in cases] != identities:
            raise ValueError("Methods must cover the same ordered native tasks")
        for reference, case in zip(anchor, cases, strict=True):
            if (case["native_control"] != reference["native_control"]
                    or case["question"] != reference["question"]
                    or case["native_control"]["split"] != "dev"
                    or len(case["branches"]) != 1):
                raise ValueError("Require actual single DEV endpoints with the same public task")
    grouped, bindings = [], {}
    for index, reference in enumerate(anchor):
        family, question = identities[index]
        for start in range(0, len(names), width):
            group_names = names[start:start + width]
            event = f"trajectory-review/{family}/{question}/group-{start // width}"
            branches = []
            for name in group_names:
                original = methods[name][index]
                branch = copy.deepcopy(original["branches"][0])
                path = branch["readout"]
                if path in bindings:
                    raise ValueError("One first-readout record cannot impersonate two trajectories")
                bindings[path] = {"method": name, "family": family,
                    "native_question_id": question, "original_event_id": original["event_id"],
                    "actual_action": branch["action"], "review_group": event}
                # Method identity is kept in the separate provenance map, not the judge payload.
                branches.append(branch)
            grouped.append({"event_id": event, "family": family,
                "question": reference["question"], "native_control": reference["native_control"],
                "branches": branches})
    return grouped, bindings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("methods", type=Path,
                        help="Ordered method -> closed endpoint compiler folder")
    parser.add_argument("output", type=Path)
    parser.add_argument("--methods-per-group", type=int, default=2)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    methods, readouts, preparations, settings = {}, {}, {}, []
    for method, directory in read_json(args.methods).items():
        directory = Path(directory)
        manifest = read_json(directory / "manifest.json")
        prepared = Path(manifest["prepared"])
        preparation = read_json(prepared / "run.json")
        if (not manifest["evaluation_only"] or manifest["source_split"] != "dev"
                or preparation.get("actual_only") is not True):
            raise ValueError("Review only closed actual DEV endpoints, never training comparisons")
        readout = Path(manifest["readouts"])
        if read_json(readout / "run.json")["status"] not in {
                "COMPLETED", "COMPLETED_WITH_FAILURES"}:
            raise ValueError("Wait for each complete first-readout matrix")
        methods[method] = read_json(directory / "review-inputs.json")
        readouts[method], preparations[method] = str(readout), str(prepared)
        settings.append(read_json(Path(preparation["config"]))["entrypoints"]["functional"])
    if not settings or any(s != settings[0] for s in settings[1:]):
        raise ValueError("Method batches changed the declared Host/review configuration")
    cases, bindings = group_endpoints(methods, args.methods_per_group)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "review-inputs.json", cases)
    write_json(args.output / "origin-bindings.json", bindings)
    write_json(args.output / "manifest.json", {
        "status": "CLOSED_ENDPOINTS_GROUPED_NOT_REVIEWED",
        "prepared": next(iter(preparations.values())), "preparations": preparations,
        "readouts": readouts, "methods": list(methods), "source_split": "dev",
        "evaluation_only": True, "training_labels_allowed": False,
        "methods_per_group": args.methods_per_group, "review_groups": len(cases),
        "actual_endpoints": len(bindings), "no_sha_validation": True,
        "scope": "Cross-trajectory task review, not same-state pair supervision. Original actions, "
                 "events and failed first answers remain distinct. Review labels join by the "
                 "actual readout path using origin-bindings.json; repeated action IDs are valid. "
                 "No training export or fabricated common decision state. Existing reviewer "
                 "hides method labels and rotates candidates; reviewer is not independent.",
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}})


if __name__ == "__main__":
    main()

