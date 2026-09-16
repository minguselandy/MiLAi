"""Two frozen-policy repetitions and same-formation handoff lesions; opt-in research only."""

from __future__ import annotations

import argparse
import copy
import json
import time
from dataclasses import asdict
from pathlib import Path

import run_workspace_continuation as base
from milai_lab.methods.workspace_policy import Exchange, Message, WorkspaceError
from run_workspace_task_a import LAB, TOKENIZER, Counts, compact, digest, dump
from v02_local_provider import accounting, append_event, read_events
from workspace_policy_host import Generation
from workspace_task_provider import Provider

VERSION = "workspace-handoff-ablation-v1"
POLICIES = LAB / "configs/policies/workspace/continuation-interpretation.json"
WITHHELD = "[Stage handoff text withheld for this development comparison; original sources remain.]"
SCHEDULE = (
    ("W1", (("R", ("FULL", "NO_HANDOFF")), ("EXPLAIN", ("NO_HANDOFF", "FULL")))),
    ("W2", (("EXPLAIN", ("FULL", "NO_HANDOFF")), ("R", ("NO_HANDOFF", "FULL")))),
)


def lesion_message(message):
    """Change only the stage output text, never its exchange's evidence or receipt."""
    if message.role != "assistant":
        return message
    try:
        value = json.loads(message.content)
    except json.JSONDecodeError:
        return message
    if isinstance(value, dict) and value.get("kind") == "HOST_CAPTURED_STAGE_OUTPUT":
        value["arguments"]["text"] = WITHHELD
        return Message(message.role, compact(value))
    return message


def fork_consumer(previous, original, counts, condition):
    if condition not in ("FULL", "NO_HANDOFF"):
        raise ValueError("UNKNOWN_CONSUMER_CONDITION")
    task = base.ContinuationTask(original.package, original.binding, counts)
    task.registry = dict(original.registry)
    task.actions = copy.deepcopy(original.actions)
    task.handoff = copy.deepcopy(original.handoff)
    new = task.begin("consumption")
    consumer = base.continue_host(previous, task, counts)
    if condition == "NO_HANDOFF":
        consumer.history = [
            Exchange(tuple(lesion_message(m) for m in g.messages), g.dependencies, g.body_refs)
            for g in consumer.history
        ]
        # H is a public history read, not an evaluator backdoor to the withheld artifact.
        for handle, text in task.history_records.items():
            value = json.loads(text)
            if value["action"]["action"] == "stage_answer":
                value["action"]["arguments"]["text"] = WITHHELD
                task.history_records[handle] = compact(value)
    new = (
        *new,
        Exchange(
            (Message("user", compact({"historical_action_handles": list(task.history_records)})),)
        ),
    )
    return task, consumer, new


def segment(host, task, new, provider, counts, directory, session, stage):
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    action_start = len(task.actions)
    terminal = {"status": "STARTED", "segment": stage}

    def generate(request):
        body = base.wire(request)
        append_event(
            directory / "events.jsonl",
            {
                "event": "HOST_ATTEMPT_BEFORE_SEND",
                "row": host.rows[-1],
                "final_http_body": body,
            },
        )
        raw = provider.generate(session, body, expected_prompt_tokens=counts.wire(body["messages"]))
        settled = read_events(provider.ledger)[-1]
        response = json.loads(
            json.loads((provider.root / (settled["request_id"] + "-http.json")).read_text())["body"]
        )
        append_event(
            directory / "events.jsonl",
            {
                "event": "RESPONSE_RECEIVED",
                "request_id": settled["request_id"],
                "usage": settled["usage"],
            },
        )
        if response["choices"][0].get("finish_reason") != "stop":
            raise WorkspaceError("INCOMPLETE_OUTPUT_NOT_DISPATCHED")
        return Generation(raw, "MODEL", True, settled["usage"])

    def dispatch(action):
        receipt = task.dispatch(action)
        append_event(directory / "events.jsonl", {"event": "ACTION_RESULT", **task.actions[-1]})
        return receipt

    try:
        for decision in range(4):
            if time.monotonic() >= provider.deadline:
                raise TimeoutError("PATH_WALL_LIMIT")
            if sum(a["cpu_seconds"] for a in task.actions) >= 10:
                raise TimeoutError("TOOL_CPU_LIMIT")
            notice = Exchange(
                (
                    Message(
                        "user",
                        compact(
                            {
                                "segment": stage,
                                "decision": decision + 1,
                                "opportunities_remaining_including_this": 4 - decision,
                                "segment_deliverable": "stage_answer"
                                if stage == "formation"
                                else "final",
                            }
                        ),
                    ),
                )
            )
            host.step(new=(*new, notice), generate=generate, dispatch=dispatch)
            new = ()
            if task.ended:
                if stage == "formation":
                    base.mark_stage_output(host)
                break
        terminal["status"] = "ENDED" if task.ended else "OPPORTUNITIES_EXHAUSTED"
    except WorkspaceError as exc:
        terminal.update(status="KNOWN_LOCAL_FAILURE_NO_RETRY", error=str(exc))
        state = accounting(read_events(provider.ledger))
        if state["pending"] or state["violations"]:
            raise
    except Exception as exc:
        terminal.update(status="STOPPED_NO_RETRY", error_type=type(exc).__name__)
        raise
    finally:
        terminal.update(
            decisions=len(host.rows),
            handoff=task.handoff,
            final=task.final,
            actions=task.actions[action_start:],
            wall_seconds=time.monotonic() - started,
            workspace_final=asdict(host.workspace),
        )
        # Workspace dependency sets are intentionally serialized as ordinary arrays.
        terminal["workspace_final"]["dependencies"] = sorted(host.workspace.dependencies)
        dump(directory / "rows.json", host.rows)
        dump(directory / "terminal.json", terminal)
    return terminal


def run(package_root: Path, root: Path):
    root.mkdir(parents=True, exist_ok=False)
    package = json.loads((package_root / "visible/task.json").read_text())
    policies = json.loads(POLICIES.read_text())
    header = {
        "version": VERSION,
        "goal_id": "MILA-HOST-CONTINUATION-DEV-03",
        "authorization": "User instruction: optimize Goal from results and complete experiments",
        "arm_kind": "RESEARCH_PROTOTYPE",
        "schedule": SCHEDULE,
        "request_cap": 48,
        "segment_cap": 4,
        "package_wall_seconds": 3600,
        "formation_plus_one_consumer_wall_seconds": 900,
        "request_timeout_seconds": 60,
        "tool_cpu_limit_seconds": 10,
        "concurrent_requests": 1,
        "package": str(package_root.resolve()),
        "package_sha256": digest(package_root / "visible/task.json"),
        "policies": policies,
        "policy_sha256": digest(POLICIES),
        "condition": "FULL_SOURCES_NATURAL_CONTEXT_WITH_EXPLICIT_HANDOFF_LESION",
        "withheld_marker": WITHHELD,
        "public_persistence": False,
        "independent_lineages": 1,
        "decoding": base.wire({}),
        "code_sha256": {},
        "tokenizer_sha256": digest(TOKENIZER / "effective-tokenizer.json"),
        "template_sha256": digest(TOKENIZER / "chat_template.jinja"),
        "formation_cost": "actual once; each strategy path includes its shared formation",
    }
    for name in (
        "tools/run_workspace_handoff_ablation.py",
        "tools/run_workspace_continuation.py",
        "tools/run_workspace_task_a.py",
        "tools/workspace_policy_host.py",
        "tools/workspace_task_provider.py",
        "tools/v0213_provider.py",
        "tools/v02_local_provider.py",
        "src/milai_lab/methods/workspace_policy.py",
        "configs/policies/workspace/note.txt",
        "configs/policies/workspace/continuation-interpretation.json",
        "studies/active/MILA_HOST_INTERPRETATION_AND_HANDOFF_GOAL_20260914.md",
    ):
        source, target = LAB / name, root / "code" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        header["code_sha256"][name] = digest(source)
    dump(root / "run-header.json", header)
    started = time.monotonic()
    counts = Counts()
    header["tokenizer_initialization_seconds"] = time.monotonic() - started
    overall_deadline = started + 3600
    provider = Provider(
        root / "provider", deadline=overall_deadline, max_requests=48, output_cap=4096
    )
    result = {"status": "STARTED", "groups": {}}
    try:
        header["verified_model"] = provider.verify()
        limits = base.capacity_limits(provider.context)
        header["limits"] = asdict(limits)
        header["capacity"] = {"effective": provider.context, "output_reserve": 4096, "guard": 0}
        dump(root / "run-header.json", header)
        for wave, arms in SCHEDULE:
            for arm, conditions in arms:
                group_name = wave + "-" + arm
                group_root = root / group_name
                group_started = time.monotonic()
                provider.deadline = min(overall_deadline, group_started + 900)
                task = base.ContinuationTask(package, "continuation-a", counts)
                host = base.make_host(task, counts, policies[arm], limits)
                group = {"status": "STARTED", "consumers": {}}
                result["groups"][group_name] = group
                group["formation"] = segment(
                    host,
                    task,
                    task.begin("formation"),
                    provider,
                    counts,
                    group_root / "formation",
                    group_name + "-formation",
                    "formation",
                )
                formation_seconds = time.monotonic() - group_started
                if task.handoff["status"] != "VALID":
                    group.update(
                        status="NO_VALID_HANDOFF",
                        consumers={c: {"status": "NOT_RUN_NO_VALID_HANDOFF"} for c in conditions},
                    )
                else:
                    for condition in conditions:
                        child, consumer, new = fork_consumer(host, task, counts, condition)
                        provider.deadline = min(
                            overall_deadline, time.monotonic() + max(0, 900 - formation_seconds)
                        )
                        group["consumers"][condition] = segment(
                            consumer,
                            child,
                            new,
                            provider,
                            counts,
                            group_root / condition,
                            group_name + "-" + condition,
                            "consumption",
                        )
                    group["status"] = "FINISHED"
                dump(root / "result.json", result)
                print(group_name, group["status"], flush=True)
        result["status"] = "SCHEDULE_FINISHED"
    except Exception as exc:
        result.update(status="STOPPED_NO_RETRY", error_type=type(exc).__name__)
    finally:
        result["accounting"] = accounting(read_events(provider.ledger))
        result["actual_total_raw_tokens"] = (
            None if result["accounting"]["pending"] else result["accounting"]["raw_tokens"]
        )
        result["wall_seconds"] = time.monotonic() - started
        dump(root / "result.json", result)
        provider.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    run(args.package, args.root)
