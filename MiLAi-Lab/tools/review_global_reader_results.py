"""Reconcile first Reader receipts and export arm-hidden source/answer review.

Known proof delivery is a controller measure, never an automatic judgment that
the Reader's answer is correct. The original native scores remain separate.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import random
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from export_global_reader_responses import response_id
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from run_musique_reader import reader_input
from summarize_musique_reader import family_difference


def usage_totals(receipts: list[dict[str, Any]], *, generated: bool = True) -> dict[str, int]:
    counts: Counter[str] = Counter(responses=len(receipts))
    fields = (
        ("prompt_tokens", "completion_tokens", "total_tokens")
        if generated
        else ("prompt_tokens", "total_tokens")
    )
    for receipt in receipts:
        usage = receipt.get("usage") or {}
        for field in fields:
            value = usage.get(field)
            if type(value) is int and value >= 0:
                counts["known_" + field] += value
            else:
                counts["unknown_" + field + "_responses"] += 1
    return dict(counts)


def standalone_reader_cost(
    results: list[dict[str, Any]],
    receipts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    unique = {r["reader_call_key"]: r for r in results}
    return {
        "positions": len(results),
        "unique_calls": len(unique),
        "usage": usage_totals([receipts[k] for k in unique]),
        "first_call_wall_seconds": sum(r["wall_seconds"] for r in unique.values()),
        "gross_position_usage": usage_totals([receipts[r["reader_call_key"]] for r in results]),
    }


def proof_delivery(review: dict[str, Any], selected: set[int]) -> bool | None:
    if review["disposition"] != "supported":
        return None
    return any(set(proof) <= selected for proof in review["complete_proofs"])


def ledger_delta(start: dict[str, Any], end: dict[str, Any], kind: str) -> dict[str, int]:
    return {
        field: end[kind][field] - start[kind][field]
        for field in ("known_tokens", "charged_tokens", "unknown_usage")
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def local_ledger_audit(
    root: Path, stage: str, phase: str, compute: dict[str, Any]
) -> dict[str, Any]:
    before = read_json(root / f"{stage}-budget-before.json")["compute"].get(phase, {})
    after = read_json(root / f"{stage}-budget-after.json")["compute"][phase]
    differences = {
        k: after.get(k, 0) - before.get(k, 0) - v
        for k, v in compute.items()
        if type(v) in (int, float) and not k.startswith("peak_")
    }
    return {
        "phase": phase,
        "differences": differences,
        "matches": all(abs(v) < 1e-6 for v in differences.values()),
    }


def collect(root: Path, output: Path) -> dict[str, Any]:
    protocol = read_json(root / "protocol.json")
    reader = root / "reader"
    run = read_json(reader / "run.json")
    if run["status"] != "COMPLETED":
        raise ValueError("First-response matrix must be terminal before final reconciliation")
    output.mkdir(parents=True, exist_ok=False)
    cases = {r["case_id"]: r for r in read_rows(Path(protocol["cases"]))}
    labels = read_rows(Path(protocol["labels"]))
    reviews = {r["source_row"]: r for r in read_json(Path(protocol["source_review"]))["cases"]}
    native = read_json(root / "score/results.json")["arms"]
    receipts = {
        str(p.parent.relative_to(reader / "http")): read_json(p)
        for p in (reader / "http").rglob("response.json")
    }
    actual = usage_totals(list(receipts.values()))
    start, end = (
        read_json(reader / name) for name in ("accounting-start.json", "accounting-end.json")
    )
    delta = ledger_delta(start, end, "generation")
    delta["requests"] = end["generation_requests"] - start["generation_requests"]
    audit = {
        "generation": delta,
        "embedding": ledger_delta(start, end, "embedding"),
        "known_token_difference": delta["known_tokens"] - actual.get("known_total_tokens", 0),
        "request_difference": delta["requests"] - len(receipts),
    }
    occurrences: dict[str, list[dict[str, str]]] = defaultdict(list)
    responses: dict[str, dict[str, Any]] = {}
    arms: dict[str, Any] = {}
    comparisons = {
        r["case_id"]: {"family": r["family"], "answerable": r["source"]["answerable"], "arms": {}}
        for r in labels
    }
    sys.path.insert(0, protocol["official_scorer"])
    from metrics.answer import AnswerMetric

    for arm, config in protocol["arms"].items():
        positions, source_rows = [], []
        control: Counter[str] = Counter()
        stops: Counter[str] = Counter()
        for label in labels:
            cid = label["case_id"]
            selection = read_json(Path(config["selection_root"]) / cid / f"{config['policy']}.json")
            result = read_json(reader / "predictions" / arm / f"{cid}.json")
            key = result["reader_call_key"]
            request = read_json(reader / "http" / key / "request.json")
            messages, schema = reader_input(  # type: ignore[no-untyped-call]
                cases[cid], selection["selected_ids"]
            )
            if request["messages"] != messages or request["response_format"] != schema:
                raise ValueError(f"Actual delivered input mismatch: {arm}/{cid}")
            positions.append(result)
            occurrences[key].append({"arm": arm, "case": cid})
            responses[key] = {
                "reader_call_key": key,
                "input": json.loads(messages[1]["content"]),
                "answer": result["answer"],
                "failure": result["failure"],
                "finish_reason": receipts[key]["choices"][0]["finish_reason"],
                "raw_final_content": receipts[key]["choices"][0]["message"].get("content"),
            }
            control["decision_positions"] += selection["decision_calls"]
            control["input_tokens"] += selection.get("standalone_model_input_tokens", 0)
            control["model_wall_seconds"] += selection.get("standalone_model_wall_seconds", 0)
            control["opened_documents"] += len(selection["selected_ids"])
            stops[selection["stop_reason"]] += 1
            review = reviews[label["source_row"]]
            selected = {label["candidate_source_indices"][i] for i in selection["selected_ids"]}
            answer = result["answer"]
            source_rows.append(
                {
                    "case": cid,
                    "family": label["family"],
                    "dataset": label.get("dataset", "musique"),
                    "disposition": review["disposition"],
                    "source_qualified": review.get("qualified", False),
                    "selected_source_indices": sorted(selected),
                    "known_reviewed_proof_delivered": proof_delivery(review, selected),
                    "reader_answerable": answer["answerable"] if answer is not None else None,
                    "empty_answer_contract_violated": bool(
                        answer is not None and not answer["answerable"] and answer["answer"]
                    ),
                    "reader_failure": result["failure"],
                    "reader_call_key": key,
                    "answer_semantics": "PENDING_ARM_HIDDEN_REVIEW",
                }
            )
            metric = AnswerMetric()
            metric(
                answer["answer"] if answer is not None else "",
                [label["source"]["answer"], *label["source"]["answer_aliases"]],
            )
            comparisons[cid]["arms"][arm] = {"f1": metric.get_metric()[1]}
        arms[arm] = {
            "native": {k: v for k, v in native[arm].items() if k != "observations"},
            "standalone_reader": standalone_reader_cost(positions, receipts),
            "standalone_controller": dict(control),
            "stop_reasons": dict(stops),
            "source_delivery": source_rows,
        }
    review_ids = {key: response_id(key) for key in responses}
    write_json(
        output / "response-occurrences.json",
        {review_ids[k]: {"reader_call_key": k, "positions": v} for k, v in occurrences.items()},
    )
    write_json(
        output / "responses-for-review.json", {review_ids[k]: v for k, v in responses.items()}
    )
    shown: dict[tuple[str, str], str] = {}
    shown_responses = set()
    view_rng = random.Random(20261019)  # noqa: S311 -- hide predictable method order
    for case_index, case in enumerate(cases.values()):
        lines = [
            f"CASE {case['case_id']} | {case['question']}",
            "Method names hidden. Judge ONLY the documents delivered for each response.",
        ]
        keys = [k for k in responses if any(o["case"] == case["case_id"] for o in occurrences[k])]
        view_rng.shuffle(keys)
        for key in keys:
            rid, item = review_ids[key], responses[key]
            if key in shown_responses:
                lines.append(f"\n{rid}: identical request/first response already shown.")
                continue
            shown_responses.add(key)
            lines.append(f"\n{rid} | finish={item['finish_reason']} | failure={item['failure']}")
            for doc in item["input"]["documents"]:
                text_key = doc["title"], doc["text"]
                if text_key in shown:
                    lines.append(f"[{doc['id']}] {doc['title']}: exact text as {shown[text_key]}.")
                else:
                    shown[text_key] = f"{rid}/{doc['id']}"
                    lines.append(f"[{doc['id']}] {doc['title']}\n{doc['text']}")
            lines.append("FIRST ANSWER: " + json.dumps(item["answer"], ensure_ascii=False))
            if item["answer"] is None:
                lines.append("RAW FINAL CONTENT: " + str(item["raw_final_content"]))
        path = output / "review-views" / f"{case_index:02d}-{case['case_id']}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
    local_compute = {}
    local_ledger = {}
    for stage in protocol.get("local_stages", []):
        name = stage["name"]
        local_compute[name] = read_json(Path(stage["root"]) / "compute.json")
        local_ledger[name] = local_ledger_audit(
            Path(protocol["stage_receipts_root"]), name, stage["phase"], local_compute[name])
    for model in protocol.get("models", []):
        local_compute[model["name"]] = {
            kind: read_json(Path(model[field]) / "compute.json")
            for kind, field in (
                ("probe", "probe_root"),
                ("selector", "selection_root"),
                ("fixed4_extension", "fixed4_root"),
            )
        }
        local_ledger[model["name"]] = {
            kind: local_ledger_audit(
                root, stage + model["name"], phase, local_compute[model["name"]][kind]
            )
            for kind, stage, phase in (
                ("probe", "probe-", "reader_invariance_probe_v1"),
                ("selector", "select-", "bounded_reader_selection_" + model["selector_backend"]),
                (
                    "fixed4_extension",
                    "fixed4-",
                    "reader_ce_fixed4_extension_v1"
                    if model["backend"] == "native"
                    else "reader_linear_fixed4_extension_v1",
                ),
            )
        }
    dense = root / "selections/dense"
    dense_receipts = [read_json(p) for p in (dense / "http/embedding").rglob("response.json")]
    dense_start, dense_end = (
        read_json(dense / name) for name in ("accounting-start.json", "accounting-end.json")
    )
    dense_usage = usage_totals(dense_receipts, generated=False)
    dense_delta = ledger_delta(dense_start, dense_end, "embedding")
    difference: Callable[[list[dict[str, Any]], str, str], dict[str, Any]] = family_difference
    paired = [
        difference(list(comparisons.values()), baseline, arm)
        for arm in arms
        if arm not in {"bm25_k4", "dense_k4", "full20"}
        for baseline in ("bm25_k4", "dense_k4")
    ]
    for item in paired:
        item["scope"] = (
            "Descriptive conditional family bootstrap on this declared cohort; "
            "not repeated-generation uncertainty or natural-population certification."
        )
    report = {
        "status": "RECEIPTS_AUDITED_SEMANTIC_REVIEW_PENDING",
        "run": run,
        "actual_reader_usage": actual,
        "reader_ledger_audit": audit,
        "arms": arms,
        "actual_local_compute_already_charged": local_compute,
        "local_ledger_audits": local_ledger,
        "reader_unknown_usage_difference": delta["unknown_usage"]
        - actual.get("unknown_total_tokens_responses", 0),
        "dense_control": {
            "usage": dense_usage,
            "ledger_delta": dense_delta,
            "known_token_difference": dense_delta["known_tokens"]
            - dense_usage.get("known_total_tokens", 0),
            "unknown_usage_difference": dense_delta["unknown_usage"]
            - dense_usage.get("unknown_total_tokens_responses", 0),
            "compute": read_json(dense / "compute.json"),
        },
        "common_retrieval": read_json(Path(protocol["common_retrieval_costs"])),
        "family_native_f1_comparisons": paired,
        "unique_responses_for_review": len(responses),
        "method_positions": sum(map(len, occurrences.values())),
        "source_scope": "Known proof delivery is not answer correctness. Insufficiency, ambiguity "
        "and qualified source judgments remain distinct from native reference metrics.",
        "cost_scope": "Actual receipts charged once. Standalone methods include each within-arm "
        "unique Reader response and all controller prefix work, including reused work. "
        "Dense encoding, common retrieval and local loads/preparation are separate. "
        "Tokenizers differ; tokens are not equivalent FLOPs. Warm component sums are "
        "not measured standalone production latency. Review cost not fully metered.",
    }
    write_json(output / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    report = collect(args.root, args.output)
    measures = {
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "audits": 1,
    }
    budget_path = Path(read_json(args.root / "protocol.json")["reader"]["budget_path"])
    with budget_path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        budget = RunBudget(RunLimits(**read_json(budget_path)["limits"]), budget_path)
        budget.record_compute("global_reader_receipt_review", measures)
        exports = args.root / "stream-review/export-compute.jsonl"
        marker = args.root / "stream-review/ledger-record.json"
        if exports.exists() and not marker.exists():
            totals: Counter[str] = Counter()
            for line in exports.read_text().splitlines():
                totals.update(json.loads(line))
            budget.record_compute("global_reader_response_stream_exports_v1", dict(totals))
            write_json(marker, {"recorded": True, "measures": dict(totals)})
    write_json(args.output / "compute.json", measures)
    print(
        json.dumps(
            {k: report[k] for k in ("status", "unique_responses_for_review", "method_positions")}
        )
    )


if __name__ == "__main__":
    main()
