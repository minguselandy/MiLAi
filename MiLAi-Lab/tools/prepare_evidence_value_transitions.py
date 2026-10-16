"""Prepare conditional-value examples from reviewed, actual subset outcomes.

Labels describe observed Reader returns, not proof of evidence sufficiency or
expected utility. Equivalent Source coverage is compared without content hashes.
No model, Source capture, retrieval, or parameter update occurs here.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.evidence_reading import pack_candidate


def coverage(intervals):
    merged = []
    for source, revision, start, end in sorted(intervals):
        if merged and merged[-1][:2] == (source, revision) and start <= merged[-1][3]:
            previous = merged.pop()
            start, end = previous[2], max(previous[3], end)
        merged.append((source, revision, start, end))
    return tuple(merged)


def contains(outer, inner):
    return all(any(a[:2] == b[:2] and a[2] <= b[2] and a[3] >= b[3] for a in outer) for b in inner)


def pack_intervals(item, expand):
    spans = item["context_source_ranges"] if expand else item["source_ranges"]
    return coverage((s["source_ref"], s["source_revision"], s["start"], s["end"]) for s in spans)


def prepare(execution: Path, reviews: dict) -> dict:
    results = read_json(execution / "results.json")
    if results["status"] != "COMPLETED":
        raise ValueError("Subset outcomes are not complete")
    protocol = read_json(execution / "protocol.json")
    qid = protocol["question_id"]
    pool = read_json(
        Path(protocol["source_run"]) / "native/longmemeval" / qid / "answer/retrieval.json"
    )["materials"]
    states = []
    for outcome in results["results"]:
        name = outcome["condition"]
        request = read_json(
            execution / "http/longmemeval" / f"{qid}:{name}" / "answer/request.json"
        )
        payload = json.loads(request["messages"][1]["content"])
        review = reviews[name]
        official = outcome.get("correct")
        reviewed = review["correct"]
        # Disagreement, missing answers and unresolved reviews remain unlabeled.
        label = (
            official
            if (type(official) is bool and type(reviewed) is bool and official == reviewed)
            else None
        )
        states.append(
            {
                "condition": name,
                "indices": outcome["indices"],
                "expand_context": outcome["expand_context"],
                "source_intervals": coverage(outcome["source_intervals"]),
                "model_input": payload,
                "reader_input_tokens": request["prompt_tokens"],
                "official_correct": official,
                "source_review": review,
                "observed_return": label,
            }
        )

    equivalents = []
    for index, state in enumerate(states):
        group = [
            other
            for other in states[index:]
            if other["source_intervals"] == state["source_intervals"]
        ]
        if len(group) < 2 or any(state["condition"] in g["conditions"] for g in equivalents):
            continue
        labels = {s["observed_return"] for s in group if s["observed_return"] is not None}
        equivalents.append(
            {
                "conditions": [s["condition"] for s in group],
                "observed_return_disagreement": len(labels) > 1,
            }
        )
        if len(labels) > 1:
            for member in group:
                member["observed_return"] = None

    edges = []
    for before in states:
        for after in states:
            prior, final = before["source_intervals"], after["source_intervals"]
            if prior == final or not contains(final, prior):
                continue
            seen, candidates = prior, []
            for index in after["indices"]:
                expanded = index in after["expand_context"]
                spans = pack_intervals(pool[index], expanded)
                if contains(seen, spans):
                    continue
                candidates.append(
                    {**pack_candidate(pool[index], index), "expand_context": expanded}
                )
                seen = coverage([*seen, *spans])
            # Train only actual one/two-open transitions with the recorded coverage.
            if not 1 <= len(candidates) <= 2 or seen != final:
                continue
            previous, following = before["observed_return"], after["observed_return"]
            gain = (
                int(following) - int(previous)
                if previous is not None and following is not None
                else None
            )
            edges.append(
                {
                    "question_id": qid,
                    "before_condition": before["condition"],
                    "after_condition": after["condition"],
                    "opens": len(candidates),
                    "model_input": {
                        **copy.deepcopy(before["model_input"]),
                        "candidate_actions": candidates,
                    },
                    "observed_gain": gain,
                    "reader_input_token_delta": (
                        after["reader_input_tokens"] - before["reader_input_tokens"]
                    ),
                    "observed_two_open_return_gain": None,
                }
            )

    by_name = {s["condition"]: s for s in states}
    for edge in edges:
        before = by_name[edge["before_condition"]]
        after = by_name[edge["after_condition"]]
        if edge["opens"] != 1 or edge["observed_gain"] is None:
            continue
        reachable = [after]
        reachable.extend(
            by_name[e["after_condition"]]
            for e in edges
            if e["before_condition"] == after["condition"]
            and e["opens"] == 1
            and e["observed_gain"] is not None
        )
        edge["observed_two_open_return_gain"] = max(
            int(s["observed_return"]) for s in reachable
        ) - int(before["observed_return"])
    return {
        "question_id": qid,
        "source_execution": str(execution),
        "states": states,
        "transitions": edges,
        "equivalent_evidence": equivalents,
        "scope": "Reviewed single-draw Reader returns on nominated subsets. Two-open return "
        "uses only observed continuations; it is neither expected utility nor proof of "
        "sufficiency. States/transitions from one question are dependent. Review and outcome "
        "labels are outside model_input. No gap text or unseen outcome is invented.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepared = prepare(args.execution, read_json(args.reviews))
    write_json(args.output, prepared)
    print(
        json.dumps(
            {
                "states": len(prepared["states"]),
                "transitions": len(prepared["transitions"]),
                "model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
