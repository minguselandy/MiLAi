"""Execute frozen discovery screening and seal sources plus offline evaluation contracts."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import time
from pathlib import Path

from check_v0210_control import write
from milai_lab.methods.prospective_admission import Qualification, admit, denominators, fixed_prefix
from v02_local_provider import append_event


def prepare_query(root: Path, item: dict, key: str) -> dict:
    """Evaluator and normal Host artifacts use disjoint allowlists."""
    import pyarrow.parquet as pq

    columns = ["conversation", "options", "correct_letter", "distractor_letter"]
    table = pq.read_table(root / "horizon-snapshot" / item["file"], columns=columns)
    record = table.take([item["row"]]).to_pylist()[0]
    options = json.loads(record["options"])
    if (
        not isinstance(record["conversation"], str)
        or not record["conversation"]
        or [row["letter"] for row in options] != list("ABCDE")
        or record["correct_letter"] not in "ABCDE"
        or len(record["correct_letter"]) != 1
    ):
        raise ValueError("CORRUPT_DATA")
    raw = record["conversation"].encode()
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("RESOURCE_INFEASIBLE")
    directory = root / "online" / key
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "history.txt").write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    write(directory / "source-index.json", {"history.txt": sha})
    profile = json.loads((root / "a0-profile.json").read_text())
    question = profile["horizon_question"]
    question += "".join(f"\n{row['letter']}: {row['option']}" for row in options)
    question += ("\nPlease respond with the letter of the option that aligns with the user's "
                 "preferences the most and nothing else.")
    write(directory / "question.json", {"question": question})
    write(
        root / "evaluation" / f"{key}.json",
        {
            "query": key,
            "original_item_id": item["id"],
            "generator": item["generator"],
            "user_id": item["user_id"],
            "has_evolved": item["has_evolved"],
            "preference_domain": item["preference_domain"],
            "row": item["row"],
            "file": item["file"],
            "official_correct_letter": record["correct_letter"],
            "official_distractor_letter": record["distractor_letter"] or "",
            "reference_revision": json.loads((root / "horizon-dataset.json").read_text())["sha"],
            "official_rule": "Pinned evaluate.py extract_letter(response) equals correct_letter",
            "local_strict": "Entire stripped final answer must be a single uppercase A-E",
            "counterexamples": ("Multiple letters or explanations remain official-rule scored but "
                                "local format-invalid; old-option choice alone does not establish "
                                "use failure"),
            "abstention": "A delivered refusal with no parsed letter is incorrect, not removed",
            "dispute": ("Report official score, local ambiguity and semantic dispute separately; "
                        "unresolved support cannot create a use-failure signal"),
            "evidence_location": "NOT_PROVIDED_OFFICIALLY",
            "derived_evidence": "Separate post-answer source/presentation audit; never online",
            "review_role": "MODEL_ASSISTED_ADJUDICATION_USER_AUTHORIZED_SUBAGENT",
            "evaluation_cost": ("Deterministic scoring plus separately reported orchestrator "
                                "review labour; benchmark Judge requests zero"),
            "source_sha256": sha,
            "source_bytes": len(raw),
            "review_exposure": "REVIEW_OPENED_NOT_TUNING_EXPOSED",
        },
    )
    append_event(
        root / "ingest-ledger.jsonl",
        {
            "operation": "HARNESS_INGEST",
            "query": key,
            "source_sha256": sha,
            "source_bytes": len(raw),
            "product_ingest": False,
            "semantic_transform": False,
        },
    )
    return {
        "query": key,
        "source_sha256": sha,
        "source_bytes": len(raw),
        "source_status": "SOURCE_READY",
        "evaluator_status": "READY",
        "modality": "TEXT",
        "source_read_requires_gold_hit": False,
        "actual_presentation": "NOT_RUN_PENDING_NORMAL_FIRST_REQUEST",
    }


def run(root: Path) -> dict:
    seal_wire = (root / "seal-a.json").read_bytes()
    assert (
        hashlib.sha256(seal_wire).hexdigest()
        == json.loads((root / "seal-a-sha256.json").read_text())["sha256"]
    )
    seal = json.loads(seal_wire)
    for name, expected in seal["pins"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    (root / "evaluation").mkdir(exist_ok=False)
    order = tuple(seal["discovery"])
    qualifications, prepared = {}, {}
    opened = []
    started = time.monotonic()
    allocation = json.loads((root / "allocation.json").read_text())
    for index, cluster in enumerate(order[: seal["screening_cap"]]):
        if len(prepared) >= seal["accepted_target"]:
            break
        if (
            time.time() - (root / "allocation.json").stat().st_mtime
            >= allocation["resources"]["preparation_seconds"]
        ):
            break
        probes = seal["preselected_probes"][cluster]
        if not probes["metadata_eligible"]:
            qualifications[cluster] = Qualification("REJECTED", ("REQUIRED_PROBE_MISSING",), ())
            continue
        rows = []
        try:
            for position, item in enumerate(probes["queries"]):
                key = f"q{index + 1:03d}-{position + 1}"
                opened.append({"cluster": cluster, "id": item["id"], "status": "REVIEW_OPENED"})
                rows.append(prepare_query(root, item, key))
            prepared[cluster] = rows
            qualifications[cluster] = Qualification(
                "ELIGIBLE", (), tuple("evaluation/" + row["query"] + ".json" for row in rows)
            )
        except (ValueError, KeyError, TypeError, OSError) as exc:
            code = (
                str(exc) if str(exc) in ("CORRUPT_DATA", "RESOURCE_INFEASIBLE") else "CORRUPT_DATA"
            )
            qualifications[cluster] = Qualification("REJECTED", (code,), (type(exc).__name__,))
        append_event(
            root / "screening-events.jsonl",
            {
                "cluster": cluster,
                "qualification": dataclasses.asdict(qualifications[cluster]),
                "benchmark_outputs_consulted": False,
            },
        )
    ledger = admit(
        order, qualifications, target=seal["accepted_target"], screening_cap=seal["screening_cap"]
    )
    accepted = fixed_prefix(ledger, seal["accepted_target"])
    first_wave = fixed_prefix(ledger, seal["minimum_batch_clusters"])
    write(root / "screening-ledger.json", [dataclasses.asdict(row) for row in ledger])
    write(root / "review-opened.json", opened)
    status = (
        "POOL_AND_CONTRACT_READY" if len(first_wave) == 2 else "BLOCKED_POOL_OR_EVALUATOR_NOT_READY"
    )
    result = {
        "seal": "B",
        "status": status,
        "seal_a_sha256": hashlib.sha256(seal_wire).hexdigest(),
        "accepted_clusters": list(accepted),
        "accepted_queries": prepared,
        "first_wave_clusters": list(first_wave) if status == "POOL_AND_CONTRACT_READY" else [],
        "first_wave_queries": [row["query"] for c in first_wave for row in prepared[c]]
        if status == "POOL_AND_CONTRACT_READY"
        else [],
        "counts": denominators(ledger),
        "accepted_query_count": sum(len(prepared[c]) for c in accepted),
        "actual_generations": 0,
        "confirmation_opened": False,
        "seconds": time.monotonic() - started,
        "evaluation_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "evaluation").glob("*.json"))
        },
        "after_accept_failure_policy": "KEEP_IN_DENOMINATOR_NO_REPLACEMENT",
        "next_wave_allocation": 0,
    }
    wire = (
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with (root / "seal-b.json").open("xb") as output:
        output.write(wire)
    write(root / "seal-b-sha256.json", {"sha256": hashlib.sha256(wire).hexdigest()})
    return {
        key: result[key]
        for key in ("status", "counts", "accepted_query_count", "first_wave_queries")
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve())))
