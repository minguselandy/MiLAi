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


def native_panel(expected_tasks: list[dict], metrics: dict[str, dict], failures: list[dict],
                 primary: tuple[str, str], seed: int) -> dict:
    """Extend actual official scores only by declared pre-Reader failure positions."""
    families = {r["family"] for r in expected_tasks}
    if len(families) != len(expected_tasks):
        raise ValueError("Native family means require one declared task per source here")
    missing = defaultdict(set)
    for failure in failures:
        if (failure["status"] != "collection_failed" or failure["method"] not in metrics
                or failure["family"] not in families
                or failure["family"] in missing[failure["method"]]):
            raise ValueError("Invalid native collection-failure coverage")
        missing[failure["method"]].add(failure["family"])
    methods = {}
    for method, metric in metrics.items():
        actual = metric["source_means"]
        if (set(actual) != families - missing[method]
                or metric["states"] != len(actual) or metric["sources"] != len(actual)):
            raise ValueError("Native scores do not cover exactly the actual nonfailed sources")
        scores = {**actual, **{family: 0.0 for family in missing[method]}}
        methods[method] = {"planned_sources": len(families), "actual_reader_positions": len(actual),
            "retained_collection_failures": len(missing[method]),
            "actual_reader_status_counts": metric["status_counts"],
            "source_macro_answer_f1_missing_zero": statistics.mean(scores.values()),
            "source_scores": scores}
    left, right = primary
    diffs = [methods[left]["source_scores"][f] - methods[right]["source_scores"][f]
             for f in sorted(families)]
    rng = random.Random(seed)  # noqa: S311 -- declared descriptive source bootstrap
    draws = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(10000))
    return {"methods": methods, "primary": {"left": left, "right": right,
        "paired_source_mean_difference": statistics.mean(diffs),
        "source_bootstrap95": [draws[249], draws[9749]]},
        "scope": "Actual official answer-field scores retained. Declared collection failures "
                 "before any Reader call contribute missing=0 to the full planned denominator; "
                 "no fictitious prediction or HTTP failure is created. Conditional native scorer "
                 "artifacts remain unchanged. Source judgments and failure causes stay separate."}


def summarize(cases: list[dict], bindings: dict, reviews: list[dict],
              primary: tuple[str, str], seed: int = 0,
              collection_failures: list[dict] | None = None,
              expected_tasks: list[dict] | None = None) -> dict:
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
    positions = {(method, row["family"], row["native_question_id"])
                 for method, rows in methods.items() for row in rows}
    if len(positions) != sum(map(len, methods.values())):
        raise ValueError("Repeated actual first task position")
    for failure in collection_failures or []:
        identity = failure["method"], failure["family"], failure["native_question_id"]
        if (identity in positions or failure.get("status") != "collection_failed"
                or failure.get("readout") is not None
                or failure.get("actual_terminal_action") is not None):
            raise ValueError("Invalid or repeated collection-failure position")
        positions.add(identity)
        methods[failure["method"]].append({"method": failure["method"],
            "family": failure["family"], "native_question_id": failure["native_question_id"],
            "original_event_id": None, "actual_action": None, "readout": None,
            "transport_status": "NOT_INVOKED", "answer_status": "collection_failed",
            "review_present": False, "collection_failure": failure})
    if expected_tasks is not None:
        expected = {(r["family"], r["native_question_id"]) for r in expected_tasks}
        if any({(r["family"], r["native_question_id"]) for r in rows} != expected
               for rows in methods.values()):
            raise ValueError("Every method must retain the entire planned task denominator")
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
                 "Explicit collection failures retain planned positions with no fabricated "
                 "action/packet/Reader call; they count as uncompleted pipeline positions, "
                 "not semantic negatives. "
                 "Native F1 remains a separate result, and no training labels are exported."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grouped", type=Path)
    parser.add_argument("reviewed", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--primary", nargs=2, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--native-summaries", type=Path,
                        help="Method -> actual official native summary.json for this same compiler")
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    manifest = read_json(args.grouped / "manifest.json")
    run = read_json(args.reviewed / "run.json")
    if (manifest.get("source_split") not in {"dev", "test"}
            or manifest.get("training_labels_allowed") is not False
            or run.get("source_split") != manifest["source_split"]
            or run["status"] not in {"COMPLETED", "COMPLETED_WITH_UNRESOLVED"}
            or Path(run["compiled"]).resolve() != args.grouped.resolve()):
        raise ValueError("Require the closed DEV/TEST review of this grouped endpoint matrix")
    result = summarize(read_json(args.grouped / "review-inputs.json"),
        read_json(args.grouped / "origin-bindings.json"),
        read_json(args.reviewed / "reviews.json")["records"], tuple(args.primary), args.seed,
        manifest.get("collection_failures"), manifest.get("expected_tasks"))
    if args.native_summaries:
        paths = read_json(args.native_summaries)
        if set(paths) != set(manifest["methods"]) or not manifest.get("expected_tasks"):
            raise ValueError("Native panel must use all declared methods and full reference tasks")
        native = {}
        for method, path in paths.items():
            scored = read_json(Path(path))
            if Path(scored["compiled"]).resolve() != Path(manifest["compilers"][method]):
                raise ValueError("Native scores came from another actual endpoint compiler")
            native[method] = scored["metrics"]["collector_actual"]
        result["native_panel"] = native_panel(manifest["expected_tasks"], native,
            manifest.get("collection_failures", []), tuple(args.primary), args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "summary.json", {**result, "status": "CLOSED_TASK_REVIEW_COMPARISON",
        "source_split": manifest["source_split"], "training_labels_allowed": False,
        "grouped": str(args.grouped.resolve()), "reviewed": str(args.reviewed.resolve()),
        "reviewer_independent": False, "no_sha_validation": True,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}})


if __name__ == "__main__":
    main()

