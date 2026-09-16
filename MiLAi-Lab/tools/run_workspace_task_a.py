"""Opt-in historical task A: deterministic pack, existing HTTP Provider, three policies.

Only published JSON materials and bounded arithmetic reach the task dispatcher.
Raw evidence lives outside Git; no Product calls or model-generated code execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import operator
import time
from dataclasses import asdict
from pathlib import Path

from milai_lab.methods.workspace_policy import Exchange, Limits, Material, Message, WorkspaceError
from v02_client_gc import overlap_ms, spans
from v02_local_provider import accounting, append_event, read_events
from v0213_provider import ENDPOINT, MODEL
from workspace_policy_host import Generation, WorkspaceHost, load_policy
from workspace_task_provider import Provider

LAB = Path(__file__).resolve().parents[1]
SOURCE = LAB / "artifacts/v02-e2e-generality"
TOKENIZER = LAB.parent / "evidence/v0213/p0-20260909"
ROOTS = ("p1-transaction-load-20260906a", "p1-client-gc-20260906a", "p1-mcp-boundary-20260906a")
ORDER = ("NOTE", "REVIEW", "REGULATED")
VERSION = "workspace-task-a-v4"
FIELDS = (
    "client_ms = 1000*(MCP client end_s-start_s); arrival.call_ms measures the outer "
    "arrival scheduler await and is a different interval. handler_ms is MCP handler elapsed; "
    "runtime_client_ms is the handler's runtime HTTP call; application_ms is runtime "
    "application elapsed. db_pool_acquire_ms measures connection acquisition; "
    "db_connection_hold_ms measures connection-held scope; db_transaction_enter_ms and "
    "db_transaction_exit_ms measure transaction context enter/exit elapsed. Counts say how "
    "many intervals were aggregated. Durations are milliseconds; monotonic timestamps seconds. "
    "Nested intervals must not be added as disjoint costs. Derived residuals are differences, "
    "not additional observations. GC callbacks cover only the named client process and recorded "
    "window. Missing observations are unknown. handler start/end timestamps are available only "
    "in batches that recorded them, and subtraction across processes requires clock binding. "
    "These are deliberately selected historical requests, not a random sample or a controlled "
    "performance treatment comparison. Each batch has a distinct measurement version."
)
TASK = (
    "Diagnose long-tail working-state reads from three batches of historical measurements. "
    "Give the most specific supported localization, important unresolved causes, and one useful "
    "next check explaining what it would distinguish. Preserve audit, durability and load limits. "
    "Two later historical batches will be released regardless of your earlier answer; they are "
    "not results of checks you request. Up to 4 normal decisions per batch, 12 total. "
    "Actions: read {ref:string} reads a published neutral handle; calculate {op:add|subtract|"
    "multiply|divide, left:number, right:number} performs arithmetic; suggest_check {text:string} "
    "records a proposed uncollected check and returns NO_OBSERVATION; stage_answer {text:string} "
    "ends the current batch; final {text:string} submits the final synthesis in batch 3 only. "
    "Batch 3's last opportunity should deliver final. All materials remain readable after release. "
    "Use concise answers with batch/request references. The optional work record is yours to write."
)


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def subset(value: dict, keys: tuple[str, ...]) -> dict:
    return {k: value[k] for k in keys if k in value}


def json_location(path: Path, index: int, key: str, value: object) -> dict:
    # Exact array index plus the line containing its identifying field.
    needle = json.dumps(key) + ": " + json.dumps(value)
    matches = [i for i, line in enumerate(path.read_text().splitlines(), 1) if needle in line]
    return {"path": str(path.resolve()), "json_pointer": f"/{index}", "matching_lines": matches}


def pack(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    batches, sources = [], {}
    extraction_cpu, extraction_wall = time.process_time(), time.monotonic()
    for batch, name in enumerate(ROOTS, 1):
        directory = SOURCE / name / (name + "-baseline")
        correlated = directory / "timing-correlated.json"
        rows = json.loads(correlated.read_text())
        tails = sorted(range(len(rows)), key=lambda i: (-rows[i]["values"]["client_ms"], i))[:1]
        median = sorted(r["values"]["client_ms"] for r in rows)[len(rows) // 2]
        chosen = set(tails)
        for i in tails:
            normal = min(
                (j for j in range(len(rows)) if rows[j]["values"]["client_ms"] <= median),
                key=lambda j: (abs(i - j), j),
            )
            chosen.add(normal)
        paths = {
            "correlated": correlated,
            "arrival": directory / "arrival-events.json",
            "mcp_event": directory / "mcp-events.json",
            "runtime": directory / (directory.name + "-product") / "api.log",
            "mcp_stage": directory / "mixed-mcp/mixed-mcp.log",
        }
        events = json.loads(paths["mcp_event"].read_text())
        arrivals = json.loads(paths["arrival"].read_text())
        raw_indexes = {}
        for kind, marker, key in (
            ("runtime", '"event":"runtime_request_timing"', "request_id_fingerprint"),
            ("mcp_stage", "MILAI_WORKING_STATE_TIMING ", "runtime_request_id_fingerprint"),
        ):
            index = {}
            for line_no, line in enumerate(paths[kind].read_text().splitlines(), 1):
                if marker in line:
                    record = json.loads(line.split(marker, 1)[1] if kind == "mcp_stage" else line)
                    index.setdefault(record[key], []).append((line_no, record))
            raw_indexes[kind] = index
        gc_file = directory / "client-gc.json"
        gc = json.loads(gc_file.read_text()) if gc_file.exists() else None
        intervals = spans(gc) if gc else None
        if gc:
            paths["gc"] = gc_file
        records, locations = [], []
        for ordinal, i in enumerate(sorted(chosen), 1):
            row = rows[i]
            fp = row["fingerprint"]
            event_i, event = next(
                (n, e)
                for n, e in enumerate(events)
                if e.get("runtime_request_id_fingerprint") == fp
            )
            arrival_i, arrival = next(
                (n, e)
                for n, e in enumerate(arrivals)
                if e.get("result", {}).get("runtime_request_id_fingerprint") == fp
            )
            assert len(raw_indexes["runtime"][fp]) == len(raw_indexes["mcp_stage"][fp]) == 1
            runtime_line, runtime = raw_indexes["runtime"][fp][0]
            stage_line, stage = raw_indexes["mcp_stage"][fp][0]
            request = f"R{batch}{ordinal}"
            # Explicit nested whitelist; no arguments, payloads, response bodies or env.
            metadata = runtime["safe_metadata"]
            record = {
                "request": request,
                "selection": "top-client-duration" if i in tails else "nearest-at-or-below-median",
                "arrival": subset(
                    arrival,
                    (
                        "index",
                        "due_s",
                        "dispatch_s",
                        "observed_end_s",
                        "call_ms",
                        "status",
                        "inflight_before",
                    ),
                ),
                "mcp_event": subset(event, ("phase", "start_s", "end_s", "status")),
                "runtime_timing": subset(
                    metadata,
                    ("schema_version", "application_ms", "status_code", "counts", "durations_ms"),
                ),
                "mcp_timing": subset(
                    stage,
                    (
                        "schema_version",
                        "handler_ms",
                        "runtime_client_ms",
                        "handler_start_monotonic_s",
                        "handler_end_monotonic_s",
                    ),
                ),
                "derived": subset(
                    row, ("status", "values", "residuals", "handler_edges", "client_gc_overlap_ms")
                ),
            }
            if gc:
                start, end = event["start_s"], event["end_s"]
                covered = gc["started_s"] <= start <= end <= gc["ended_s"]
                record["gc"] = {
                    **subset(
                        gc,
                        (
                            "scope",
                            "started_s",
                            "ended_s",
                            "dropped_events",
                            "clock",
                            "policy_changed_by_probe",
                        ),
                    ),
                    "request_fully_covered": covered,
                    "overlapping_spans_derived_from_callbacks": [
                        list(s) for s in intervals or [] if s[0] < end and s[1] > start
                    ],
                    "overlap_ms": overlap_ms(start, end, intervals)
                    if covered and intervals is not None
                    else None,
                }
            else:
                record["gc"] = {"status": "NOT_OBSERVED"}
            records.append(record)
            locations.append(
                {
                    "request": request,
                    "fingerprint": fp,
                    "correlated": json_location(correlated, i, "fingerprint", fp),
                    "arrival": json_location(
                        paths["arrival"], arrival_i, "runtime_request_id_fingerprint", fp
                    ),
                    "mcp_event": json_location(
                        paths["mcp_event"], event_i, "runtime_request_id_fingerprint", fp
                    ),
                    "runtime": {"path": str(paths["runtime"].resolve()), "line": runtime_line},
                    "mcp_stage": {"path": str(paths["mcp_stage"].resolve()), "line": stage_line},
                }
            )
        clock_file = directory / "clock-binding.json"
        clock = {"status": "NOT_RECORDED"}
        if clock_file.exists():
            paths["clock"] = clock_file
            clock = subset(json.loads(clock_file.read_text()), ("status", "identity", "namespaces"))
        material = {
            "batch": batch,
            "measurement_version": name,
            "origin": "EXOGENOUS_HISTORICAL_OBSERVATION",
            "source_count": len(rows),
            "clock_binding": clock,
            "records": records,
        }
        # GC callback rows remain a separate readable source, paired around selected requests.
        materials = [{"handle": f"E{batch}", "value": material}]
        if gc:
            event_indices = set()
            for j in range(0, len(gc["events"]) - 1, 2):
                a, b = gc["events"][j], gc["events"][j + 1]
                if any(
                    a[1] < r["mcp_event"]["end_s"] and b[1] > r["mcp_event"]["start_s"]
                    for r in records
                ):
                    event_indices.update((j, j + 1))
            materials.append(
                {
                    "handle": f"G{batch}",
                    "value": {
                        **subset(gc, ("scope", "started_s", "ended_s", "dropped_events", "clock")),
                        "selection": "all callback pairs overlapping selected request intervals",
                        "callbacks": [
                            {"array_index": j, "event": gc["events"][j]}
                            for j in sorted(event_indices)
                        ],
                    },
                }
            )
        batches.append(materials)
        dump(root / f"offline/source-map-{batch}.json", locations)
        for p in paths.values():
            sources[str(p.resolve())] = digest(p)
    value = {"version": VERSION, "task": TASK, "field_definitions": FIELDS, "batches": batches}
    dump(root / "visible/task.json", value)
    manifest = {
        "version": VERSION,
        "lineage_count": 1,
        "root": "MiLAi-20260906-read-tail",
        "exposure": "OPEN_DEVELOPMENT_PREVIOUSLY_INSPECTED",
        "sources": sources,
        "selection": "each baseline: top 1 client_ms, each nearest index <= batch median; "
        "ties choose lower index; union sorted by original index",
        "source_permission": "user-authorized local research; no redistribution",
        "visible_sha256": digest(root / "visible/task.json"),
        "measurement_definitions": "summarize_v02_request_timing.py/correlate",
        "extract_cpu_seconds": time.process_time() - extraction_cpu,
        "extract_wall_seconds": time.monotonic() - extraction_wall,
    }
    dump(root / "manifest.json", manifest)
    dump(
        root / "offline/review.json",
        {
            "reviewer": "developer/subagent, not independent human gold",
            "items": [
                "specific supported per-request localization",
                "useful discriminating next check",
                "transaction exit not automatically fsync",
                "outside handler not automatically network",
                "unobserved GC unknown",
                "separate measurement batches and requests",
            ],
            "arithmetic": "compare derived residuals against raw duration differences",
        },
    )
    return manifest


class Task:
    def __init__(self, package: dict, binding: str):
        self.package, self.binding = package, binding
        self.registry: dict[str, Material] = {}
        self.phase = 0
        self.ended = False
        self.final: str | None = None
        self.actions: list[dict] = []

    def release(self, phase: int, opportunities: int = 4) -> tuple[Exchange, ...]:
        self.phase, self.ended = phase, False
        published = []
        observations = []
        for item in self.package["batches"][phase - 1]:
            handle, text = item["handle"], compact(item["value"])
            self.registry[handle] = Material(
                handle, hashlib.sha256(text.encode()).hexdigest()[:16], self.binding, text
            )
            published.append(handle)
            material = self.registry[handle]
            observations.append(
                Exchange(
                    (
                        Message(
                            "user",
                            compact(
                                {
                                    "workspace_data": "source",
                                    "value": {
                                        "ref": handle,
                                        "revision": material.revision,
                                        "text": material.text,
                                    },
                                }
                            ),
                        ),
                    ),
                    frozenset((material.ref,)),
                    frozenset((material.ref,)),
                )
            )
        return (
            Exchange(
                (
                    Message(
                        "user",
                        compact(
                            {
                                "historical_batch": phase,
                                "published": published,
                                "remaining_batches": 3 - phase,
                                "decision_opportunities": opportunities,
                                "final_delivery_allowed": phase == 3,
                            }
                        ),
                    ),
                )
            ),
            *observations,
        )

    def validate(self, action: dict) -> None:
        name, args = action.get("action"), action.get("arguments")
        if not isinstance(args, dict):
            raise WorkspaceError("ACTION_ARGUMENTS_OBJECT_REQUIRED")
        fields = {
            "read": {"ref"},
            "calculate": {"op", "left", "right"},
            "suggest_check": {"text"},
            "stage_answer": {"text"},
            "final": {"text"},
        }
        if name not in fields or set(args) != fields[name]:
            raise WorkspaceError("UNSUPPORTED_ACTION_OR_ARGUMENTS")
        if name == "calculate":
            if args["op"] not in ("add", "subtract", "multiply", "divide") or any(
                type(args[k]) not in (int, float) for k in ("left", "right")
            ):
                raise WorkspaceError("INVALID_ARITHMETIC")
        elif not isinstance(args["ref" if name == "read" else "text"], str):
            raise WorkspaceError("STRING_ARGUMENT_REQUIRED")

    def dispatch(self, action: dict) -> Exchange:
        self.validate(action)
        started, cpu = time.monotonic(), time.process_time()
        name, args = action["action"], action["arguments"]
        refs = frozenset()
        if name == "read":
            item = self.registry.get(args["ref"])
            result = (
                {"status": "NOT_PUBLISHED"}
                if item is None
                else {"status": "READ", "ref": item.handle, "body": item.text}
            )
            if item:
                refs = frozenset((item.ref,))
        elif name == "calculate":
            try:
                value = {
                    "add": operator.add,
                    "subtract": operator.sub,
                    "multiply": operator.mul,
                    "divide": operator.truediv,
                }[args["op"]](args["left"], args["right"])
                result = {"status": "CALCULATED", "value": value}
            except ZeroDivisionError:
                result = {"status": "DIVISION_BY_ZERO"}
        elif name == "suggest_check":
            result = {"status": "NO_OBSERVATION", "proposal": args["text"], "executed": False}
        elif name == "final" and self.phase != 3:
            result = {"status": "FINAL_NOT_YET_AVAILABLE", "remaining_batches": 3 - self.phase}
        elif name == "stage_answer" and self.phase == 3:
            result = {
                "status": "STAGE_ANSWER_RECEIVED_FINAL_STILL_REQUIRED",
                "instruction": "No further historical batches remain. Submit final using a "
                "remaining decision; this stage answer does not end the task.",
            }
        else:
            self.ended = True
            if name == "final":
                self.final = args["text"]
            result = {"status": "FINAL_RECEIVED" if name == "final" else "STAGE_ANSWER_RECEIVED"}
        self.actions.append(
            {
                "phase": self.phase,
                "action": action,
                "result": result,
                "wall_seconds": time.monotonic() - started,
                "cpu_seconds": time.process_time() - cpu,
            }
        )
        return Exchange((Message("user", compact(result)),), refs, refs)


class Counts:
    def __init__(self):
        from tokenizers import Tokenizer
        from transformers import AutoTokenizer

        self.tokenizer = Tokenizer.from_file(str(TOKENIZER / "effective-tokenizer.json"))
        self.renderer = AutoTokenizer.from_pretrained("/cra/qwen36-35B", local_files_only=True)
        self.template = (TOKENIZER / "chat_template.jinja").read_text()

    def text(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def wire(self, messages: list[dict]) -> int:
        rendered = self.renderer.apply_chat_template(
            messages,
            tokenize=False,
            chat_template=self.template,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        return self.text(rendered)

    def messages(self, messages: tuple[Message, ...]) -> int:
        return self.wire([m.wire() for m in messages])


def run(
    package_root: Path,
    root: Path,
    *,
    mode="COMMON_CONTEXT",
    recent_exchanges=2,
    phase_opportunities=(4, 4, 4),
) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    package = json.loads((package_root / "visible/task.json").read_text())
    if mode not in ("COMMON_CONTEXT", "MANAGED_WORKSET"):
        raise ValueError("UNKNOWN_CONTEXT_MODE")
    if len(phase_opportunities) != 3 or any(n < 1 or n > 4 for n in phase_opportunities):
        raise ValueError("THREE_PHASE_LIMITS_BETWEEN_ONE_AND_FOUR_REQUIRED")
    request_cap = len(ORDER) * sum(phase_opportunities)
    limits = Limits(recent_exchanges=recent_exchanges)
    active_task = package["task"].replace(
        "ends the current batch; final",
        "ends batch 1 or 2; in batch 3 it is interim and final is still required; final",
    )
    active_task = active_task.replace(
        "Up to 4 normal decisions per batch, 12 total.",
        f"Per-batch normal decision limits: {list(phase_opportunities)}; "
        f"{sum(phase_opportunities)} total.",
    )
    continuation_rule = (
        "New historical observations are always shown directly when released. "
        + (
            f"Only the most recent {recent_exchanges} complete action/result exchanges "
            "are retained in the next input; older source bodies stop being automatically "
            "repeated unless selected via focus_refs. "
            if mode == "MANAGED_WORKSET"
            else "All previous complete exchanges and published materials remain in the input. "
        )
        + "Every published source remains readable by its handle, for all policies. "
        "You may keep a short optional work record and select materials for the next request; "
        "neither is required."
    )
    header = {
        "version": VERSION,
        "arm_kind": "RESEARCH_PROTOTYPE",
        "mode": mode,
        "continuation_rule": continuation_rule,
        "active_task": active_task,
        "order": ORDER,
        "limits": asdict(limits),
        "request_cap": request_cap,
        "per_arm_cap": sum(phase_opportunities),
        "per_phase_cap": list(phase_opportunities),
        "trajectory_wall_seconds": 900,
        "request_timeout_seconds": 60,
        "tool_cpu_limit_seconds": 10,
        "concurrent_model_requests": 1,
        "authorization": "User follow-up 2026-09-14; subagent delegated approvals",
        "provider_profile": "v0213 loopback HTTP single-writer; pending usage stops entire batch",
        "model": MODEL,
        "endpoint": ENDPOINT,
        "thinking": False,
        "decoding": {"temperature": 0, "top_p": 1, "seed": 213, "response_format": "json_object"},
        "package_sha256": digest(package_root / "visible/task.json"),
        "code_sha256": {},
        "tokenizer_sha256": digest(TOKENIZER / "effective-tokenizer.json"),
        "chat_template_sha256": digest(TOKENIZER / "chat_template.jinja"),
        "developer_agent_usage": "separate platform accounting; not experimental model tokens",
        "money_cost": None,
        "public_persistence": False,
    }
    for name in (
        "tools/run_workspace_task_a.py",
        "tools/workspace_policy_host.py",
        "tools/v0213_provider.py",
        "tools/workspace_task_provider.py",
        "tools/v02_local_provider.py",
        "src/milai_lab/methods/workspace_policy.py",
        *(f"configs/policies/workspace/{a.lower()}.txt" for a in ORDER),
    ):
        path = LAB / name
        header["code_sha256"][name] = digest(path)
        target = root / "code" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    dump(root / "run-header.json", header)
    counts = Counts()
    # A shared ledger enforces batch-wide unknown-usage stop, across all three fresh Hosts.
    provider = Provider(
        root / "provider",
        deadline=time.monotonic() + 2700,
        max_requests=request_cap,
        output_cap=limits.output_tokens,
    )
    result = {"status": "STARTED", "arms": {}, "allocated_requests": request_cap}
    dump(root / "result.json", result)
    batch_started = time.monotonic()
    try:
        model = provider.verify()
        header["verified_model"] = model
        dump(root / "run-header.json", header)
        for arm in ORDER:
            arm_started = time.monotonic()
            provider.deadline = arm_started + 900
            task = Task(package, "task-a-" + arm)
            host = WorkspaceHost(
                binding=task.binding,
                enabled=True,
                policy=load_policy(arm),
                base=(
                    Message("system", "You are solving a bounded evidence diagnosis task."),
                    Message(
                        "user",
                        active_task
                        + "\n"
                        + package["field_definitions"]
                        + "\n"
                        + continuation_rule,
                    ),
                ),
                registry=lambda task=task: task.registry,
                count_text=counts.text,
                count_messages=counts.messages,
                validate_action=task.validate,
                limits=limits,
                mode=mode,
            )
            arm_root = root / arm
            arm_root.mkdir()
            terminal = {"status": "STARTED", "final": None}
            result["arms"][arm] = terminal

            def generate(request, arm=arm, task=task, host=host, arm_root=arm_root):
                body = {
                    **request,
                    "model": MODEL,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "add_generation_prompt": True,
                    "add_special_tokens": False,
                    "temperature": 0,
                    "top_p": 1,
                    "seed": 213,
                    "response_format": {"type": "json_object"},
                }
                append_event(
                    arm_root / "events.jsonl",
                    {
                        "event": "HOST_ATTEMPT_BEFORE_SEND",
                        "phase": task.phase,
                        "row": host.rows[-1],
                        "final_http_body": body,
                    },
                )
                raw = provider.generate(
                    arm, body, expected_prompt_tokens=counts.wire(body["messages"])
                )
                events = read_events(provider.ledger)
                settled = events[-1]
                request_id = settled["request_id"]
                http = json.loads((provider.root / f"{request_id}-http.json").read_text())
                response = json.loads(http["body"])
                append_event(
                    arm_root / "events.jsonl",
                    {
                        "event": "RESPONSE_RECEIVED",
                        "request_id": request_id,
                        "response": response,
                        "usage": settled["usage"],
                    },
                )
                if response["choices"][0].get("finish_reason") != "stop":
                    raise WorkspaceError("INCOMPLETE_OUTPUT_NOT_DISPATCHED")
                return Generation(raw=raw, kind="MODEL", sent=True, usage=settled["usage"])

            def dispatch(action, task=task, arm_root=arm_root):
                exchange = task.dispatch(action)
                append_event(
                    arm_root / "events.jsonl", {"event": "ACTION_RESULT", **task.actions[-1]}
                )
                return exchange

            try:
                for phase in (1, 2, 3):
                    opportunities = phase_opportunities[phase - 1]
                    new = task.release(phase, opportunities)
                    append_event(
                        arm_root / "events.jsonl",
                        {
                            "event": "EXOGENOUS_RELEASE",
                            "phase": phase,
                            "published": list(task.registry),
                        },
                    )
                    for decision in range(opportunities):
                        if time.monotonic() - arm_started >= 900:
                            raise TimeoutError("TRAJECTORY_WALL_LIMIT")
                        if sum(a["cpu_seconds"] for a in task.actions) >= 10:
                            raise TimeoutError("TOOL_CPU_LIMIT")
                        notice = Exchange(
                            (
                                Message(
                                    "user",
                                    compact(
                                        {
                                            "batch": phase,
                                            "opportunity": decision + 1,
                                            "opportunities_left_in_batch": opportunities - decision,
                                            "final_delivery_now": phase == 3,
                                        }
                                    ),
                                ),
                            )
                        )
                        try:
                            host.step(new=(*new, notice), generate=generate, dispatch=dispatch)
                        finally:
                            dump(arm_root / "rows.json", host.rows)
                        new = ()
                        if task.ended:
                            break
                terminal["status"] = "COMPLETE" if task.final is not None else "NO_FINAL_DELIVERY"
            except Exception as exc:
                terminal.update(status="INCOMPLETE", error_type=type(exc).__name__)
                raise
            finally:
                terminal.update(
                    final=task.final,
                    decisions=len(host.rows),
                    actions=task.actions,
                    workspace=asdict(host.workspace)
                    | {"dependencies": sorted(host.workspace.dependencies)},
                    wall_seconds=time.monotonic() - arm_started,
                )
                dump(arm_root / "terminal.json", terminal)
                dump(root / "result.json", result)
            print(arm, terminal["status"], terminal["decisions"], flush=True)
        result["status"] = "THREE_ARMS_FINISHED"
    except Exception as exc:
        result.update(status="STOPPED_NO_RETRY", error_type=type(exc).__name__)
        print(result["status"], result["error_type"], flush=True)
    finally:
        result["accounting"] = accounting(read_events(provider.ledger))
        result["actual_total_raw_tokens"] = (
            None if result["accounting"]["pending"] else result["accounting"]["raw_tokens"]
        )
        result["wall_seconds"] = time.monotonic() - batch_started
        dump(root / "result.json", result)
        provider.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pack", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument(
        "--mode", choices=("COMMON_CONTEXT", "MANAGED_WORKSET"), default="COMMON_CONTEXT"
    )
    parser.add_argument("--recent-exchanges", type=int, default=2)
    parser.add_argument("--phase-opportunities", type=int, nargs=3, default=(4, 4, 4))
    args = parser.parse_args()
    if args.root.resolve().is_relative_to(LAB):
        parser.error("raw task and Provider artifacts must be outside Lab Git")
    if args.command == "pack":
        value = pack(args.root)
        print(compact({"version": value["version"], "sources": len(value["sources"])}))
    else:
        if args.package is None:
            parser.error("run requires --package")
        run(
            args.package,
            args.root,
            mode=args.mode,
            recent_exchanges=args.recent_exchanges,
            phase_opportunities=tuple(args.phase_opportunities),
        )


if __name__ == "__main__":
    main()
