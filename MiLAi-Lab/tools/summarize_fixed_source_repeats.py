"""Compare preselected first/second Reader outcomes without replacing either run."""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from summarize_trajectory_outcomes import endpoint_status


def completed_response_content(branch: dict) -> str:
    """Read the original final content, excluding provider metadata and reasoning."""
    response = read_json(Path(branch["readout"]).parent / "response.json")
    content = response["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("Completed Reader response must have textual final content")
    parsed = json.loads(content)
    fields = branch.get("answer_fields")
    if ((fields is not None and parsed != fields)
            or parsed.get("answer") != branch["answer"]):
        raise ValueError("Original final response differs from the bound answer fields")
    return content


def difference(values: list[float], seed: int) -> dict:
    rng = random.Random(seed)  # noqa: S311 -- fixed descriptive source bootstrap
    draws = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(10000))
    return {"source_mean": statistics.mean(values), "source_bootstrap95": [draws[249], draws[9749]]}


def summarize_pairs(rows: list[dict], primary: tuple[str, str], seed: int) -> dict:
    by_method = defaultdict(dict)
    for row in rows:
        if row["family"] in by_method[row["method"]]:
            raise ValueError("Repeated method/source stability position")
        by_method[row["method"]][row["family"]] = row
    if not rows or not set(primary) <= set(by_method):
        raise ValueError("Require the declared primary methods and paired source positions")
    families = sorted(next(iter(by_method.values())))
    if any(set(values) != set(families) for values in by_method.values()):
        raise ValueError("All methods must retain the same preselected sources")
    methods = {}
    for method, values in by_method.items():
        selected = [values[f] for f in families]
        transitions = Counter((r["first_status"], r["second_status"]) for r in selected)
        source_transitions = Counter((r["first_source_status"], r["second_source_status"])
                                     for r in selected)
        methods[method] = {"sources": len(families),
            "first_native_F1": statistics.mean(r["first_native_F1"] for r in selected),
            "second_native_F1": statistics.mean(r["second_native_F1"] for r in selected),
            "second_minus_first_native_F1": difference([
                r["second_native_F1"] - r["first_native_F1"] for r in selected], seed),
            "both_completed": sum(r["first_status"] == r["second_status"] == "COMPLETED"
                                  for r in selected),
            "both_completed_exact_answer_field": sum(r["exact_answer_field"] for r in selected),
            "both_completed_exact_full_response": sum(r["exact_full_response"] for r in selected),
            "transport_transitions": [{"first": a, "second": b, "count": n}
                                      for (a, b), n in sorted(transitions.items())],
            "source_status_transitions": [{"first": a, "second": b, "count": n}
                                          for (a, b), n in sorted(source_transitions.items())]}
    left, right = primary
    first = [by_method[left][f]["first_native_F1"] - by_method[right][f]["first_native_F1"]
             for f in families]
    second = [by_method[left][f]["second_native_F1"] - by_method[right][f]["second_native_F1"]
              for f in families]
    return {"methods": methods, "primary_same_subset": {"left": left, "right": right,
        "sources": len(families), "first_difference": difference(first, seed),
        "second_difference": difference(second, seed),
        "second_minus_first_contrast": difference([
            b - a for a, b in zip(first, second, strict=True)], seed)},
        "scope": "First and second outcomes remain separate; no best-of-two, replacing a failed "
                 "first or doubling the independent source count. These are the preselected "
                 "subset, not the full primary confirmation. Native score changes describe "
                 "Reader output variation. Source-status changes also include reviewer sampling "
                 "and grouping effects, not pure Host variance or independent truth. Exact full "
                 "response compares the saved final message.content, including explanation and "
                 "evidence; it excludes provider IDs, usage, timings and reasoning content."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("closed_owner", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    protocol, owner = read_json(args.protocol), read_json(args.closed_owner)
    if owner["status"] != "COMPLETED_CONFIRMATION_FIRSTS_AND_SECOND_READOUTS_AUTHOR_COST_PENDING":
        raise ValueError("Wait for all declared first and second Reader/source-review runs")
    sampling = read_json(Path(protocol["sampling_freeze"]))
    groups = sampling["second_Host_readout"]["source_groups"]
    first_reviews = {r["readout"]: r for r in read_json(
        Path(owner["first_reviewed"]) / "reviews.json")["records"]}
    second_reviews = {r["readout"]: r for r in read_json(
        Path(owner["repeat_reviewed"]) / "reviews.json")["records"]}
    rows = []
    for method in protocol["methods"]:
        first_root = Path(owner["first_bound"][method])
        second_root = Path(owner["repeat_bound"][method])
        first_manifest, second_manifest = read_json(first_root / "manifest.json"), read_json(
            second_root / "manifest.json")
        repeat_run = read_json(Path(second_manifest["prepared"]) / "run.json")
        if (first_manifest["source_split"] != "test" or second_manifest["source_split"] != "test"
                or not repeat_run.get("repeat_preparation")
                or Path(repeat_run["original_firsts"]).resolve()
                != Path(first_manifest["readouts"]).resolve()
                or read_json(Path(repeat_run["sampling"])) != sampling):
            raise ValueError("Repeated run differs from the declared firsts or source sampling")
        first_cases = {c["family"]: c for c in read_json(first_root / "review-inputs.json")}
        second_cases = {c["family"]: c for c in read_json(second_root / "review-inputs.json")}
        if list(first_cases) != sampling["source_order"] or list(second_cases) != groups:
            raise ValueError("Repeat source order or coverage changed")
        first_native, second_native = read_json(Path(owner["first_native"][method])), read_json(
            Path(owner["repeat_native"][method]))
        if (Path(first_native["compiled"]).resolve() != first_root.resolve()
                or Path(second_native["compiled"]).resolve() != second_root.resolve()):
            raise ValueError("Native scores belong to another actual compiler")
        first_scores = first_native["metrics"]["collector_actual"]["source_means"]
        second_scores = second_native["metrics"]["collector_actual"]["source_means"]
        for family in groups:
            a, b = first_cases[family], second_cases[family]
            if a["native_control"] != b["native_control"] or a["question"] != b["question"]:
                raise ValueError("Repeated native task identity changed")
            first, second = a["branches"][0], b["branches"][0]
            x, y = read_json(Path(first["readout"])), read_json(Path(second["readout"]))
            if (first["action"] != second["action"] or a["event_id"] != b["event_id"]
                    or read_json(Path(x["request"])) != read_json(Path(y["request"]))):
                raise ValueError("The second Reader did not receive the exact first input")
            for branch, reviewed in [(first, first_reviews), (second, second_reviews)]:
                grade = reviewed.get(branch["readout"])
                if grade and (grade["family"] != family
                              or grade["actual_action"] != branch["action"]):
                    raise ValueError("Source grade belongs to another actual packet")
            both = first["readout_status"] == second["readout_status"] == "COMPLETED"
            af, bf = first.get("answer_fields"), second.get("answer_fields")
            rows.append({"method": method, "family": family,
                "native_question_id": a["native_control"]["native_question_id"],
                "first_readout": first["readout"], "second_readout": second["readout"],
                "first_status": first["readout_status"], "second_status": second["readout_status"],
                "first_native_F1": first_scores[family],
                "second_native_F1": second_scores[family],
                "exact_answer_field": bool(both and af and bf and af["answer"] == bf["answer"]),
                "exact_full_response": bool(both and completed_response_content(first)
                                            == completed_response_content(second)),
                "first_source_status": endpoint_status(first["readout_status"],
                                                        first_reviews.get(first["readout"])),
                "second_source_status": endpoint_status(second["readout_status"],
                                                         second_reviews.get(second["readout"])),
                "full_request_wire_equal": True})
    result = summarize_pairs(rows, tuple(protocol["primary"]), 20261112)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "summary.json", {"status": "CLOSED_FIXED_SOURCE_REPEAT_STABILITY",
        **result, "positions": rows, "protocol": str(args.protocol.resolve()),
        "no_sha_validation": True, "model_calls": 0, "Host_calls": 0,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}})
    with (args.output / "paired-results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
