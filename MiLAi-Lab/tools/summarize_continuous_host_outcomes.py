"""Join continuous Host first outcomes to offline references without dropping failed positions."""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.scorers.answers import answer_values, score_normalized_em_f1_v1


def unique_object(pairs: list[tuple]) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Repeated JSON field in final answer")
    return result


def group_values(rows: list[dict], field: str) -> dict[str, float]:
    """Equal histories inside each dependency group; equal groups in the final mean."""
    histories = defaultdict(list)
    for row in rows:
        if row[field] is not None:
            histories[row["source_group"], row["history"]].append(row[field])
    groups = defaultdict(list)
    for (group, _), values in histories.items():
        groups[group].append(statistics.mean(values))
    return {group: statistics.mean(values) for group, values in groups.items()}


def summarize(fixture: dict, controls: list[dict], runs: dict[str, tuple[dict, str]],
              reviews: list[dict], primary: tuple[str, str], seed: int = 0,
              answer_format: str = "literal") -> dict:
    if answer_format not in {"literal", "answer_separate_v1"}:
        raise ValueError("Unknown prospectively declared answer format")
    expected = {}
    for history in fixture["histories"]:
        arrived = len(history["sources"])
        for request in history["requests"]:
            arrived += len(request.get("incoming_sources", []))
            expected[history["id"], request["id"]] = {
                "source_group": history["source_group"], "arrived_sources": arrived}
    control_map = {(c["history"], c["request_id"]): c for c in controls}
    if len(control_map) != len(controls) or set(control_map) != set(expected):
        raise ValueError("Offline controls must cover the declared request panel exactly")
    review_map = {(r["method"], r["history"], r["request"]): r for r in reviews}
    if len(review_map) != len(reviews):
        raise ValueError("Duplicate first-outcome review")
    used_reviews, methods, rows = set(), {}, []
    for method, (driver, profile) in runs.items():
        if driver["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES", "FAILED"}:
            raise ValueError("Use a closed Host run; live runs are not final evidence")
        if (driver.get("given_requests") or driver.get("native_probe")
                or not driver.get("continue_host_history")):
            raise ValueError("Require autonomous continuous Host history")
        actual = {}
        for position in driver["completed"]:
            if position.get("profile", position["policy"]) != profile:
                continue
            key = position["history"], position["request"]
            if key not in expected or key in actual:
                raise ValueError("Unexpected or repeated first Host position")
            actual[key] = position
        method_rows = []
        for key, declared in expected.items():
            control = control_map[key]
            if control["source_group"] != declared["source_group"]:
                raise ValueError("Offline dependency group differs from the runtime fixture")
            result = actual.get(key, {})
            status = result.get("status", "NOT_EXECUTED")
            complete = status == "COMPLETED"
            answer = result.get("answer")
            if complete and not isinstance(answer, str):
                raise ValueError("Completed Host response has no textual answer")
            review_key = method, *key
            review = review_map.get(review_key)
            if review is not None:
                used_reviews.add(review_key)
                if not complete or review["answer"] != answer:
                    raise ValueError("Semantic review does not match the actual completed answer")
                if review["outcome"] not in {"supported", "incomplete", "incorrect", "unknown"}:
                    raise ValueError("Unknown source-review outcome")
            semantic = (review["outcome"] if review else "unknown") if complete else status
            arrived = control["all_native_references_arrived"]
            score_answer, format_valid = answer if complete else "", None
            answer_fields = None
            if answer_format == "answer_separate_v1" and complete:
                # Only the whole declared JSON response is parsed. No fence stripping,
                # substring extraction, repair or fallback to explanatory prose.
                try:
                    fields = json.loads(answer, object_pairs_hook=unique_object)
                except (ValueError, TypeError):
                    fields = None
                format_valid = (
                    isinstance(fields, dict)
                    and set(fields) == {"answer", "explanation", "evidence"}
                    and isinstance(fields["answer"], str)
                    and isinstance(fields["explanation"], str)
                    and isinstance(fields["evidence"], list)
                    and all(isinstance(item, str) for item in fields["evidence"]))
                answer_fields = fields if format_valid else None
                score_answer = fields["answer"] if format_valid else ""
            # Missing/future native citations cannot establish the currently answerable target.
            # This diagnostic is deliberately not called the benchmark's official metric.
            overlap = (score_normalized_em_f1_v1(score_answer,
                       answer_values(control["native_answer"])) if arrived else None)
            row = {"method": method, "history": key[0], "request": key[1], **declared,
                   "status": status, "answer": answer, "execution_complete": int(complete),
                   "answer_format": answer_format, "answer_format_valid": format_valid,
                   "answer_fields": answer_fields, "scored_answer": score_answer,
                   "semantic_outcome": semantic, "review": review,
                   "observed_supported": int(semantic == "supported"),
                   "possible_supported": int(complete and semantic in {"supported", "unknown"}),
                   "all_native_references_arrived": arrived,
                   "native_evidence_ids": control["native_evidence_ids"],
                   "missing_native_evidence_ids": control["missing_native_evidence_ids"],
                   "not_yet_arrived_native_evidence_ids":
                       control["not_yet_arrived_native_evidence_ids"],
                   "reference_overlap_f1": overlap["normalized_f1"] if overlap else None,
                   "closed_host_snapshots": result.get("closed_host_snapshots", [])}
            method_rows.append(row)
        rows.extend(method_rows)
        group_metrics = {field: group_values(method_rows, field) for field in (
            "execution_complete", "observed_supported", "possible_supported",
            "reference_overlap_f1")}
        methods[method] = {"run_status": driver["status"], "profile": profile,
            "planned_positions": len(expected), "executed_positions": len(actual),
            "histories": len({key[0] for key in expected}),
            "dependency_groups": len(group_metrics["execution_complete"]),
            "status_counts": dict(Counter(r["status"] for r in method_rows)),
            "semantic_counts": dict(Counter(r["semantic_outcome"] for r in method_rows)),
            "answer_format_failures": sum(r["answer_format_valid"] is False
                                          for r in method_rows),
            "reference_overlap_positions": sum(
                r["all_native_references_arrived"] for r in method_rows),
            "group_metrics": group_metrics,
            "group_macro": {field: statistics.mean(values.values()) if values else None
                            for field, values in group_metrics.items()}}
    if used_reviews != set(review_map):
        raise ValueError("Review identifies an outcome outside the declared method panel")
    left, right = primary
    a, b = methods[left]["group_metrics"], methods[right]["group_metrics"]
    groups = sorted(a["observed_supported"])
    diffs = [a["observed_supported"][g] - b["observed_supported"][g] for g in groups]
    rng = random.Random(seed)  # noqa: S311 -- descriptive dependency-group bootstrap
    draws = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(10000))
    return {"methods": methods, "positions": rows, "answer_format": answer_format,
        "primary": {
        "left": left, "right": right, "dependency_groups": len(groups),
        "observed_supported_difference": statistics.mean(diffs),
        "descriptive_group_bootstrap95": [draws[249], draws[9749]],
        "unknown_identification_interval": [statistics.mean(
            a["observed_supported"][g] - b["possible_supported"][g] for g in groups),
            statistics.mean(a["possible_supported"][g] - b["observed_supported"][g]
                            for g in groups)]},
        "scope": "All declared positions retained, including execution failures and unexecuted "
                 "positions. Supported success requires a separate source review of the exact "
                 "answer at the original arrival stage. Such a review may validate a justified "
                 "abstention; unavailable future evidence never becomes a negative answer label. "
                 "Reference overlap is an auxiliary local text metric only where all native "
                 "citations have arrived; it does not prove semantic support or implement an "
                 "official benchmark score. Group bootstrap is descriptive, especially with "
                 "only three participant components; it does not measure reviewer or seed error. "
                 "When answer_separate_v1 was declared before execution, only its strict "
                 "answer field enters text overlap; malformed completed outputs score as "
                 "missing and retain their raw text, execution status and semantic review. "
                 "This report does not export training labels or reconcile cost receipts."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("controls", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--run", nargs=3, action="append", required=True,
                        metavar=("METHOD", "ROOT", "PROFILE"))
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--primary", nargs=2, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--answer-format", choices=("literal", "answer_separate_v1"),
                        default="literal", help="Format declared in every run before inference")
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    fixture, runs, roots = read_json(args.fixture), {}, {}
    for method, root, profile in args.run:
        if method in runs:
            raise ValueError("Repeated method name")
        path = Path(root)
        if read_json(path / "fixture.json") != fixture:
            raise ValueError("Compared runs must use the declared common fixture")
        if not (path / f"{profile}-config.json").is_file():
            raise ValueError("Selected profile was not prepared in this run")
        if args.answer_format == "answer_separate_v1":
            recipe = read_json(path / f"{profile}-config.json")["entrypoints"]["functional"]
            if "answer_separate_v1" not in recipe.get("system_prompt", ""):
                raise ValueError("Separate answer format was not declared in the run config")
        runs[method] = read_json(path / "driver.json"), profile
        roots[method] = str(path.resolve())
    result = summarize(fixture, read_json(args.controls), runs,
                       read_json(args.reviews) if args.reviews else [],
                       tuple(args.primary), args.seed, args.answer_format)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "summary.json", {**result, "run_roots": roots,
        "fixture": str(args.fixture.resolve()), "offline_controls": str(args.controls.resolve()),
        "review_source": str(args.reviews.resolve()) if args.reviews else None,
        "no_sha_validation": True, "model_calls": 0,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}})


if __name__ == "__main__":
    main()
