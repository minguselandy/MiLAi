"""Compare frozen full-menu models at the same actual reached states and continuation."""

from __future__ import annotations

import argparse
import copy
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from collect_qasper_operation_states import complete, covered_sources, reference_proofs
from collected_handoff import replay_collected_prefix
from feedback_choices import full_menu_choice
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.laya_memory_policy import project_operation_payload
from milai_lab.methods.memory_control import MemoryAction
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request
from prepare_collected_operation_feedback import execute_branch


def bind_choice(
    row: dict[str, Any],
    case: dict[str, Any],
    projection: str,
    actual_input: dict[str, Any],
    prediction: dict[str, Any],
) -> str:
    expected = decision_example({"before": case["before"], "actions": case["actions"]}, {})
    if any(row[k] != expected[k] for k in ("state", "questions")):
        raise ValueError("Scored before/menu differs from the actual complete action bindings")
    projected = project_operation_payload(row, projection)
    if {k: projected[k] for k in ("state", "questions")} != actual_input:
        raise ValueError("Scorer input differs from the original complete reached-state input")
    if row["metadata"]["event_id"] != case["event_id"]:
        raise ValueError("Scorer row does not belong to this actual state")
    choice = full_menu_choice(case["actions"], prediction["logits"])
    if choice != prediction["choice"]:
        raise ValueError("Recorded full-menu choice differs from its actual logits")
    return choice


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument(
        "scorers", type=Path, help="JSON mapping method names to closed scorer folders"
    )
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--offset", type=int, default=0, help="Source-family offset, original order"
    )
    parser.add_argument("--families", type=int)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    preparation = read_json(args.prepared / "run.json")
    if preparation["status"] != "COMPLETED":
        raise ValueError("Use a complete actual comparison preparation")
    rows = read_jsonl(args.prepared / "states.jsonl")
    original = read_json(args.prepared / "cases.json")
    families = list(dict.fromkeys(c["family"] for c in original))
    selected = families[
        args.offset : None if args.families is None else args.offset + args.families
    ]
    cases = [c for c in original if c["family"] in selected]
    baseline = preparation["nomination_baseline"]
    scoring = {
        name: (Path(path), read_json(Path(path) / "run.json"))
        for name, path in read_json(args.scorers).items()
    }
    if not scoring or baseline in scoring:
        raise ValueError("Give distinct learned model names and retain the existing baseline")
    for _, scored in scoring.values():
        if (
            scored["status"] != "COMPLETED"
            or scored["completed_states"] != len(rows)
            or read_jsonl(Path(scored["data"])) != rows
        ):
            raise ValueError("Scorers must cover the same original complete state matrix")
    collection = Path(preparation["collection"])
    collection_run = read_json(collection / "run.json")
    histories = {h["source_group"]: h for h in read_json(collection / "sources.json")["histories"]}
    controls = {
        (r["source_group"], r["request_id"]): r
        for r in read_jsonl(Path(collection_run["controls"]))
    }
    settings = read_json(Path(preparation["config"]))["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    args.output.mkdir(parents=True, exist_ok=False)
    run = {
        "status": "RUNNING",
        "config": preparation["config"],
        "collection": str(collection),
        "original_preparation": str(args.prepared.resolve()),
        "scorers": str(args.scorers.resolve()),
        "families": len(selected),
        "states": len(cases),
        "split": preparation["split"],
        "new_packets_executed": 0,
        "reused_tool_packets": 0,
        "packets": 0,
        "new_model_calls": 0,
        "Host_calls": 0,
        "no_sha_validation": True,
        "nomination_baseline": baseline,
        "continuation_policy": preparation["continuation_policy"],
        "continuation_steps": preparation["continuation_steps"],
        "terminal_handoff": preparation["terminal_handoff"],
        "scope": "Full-menu next actions at the original frozen learner's reached states, "
        "common bounded continuation. Reuse actual identical executed bindings; execute "
        "only new full bindings. No gold nomination, Store copy, policy fallback, "
        "autonomous-trajectory claim or change to source roles.",
    }
    output = []
    write_json(args.output / "run.json", run)
    try:
        for source in cases:
            row = rows[source["state_index"]]
            choices = {baseline: source["choices"][baseline]}
            for name, (folder, scored) in scoring.items():
                call = folder / "calls" / str(source["state_index"])
                choices[name] = bind_choice(
                    row,
                    source,
                    scored["operation_state"],
                    read_json(call / "input.json"),
                    read_json(call / "output.json"),
                )
            executed = {b["action"]["id"]: copy.deepcopy(b) for b in source["branches"]}
            missing = [key for key in dict.fromkeys(choices.values()) if key not in executed]
            if missing:
                history = histories[source["family"]]
                request = next(q for q in history["requests"] if q["id"] == source["request_id"])
                source_map = read_json(collection / "banks" / history["id"] / "source-map.json")
                # Reference labels are consulted only after all model nominations are fixed.
                proofs = reference_proofs(controls[source["family"], source["request_id"]])
                with replay_collected_prefix(
                    collection, history, source, settings, capacity, target_step=source["step"]
                ) as (operations, state):
                    saved = operations.checkpoint()
                    observation = (
                        operations.source_pages.budget if operations.source_pages else None
                    )
                    for key in missing:
                        operations.restore_checkpoint(saved, observation)
                        action = next(
                            MemoryAction(**a) for a in source["actions"] if a["id"] == key
                        )
                        result = execute_branch(
                            operations,
                            source["before"],
                            action,
                            source["step"],
                            preparation["continuation_steps"],
                            preparation["terminal_handoff"],
                            baseline,
                        )
                        packet = controlled_reader_packet(
                            operations.reader_evidence(), "collection"
                        )
                        last = result["trace"][-1]
                        last_action = next(
                            a for a in last["actions"] if a["id"] == last["selected"]
                        )
                        ok = result["reason"] != "operation_outcome_unknown" and not (
                            last_action["kind"] == "HANDOFF"
                            and not last.get("result", {"ok": True})["ok"]
                        )
                        covered = covered_sources(
                            list(operations.opened.values()),
                            source_map["mapping"],
                            source_map["source_lengths"],
                        )
                        executed[key] = {
                            "action": asdict(action),
                            "continuation": result,
                            "execution_result": {"ok": ok, "status": result["reason"]},
                            "packet": packet,
                            "body_tokens": capacity.text_tokens(
                                json.dumps(packet, ensure_ascii=False)
                            ),
                            "delivered_native_sources": sorted(covered),
                            "reference_proof_complete": complete(proofs, covered)
                            if proofs
                            else None,
                            "readout_request": given_packet_request(
                                {
                                    "content": request["content"],
                                    "query_time": state.task["query_time"],
                                    "calendar_context": state.task["calendar_context"],
                                },
                                state.task["retrieval_request"],
                                packet,
                                settings,
                            ),
                        }
                        run["new_packets_executed"] += 1
            case = {
                **source,
                "choices": choices,
                "branches": [],
                "original_prefix_reexecuted_for_reconstruction": source.get(
                    "prefix_reexecuted_for_reconstruction"
                ),
                "prefix_reexecuted_for_reconstruction": bool(missing),
            }
            for key in dict.fromkeys(choices.values()):
                branch = executed[key]
                branch.update(
                    policies=[name for name, choice in choices.items() if choice == key],
                    new_tool_execution=key in missing,
                )
                case["branches"].append(branch)
                run["reused_tool_packets"] += key not in missing
            output.append(case)
            run["packets"] += len(case["branches"])
            write_json(args.output / "cases.json", output)
            write_json(args.output / "run.json", run)
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        write_json(args.output / "cases.json", output)
        (args.output / "states.jsonl").write_text((args.prepared / "states.jsonl").read_text())
        run["compute"] = {
            "cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.perf_counter() - started,
        }
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
