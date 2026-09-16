"""Real local Host acquisition/delivery/save/cold-resume chains, with isolated public MCP."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from tokenizers import Tokenizer
from transformers import AutoTokenizer

from milai_lab.methods.acquisition_use import Source, retrieval_query, score_intent
from milai_lab.methods.host_acquisition import AcquisitionHelper
from replay_v0213_cost import read, save, sha
from run_v0212_horizon import product, source_call
from run_v0213_decomposition import SCHEMA, SOURCE_TOOLS, SYSTEM, initial_view
from v02_local_provider import accounting, append_event, read_events
from v0210_v05_product import observer
from v0213_provider import Provider, payload
from v0214_budget import BudgetContract, DeliveryBudget
from v0214_delivery import Readiness, check_delivery, check_host_delivery, readiness_schema
from v0214_host_runtime import source_runtime
from v0214_source_binding import FileSources, acquire_for_task

LAB = Path(__file__).resolve().parents[1]
HOST_POLICY = (
    "For this Host, return an object with assessment followed by delivery. assessment.basis "
    "is a brief public summary of source availability or the missing/ambiguous input, not "
    "private reasoning. Decide readiness before drafting arguments: NEEDS_SOURCE to acquire, "
    "NEEDS_CLARIFICATION for unresolved inputs, BLOCKED for denied/unavailable prerequisites, "
    "READY only for a grounded unambiguous plan. requested_business_operations counts only "
    "the business operations explicitly requested, excluding memory saves and source reads. "
    "delivery contains action/calls/answer as specified below; it must match the assessment. "
    "Generic Host acquisition policy: source files are normal history entries, separate from "
    "Product memory. If current user inputs already specify all needed values, deliver without "
    "retrieving history. Otherwise call host_acquire with empty arguments: it selects an exact "
    "read, bounded scan or fixed lexical search based on the trusted source inventory. You may "
    "continue source pages or search for short literal terms if necessary. Query completion and "
    "source coverage do not prove semantic sufficiency. NOT_ACQUIRED/UNKNOWN means history has "
    "not been checked, NOT that values are missing. When the request refers to past agreements "
    "and eligible sources have not been read, first choose NEEDS_SOURCE and set delivery to "
    '{"action":"tools","calls":[{"name":"host_acquire","arguments":{}}],'
    '"answer":"I will read the available history before preparing the plan."}. '
    "Only after checking available sources and current Note/State results, missing required "
    "values or unresolved identity require action=abstain with a specific clarification "
    "question, not invented values. If no sources are available, ask directly. "
    "Several individually valid alternatives do not identify the requested one. If history "
    "records multiple active choices without a preference, ask the user which choice to use; "
    "never select the first, invent a default or let schema validity resolve ambiguity. "
    "Current explicit user inputs override old memory. Business calls are DRAFT INTENTS ONLY. "
    "Emit exactly the business operations requested, with no duplicate calls unless the user "
    "explicitly asks for repetition. Remembering a configuration is not another business "
    "operation: the Host separately performs an explicitly requested optional Note save after "
    "delivery. Do not put that save into the business plan or claim it has already happened. "
    "The answer must describe the pending plan, never claim a new live result or successful "
    "external execution. Historical outputs are historical evidence, not current results."
)


def prepare(root: Path, inputs: Path, config_path: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    config = read(config_path)
    _, runtime_identity = source_runtime(config)
    shutil.copytree(inputs, root / "cases")
    implementation = [Path(__file__), LAB / "src/milai_lab/methods/host_acquisition.py",
        LAB / "tools/v0214_source_binding.py", LAB / "tools/v0214_delivery.py",
        LAB / "tools/v0214_budget.py", LAB / "tools/v0213_provider.py",
        LAB / "tools/v0213_host_policy.py", LAB / "tools/run_v0212_horizon.py",
        LAB / "tools/v0214_host_runtime.py"]
    for path in implementation:
        target = root / "executed-source" / path.relative_to(LAB)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    files = [p for p in (root / "cases").rglob("*") if p.is_file()]
    manifest = {"status": "SEALED_NOT_RUN", "config": config,
        "files": {str(p.relative_to(root)): sha(p.read_bytes()) for p in files},
        "implementation": {str(p.relative_to(LAB)): sha(p.read_bytes()) for p in implementation},
        "model_requests_before_seal": 0, "host_acquisition": runtime_identity}
    save(root / "manifest.json", manifest)
    save(root / "manifest-sha256.json", {"sha256": sha((root / "manifest.json").read_bytes())})
    return manifest


def task_directory(root: Path, key: str, phase: int) -> Path:
    online = root / "cases" / key / "online"
    return online / f"phase-{phase}" if (online / f"phase-{phase}").exists() else online


def reconcile_presentation(directory: Path, helper: AcquisitionHelper) -> list[dict]:
    receipts = []
    for event in read_events(directory / "provider-ledger.jsonl"):
        if event["event"] != "RESERVED":
            continue
        rid = event["request_id"]
        responded = (directory / f"{rid}-http.json").exists()
        pages = []
        for message in read(directory / f"{rid}-request.json")["messages"]:
            if message["role"] != "user" or not message["content"].startswith("{"):
                continue
            for value in json.loads(message["content"]).get("source_pages", []):
                original = helper.calls[value["request_id"]].page
                pages.append(type(original)(**{**value,
                    "binding": type(original.binding)(**value["binding"]),
                    "coverage": type(original.coverage)(value["coverage"])}))
        if responded:
            helper.record_presentation(rid, pages)
        receipts.append({"request_id": rid, "transmission": "HTTP_RESPONSE_OBSERVED" if responded
                         else "UNKNOWN_AFTER_RESERVATION", "source_request_ids": [
                             page.request_id for page in pages if page.text]})
    return receipts


def cold(root: Path, owned: Path, key: str, arm: str, phase: int) -> dict:
    with asyncio.Runner() as loop:
        return cold_session(root, owned, key, arm, phase, loop)


def cold_session(root: Path, owned: Path, key: str, arm: str, phase: int,
                 loop: asyncio.Runner) -> dict:
    config = read(root / "manifest.json")["config"]
    if not config["model_transport_enabled"]:
        raise ValueError("MODEL_TRANSPORT_DISABLED")
    api, runtime_identity = source_runtime(config)
    assert runtime_identity == read(root / "manifest.json").get(
        "host_acquisition", {"implementation": "LAB"})
    directory = root / "runs" / key / arm / f"phase-{phase}"
    directory.mkdir(parents=True, exist_ok=False)
    online = task_directory(root, key, phase)
    task = read(online / "task.json")
    scope = f"v0214-{root.name}-{key}-{arm}"
    binding = api.Binding(scope, scope, scope)
    backend = FileSources({binding: online}, source_api=api)
    helper = api.AcquisitionHelper(backend, max_parallel_source_reads=config["source_parallelism"])
    refs = loop.run(helper.resolve_sources(binding))
    save(directory / "host-runtime.json", runtime_identity)
    save(directory / "source-binding.json", {"binding": asdict(binding),
                                             "sources": [asdict(ref) for ref in refs]})
    index = {ref.source_id: ref.version for ref in refs}
    sources = [Source(ref.source_id, (online / ref.source_id).read_text()) for ref in refs]
    acquired, product_outputs = [], []
    began = time.monotonic()
    cpu_began = time.process_time()
    provider = Provider(directory, deadline=began + config["seconds_per_phase"], max_requests=3)
    budget = DeliveryBudget(root / "runs" / key / arm / "budget-ledger.jsonl",
        BudgetContract(6, 65536, 4096, config["final_delivery_reserve"], None))
    result = {"key": key, "arm": arm, "phase": phase, "pid": os.getpid(),
              "started_monotonic": began,
              "status": "STARTED", "intent": None, "memory_mutations": 0,
              "business_actions_executed": 0, "save": "NO_CHANGE", "model_messages_inherited": 0}
    tokenizer_root = Path(config["tokenizer_snapshot"])
    tokenizer = Tokenizer.from_file(str(tokenizer_root / "effective-tokenizer.json"))
    renderer = AutoTokenizer.from_pretrained("/cra/qwen36-35B", local_files_only=True)
    template = (tokenizer_root / "chat_template.jinja").read_text()

    def count(messages):
        rendered = renderer.apply_chat_template(messages, tokenize=False, chat_template=template,
                                                add_generation_prompt=True, enable_thinking=False)
        return len(tokenizer.encode(rendered, add_special_tokens=False).ids)

    try:
        with observer(owned, directory / "mcp", task=scope,
                      principal=scope, project=scope) as public:
            catalog = public(None, {})
            actual = [{k: item[k] for k in ("name", "description", "inputSchema")}
                      for item in catalog["tools"]["tools"]]
            expected = read(LAB.parent / "MiLAi-Product/contracts/mcp/"
                            "compact-memory-v1.release-0.1.15.tools.json")[
                                "catalogs"]["compact-memory-v1"]["tools"]
            assert {x["name"]: x["inputSchema"] for x in actual} == {
                x["name"]: x["inputSchema"] for x in expected}
            save(directory / "catalog.json", catalog)

            def memory(name, arguments, purpose="MODEL"):
                start = time.monotonic()
                value = public(name, arguments)
                append_event(directory / "public-calls.jsonl", {"tool": name,
                    "arguments": arguments, "result": value, "purpose": purpose,
                    "started_monotonic": start, "ended_monotonic": time.monotonic(),
                    "seconds": time.monotonic() - start,
                    "request_json_bytes": len(json.dumps(arguments).encode()),
                    "response_json_bytes": len(json.dumps(value).encode())})
                return value

            state = memory("milai_working_state_get", {"scope": "TASK"}, "COLD_REBIND")
            notes = memory("milai_memory_list", {"selection": {"kind": "NOTE"}, "limit": 4},
                           "COLD_REBIND")
            save(directory / "cold-resume.json", {"phase": phase, "pid": os.getpid(),
                "binding": asdict(binding), "state": state, "notes": notes,
                "inherited_messages": 0, "shared_model_cache_allowed": True})
            # Normal current-scope inventory, not a retained note ID or another arm's log.
            if phase:
                for note in notes.get("items", []):
                    nid = note.get("memory_id", note.get("note_id", note.get("id")))
                    if nid:
                        target = {"target": {"kind": "NOTE", "id": nid}}
                        product_outputs.append({"name": "milai_memory_read", "arguments": target,
                            "result": memory("milai_memory_read", target,
                            "COLD_CURRENT_NOTE_READ")})
            provider.verify()
            info = {"mode": "NOT_ACQUIRED", "coverage": "UNKNOWN"}

            def acquire():
                nonlocal info
                start = time.monotonic()
                pages, info = loop.run(acquire_for_task(helper, backend, binding, task,
                    complete_bytes=config["complete_read_bytes"], max_pages=config["max_pages"]))
                acquired.extend(page.request_id for page in pages)
                save(directory / "acquisition-plan.json", info)
                append_event(directory / "timeline.jsonl", {"event": "SOURCE_ACQUIRED",
                    "started_monotonic": start, "ended_monotonic": time.monotonic(),
                    "request_ids": [page.request_id for page in pages]})

            if arm == "LX":
                acquire()
            journal = []
            force_final = False
            for turn in range(3):
                rid = f"{key}-p{phase}-{turn+1:02d}"
                pages = loop.run(helper.presentation(binding, acquired, rid))
                if turn:
                    state = memory("milai_working_state_get", {"scope": "TASK"},
                                   "CURRENT_PRESENTATION_CHECK")
                    notes = memory("milai_memory_list", {
                        "selection": {"kind": "NOTE"}, "limit": 4}, "CURRENT_PRESENTATION_CHECK")
                    for item in product_outputs:
                        if item["name"].startswith("milai_") and "arguments" in item:
                            item["result"] = memory(item["name"], item["arguments"],
                                                    "CURRENT_PRESENTATION_CHECK")
                tools = copy.deepcopy(SOURCE_TOOLS)
                if arm != "A0":
                    tools.append({"name": "host_acquire", "arguments": {}})
                common = {"question": task["question"], "business_tools": task["business_tools"],
                    "current_inputs": task.get("current_inputs", {}),
                    "source_files": index, "memory_tools": actual, "source_tools": tools,
                    "source_binding": {"mode": "CURRENT_TRUSTED_INVENTORY",
                        "carriers": {"SOURCE_FILES": [asdict(ref) for ref in refs],
                            "PRODUCT_NOTES": {"items": notes.get("items", []),
                                "next_cursor": notes.get("next_cursor"),
                                "entrypoint": "milai_memory_read"},
                            "WORKING_STATE": {"status": state.get("status"),
                                "entrypoint": "milai_working_state_get"}},
                        "product_populated": bool(notes.get("items")) or
                            state.get("status") not in (None, "ABSENT")},
                    "source_view": initial_view(sources) if sources and arm == "A0" else None,
                    "current_state": state, "current_note_results": product_outputs,
                    "source_pages": [asdict(page) for page in pages],
                    "coverage": {"mode": info["mode"], "observation": info["coverage"]},
                    "host_journal": journal}
                messages = [{"role": "system", "content": SYSTEM + (
                    "\n" + HOST_POLICY if arm != "A0" else "")},
                    {"role": "user", "content": json.dumps(common, ensure_ascii=False)}]
                final = turn == 2 or arm == "LX" or force_final
                if final:
                    messages.append({"role": "user", "content":
                        "Final delivery slot: submit the pending call plan or ask clarification. "
                        "External business actions have not executed. Do not acquire more."})
                schema = SCHEMA if arm == "A0" else readiness_schema(task["business_tools"], SCHEMA)
                body = payload(messages, schema)
                upper = count(messages) + 4096
                if not final and budget.allow(upper) == "FINAL_ONLY":
                    final = True
                    messages.append({"role": "user", "content":
                        "The Host has reserved this final slot: deliver a pending plan or "
                        "ask for missing inputs now. No more acquisition is allowed."})
                    body = payload(messages, schema)
                    upper = count(messages) + 4096
                decision = budget.reserve(rid, upper, final=final)
                append_event(directory / "allocations.jsonl", {"request_id": rid,
                    "upper": upper, "final": final, "decision": decision,
                    "final_delivery_reserve": config["final_delivery_reserve"]})
                if decision != "ALLOW":
                    result.update(status="BUDGET_STOP", reason=decision)
                    break
                dispatch_started = time.monotonic()
                output = provider.generate(f"{key}-p{phase}", body)
                event = read_events(directory / "provider-ledger.jsonl")[-1]
                budget.settle(rid, event["usage"]["total_tokens"])
                helper.record_presentation(rid, pages)
                append_event(directory / "timeline.jsonl", {"event": "MODEL_SETTLED",
                    "request_id": rid, "started_monotonic": dispatch_started,
                    "ended_monotonic": time.monotonic(),
                    "source_request_ids": [page.request_id for page in pages if page.text]})
                envelope = json.loads(output)
                action = envelope if arm == "A0" else envelope["delivery"]
                check = (check_delivery if arm == "A0" else check_host_delivery)(
                    envelope, task["business_tools"], current_inputs=task.get("current_inputs"))
                append_event(directory / "delivery-checks.jsonl", {"request_id": rid,
                    "decision": asdict(check), "model_action": action,
                    "assessment": envelope.get("assessment")})
                if action["action"] != "tools":
                    result.update(status=("DELIVERED" if check.structurally_valid
                        and action["action"] == "business" else "CLARIFIED" if
                        check.structurally_valid else "FORMAT_ERROR"), intent=check.complete_plan,
                        readiness=check.readiness, answer=action["answer"])
                    if check.structurally_valid and check.readiness == Readiness.BLOCKED:
                        result["status"] = "BLOCKED"
                    break
                if final:
                    result["status"] = "NO_FINAL_DELIVERY"
                    break
                for call in action["calls"]:
                    if len(journal) >= config["max_model_acquisition_calls"]:
                        result["status"] = "ACQUISITION_LIMIT"
                        break
                    # Reserve one bounded tool result in the final request before acquiring it.
                    tool_decision = budget.allow(upper + config["tool_result_upper_tokens"],
                                                 final=True)
                    if tool_decision != "ALLOW":
                        journal.append({"tool": call["name"], "status": "FINAL_RESERVE_ONLY"})
                        force_final = True
                        break
                    name, args = call["name"], call["arguments"]
                    if name == "host_acquire" and arm != "A0":
                        acquire()
                    elif name == "source_read":
                        ref = next(item for item in refs if item.source_id == args.get(
                            "path", refs[0].source_id))
                        page = loop.run(helper.read_source(binding, ref, args.get("offset", 0)))
                        acquired.append(page.request_id)
                    elif name == "source_search":
                        start = time.monotonic()
                        value = source_call(online, index, name, args)
                        product_outputs.append({"name": name, "result": value})
                        append_event(directory / "source-search.jsonl", {"arguments": args,
                            "result": value, "seconds": time.monotonic() - start})
                    elif name in {item["name"] for item in actual} and name not in (
                            "milai_memory_save", "milai_memory_delete",
                            "milai_working_state_update"):
                        product_outputs.append({"name": name, "arguments": args,
                                                "result": memory(name, args)})
                    else:
                        product_outputs.append({"name": name, "result": {
                            "error": "UNKNOWN_OR_UNAUTHORIZED_ACQUISITION"}})
                    journal.append({"tool": name, "status": "RETURNED"})
            if task.get("remember_sources_on_success") and result["status"] == "DELIVERED":
                # Explicit fixture/user save request; no automatic file-to-Memory ingestion.
                text = "\n".join(source.text for source in sources)
                saved = memory("milai_memory_save", {"content": text,
                    "operation_id": f"{scope}-explicit-remember",
                    "options": {"action": "ADD_NOTE"}}, "EXPLICIT_USER_REMEMBER")
                result.update(save=saved, memory_mutations=1)
            # Counterfactual query cross-replays are evaluator artifacts, not model inputs.
            replay = []
            queries = [event["arguments"]["query"] for event in read_events(
                directory / "public-calls.jsonl") if event["tool"] == "milai_memory_search"]
            for query in queries:
                replay.append({"origin": "A0_OR_HOST_QUERY", "query": query,
                    "lexical": loop.run(backend.search(binding, query, []))})
            lexical_query = retrieval_query(task["question"], task["business_tools"])
            replay.append({"origin": "FIXED_LEXICAL_QUERY", "query": lexical_query,
                "original_product_backend": memory("milai_memory_search", {
                    "query": lexical_query}, "ZERO_GENERATION_CROSS_REPLAY")})
            save(directory / "query-cross-replay.json", {"new_generations": 0,
                                                       "presented_to_model": False, "rows": replay})
    except Exception as exc:
        result.update(status="PROTOCOL_OR_RESOURCE_FAILURE", reason=str(exc))
    finally:
        provider.close()
        save(directory / "transport-presentation.json", reconcile_presentation(directory, helper))
        result["accounting"] = accounting(read_events(directory / "provider-ledger.jsonl"))
        used, reservations, pending = budget.state()
        result["delivery_budget"] = {"settled_raw_tokens": used,
            "reservations_including_prior_phase": reservations, "pending": pending}
        result["seconds"] = time.monotonic() - began
        result["ended_monotonic"] = time.monotonic()
        result["host_cpu_seconds"] = time.process_time() - cpu_began
        result["memory_need_policy"] = "HOST_DECIDES_FROM_CURRENT_REQUEST"
        result["acquired_calls"] = len(helper.calls)
        result["presented_request_ids"] = sorted({rid for _, rid in helper.presented})
        save(directory / "acquisition-calls.json", [asdict(item) for item in helper.calls.values()])
        save(directory / "presentation.json", helper.presented)
        save(directory / "result.json", result)
    return result


def run(root: Path, installed: Path) -> dict:
    manifest = read(root / "manifest.json")
    assert sha((root / "manifest.json").read_bytes()) == read(root / "manifest-sha256.json")[
        "sha256"]
    for relative, expected in manifest["implementation"].items():
        assert sha((LAB / relative).read_bytes()) == expected
    for relative, expected in manifest["files"].items():
        assert sha((root / relative).read_bytes()) == expected
    config, results = manifest["config"], []
    _, runtime_identity = source_runtime(config)
    assert runtime_identity == manifest.get("host_acquisition", {"implementation": "LAB"})
    with product(root / "product", installed) as owned:
        def execute(case):
            key, arm, phase = case
            subprocess.run(  # noqa: S603 -- declared local frozen runner inputs
                [sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                 "--cold", key, "--arm", arm, "--phase", str(phase), "--owned", str(owned)],
                check=True, timeout=config["seconds_per_phase"] + 20, cwd=LAB)
            row = read(root / "runs" / key / arm / f"phase-{phase}/result.json")
            evaluation = root / "cases" / key / "evaluation"
            path = evaluation / f"contract-{phase}.json"
            contract = read(path if path.exists() else evaluation / "contract.json")
            if contract.get("expected_readiness") == "NEEDS_CLARIFICATION":
                row["outcome"] = "CORRECT_CLARIFICATION" if row["status"] == "CLARIFIED" \
                    else "CLARIFICATION_FAILURE"
            else:
                expected = contract["expected_intent"]
                expected = expected["calls"] if isinstance(expected, dict) else expected
                row["outcome"] = score_intent(row["intent"], expected, adjudicable=True) \
                    if row["status"] == "DELIVERED" else row["status"]
            return row

        def record(rows):
            results.extend(rows)
            save(root / "progress.json", {"results": results})
            if any(row["accounting"]["pending"] or row["accounting"]["violations"] or
                   row["delivery_budget"]["pending"] for row in rows):
                raise ValueError("UNKNOWN_USAGE_STOP_NO_AUTOMATIC_RETRY")

        concurrent = config.get("concurrent_task_keys", [])
        for key in config["tasks"]:
            if key not in concurrent:
                for arm in config["arms"]:
                    if arm == "LX" and key not in config.get("lexical_task_keys", config["tasks"]):
                        continue
                    for phase in config["phases"]:
                        record([execute((key, arm, phase))])
        if concurrent:
            with ThreadPoolExecutor(max_workers=len(concurrent)) as pool:
                for arm in config["arms"]:
                    for phase in config["phases"]:
                        record(list(pool.map(execute, [(key, arm, phase) for key in concurrent])))
    report = {"status": "REAL_HOST_RUN_SETTLED", "results": results,
        "requests": sum(row["accounting"]["requests"] for row in results),
        "raw_tokens": sum(row["accounting"]["raw_tokens"] for row in results),
        "cleanup": read(root / "product/cleanup.json"), "cumulative_raw_cap": None}
    save(root / "result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prepare-from", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--installed", type=Path)
    parser.add_argument("--cold")
    parser.add_argument("--arm", choices=("A0", "H", "LX"))
    parser.add_argument("--phase", type=int)
    parser.add_argument("--owned", type=Path)
    args = parser.parse_args()
    if args.prepare_from:
        result = prepare(args.root, args.prepare_from, args.config)
    elif args.cold:
        result = cold(args.root, args.owned, args.cold, args.arm, args.phase)
    else:
        result = run(args.root, args.installed)
    print(json.dumps({k: result[k] for k in ("status", "requests", "raw_tokens") if k in result}))
