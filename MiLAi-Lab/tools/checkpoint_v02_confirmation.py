"""Save an offline-reviewed ordinary C note through its actual G public binding."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import run_v02_memory_flow as base
from check_v02_payload_fidelity import ROOT
from v02_exact_note import checkpoint
from v02_low_cost_protocol import digest
from v02_low_cost_public import observer


def run(case: str) -> None:
    base.pin(base.LAB / "configs/v02-fidelity-confirmation.json")
    plan = base.read_json(base.LAB / "studies/active/MILA_V02_FIDELITY_CONFIRMATION_C.json")
    cluster = next(c for c in plan["clusters"] if c["case_id"] == case)
    generator = Path(base.read_json(ROOT / f"generator-{case}.json")["observation"])
    review = base.read_json(generator / "note-source-review.json")
    allocation = base.read_json(generator / "allocation.json")
    workspace = Path(base.read_json(generator / "host-paths.json")["workspace"])
    note = workspace / cluster["note_path"]
    assert review["supported"] and digest(note) == review["note_sha256"]
    coordinates = set(review["coordinates"])
    receipts = [json.loads(s) for s in
                (generator / "source-receipts.jsonl").read_text().splitlines()]
    refs = [r["receipt"]["evidence_id"] for r in receipts
            if r["source_id"].split("/session/")[1] in coordinates]
    assert len(refs) == len(coordinates)
    directory = ROOT / case
    directory.mkdir(exist_ok=False)
    with observer(ROOT, directory, allocation["project"], allocation["task_ref"]) as (call, _):
        current = call("milai_working_state_get", {"scope": "TASK"})
        original = base.read_json(generator / "after.json")
        assert all(current[k] == original[k] for k in ("status", "version", "state_id", "payload"))
        result = checkpoint(call, workspace, cluster["note_path"], refs,
                            "copy-" + allocation["task_ref"])
        base.write_json(directory / "checkpoint.json", result)
        base.write_json(generator / "checkpoint.json", result)
    eligible = result["status"] == "SAVED_CONFIRMED"
    if eligible:
        saved = result["after"]["payload"]["milai_lab_exact_note_v1"]["text"]
        assert saved.encode() == note.read_bytes()
    base.write_json(generator / "qualification.json", {
        "status": "ELIGIBLE" if eligible else "INELIGIBLE", "checkpoint_status": result["status"],
        "note_sha256": digest(note), "note_bytes": note.stat().st_size,
        "original_file_modified": False, "source_review": review,
        "delta_save_seconds": result["delta_save_seconds"], "model_allocations": 0})
    print(json.dumps({"case": case, "status": result["status"],
                      "delta_save_seconds": result["delta_save_seconds"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    run(parser.parse_args().case)
