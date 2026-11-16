"""Run the existing frozen F1 entry with a declared, ordinary-HANDOFF lexical-tie variant."""

from __future__ import annotations

import json
import runpy
import sys
import time
from pathlib import Path
from typing import Any

from current_raw_packet_tie import PROFILE, current_raw_packet_tie
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods import memory_control


def main() -> None:
    receipt, entry, policies = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[4])
    recipes = read_json(policies)
    if (entry.name != "run_frozen_retrieval_calls.py" or not recipes
            or any(r["policy"]["policy"] != "rules"
                   or r["policy"]["routing"] != "handoff_only"
                   or "intervention" in r for r in recipes)):
        raise ValueError("This wrapper owns only declared ordinary rules/HANDOFF F1 branches")
    started = time.process_time()
    original_argv = sys.argv[:]
    original = vars(memory_control)["original_evidence_action"]
    report: dict[str, Any] = {"status": "RUNNING", "profile": PROFILE,
        "base_runtime_module": memory_control.__file__,
        "original_selector_file": original.__code__.co_filename,
        "policy_wrapper_file": str(Path(__file__).resolve()), "entry": str(entry.resolve()),
        "argv": sys.argv[2:], "recipes": str(policies.resolve()),
        "policy_calls": [], "automatic_retry": False, "intervention_used": False,
        "public_termination_protocol": "Ordinary policy_handoff; no intervention marker added.",
        "source_version_scope": "Entry source-version identifies the unchanged base runtime; "
            "this receipt separately identifies the explicit process-local policy extension."}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)

    def record(row: dict[str, Any]) -> None:
        report["policy_calls"].append(row)
        write_json(receipt, report)

    try:
        sys.path.insert(0, str(entry.parent))
        sys.argv = sys.argv[2:]
        with current_raw_packet_tie(record):
            runpy.run_path(str(entry), run_name="__main__")
        report["status"] = "COMPLETED"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        sys.argv = original_argv
        report.update(selector_restored=(
                          vars(memory_control)["original_evidence_action"] is original),
                      cpu_seconds_nested=time.process_time() - started,
                      cpu_accounting="Nested wrapper/runner CPU; whole child owner measures once.")
        write_json(receipt, report)


if __name__ == "__main__":
    main()
