"""Summarize the original100-source run and its actual pre-update reuse prefixes."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from summarize_innovation_structure_delivery import costs, ledger_delta, read


def tokens(root):
    return sum(read(path)["usage"]["total_tokens"] for path in root.rglob("response.json"))


def main() -> None:
    lab = Path(__file__).resolve().parents[1]
    root = lab / "artifacts/innovation-v4/scale-100-v1"
    summary = {"status": "CLOSED", "source_version": "92337978", "initial_sources": 100,
        "total_sources": 102, "independent_target_scenarios": 1, "arms": {},
        "scope": "One scenario with 99 unrelated depot sources. Sixteen initial questions "
                 "precede either update. Not 100 independent cases or external confirmation."}
    for arm in ("source-first", "incremental-first"):
        folder = root / arm / "MiLAi-memory-only"
        official = read(folder / "halumem-official-results.json")["question_answering_records"]
        stages = costs(folder)
        reports = [read(path)["report"] for path in (
            folder / "http/query-structure").rglob("interpretation.json")]
        rows, retrieval_seconds = [], []
        for ordinal in (99, 100, 101):
            for index in range(16 if ordinal == 99 else 4):
                key = f"halumem/innovation-scale-aster-100/{ordinal}/qa/{index}"
                view = read(folder / "http" / key / "memory-view.json")
                native = read(folder / "native" / key / "retrieval.json")
                materials = native["materials"]
                retrieval_seconds.append(native["native_return"]["source_retrieval"][
                    "timings"]["total_seconds"])
                packet = read(folder / "http" / key / "view/pack-0/request.json")
                message_text = json.dumps(packet["messages"], ensure_ascii=False).lower()
                rows.append({"session": ordinal, "question": index, "reader_calls": view["steps"],
                    "opened_kinds": [materials[i]["kind"] for i in view["opened_indices"]],
                    "reading_tokens": tokens(folder / "http" / key),
                    "construction_tokens": tokens(folder / "http/query-structure/native" / key),
                    "first_input_contains_white": "white" in message_text,
                    "first_input_contains_drawer": "drawer" in message_text,
                    "source_retrieval_seconds": retrieval_seconds[-1]})
        curves = {}
        for count in (1, 4, 16):
            selected = [row for row in rows if row["session"] == 99][:count]
            construction = sum(row["construction_tokens"] for row in selected)
            reading = sum(row["reading_tokens"] for row in selected)
            curves[str(count)] = {"query_opportunities": count, "construction_tokens": construction,
                                  "reading_tokens": reading, "total_tokens": construction + reading}
        summary["arms"][arm] = {
            "first_labels": dict(Counter(row.get("result_type") or "invalid" for row in official)),
            "stages": stages, "prediction_tokens": sum(v["total_tokens"] for k, v in stages.items()
                                                       if k != "judge"),
            "reuse_prefixes_before_updates": curves, "queries": rows,
            "structure_actions": dict(Counter(row["action"] for row in reports)),
            "visible_sources_enumerated_for_structure": sum(
                row["visible_sources_enumerated"] for row in reports),
            "source_bodies_sent_for_structure": sum(
                row["source_bodies_delivered"] for row in reports),
            "source_retrieval_total_seconds": sum(retrieval_seconds),
            "timing_limit": "Observed shared machine time, including concurrent CPU adapter work; "
                            "not exclusive hardware speed or monetary cost.",
        }
    summary["ledger_delta"] = ledger_delta(root)
    summary["receipt_ledger_difference"] = sum(stage["total_tokens"]
        for arm in summary["arms"].values() for stage in arm["stages"].values()
    ) - summary["ledger_delta"]["generation"]["known_tokens"]
    summary["author_review"] = {
        "scope": "All48 answers and allthree constructed cache versions read against target "
                 "sources; selected failure/correct-but-unsupported packets inspected in full.",
        "source_first": "All24 core answers match the source. Initial query15 additionally says "
                        "the folio access route also applies to the index, which is not stated. "
                        "Some outputs also infer female gender without source support.",
        "incremental_first": "Initial query5 falsely reports no reference-index information and "
                             "answers about unrelated depot crates, despite raw candidate0 being "
                             "the correct source. It neither opens that body nor states a gap.",
        "unsupported_correct_answers": [
            {"session": 99, "question": 12}, {"session": 100, "question": 3}],
        "unsupported_correct_explanation": "These answers name the white drawer, but the entire "
            "saved Reader request contains neither white nor drawer; the cached interpretation "
            "omits the fact and raw excerpts stop before it. Correct labels do not demonstrate "
            "evidence use. This observation does not establish the cause of the model output.",
        "structure": [
            "Initial5-node cache omits the white-drawer fact and incorrectly makes the reported "
            "expired badge a positive alternative support for eligibility. The valid-voucher "
            "route makes the current conclusion true but does not justify that alternative.",
            "January3 refresh correctly removes the voucher policy route and changes the "
            "eligibility claim to denial, preserving orientation and voucher validity.",
            "January4 refresh adds a source-bound black-cabinet node without changing eligibility.",
            "Both updates resend20 raw source bodies because the retrieved set changes. Cache "
            "reuse still enumerates all 100-102 Sources; full locality is not established.",
        ],
    }
    summary["decision"] = (
        "No advantage for this cached graph against retrieved-first raw reading at100sources. "
        "Do not expand the unchanged graph condition to1000/5000 merely to seek a win; those "
        "inputs remain prepared, not measured. Prioritize scope/value decisions and learned "
        "source-faithful formation. Retain simple controls and full lifecycle costs.")
    summary.update(official_scores_modified=False, independent_blind_review=False,
                   full_goal_complete=False)
    output = lab / "data/manifests/innovation-v4-scale-100-v1-summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"arms": {name: {key: arm[key] for key in (
        "first_labels", "prediction_tokens", "reuse_prefixes_before_updates", "structure_actions")}
        for name, arm in summary["arms"].items()}, "ledger": summary["ledger_delta"],
        "receipt_difference": summary["receipt_ledger_difference"]}, indent=2))


if __name__ == "__main__":
    main()
