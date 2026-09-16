"""Real public MCP / PostgreSQL checkpoint gates; no model dispatch."""

from __future__ import annotations

import argparse
import secrets
from uuid import uuid4

import run_v02_memory_flow as base
from run_v02_low_cost_diagnostics import CONFIG, ROOT
from v02_exact_note import FIELD, checkpoint
from v02_low_cost_public import observer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-name", default="n3-public-checks-r4")
    args = parser.parse_args()
    pin = base.pin(CONFIG)
    directory = ROOT / args.run_name
    directory.mkdir(exist_ok=False)
    workspace = directory / "workspace"
    workspace.mkdir()
    source_rows = [__import__("json").loads(line) for line in
                   (ROOT / "diagnostics/0a995998/source-receipts.jsonl").read_text().splitlines()]
    ref = source_rows[0]["receipt"]["evidence_id"]
    old_ref = source_rows[1]["receipt"]["evidence_id"]
    (workspace / "note.md").write_text('UTF-8 引用测试 "quoted"\n' + ref)
    records = {"pin": pin, "model_dispatches": 0}
    task = "n3-" + secrets.token_hex(8)
    base.write_json(directory / "binding.json", {"project": "v0203-diag-0a995998", "task": task})
    with observer(ROOT, directory, "v0203-diag-0a995998", task) as (
        call, _
    ):
        original_call = call

        def call(tool, arguments):
            if "operation_id" in arguments:
                arguments = {**arguments, "operation_id": args.run_name + "-"
                             + arguments["operation_id"]}
            return original_call(tool, arguments)

        base.write_json(directory / "tool-catalog.json", call(None, {}))
        first = checkpoint(call, workspace, "note.md", [ref], "n3-absent")
        records["absent"] = first
        base.write_json(directory / "first-checkpoint.json", first)
        assert first["status"] == "SAVED_CONFIRMED", first["status"]
        second = checkpoint(call, workspace, "note.md", [ref], "n3-absent")
        records["repeat"] = second
        assert second["status"] == "NO_OP" and second["api_calls"] == 1
        before = call("milai_working_state_get", {"scope": "TASK"})
        seed = call("milai_working_state_update", {"operation_id": "n3-old-fields",
                    "expected_version": before["version"], "state_id": before["state_id"],
                    "payload": {**before["payload"], "unrelated": {"text": "retain",
                                                                    "evidence_refs": [old_ref]}}})
        records["old_field_seed"] = seed
        (workspace / "note.md").write_text('UTF-8 第二版\n' + ref)
        changed = checkpoint(call, workspace, "note.md", [ref], "n3-active")
        records["active"] = changed
        assert changed["status"] == "SAVED_CONFIRMED"
        assert changed["after"]["payload"]["unrelated"]["evidence_refs"] == [old_ref]
        assert changed["after"]["version"] == before["version"] + 2
        assert changed["after"]["state_id"] == before["state_id"]
        records["stale"] = call("milai_working_state_update", changed["request"] | {
            "operation_id": "n3-stale"})
        assert "STALE_WORKING_STATE" in str(records["stale"])
        records["conflict"] = call("milai_working_state_update", changed["request"] | {
            "payload": {"other": "different"}})
        assert "OPERATION_CONFLICT" in str(records["conflict"])
        (workspace / "note.md").write_text(str(uuid4()))
        records["missing_mapping"] = checkpoint(call, workspace, "note.md", [ref], "n3-badmap")
        assert records["missing_mapping"]["status"] == "REJECTED"
        invalid = str(uuid4())
        (workspace / "note.md").write_text(invalid)
        records["invalid_ref"] = checkpoint(call, workspace, "note.md", [invalid], "n3-badref")
        assert records["invalid_ref"]["status"] == "REJECTED_EVIDENCE_REFERENCE_INVALID"
        other = [__import__("json").loads(line) for line in
                 (ROOT / "diagnostics/8550ddae/source-receipts.jsonl").read_text().splitlines()]
        cross = other[0]["receipt"]["evidence_id"]
        (workspace / "note.md").write_text(cross)
        records["cross_scope"] = checkpoint(call, workspace, "note.md", [cross], "n3-cross")
        assert records["cross_scope"]["status"] == "REJECTED_EVIDENCE_REFERENCE_INVALID"
        final = call("milai_working_state_get", {"scope": "TASK"})
        assert final["version"] == changed["after"]["version"]
        assert final["payload"][FIELD] == changed["after"]["payload"][FIELD]
        records["final"] = final
    base.write_json(directory / "result.json", {"status": "PASS", **records})
    print("N3_PUBLIC_PG_PASS")


if __name__ == "__main__":
    main()
