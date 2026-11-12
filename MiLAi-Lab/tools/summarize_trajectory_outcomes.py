"""Join task-level DEV reviews by actual first-readout identity, retaining unknowns and failures."""
from __future__ import annotations

import argparse
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json


def endpoint_status(transport: str, review: dict | None) -> str:
    if transport != "COMPLETED":
        return "execution_failed"
    if review is None:
        return "unknown"
    answer = review["answer_status"]
    if (answer == "complete" and review["material_status"] == "sufficient"
            and review["answer_support"] == "supported"):
        return "complete_supported"
    if answer in {"incomplete", "incorrect"}:
        return answer
    return "unknown"


def summarize(cases: list[dict], bindings: dict, reviews: list[dict],
              primary: tuple[str, str], seed: int = 0) -> dict:
    by_readout = {}
    for review in reviews:
        path = review["readout"]
        if path not in bindings or path in by_readout:
            raise ValueError("Review must identify one actual bound first readout")
        binding = bindings[path]
        if (review["actual_action"] != binding["actual_action"]
                or review["event_id"] != binding["review_group"]
                or review["family"] != binding["family"]):
            raise ValueError("Review provenance changed")
        by_readout[path] = review
    methods = defaultdict(list)
    seen = set()
    for case in cases:
        for branch in case["branches"]:
            path = branch["readout"]
            if path in seen:
                raise ValueError("A first readout was counted twice")
            seen.add(path)
            bound = bindings[path]
            status = endpoint_status(branch["readout_status"], by_readout.get(path))
            methods[bound["method"]].append({**bound, "readout": path,
                "transport_status": branch["readout_status"], "answer_status": status,
                "review_present": path in by_readout})
    if seen != set(bindings):
        raise ValueError("Actual endpoint coverage differs from the provenance map")
    metrics, values = {}, {}
    for method, rows in methods.items():
        groups = defaultdict(list)
        for row in rows:
            groups[row["family"]].append(row["answer_status"])
        values[method] = {family: {
            "observed": statistics.mean(x == "complete_supported" for x in statuses),
            "possible": statistics.mean(x in {"complete_supported", "unknown"} for x in statuses)}
            for family, statuses in groups.items()}
        metrics[method] = {"questions": len(rows), "sources": len(groups),
            "status_counts": dict(Counter(row["answer_status"] for row in rows)),
            "source_macro_observed_complete": statistics.mean(
                x["observed"] for x in values[method].values()),
            "source_macro_possible_complete": statistics.mean(
                x["possible"] for x in values[method].values()), "endpoints": rows}
    left, right = primary
    if left not in values or right not in values or set(values[left]) != set(values[right]):
        raise ValueError("Primary methods require the same actual source panel")
    sources = sorted(values[left])
    diffs = [values[left][f]["observed"] - values[right][f]["observed"] for f in sources]
    rng = random.Random(seed)  # noqa: S311 -- declared descriptive source bootstrap
    draws = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(10000))
    return {"methods": metrics, "primary": {
        "left": left, "right": right, "sources": len(sources),
        "observed_complete_difference": statistics.mean(diffs),
        "source_bootstrap95": [draws[249], draws[9749]],
        "unknown_identification_interval": [
            statistics.mean(values[left][f]["observed"] - values[right][f]["possible"]
                            for f in sources),
            statistics.mean(values[left][f]["possible"] - values[right][f]["observed"]
                            for f in sources)]},
        "scope": "Observed complete-supported answers over the full fixed task panel. Missing "
                 "reviews and qualified judgments remain unknown; failures remain failures. "
                 "Bootstrap conditions on the nonindependent judgments and this source panel. "
                 "Unknown limits do not certify reviewer truth or training-seed variance. "
                 "Native F1 remains a separate result, and no training labels are exported."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grouped", type=Path)
    parser.add_argument("reviewed", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--primary", nargs=2, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    manifest = read_json(args.grouped / "manifest.json")
    run = read_json(args.reviewed / "run.json")
    if (manifest.get("source_split") != "dev"
            or manifest.get("training_labels_allowed") is not False
            or run["status"] not in {"COMPLETED", "COMPLETED_WITH_UNRESOLVED"}
            or Path(run["compiled"]).resolve() != args.grouped.resolve()):
        raise ValueError("Require the closed DEV review of this grouped endpoint matrix")
    result = summarize(read_json(args.grouped / "review-inputs.json"),
        read_json(args.grouped / "origin-bindings.json"),
        read_json(args.reviewed / "reviews.json")["records"], tuple(args.primary), args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "summary.json", {**result, "status": "CLOSED_TASK_REVIEW_COMPARISON",
        "grouped": str(args.grouped.resolve()), "reviewed": str(args.reviewed.resolve()),
        "reviewer_independent": False, "no_sha_validation": True,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}})


if __name__ == "__main__":
    main()

