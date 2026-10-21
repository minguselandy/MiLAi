"""Run development requests through the existing persistent Host and retrieval tool."""
from __future__ import annotations

import argparse
import copy
import json
import os
import site
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def bind_given_request(request: dict[str, Any], delivered_refs: list[dict[str, Any]],
                       ) -> dict[str, Any]:
    """Resolve an explicit fixture condition using only earlier delivered references."""
    bound: dict[str, Any] = copy.deepcopy(request["retrieval_request"])
    if request.get("use_delivered_refs", False):
        context = bound.setdefault("task_context", {})
        if context.get("known_evidence_refs"):
            raise ValueError("Dynamic delivered refs cannot replace explicit fixture references")
        context["known_evidence_refs"] = copy.deepcopy(delivered_refs)
    return bound


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("histories", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--policies", nargs="+", choices=("fixed", "fixed_context", "rules",
                        "laya", "generative", "view_cache", "mempursuit", "coalent"),
                        default=["rules", "laya"])
    parser.add_argument("--history", action="append")
    parser.add_argument("--split", choices=("train", "dev"))
    parser.add_argument("--interfaces", nargs="+", choices=("query_only", "rich"),
                        help="Collect each request form in its own original Store bank")
    parser.add_argument("--host-site-packages", type=Path)
    parser.add_argument("--transport", choices=("native", "json_action"),
                        help="Explicit transport experiment; JSON-action is not native E0 evidence")
    parser.add_argument("--native-probe", action="store_true", help=(
        "E0 only: one named native retrieval call then the original Host answer. "
        "This is interface validation, not autonomous tool-use evaluation."))
    parser.add_argument("--capture-retrieval-calls", action="store_true",
                        help="Save each actual pre-call Store/allowance for E2; "
                             "serial tool execution")
    parser.add_argument("--capture-control-steps", action="store_true",
                        help="Also retain actual post-operation executor/Store checkpoints; "
                             "implies --capture-retrieval-calls")
    parser.add_argument("--continue-host-history", action="store_true",
                        help="Continuous banks retain their own completed Host/tool messages")
    parser.add_argument("--given-requests", action="store_true",
                        help="Conditional retrieval-only probes from fixture retrieval_request; "
                             "use_delivered_refs binds earlier actual receipts, no Host answer")
    args = parser.parse_args()
    if args.native_probe and args.transport == "json_action":
        parser.error("--native-probe requires native transport")
    if args.given_requests and (args.native_probe or args.continue_host_history):
        parser.error("--given-requests cannot generate or continue an autonomous Host conversation")
    if args.host_site_packages:
        site.addsitedir(str(args.host_site_packages))
    from langchain_core.messages import ToolMessage

    from milai_lab.runners.functional import message, prepare
    from milai_lab.runners.retrieval_histories import host_task_content, prepare_history_bank

    def native_probe(messages: list[Any]) -> Any:
        if any(isinstance(row, ToolMessage) and row.name == "milai_retrieve" for row in messages):
            return "none"
        return {"type": "function", "function": {"name": "milai_retrieve"}}

    args.output.mkdir(parents=True, exist_ok=False)
    fixture = read_json(args.histories)
    histories = [h for h in fixture["histories"]
                 if (not args.history or h["id"] in args.history)
                 and (not args.split or h["split"] == args.split)]
    config = read_json(args.config)
    if args.transport:
        settings = config["entrypoints"]["functional"]
        settings["host"]["tool_mode"] = args.transport
        for client in settings["http_ownership_domain"]["clients"]:
            if client["model"] == settings["host"]["model"]:
                client["tool_mode"] = args.transport
    budget_path = Path(config["entrypoints"]["functional"]["budget_path"])
    interfaces = args.interfaces or [config["entrypoints"]["functional"]["retrieval_tool"]]
    arms = [(policy, interface, policy + "-" + interface if args.interfaces else policy)
            for policy in args.policies for interface in interfaces]
    driver: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": args.source_version, "started_epoch": time.time(),
        "transport": config["entrypoints"]["functional"]["host"]["tool_mode"],
        "native_probe": args.native_probe, "planned_positions": sum(
            len(h["requests"]) for h in histories) * len(arms), "completed": [],
        "interfaces": interfaces, "split": args.split,
        "continue_host_history": args.continue_host_history,
        "given_requests": args.given_requests,
        "capture_retrieval_calls": args.capture_retrieval_calls or args.capture_control_steps,
        "capture_control_steps": args.capture_control_steps,
        "automatic_retry": False, "source_groups": [h["source_group"] for h in histories],
        "costs": "original continuous ledger; provider and local model traces retained"}
    write_json(args.output / "fixture.json", fixture)
    write_json(args.output / "driver.json", driver)
    write_json(args.output / "budget-before.json", read_json(budget_path))
    models: dict[tuple[Any, ...], Any] = {}
    setups: dict[tuple[str, str], dict[str, Any]] = {}
    previous_messages: dict[tuple[str, str], str] = {}
    delivered_refs: dict[tuple[str, str], list[dict[str, Any]]] = {}
    started, cpu = time.perf_counter(), time.process_time()
    try:
        for policy, interface, profile in arms:
            recipe = copy.deepcopy(config)
            settings = recipe["entrypoints"]["functional"]
            settings["memory_control"]["policy"] = policy
            settings["retrieval_tool"] = interface
            settings["config_version"] += "-" + profile
            if interface == "query_only":
                settings["system_prompt"] = (
                    "Use past evidence when the user's task needs it. Call milai_retrieve "
                    "with a query describing the missing information, then use the actual "
                    "returned evidence to finish the task. Do not invent missing history or "
                    "treat an empty result as proof that information never existed.")
            path = args.output / f"{profile}-config.json"
            write_json(path, recipe)
            prepare(args.output / profile, path, source_version=args.source_version)
        for history in histories:
            for policy, interface, profile in arms:
                for request in history["requests"]:
                    driver["active"] = {"history": history["id"], "policy": policy,
                                        "interface": interface, "profile": profile,
                                        "request": request["id"]}
                    write_json(args.output / "driver.json", driver)
                    bank = (history["id"] if history.get("continuous")
                            and not request.get("independent") else
                            history["id"] + "-" + request["id"])
                    if (profile, bank) not in setups:
                        setups[profile, bank] = prepare_history_bank(args.output / profile,
                            bank=bank, owner="development-user", history={**history,
                                "sources": request.get("sources", history["sources"]),
                                **{key: request[key] for key in ("stored_revisions", "prefetch")
                                   if key in request}})
                    # Independent goals share the declared initial source pool. Continuous
                    # histories keep their own policy's actual view and subsequent arrivals.
                    message_started, message_cpu = time.perf_counter(), time.process_time()
                    result = message(args.output / profile,
                        bank=bank, owner="development-user",
                        session="host", message_id=request["id"],
                        content=host_task_content(request, setups[profile, bank]),
                        incoming_sources=copy.deepcopy(request.get("incoming_sources", [])),
                        previous_host_message=previous_messages.get((profile, bank)),
                        **{key: request[key] for key in (
                            "occurred_at", "query_time", "calendar_context") if key in request},
                        control_models=models,
                        retrieval_snapshots=(args.output / "frozen-retrieval-calls"
                                             if args.capture_retrieval_calls
                                             or args.capture_control_steps else None),
                        retrieval_step_snapshots=args.capture_control_steps,
                        given_retrieval_request=(bind_given_request(
                            request, delivered_refs.get((profile, bank), []))
                            if args.given_requests else None),
                        model_tool_choice=native_probe if args.native_probe else None)
                    if args.given_requests:
                        known = delivered_refs.setdefault((profile, bank), [])
                        for item in result.get("retrieval_result", {}).get("evidence", []):
                            if item["ref"] not in known:
                                known.append(copy.deepcopy(item["ref"]))
                    row = {**driver["active"], "status": result["status"],
                           "answer": result.get("final_answer"), "error": result.get("error"),
                           "wall_seconds": time.perf_counter() - message_started,
                           "cpu_seconds": time.process_time() - message_cpu}
                    driver["completed"].append(row)
                    if args.continue_host_history and result["status"] == "COMPLETED":
                        previous_messages[profile, bank] = request["id"]
                    write_json(args.output / "driver.json", driver)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                    known_response_failure = (
                        (result.get("error_type") == "IncompleteChatResponse"
                         and result.get("error_category") == "provider_protocol")
                        or result.get("error") == "FUNCTIONAL_FORMAT_REPROPOSAL_EXHAUSTED")
                    known_response_failure = known_response_failure and all(
                        result["budget_after"][kind]["unknown_usage"]
                        == result["budget_before"][kind]["unknown_usage"]
                        for kind in ("generation", "embedding"))
                    if result["status"] != "COMPLETED" and not known_response_failure:
                        raise RuntimeError(
                            "First failed position retained; inspect before continuing")
        driver["status"] = ("COMPLETED_WITH_FAILURES" if any(
            row["status"] != "COMPLETED" for row in driver["completed"]) else "COMPLETED")
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        driver.update(wall_seconds=time.perf_counter() - started,
                      cpu_seconds=time.process_time() - cpu, finished_epoch=time.time())
        write_json(args.output / "driver.json", driver)
        write_json(args.output / "budget-after.json", read_json(budget_path))


if __name__ == "__main__":
    main()
