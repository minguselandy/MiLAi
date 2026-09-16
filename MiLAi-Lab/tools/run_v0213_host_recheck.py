"""Frozen exposed-task A0/H1 regression with independent cold Hosts and Product scopes."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from jsonschema import Draft202012Validator

from milai_lab.methods.acquisition_use import business_delivery_status, score_intent
from replay_v0213_cost import read, save, sha
from run_v0212_horizon import product, source_call, tool_window
from run_v0213_decomposition import FINAL
from v02_deadline import Deadline
from v02_local_provider import accounting, append_event, read_events
from v0210_v05_product import observer
from v0213_host_policy import candidate_payload, paged_bootstrap
from v0213_provider import Provider

LAB = Path(__file__).resolve().parents[1]


def prepare(root: Path, previous: Path, config_path: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    config = read(config_path)
    for key in config["tasks"]:
        for area in ("online", "evaluation"):
            shutil.copytree(previous / area / key, root / area / key)
        original = previous / "host-inputs" / key / "A0.json"
        target = root / "inputs" / key
        target.mkdir(parents=True)
        shutil.copyfile(original, target / "A0.json")
        save(target / "H1.json", candidate_payload(
            read(original), full_paged=config.get("full_paged", False)))
    files = [p for area in ("online", "evaluation", "inputs")
             for p in (root / area).rglob("*") if p.is_file()]
    implementation = [Path(__file__), LAB / "tools/v0213_host_policy.py",
                      LAB / "tools/v0213_provider.py", LAB / "tools/run_v0213_decomposition.py",
                      LAB / "tools/prepare_v0213_cases.py"]
    for path in implementation:
        destination = root / "executed-source" / path.relative_to(LAB)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    seal = {"status": "HOST_RECHECK_SEALED", "config": config,
            "parent_seal_sha256": sha((previous / "seal-b.json").read_bytes()),
            "files": {str(p.relative_to(root)): sha(p.read_bytes()) for p in files},
            "implementation": {str(p.relative_to(LAB)): sha(p.read_bytes())
                               for p in implementation}, "generations_before_seal": 0}
    save(root / "seal.json", seal)
    save(root / "seal-sha256.json", {"sha256": sha((root / "seal.json").read_bytes())})
    return seal


def cold(root: Path, owned: Path, repeat: int, key: str, arm: str) -> dict:
    directory = root / f"repeat-{repeat}" / key / arm
    directory.mkdir(parents=True, exist_ok=False)
    body = read(root / "inputs" / key / f"{arm}.json")
    config = read(root / "seal.json")["config"]
    source = root / "online" / key
    index = read(source / "source-index.json")
    scope = f"host-recheck-{repeat}-{key}-{arm}"
    start = time.monotonic()
    provider = Provider(directory, deadline=start + 300, max_requests=3)
    result = {"key": key, "arm": arm, "repeat": repeat, "status": "STARTED", "intent": None,
              "scope": scope, "source_calls": 0, "acquisition_calls": 0,
              "model_acquisition_calls": 0,
              "memory_mutations": 0, "business_actions_executed": 0}
    try:
        with Deadline(start, 300) as deadline, observer(
                owned, directory / "mcp", task=scope, principal=scope, project=scope) as public:
            catalog = public(None, {})
            actual = [{k: row[k] for k in ("name", "description", "inputSchema")}
                      for row in catalog["tools"]["tools"]]
            expected = json.loads(body["messages"][1]["content"])["memory_tools"]
            assert sorted(actual, key=lambda x: x["name"]) == sorted(
                expected, key=lambda x: x["name"])
            save(directory / "catalog.json", catalog)
            initial = {
                "notes": public("milai_memory_list", {"selection": {"kind": "NOTE"},
                                                       "limit": 100}),
                "state": public("milai_working_state_get", {"scope": "TASK"}),
                "class": "COLD_PREFLIGHT_NOT_MODEL_PRESENTED"}
            save(directory / "cold-state.json", initial)
            assert initial["notes"]["items"] == []
            assert initial["state"]["status"] == "ABSENT"
            provider.verify()

            def acquire(call: dict, actor: str) -> dict:
                limit = config["max_acquisition_calls_per_arm_including_bootstrap"]
                if result["acquisition_calls"] >= (limit if arm == "H1" else 6):
                    raise ValueError("TOOL_COUNT_LIMIT")
                if actor == "MODEL" and result["model_acquisition_calls"] >= 6:
                    raise ValueError("MODEL_TOOL_COUNT_LIMIT")
                name, arguments = call["name"], call["arguments"]
                begin = time.monotonic()
                with tool_window(deadline):
                    if name in ("source_read", "source_search"):
                        if name == "source_read" and "path" not in arguments and len(index) == 1:
                            arguments = {**arguments, "path": next(iter(index))}
                        response = source_call(source, index, name, arguments)
                        result["source_calls"] += 1
                    elif name in {row["name"] for row in actual}:
                        response = public(name, arguments)
                    else:
                        response = {"error": "UNKNOWN_ACQUISITION_TOOL"}
                result["acquisition_calls"] += 1
                result["model_acquisition_calls"] += int(actor == "MODEL")
                result["memory_mutations"] += int(name in (
                    "milai_memory_save", "milai_memory_delete", "milai_working_state_update"))
                append_event(directory / "tool-ledger.jsonl", {
                    "tool": name, "arguments": arguments, "result": response,
                    "actor": actor, "seconds": time.monotonic() - begin})
                return {"name": name, "result": response}

            if arm == "H1":
                if config.get("full_paged", False):
                    outputs, coverage = paged_bootstrap(
                        sorted(index), acquire, max_pages=config["max_bootstrap_pages"])
                else:
                    outputs = [acquire({"name": "source_read", "arguments": {
                        "path": path, "offset": 0}}, "HOST_BOOTSTRAP") for path in sorted(index)]
                    coverage = {"complete": False}
                result["source_coverage"] = coverage
                presentation = {"tool_results": outputs}
                if config.get("full_paged", False):
                    presentation["source_coverage"] = coverage
                body["messages"].append({"role": "user", "content": json.dumps({
                    **presentation}, ensure_ascii=False)})
            for turn in range(3):
                if turn == 2:
                    body["messages"].append(FINAL)
                output = provider.generate(key, body)
                action = json.loads(output)
                Draft202012Validator(body["response_format"]["json_schema"]["schema"]).validate(
                    action)
                body["messages"].append({"role": "assistant", "content": output})
                if action["action"] != "tools":
                    result.update(
                        status=business_delivery_status(action),
                        intent=action["calls"] if action["action"] == "business" else None)
                    break
                if turn == 2:
                    result["status"] = "NO_FINAL_ACTION_INTENT"
                    break
                outputs = [acquire(call, "MODEL") for call in action["calls"]]
                body["messages"].append({"role": "user", "content": json.dumps({
                    "tool_results": outputs}, ensure_ascii=False)})
    except Exception as exc:
        result.update(status="STOPPED_RESOURCE_OR_PROTOCOL_LIMIT", reason=str(exc))
    finally:
        provider.close()
        result["accounting"] = accounting(read_events(directory / "provider-ledger.jsonl"))
        result["seconds"] = time.monotonic() - start
        result["source_immutable"] = all(sha((source / p).read_bytes()) == h
                                         for p, h in index.items())
        save(directory / "result.json", result)
    return result


def audit_arm(root: Path, row: dict) -> dict:
    directory = root / f"repeat-{row['repeat']}" / row["key"] / row["arm"]
    events = read_events(directory / "provider-ledger.jsonl")
    assert accounting(events) == row["accounting"]
    assert not row["accounting"]["pending"] and not row["accounting"]["violations"]
    tools = read_events(directory / "tool-ledger.jsonl")
    presented = []
    for event in events:
        if event["event"] == "RESERVED":
            path = directory / f"{event['request_id']}-request.json"
            assert sha(path.read_bytes()) == event["payload_sha256"]
            body = read(path)
            presented = [item for message in body["messages"]
                         if message["role"] == "user" and message["content"].startswith("{")
                         for item in json.loads(message["content"]).get("tool_results", [])]
        elif event["event"] == "SETTLED":
            rid = event["request_id"]
            assert event["input_tokens"] == read(directory / f"{rid}-tokenize.json")["count"]
            assert event["usage"] == json.loads(read(directory / f"{rid}-http.json")["body"])[
                "usage"]
    assert presented == [{"name": item["tool"], "result": item["result"]}
                         for item in tools[:len(presented)]]
    assert row["source_immutable"]
    return {"usage_reconciled": True, "acquired_calls": len(tools),
            "presented_calls": len(presented), "unpresented_calls": len(tools) - len(presented),
            "host_bootstrap_calls": sum(item["actor"] == "HOST_BOOTSTRAP" for item in tools)}


def run(root: Path, installed: Path) -> dict:
    seal = read(root / "seal.json")
    assert sha((root / "seal.json").read_bytes()) == read(root / "seal-sha256.json")["sha256"]
    for relative, expected in seal["files"].items():
        assert sha((root / relative).read_bytes()) == expected
    for relative, expected in seal["implementation"].items():
        assert sha((LAB / relative).read_bytes()) == expected
    results = []
    for repeat in (1, 2):
        with product(root / f"repeat-{repeat}/product", installed) as owned:
            for key in seal["config"]["tasks"]:
                for arm in (("A0", "H1") if repeat == 1 else ("H1", "A0")):
                    subprocess.run(  # noqa: S603 -- frozen local experiment arguments
                        [sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                         "--cold", key, "--owned", str(owned), "--repeat", str(repeat),
                         "--arm", arm], check=True, timeout=310, cwd=LAB)
                    row = read(root / f"repeat-{repeat}" / key / arm / "result.json")
                    results.append(row)
                    save(root / "progress.json", {"results": results})
                    if row["accounting"]["pending"] or row["accounting"]["violations"]:
                        raise ValueError("UNKNOWN_USAGE_STOP_NO_RETRY")
    # Evaluation occurs after all cold runs; the cold function never opens evaluation files.
    for row in results:
        row["audit"] = audit_arm(root, row)
        evaluation = root / "evaluation" / row["key"]
        contract, support = read(evaluation / "evaluation-contract.json"), read(
            evaluation / "support-review.json")
        row["outcome"] = (score_intent(row["intent"], contract["expected_intent"],
                                       adjudicable=support["adjudicable"])
                          if row["status"] == "ANSWERED" else row["status"])
    report = {"status": "COLD_RECHECK_SETTLED", "results": results,
              "requests": sum(r["accounting"]["requests"] for r in results),
              "raw_tokens": sum(r["accounting"]["raw_tokens"] for r in results),
              "cumulative_raw_cap": None, "baseline": "KEEP_A0", "new_samples": 0}
    report["h1_acceptance"] = all(
        row["outcome"] == "CORRECT" and row["source_calls"] > 0
        and row["audit"]["unpresented_calls"] == 0
        and (not seal["config"].get("full_paged", False) or row["source_coverage"]["complete"])
        for row in results if row["arm"] == "H1")
    report["cleanup"] = [read(root / f"repeat-{repeat}/product/cleanup.json") for repeat in (1, 2)]
    assert all(row["api_stopped"] and row["compose_stop_returncode"] == 0
               for row in report["cleanup"])
    save(root / "result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prepare-from", type=Path)
    parser.add_argument("--config", type=Path, default=LAB / "configs/v0213-host-recheck.json")
    parser.add_argument("--installed", type=Path)
    parser.add_argument("--cold")
    parser.add_argument("--owned", type=Path)
    parser.add_argument("--repeat", type=int)
    parser.add_argument("--arm", choices=("A0", "H1"))
    args = parser.parse_args()
    if args.prepare_from:
        result = prepare(args.root, args.prepare_from, args.config)
    elif args.cold:
        result = cold(args.root, args.owned, args.repeat, args.cold, args.arm)
    else:
        result = run(args.root, args.installed)
    print(json.dumps({k: result[k] for k in ("status", "requests", "raw_tokens") if k in result}))
