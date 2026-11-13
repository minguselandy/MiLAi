"""Export a frozen reserved TEST cohort without changing roles or selecting by answers."""
from __future__ import annotations

import argparse
import copy
import json
import tarfile
import time
from pathlib import Path

from milai_lab.datasets.qasper import export_paper
from milai_lab.harness.artifact_io import read_json, write_json


def export_reserved(papers: dict, identities: list[dict]) -> tuple[list[dict], list[dict]]:
    ids = [row["paper_id"] for row in identities]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Require unique reserved native paper identities")
    histories, controls = [], []
    for row in identities:
        paper_id = row["paper_id"]
        if (row["native_split"] != "test"
                or row["source_group"] != "qasper-paper-" + paper_id):
            raise ValueError("Reserved native TEST role or identity changed")
        history, references = export_paper(paper_id, papers[paper_id], "test",
                                           max_questions=1, given_requests=True)
        if len(history["requests"]) != 1 or len(references) != 1:
            raise ValueError("Missing reserved first question; do not replace the source")
        histories.append(history)
        controls.extend(references)
    return histories, controls


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    protocol = read_json(args.protocol)
    if protocol.get("status") != "FROZEN_BEFORE_CONFIRMATION_SOURCE_EXPORT":
        raise ValueError("Freeze final methods, primary comparison and budgets before TEST export")
    methods, primary = protocol["methods"], protocol["primary"]
    if (len(methods) < 4 or len(primary) != 2 or primary[0] == primary[1]
            or not set(primary) <= set(methods) or not protocol["primary_metric"]
            or protocol["answer_format"] != "answer_separate_v1"):
        raise ValueError("Require the declared controls, primary task metric and answer format")
    settings = read_json(Path(protocol["host_config"]))
    sampling = read_json(Path(protocol["sampling_freeze"]))
    reservation_path = Path(protocol["reservation"])
    reservation = read_json(reservation_path)
    identities = reservation["candidate_metadata"]
    groups = [row["source_group"] for row in identities]
    if (sampling["source_order"] != groups or sampling["source_count"] != len(groups)
            or protocol["source_count"] != len(groups)
            or Path(sampling["reservation"]).resolve() != reservation_path.resolve()):
        raise ValueError("Reserved source order/count differs from the predeclared sampling")
    for key in ("second_Host_readout", "author_review"):
        subset = sampling[key]
        indices = subset["indices_zero_based"]
        if (len(indices) != subset["sources"] or len(set(indices)) != len(indices)
                or any(not 0 <= i < len(groups) for i in indices)
                or [groups[i] for i in indices] != subset["source_groups"]):
            raise ValueError("Predeclared repeat/author positions changed")
    # Do not open the native task contents until the complete protocol is frozen.
    with tarfile.open(reservation["archive"]) as archive:
        member = archive.extractfile("qasper-test-v0.3.json")
        if member is None:
            raise ValueError("The named native TEST member is absent")
        with member:
            papers = json.load(member)
    histories, controls = export_reserved(papers, identities)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "histories.json", {"histories": histories})
    with (args.output / "controls.jsonl").open("w") as stream:
        for row in controls:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "frozen-protocol.json", copy.deepcopy(protocol))
    write_json(args.output / "host-config.json", settings)
    write_json(args.output / "sampling-freeze.json", sampling)
    write_json(args.output / "manifest.json", {
        "status": "FROZEN_TEST_SOURCES_EXPORTED_NO_MODEL_CALLS",
        "protocol": str(args.protocol.resolve()), "reservation": str(reservation_path.resolve()),
        "archive": reservation["archive"], "native_split": "test", "research_split": "test",
        "sources": len(histories), "native_questions": len(controls),
        "source_order": groups, "given_requests": True,
        "question_selection": "First native question in each reserved paper; no answer filtering",
        "training_exports_written": False, "training_labels_allowed": False,
        "model_calls": 0, "Host_calls": 0, "no_sha_validation": True,
        "scope": "Original public Source units and literal questions use the existing exporter. "
                 "Answers, native question IDs and evidence annotations stay in offline controls. "
                 "No paper substitution, new source selection or pretraining isolation claim.",
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}})


if __name__ == "__main__":
    main()
