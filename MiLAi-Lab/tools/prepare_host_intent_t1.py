"""Add registered source groups while preserving the closed T0 public histories."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.datasets.intent_training import musique_intent_request
from milai_lab.harness.artifact_io import read_json, write_json


def prepare_sources(allocation: dict[str, Any], t0: dict[str, Any],
                    references: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The admitted 2Wiki records use the same lossless paragraph schema as MuSiQue."""
    source_index = {(r["metadata"]["dataset"], r["metadata"]["source_row"]): r
                    for r in references}
    new = []
    existing = {h["source_group"] for h in t0["histories"]}
    for split in ("train", "dev"):
        for group in allocation["new_sources"][split]:
            if group["family"] in existing:
                raise ValueError("New collection would repeat a closed T0 source group")
            requests = []
            for index in group["source_rows"]:
                reference = source_index[group["dataset"], index]
                metadata, source = reference["metadata"], reference["source"]
                if (metadata["family"], metadata["split"], source["id"]) != (
                    group["family"], split, group["question_id"]
                ):
                    raise ValueError("Admitted source identity or inherited split differs")
                requests.append(musique_intent_request(source, index))
            new.append({"id": group["family"], "source_group": group["family"],
                        "split": split, "sources": [], "requests": requests})
    common = {"schema": "host_intent_t1_histories_v1",
              "scope": "Public sources/tasks only; actual trajectories and labels pending"}
    return ({**common, "histories": new},
            {**common, "histories": [*t0["histories"], *new]})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("allocation", type=Path)
    parser.add_argument("t0_histories", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    allocation = read_json(args.allocation)
    references = [json.loads(line) for line in
                  Path(allocation["normalized_original_sources"]).read_text().splitlines()]
    t0 = read_json(args.t0_histories)
    new, full = prepare_sources(allocation, t0, references)
    counts = {split: sum(h["split"] == split for h in full["histories"])
              for split in ("train", "dev")}
    if counts != allocation["primary_source_groups"]:
        raise ValueError("Prepared histories do not cover the registered source groups")
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "new-histories.json", new)
    write_json(args.output / "full-histories.json", full)
    wanted = {(g["dataset"], i) for groups in allocation["new_sources"].values()
              for g in groups for i in g["source_rows"]}
    with (args.output / "offline-references.jsonl").open("w") as stream:
        for reference in references:
            metadata = reference["metadata"]
            if (metadata["dataset"], metadata["source_row"]) in wanted:
                stream.write(json.dumps(reference, ensure_ascii=False) + "\n")
    report = {"status": "PREPARED_NEW_SOURCES_NOT_COLLECTED",
        "allocation": str(args.allocation), "t0_public_histories": str(args.t0_histories),
        "t0_histories_unchanged": full["histories"][:len(t0["histories"])] == t0["histories"],
        "primary_source_groups": counts,
        "new_positions_two_interfaces": {split: 2 * sum(len(h["requests"])
            for h in new["histories"] if h["split"] == split) for split in ("train", "dev")},
        "collection_input": str(args.output / "new-histories.json"),
        "rule": "Collect only new histories; reuse closed T0 trajectories and preserve first "
                "failures. Offline references never enter Host input. Native support/answers "
                "are not operation labels; all new pools and actual requests need review.",
        "model_calls": 0, "http_requests": 0, "ledger_recorded": False,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu}
    write_json(args.output / "preparation.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
