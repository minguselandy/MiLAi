"""Frozen V0219 first baseline wave; natural A and fresh matched-information B."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from check_v0218_persistence import freeze_delivery
from v02_local_provider import accounting, read_events
from v0210_v05_product import observer
from v0218_host import SCHEMA, TOOLS
from v0218_memory import read_note, save_note
from v0218_world import World, digest
from v0219_artifacts import export_artifacts
from v0219_host import PUBLIC_PREFETCH, system_for
from v0219_record_check import evaluate

LAB = Path(__file__).resolve().parents[1]
ARMS = ("N0", "N1", "R1")
VARIANTS = ("stable", "changed")
CASE_FILES = (
    "public-initial.json",
    "public-changed.json",
    "public-schemas.json",
    "oracle-initial.json",
    "oracle-changed.json",
    "independent-reference.json",
)
RESOURCE_STOPS = {"MODEL_CONTEXT_LIMIT", "WALL_CLOCK_LIMIT"}


def read(path: Path):
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object, *, exclusive: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def costs(root: Path) -> dict:
    rows = [accounting(read_events(p)) for p in root.rglob("provider-ledger.jsonl")]
    return {
        "requests": sum(r["requests"] for r in rows),
        "raw_tokens": sum(r["raw_tokens"] for r in rows),
        "pending": sum(len(r["pending"]) for r in rows),
        "violations": sum(len(r["violations"]) for r in rows),
    }


def episode_plan(roots: list[str]) -> list[dict]:
    if len(roots) != len(set(roots)) or not roots:
        raise ValueError("DISTINCT_ORDERED_ROOTS_REQUIRED")
    rows = []
    for key in roots:
        rows.append({"id": key + "-A", "root": key, "phase": "A", "arm": "A", "variant": "initial"})
        for variant in VARIANTS:
            arms = sorted(ARMS, key=lambda a: digest(["MILA-V02-19", 219, key, variant, a]))
            rows.extend(
                {
                    "id": f"{key}-{variant}-{a}",
                    "root": key,
                    "phase": "B",
                    "arm": a,
                    "variant": variant,
                }
                for a in arms
            )
    return rows


def code_files() -> list[Path]:
    """Freeze transitive local Python imports; no corpus/module execution for discovery."""
    pending = [LAB / "tools" / name for name in ("run_v0219.py", "audit_v0219.py", "v0219_host.py")]
    seen = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                candidate = LAB / "tools" / (name.split(".")[0] + ".py")
                if candidate.is_file() and candidate not in seen:
                    pending.append(candidate)
    # Public Lab package implementation and dependency environment are also execution inputs.
    return sorted(
        seen
        | set((LAB / "src/milai_lab").rglob("*.py"))
        | {LAB / "pyproject.toml", LAB / "uv.lock", LAB / "configs/v0210-control-e1.json"}
    )


def verify_admission(screen: Path, seal: Path, prefix: list[int]) -> list[dict]:
    frozen = read(seal / "seal-A.json")
    for name, expected in frozen["files"].items():
        assert sha(seal / name) == expected
    order = read(seal / "assignment.json")["D_order"]
    accepted = []
    for index in range(1, max(prefix) + 1):
        op, d = read(screen / f"{index:03d}-open.json"), read(screen / f"{index:03d}-decision.json")
        assert op["root_id"] == d["root_id"] == order[index - 1]["root_id"]
        assert op["seal_sha256"] == d["seal_A_sha256"] == sha(seal / "seal-A.json")
        assert op["source_sha256"] == d["source_sha256"] == sha(Path(op["source_path"]))
        assert d["status"] in {"ACCEPT_STATIC", "HOLD", "REJECT"}
        if d["status"] != "ACCEPT_STATIC":
            continue
        profile = screen / f"profile-{index:03d}-v1"
        for name, expected in d["artifacts"].items():
            assert sha(profile / name) == expected
        for name, expected in d["frozen_code"].items():
            assert sha(LAB / name) == sha(profile / "accepted-code-v1" / name) == expected
        accepted.append(
            {
                "order": index,
                "root": d["root_id"],
                "family": d["family"],
                "profile": str(profile),
                "decision_sha256": sha(screen / f"{index:03d}-decision.json"),
            }
        )
    assert [r["order"] for r in accepted] == prefix
    return accepted


def freeze(root: Path, plan_path: Path) -> dict:
    plan = read(plan_path)
    assert plan["stage"] == "F2_FIRST_MATCHED_BASELINE_WAVE_V1"
    assert plan["accepted_prefix"] == [1, 3, 31, 56]
    assert plan["generation_cap"] == 16 and plan["seconds_per_episode"] == 900
    assert plan["raw_token_cap"] is None and plan["max_requests"] == 448
    assert plan["batch_seconds"] == 28 * 990 + 300
    accepted = verify_admission(
        Path(plan["screening"]), Path(plan["seal"]), plan["accepted_prefix"]
    )
    episodes = episode_plan([r["root"] for r in accepted])
    assert len(episodes) == 28 and len(episodes) * plan["generation_cap"] == plan["max_requests"]
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    inputs = {}
    for row in accepted:
        for name in CASE_FILES:
            source = Path(row["profile"]) / name
            target = root / "cases" / row["root"] / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            inputs[str(target.relative_to(root))] = sha(target)
        source = Path(plan["screening"]) / f"{row['order']:03d}-decision.json"
        target = root / "admission" / source.name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        inputs[str(target.relative_to(root))] = sha(target)
    shutil.copyfile(plan_path, root / "plan.json")
    inputs["plan.json"] = sha(root / "plan.json")
    goal = LAB / "studies/active/MILA_V0219_外部行为失效区间发现与机制筛选_GOAL_20260911.md"
    shutil.copyfile(goal, root / "goal-as-executed.md")
    inputs["goal-as-executed.md"] = sha(root / "goal-as-executed.md")
    implementation = {}
    for source in code_files():
        name = str(source.relative_to(LAB))
        target = root / "executed-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        implementation[name] = sha(target)
    pin = freeze_delivery(root / "pinned-delivery")
    assert pin["valid"]
    for p in (root / "pinned-delivery").rglob("*"):
        if p.is_file():
            inputs[str(p.relative_to(root))] = sha(p)
    manifest = {
        **plan,
        "status": "SEALED_BEFORE_GENERATION",
        "roots": accepted,
        "episodes": episodes,
        "arms": list(ARMS),
        "variants": list(VARIANTS),
        "public_prefetch": PUBLIC_PREFETCH,
        "policy_systems": {arm: system_for(arm) for arm in ("A", *ARMS)},
        "action_schema": SCHEMA,
        "tools": TOOLS,
        "implementation": implementation,
        "input_files": inputs,
        "model_assets": {
            str(Path("/cra/qwen36-35B") / name): sha(Path("/cra/qwen36-35B") / name)
            for name in (
                "config.json",
                "tokenizer.json",
                "tokenizer_config.json",
                "chat_template.jinja",
            )
        },
        "new_compatibility_requests": 0,
        "new_judge_requests": 0,
        "model": "Qwen3.6-35B-A3B-FP8",
        "context": 65536,
        "output_cap": 4096,
        "request_timeout_seconds": 60,
        "temperature": 0,
        "seed": 213,
        "enable_thinking": False,
        "generation_parallelism": 1,
        "source_projection": False,
        "policies": {a: {"carry_note": a != "N0"} for a in ARMS},
        "order": "Fixed accepted prefix; stable then changed; arms sorted by canonical SHA256 "
        "of [MILA-V02-19,219,root,variant,arm].",
        "no_write": "Run all B without inherited Note; no root replacement or A rerun to force it.",
        "resource_stop": "Known context/deadline stop with settled usage remains an episode "
        "outcome; continue other frozen arms from actual A. Unknown usage/commit or "
        "process/protocol failure stops batch, no automatic retry.",
        "scoring": "Independent frozen full-record oracle plus content/state/contract-bound "
        "nonblind source review; unreviewed prose UNKNOWN. All states and failures retained. "
        "No native score or automatic keyword semantics.",
        "product_boundary": "Run-specific immutable public release lock; global drift preserved; "
        "only isolated scopes/local business worlds, no real messages or Product behavior changes.",
        "cost_policy": "Shared A counted once; all Provider reservations and failed attempts "
        "retained; public reads/copies/prefetch and writer/consumer costs separate. "
        "Agent labor separate from experimental Provider cost.",
        "confirmation": "No reserve semantic access; C static accepted0; no mechanism preselected.",
    }
    save(root / "manifest.json", manifest)
    save(root / "manifest-sha256.json", {"sha256": sha(root / "manifest.json")})
    return manifest


def validate(root: Path) -> dict:
    manifest = read(root / "manifest.json")
    assert sha(root / "manifest.json") == read(root / "manifest-sha256.json")["sha256"]
    for name, expected in manifest["implementation"].items():
        assert sha(LAB / name) == sha(root / "executed-source" / name) == expected
    for name, expected in manifest["input_files"].items():
        assert sha(root / name) == expected
    for name, expected in manifest["model_assets"].items():
        assert sha(Path(name)) == expected
    return manifest


def branch_world(root: Path, episode: dict, upstream: dict | None, scope: str) -> World:
    target = root / "worlds" / (episode["id"] + ".sqlite")
    case = root / "cases" / episode["root"]
    if episode["phase"] == "A":
        world = World.create(target, scope, read(case / "public-initial.json"))
    else:
        assert upstream is not None
        world = World(Path(upstream["world"]), upstream["scope"]).clone(target, scope)
        if episode["variant"] == "changed":
            world.publish(
                event_id="source-grounded-changed", current=read(case / "public-changed.json")
            )
    save(root / "starts" / (episode["id"] + ".json"), world.snapshot())
    return world


def prepare_note(
    root: Path, episode: dict, owned: Path, scope: str, upstream: dict | None
) -> dict | None:
    directory = root / "branch-audits" / episode["id"]
    calls = []
    with observer(owned, directory / "mcp", task=scope, principal=scope, project=scope) as public:

        def call(name, arguments):
            start = time.monotonic()
            response = public(name, arguments)
            calls.append(
                {
                    "tool": name,
                    "arguments": arguments,
                    "response": response,
                    "seconds": time.monotonic() - start,
                }
            )
            save(directory / "public-calls.json", {"calls": calls}, exclusive=False)
            return response

        before = call("milai_memory_list", {"selection": {"kind": "NOTE"}, "limit": 100})
        save(directory / "initial-memory-list.json", before)
        assert not before.get("mcp_error") and before["items"] == []
        if (
            episode["phase"] == "A"
            or episode["arm"] == "N0"
            or not upstream
            or not upstream["note"]
        ):
            return None
        committed = save_note(call, upstream["note"]["content"], scope + "-exact-copy")
        copied = read_note(call, committed)
        assert copied["content"] == upstream["note"]["content"]
        save(
            directory / "note-copy.json",
            {
                "kind": "HARNESS_EXACT_COPY_OF_AGENT_NOTE",
                "origin": upstream["commit"],
                "destination": committed,
                "content_rewritten": False,
                "source_A_process_exit": upstream["exit"],
                "public_readback": copied,
            },
        )
        return committed


def cold(config: dict, path: Path, remaining: float) -> dict:
    save(path, config)
    with path.with_suffix(".log").open("x") as log:
        child = subprocess.Popen(  # noqa: S603 -- own fixed Host, no model-supplied command
            [sys.executable, str(LAB / "tools/v0219_host.py"), "--config", str(path)],
            cwd=LAB,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        started = time.time()
        timed_out = False
        try:
            code = child.wait(timeout=min(remaining, config["seconds"] + 90))
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
            code = child.returncode
    exit_receipt = {
        "pid": child.pid,
        "returncode": code,
        "started_unix": started,
        "exited_unix": time.time(),
        "wait_reaped": child.poll() is not None,
        "timeout": timed_out,
        "exit_verified_before_next_episode": True,
    }
    save(path.with_suffix(".exit.json"), exit_receipt)
    result_path = Path(config["output"]) / "result.json"
    if code or not result_path.exists():
        raise ValueError("COLD_PROCESS_FAILURE_PRESERVE_UNKNOWN_COMMIT")
    outcome = read(result_path)
    assert outcome["pid"] == child.pid
    return {**outcome, "exit_receipt": exit_receipt, "exit_verified_before_next_episode": True}


def recover_a_handoff(config: dict, outcome: dict) -> tuple[dict, dict]:
    """After a settled resource stop, read an already observed commit; never write/retry A."""
    assert config["phase"] == "A" and outcome.get("reason") in RESOURCE_STOPS
    directory = Path(config["output"])
    actions = [
        a
        for a in outcome["actions"]
        if a.get("tool_result", {}).get("status") == "PUBLIC_NOTE_COMMITTED"
    ]
    assert len(actions) == outcome["agent_note_writes"] and actions
    calls = read(directory / "memory-calls.json")["calls"]
    saves = [r for r in calls if r["tool"] == "milai_memory_save"]
    assert len(saves) == len(actions)
    previous = None
    for action, recorded in zip(actions, saves, strict=True):

        def check_call(name, arguments, recorded=recorded):
            assert name == recorded["tool"] and arguments == recorded["arguments"]
            return recorded["response"]

        previous = save_note(
            check_call,
            action["action"]["note"],
            f"{config['episode_id']}-note-{action['turn']}",
            previous,
        )
    assert previous is not None
    scope = config["memory_scope"]
    recovery = directory / "handoff-recovery"
    calls = []
    started = time.time()
    assert started >= outcome["exit_receipt"]["exited_unix"]
    with observer(
        Path(config["owned"]), recovery / "mcp", task=scope, principal=scope, project=scope
    ) as public:

        def call(name, arguments):
            tick = time.monotonic()
            response = public(name, arguments)
            calls.append(
                {
                    "tool": name,
                    "arguments": arguments,
                    "response": response,
                    "seconds": time.monotonic() - tick,
                }
            )
            save(recovery / "public-calls.json", {"calls": calls}, exclusive=False)
            return response

        note = read_note(call, previous)
    save(
        recovery / "receipt.json",
        {
            "started_unix": started,
            "source_exit": outcome["exit_receipt"],
            "commit": previous,
            "note": note,
            "harness_read_only": True,
            "generation_requests": 0,
            "note_mutations": 0,
        },
    )
    return previous, note


def continuation_allowed(outcome: dict, cost: dict) -> bool:
    if cost["pending"] or cost["violations"]:
        return False
    if outcome["status"] == "INFRASTRUCTURE_OR_PROTOCOL_STOP":
        return outcome.get("reason") in RESOURCE_STOPS
    return outcome["status"] in {"FINISHED", "GENERATION_CAP_REACHED", "EPISODE_DEADLINE"}


def run(root: Path, installed: Path) -> dict:
    from run_v0212_horizon import product

    manifest = validate(root)
    if (
        (root / "run-start.json").exists()
        or (root / "result.json").exists()
        or any(root.rglob("provider-ledger.jsonl"))
    ):
        raise ValueError("PRESERVE_PREVIOUS_ATTEMPT_NO_AUTOMATIC_RESTART")
    save(
        root / "run-start.json",
        {
            "pid": os.getpid(),
            "started_unix": time.time(),
            "manifest_sha256": sha(root / "manifest.json"),
            "allocated_max_requests": manifest["max_requests"],
        },
    )
    rows, upstream = [], {}
    started = time.monotonic()
    status, error = "F2_EXECUTED_REQUIRES_CHAIN_AND_SEMANTIC_AUDIT", None
    active = None
    try:
        with product(root / "product", installed) as owned:
            for episode in manifest["episodes"]:
                active = episode
                validate(root)
                used = costs(root)
                assert not used["pending"] and not used["violations"], "UNKNOWN_USAGE_NO_RETRY"
                assert used["requests"] + manifest["generation_cap"] <= manifest["max_requests"]
                remaining = manifest["batch_seconds"] - (time.monotonic() - started)
                assert remaining > 990, "BATCH_DEADLINE_NO_COMPLETE_NEW_EPISODE"
                key = episode["root"]
                scope = "v0219-" + digest([str(root), episode["id"]])[:24]
                world = branch_world(root, episode, upstream.get(key), scope)
                commit = prepare_note(root, episode, owned, scope, upstream.get(key))
                config = {
                    **episode,
                    "episode_id": episode["id"],
                    "world": str(world.path),
                    "world_scope": scope,
                    "memory_scope": scope,
                    "owned": str(owned),
                    "note_commit": commit,
                    "output": str(root / "episodes" / episode["id"]),
                    "seconds": manifest["seconds_per_episode"],
                    "generation_cap": manifest["generation_cap"],
                    "policy_system": manifest["policy_systems"][episode["arm"]],
                }
                if episode["phase"] == "B":
                    config["public_prefetch"] = manifest["public_prefetch"]
                outcome = cold(
                    config, root / "episode-configs" / (episode["id"] + ".json"), remaining
                )
                handoff_note = None
                if episode["phase"] == "A":
                    note_path = Path(config["output"]) / "final-public-note.json"
                    handoff_note = read(note_path) if note_path.exists() else None
                    if outcome["agent_note_writes"] and not handoff_note:
                        assert continuation_allowed(outcome, costs(root))
                        outcome["note_commit"], handoff_note = recover_a_handoff(config, outcome)
                        outcome["handoff_recovered_by_public_read_only"] = True
                final = read(Path(config["output"]) / "final-world.json")
                assert final == world.snapshot()
                oracle_name = (
                    "oracle-changed.json"
                    if episode["variant"] == "changed"
                    else "oracle-initial.json"
                )
                outcome["business_unreviewed"] = evaluate(
                    final, read(root / "cases" / key / oracle_name)
                )
                if set(final["records"]) == set(final["objects"]):
                    mapping = {k: {"path": k + ".json", "format": "json"} for k in final["objects"]}
                    outcome["export"] = export_artifacts(
                        final, mapping, root / "exports" / episode["id"]
                    )
                else:
                    outcome["export"] = {
                        "status": "INCOMPLETE_OBJECT_SET_RETAINED_IN_SQLITE_AND_SNAPSHOT"
                    }
                rows.append({**episode, **outcome})
                save(root / "progress.json", {"rows": rows, "cost": costs(root)}, exclusive=False)
                print(
                    json.dumps(
                        {"episode": episode["id"], "status": outcome["status"], "cost": costs(root)}
                    ),
                    flush=True,
                )
                if not continuation_allowed(outcome, costs(root)):
                    raise ValueError("UNKNOWN_USAGE_COMMIT_OR_PROTOCOL_STOP_NO_RETRY")
                if episode["phase"] == "A":
                    note = handoff_note
                    # A known context/deadline stop can precede the Host's final public read.
                    # Never silently replace a written-but-unverified Note with NO_WRITE.
                    if outcome["agent_note_writes"] and (
                        not note or not outcome.get("note_commit")
                    ):
                        raise ValueError("A_NOTE_COMMIT_NOT_HANDOFF_VERIFIED_NO_RETRY")
                    upstream[key] = {
                        "world": str(world.path),
                        "scope": scope,
                        "note": note,
                        "commit": outcome.get("note_commit"),
                        "exit": outcome["exit_receipt"],
                    }
                active = None
    except Exception as exc:
        status, error = "F2_STOPPED_PRESERVED", {"type": type(exc).__name__, "reason": str(exc)}
    result = {
        "status": status,
        "error": error,
        "rows": rows,
        "cost": costs(root),
        "interrupted_episode": active,
        "not_completed": [
            e for e in manifest["episodes"] if e["id"] not in {r["id"] for r in rows}
        ],
        "seconds": time.monotonic() - started,
        "raw_token_cap": None,
        "model_judge_requests": 0,
        "goal_complete": False,
    }
    cleanup = root / "product/cleanup.json"
    if cleanup.exists():
        result["cleanup"] = read(cleanup)
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--freeze-plan", type=Path)
    parser.add_argument("--installed", type=Path)
    args = parser.parse_args()
    result = (
        freeze(args.root, args.freeze_plan) if args.freeze_plan else run(args.root, args.installed)
    )
    print(
        json.dumps(
            {k: result[k] for k in ("status", "max_requests", "cost", "error") if k in result}
        )
    )
