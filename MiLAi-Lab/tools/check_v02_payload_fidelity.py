"""Replay unchanged task notes through the repaired public State boundary, without models."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import run_v02_memory_flow as base
from v02_exact_note import checkpoint
from v02_lme_capture import capture_persistent
from v02_low_cost_protocol import derived_events, derived_history, digest
from v02_low_cost_public import observer

ROOT = base.LAB / "artifacts/v02-state-payload-fidelity/run-20260906a"
CONFIG = base.LAB / "configs/v02-state-payload-fidelity.json"
PRIOR = base.LAB / "artifacts/v02-low-cost-reuse/n0n1-20260906a"
DATA = base.LAB / "artifacts/v02-lme-incremental/data-20260905b"


def summary(case: str, note_path: Path, result: dict, repeated: dict) -> dict:
    assert result["status"] == "SAVED_CONFIRMED"
    saved = result["after"]["payload"]["milai_lab_exact_note_v1"]
    assert saved["text"].encode() == note_path.read_bytes()
    assert saved["content_sha256"] == digest(note_path)
    assert repeated["status"] == "NO_OP" and repeated["api_calls"] == 1
    return {"case": case, "status": "EXACT_PUBLIC_ROUNDTRIP_PASS",
            "note_bytes": note_path.stat().st_size, "note_sha256": digest(note_path),
            "original_file_changed": False, "version": result["after"]["version"],
            "repeat_status": repeated["status"], "delta_save_seconds": result["delta_save_seconds"],
            "api_calls": result["api_calls"], "model_allocations": 0}


def main() -> None:
    verification = base.pin(CONFIG)
    results = []
    plan = base.read_json(base.LAB / "studies/active/MILA_V02_LOW_COST_REUSE_R.json")
    for cluster in plan["clusters"]:
        case = cluster["case_id"]
        original = Path(base.read_json(PRIOR / f"generator-{case}.json")["observation"])
        workspace = Path(base.read_json(original / "host-paths.json")["workspace"])
        note_path = workspace / cluster["note_path"]
        before_hash = digest(note_path)
        directory = ROOT / case
        if (directory / "repeat.json").exists():
            results.append(summary(case, note_path, base.read_json(directory / "checkpoint.json"),
                                   base.read_json(directory / "repeat.json")))
            continue
        directory.mkdir(exist_ok=False)
        task = secrets.token_hex(12)
        project = "fidelity-" + task
        base.write_json(directory / "binding.json", {"project": project, "task": task})
        source_path = DATA / "sources" / f"{case}.json"
        expected = base.read_json(DATA / "manifest.json")["cases"][case]["source_sha256"]
        if digest(source_path) != expected:
            raise ValueError("Source identity changed")
        history = derived_history(base.read_json(source_path), cluster["cutoff"])
        with observer(ROOT, directory, project, task) as (call, values):
            preparation = capture_persistent(values, project, derived_events(history, task),
                                               directory, 300)
            base.write_json(directory / "preparation.json", preparation)
            receipts = [json.loads(line) for line in
                        (directory / "source-receipts.jsonl").read_text().splitlines()]
            coordinates = ({f"{s}/turn/{t}" for s in [11, 31] for t in [0, 2, 4, 6, 8, 10]}
                           if case == "27016adc" else
                           {f"2/turn/{t}" for t in [2, 3, 6, 8, 9, 11]}
                           | {f"36/turn/{t}" for t in [0, 6, 10]})
            refs = [r["receipt"]["evidence_id"] for r in receipts
                    if r["source_id"].split("/session/")[1] in coordinates]
            result = checkpoint(call, workspace, cluster["note_path"], refs, "copy-" + task)
            base.write_json(directory / "checkpoint.json", result)
            assert result["status"] == "SAVED_CONFIRMED", result["status"]
            note = result["after"]["payload"]["milai_lab_exact_note_v1"]
            assert note["text"].encode("utf-8") == note_path.read_bytes()
            assert note["content_sha256"] == before_hash == digest(note_path)
            repeated = checkpoint(call, workspace, cluster["note_path"], refs, "copy-" + task)
            base.write_json(directory / "repeat.json", repeated)
            assert repeated["status"] == "NO_OP" and repeated["api_calls"] == 1
            results.append(summary(case, note_path, result, repeated))
    base.write_json(ROOT / "roundtrip-results.json", {"status": "PASS", "pin": verification,
                    "model_allocations": 0, "cases": results, "F_S_effect": "NOT_YET_EVALUATED"})
    print(json.dumps(results))


if __name__ == "__main__":
    main()
