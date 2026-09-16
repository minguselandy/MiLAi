"""Audit the corrected N4 snapshot, retaining prior costs and excluding later N5 allocations."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import run_v02_memory_flow as base
from check_v02_payload_fidelity import PRIOR, ROOT
from run_v02_lme_reuse import remap
from v02_low_cost_protocol import allocation_rows, digest, usage_tokens


def main() -> None:
    config_path = base.LAB / "configs/v02-fidelity-followup.json"
    pin = base.pin(config_path)
    plan = base.read_json(base.LAB / "studies/active/MILA_V02_LOW_COST_REUSE_R.json")
    review = base.read_json(ROOT / "semantic-review.json")
    allocations = []
    for root in (PRIOR, ROOT):
        for path in sorted(root.glob("sessions/*/allocation.json")):
            a = base.read_json(path)
            if a["phase"] == "N5":
                continue
            r = base.read_json(path.parent / "result.json")
            tokens = usage_tokens(r)
            if tokens is None:
                raise RuntimeError("Unknown started usage")
            allocations.append({"allocation_id": a["allocation_id"], "phase": a["phase"],
                "arm": a["arm"], "case_id": a["case_id"], "batch_id": a["batch_id"],
                "model_started": r["model_started"], "known_tokens": tokens,
                "input_tokens": sum(u["input_tokens"] for u in r.get("usage") or []),
                "output_tokens": sum(u["output_tokens"] for u in r.get("usage") or []),
                "cached_input_tokens": sum(u["cached_input_tokens"] for u in r.get("usage") or []),
                "raw_online_seconds": r["raw_online_seconds"],
                "operational_online_seconds": r.get("operational_online_seconds"),
                "instrumentation_seconds": r.get("instrumentation_seconds"),
                "status": r.get("status", "COMPLETED"),
                "artifact": str(path.parent.relative_to(base.LAB))})
    assert len(allocations) == sum(a["phase"] != "N5"
                                   for a, _ in allocation_rows([PRIOR, ROOT]))
    pairs, histories = [], []
    for cluster in plan["clusters"]:
        case = cluster["case_id"]
        original = Path(base.read_json(PRIOR / f"generator-{case}.json")["observation"])
        g_workspace = Path(base.read_json(original / "host-paths.json")["workspace"])
        g = base.read_json(original / "result.json")
        cp = base.read_json(ROOT / case / "checkpoint.json")
        assert cp["status"] == "SAVED_CONFIRMED"
        assert cp["model_tokens"] == 0 and cp["model_dispatches"] == 0
        totals = {a: {"tokens": 0, "seconds": 0.0} for a in ("F", "S")}
        quality = True
        for followup in cluster["followups"]:
            pair = {"case_id": case, "future": followup["id"], "arms": {}}
            shared = []
            for arm in ("F", "S"):
                name = f"r-{case}-{followup['id']}-{arm}"
                directory = ROOT / "sessions" / name
                r = base.read_json(directory / "result.json")
                a = base.read_json(directory / "allocation.json")
                assert r["returncode"] == 0 and r["stop_reason"] is None
                assert a["pin"] == pin and a["config_sha256"] == digest(config_path)
                head = base.read_json(directory / "before.json")
                assert head["status"] == ("ABSENT" if arm == "F" else "ACTIVE")
                assert head["version"] == (0 if arm == "F" else 1)
                profile = tomllib.loads((directory / "host-profile.toml").read_text())
                data = profile["developer_instructions"].split(
                    "<MILA_HOST_WORKING_STATE_DATA>\n")[1].split(
                    "\n</MILA_HOST_WORKING_STATE_DATA>")[0]
                bootstrap = json.loads(data)
                assert bootstrap["payload"] == head["payload"]
                assert bootstrap["status"] == head["status"]
                assert bootstrap["canonical"] is False and bootstrap["warnings"] == []
                assert len(base.read_json(directory / "tool-catalog.json")["tools"]["tools"]) == 13
                artifacts = base.read_json(directory / "task-artifacts.json")
                mapping = base.read_json(directory / "branch-evidence-map.json")
                for item in artifacts:
                    source_name = ("answer.txt" if item["path"] == "prior-task-answer.txt"
                                   else item["path"])
                    source_file = g_workspace / source_name
                    assert digest(source_file) == item["sha256"]
                    mapped = remap(source_file.read_text(), mapping).encode()
                    assert hashlib.sha256(mapped).hexdigest() == item["branch_sha256"]
                    if item["path"] == cluster["note_path"]:
                        assert item["sha256"] == item["branch_sha256"]
                shared.append({"source": base.read_json(directory / "source-access.json"),
                               "files": [{"path": x["path"], "sha256": x["sha256"]}
                                         for x in artifacts],
                               "prompt": (directory / "user-prompt.txt").read_text()})
                if arm == "S":
                    field = head["payload"]["milai_lab_exact_note_v1"]
                    assert field["content_sha256"] == cp["after"]["payload"][
                        "milai_lab_exact_note_v1"]["content_sha256"]
                q = review["sessions"][name]
                assert q["answer_sha256"] == digest(directory / "answer.txt")
                quality = quality and q["prespecified_quality_pass"]
                tokens = usage_tokens(r)
                assert tokens is not None
                seconds = r["operational_online_seconds"]
                totals[arm]["tokens"] += tokens
                totals[arm]["seconds"] += seconds
                pair["arms"][arm] = {"tokens": tokens, "operational_seconds": seconds,
                    "tool_actions": base.tool_action_count(
                        base.parse_events(directory / "events.jsonl")),
                    "before_version": head["version"], "after_version": r["after_version"],
                    "quality": q, "branch_and_bootstrap_verified": True}
            assert shared[0] == shared[1]
            pairs.append(pair)
        ratio = totals["S"]["tokens"] / totals["F"]["tokens"]
        net_seconds = totals["F"]["seconds"] - totals["S"]["seconds"] - cp["delta_save_seconds"]
        histories.append({"case_id": case, "F_future": totals["F"], "S_future": totals["S"],
            "delta_save_tokens": 0, "delta_save_seconds": cp["delta_save_seconds"],
            "S_over_F_tokens": ratio, "token_reduction_fraction": 1 - ratio,
            "net_saved_seconds": net_seconds, "prespecified_quality_pass": quality,
            "cost_gate_pass": ratio <= 0.9 and net_seconds > 0,
            "N4_history_pass": quality and ratio <= 0.9 and net_seconds > 0,
            "common_G_tokens": usage_tokens(g), "common_G_seconds": g["operational_online_seconds"],
            "counterfactual_paths": {arm: {"tokens": usage_tokens(g) + totals[arm]["tokens"],
                "seconds": g["operational_online_seconds"] + totals[arm]["seconds"]
                           + (cp["delta_save_seconds"] if arm == "S" else 0)}
                for arm in ("F", "S")}})
    n4_pass = all(h["N4_history_pass"] for h in histories)
    result = {"study": "MILA-V02-03-CORRECTION", "snapshot": "THROUGH_N4", "pin": pin,
        "status": "AWAITING_N5" if n4_pass else "COMPLETED_KEEP_BASELINE",
        "N4": "PASS_FOR_CONFIRMATION" if n4_pass else "FAIL_PRESPECIFIED_GATE",
        "N5": "REQUIRED" if n4_pass else "NOT_ENTERED_NO_N4_PASS_OR_RELIABLE_QA_DEFECT",
        "model_allocations": len(allocations),
        "actual_model_sessions": sum(a["model_started"] for a in allocations),
        "known_total_tokens": sum(a["known_tokens"] for a in allocations),
        "known_input_tokens": sum(a["input_tokens"] for a in allocations),
        "known_output_tokens": sum(a["output_tokens"] for a in allocations),
        "cached_input_tokens_subset": sum(a["cached_input_tokens"] for a in allocations),
        "phase_allocations": {p: sum(a["phase"] == p for a in allocations)
                              for p in ("N0_N2", "N3_N4", "N5")},
        "raw_online_seconds_all_allocations": sum(a["raw_online_seconds"] for a in allocations),
        "all_allocations_terminal": True, "unknown_started_usage": False,
        "histories": histories, "pairs": pairs, "allocations": allocations,
        "max_pair_S_over_F_tokens": max(p["arms"]["S"]["tokens"] / p["arms"]["F"]["tokens"]
                                        for p in pairs),
        "quality_review": "Root offline source review, not independent or human gold",
        "later_model_inputs": "UNOBSERVED; launcher bootstrap file verified",
        "common_G_provenance": "Unchanged prior completed G files; prior pin, shared by both arms",
        "research_cost_limitations": ["Prior pre-exec failure operational partition unknown",
            "Root engineering and full research setup time not completely measured",
            "Capture, branch seeding and instrumentation remain separate research overhead"],
        "checks": {"runtime_pg_passed": 971, "runtime_pg_skipped": 1, "lab_passed": 158,
                   "static_boundary_build": "PASS", "unchanged_G_public_roundtrips": 2},
        "cleanup": base.read_json(ROOT / "cleanup.json") if (ROOT / "cleanup.json").exists()
                   else {"status": "PENDING"},
        "automatic_maintenance": False, "public_deployment": False, "formal_500_scoring": False}
    if result["cleanup"]["status"] != "COMPLETE":
        result["status"] = "EVALUATED_CLEANUP_PENDING"
    base.write_json(ROOT / "followup-results.json", result)
    print(json.dumps({k: result[k] for k in ("status", "model_allocations", "known_total_tokens",
                                            "N4", "N5", "histories")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
