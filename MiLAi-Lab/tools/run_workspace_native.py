"""One prospectively allocated native task wave, through Harbor public Trial API.

Run using the pinned external Harbor Python with Lab src/ and tools/ on PYTHONPATH.
No scheduler retries, benchmark solution execution, or task-specific agent hints.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import shutil
import time
import tomllib
from pathlib import Path

from harbor.models.trial.config import AgentConfig, EnvironmentConfig, TaskConfig, TrialConfig
from harbor.trial.trial import Trial

from v02_local_provider import accounting, read_events
from v0213_provider import MODEL
from workspace_terminal_session import dump


async def run(args):
    if importlib.metadata.version("harbor") != "0.23.0":
        raise ValueError("HARBOR_VERSION_CHANGED")
    args.root.mkdir(parents=True, exist_ok=False)
    task = tomllib.loads((args.task / "task.toml").read_text())
    timeout = task["agent"]["timeout_sec"]
    if task["environment"].get("gpus", 0) != 0:
        raise ValueError("CPU_TASK_REQUIRED")
    order = ["SMOKE"] if args.smoke else args.order
    method_arms = {
        "HIAGENT",
        "H_ONCE",
        "EVIDENCE_0",
        "EVIDENCE_1",
        "INCREMENTAL",
        "CONTROL_0",
        "WORKSPACE_SIMPLE",
        "MILAI_RWC",
        "OM_SYNC_PORT",
        "ADAPTIVE_MEMORY_SIMPLE",
        "ADAPTIVE_MEMORY_CANDIDATE",
    }
    call_caps = [
        (args.hiagent_max_calls or args.max_calls)
        if arm in method_arms
        else 64
        if arm == "TERMINUS_2"
        else args.max_calls
        for arm in order
    ]
    generation_cap = 0 if args.smoke else sum(call_caps)
    hashes = {
        str(p.relative_to(args.task)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in args.task.rglob("*")
        if p.is_file() and "solution" not in p.relative_to(args.task).parts
    }
    lab = Path(__file__).resolve().parents[1]
    implementation = [
        "tools/run_workspace_native.py",
        "tools/workspace_harbor_agent.py",
        "tools/workspace_terminus_reference.py",
        "tools/workspace_terminal_session.py",
        "tools/workspace_policy_host.py",
        "tools/workspace_task_provider.py",
        "src/milai_lab/methods/workspace_policy.py",
    ]
    implementation += [
        str(p.relative_to(lab)) for p in (lab / "configs/policies/workspace").glob("*.txt")
    ]
    if method_arms.intersection(order):
        implementation += [
            "tools/hiagent_harbor_agent.py",
            "tools/hiagent_terminal_session.py",
            "src/milai_lab/methods/hiagent.py",
            "configs/policies/hiagent/actor.txt",
            "configs/policies/hiagent/summary.txt",
        ]
        implementation += [
            "src/milai_lab/methods/evidence_maintenance.py",
            "src/milai_lab/methods/workspace_control.py",
            "src/milai_lab/methods/controlled_workspace.py",
            "src/milai_lab/methods/observational_memory.py",
            "src/milai_lab/methods/adaptive_memory.py",
        ]
        implementation += [
            str(p.relative_to(lab)) for p in (lab / "configs/policies/evidence").glob("*.txt")
        ]
    if "CONTROL_0" in order:
        implementation += [
            str(p.relative_to(lab)) for p in (lab / "configs/policies/control").glob("*.txt")
        ]
    if {"WORKSPACE_SIMPLE", "MILAI_RWC"}.intersection(order):
        implementation += ["tools/workspace_checkpoint.py"]
        implementation += [
            str(p.relative_to(lab))
            for p in (lab / "configs/policies/workspace_control").glob("*.txt")
        ]
    if "OM_SYNC_PORT" in order:
        implementation += [
            str(p.relative_to(lab)) for p in (lab / "configs/policies/om_sync").glob("*.txt")
        ]
    if {"ADAPTIVE_MEMORY_SIMPLE", "ADAPTIVE_MEMORY_CANDIDATE"}.intersection(order):
        implementation += ["tools/workspace_checkpoint.py"]
        implementation += [
            str(p.relative_to(lab))
            for p in (lab / "configs/policies/adaptive_memory").glob("*.txt")
        ]
    for name in implementation:
        target = args.root / "implementation" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lab / name, target)
    dump(
        args.root / "allocation.json",
        {
            "kind": "RESEARCH_PROTOTYPE",
            "harbor": "0.23.0",
            "task_path": str(args.task),
            "source_commit": "2fd12b88aafdd04a52c298e3940bcb189f9766d6",
            "hashes": hashes,
            "order": order,
            "generation_cap": generation_cap,
            "trajectory_call_caps": dict(zip(order, call_caps, strict=True)),
            "per_trajectory_cap": max(call_caps),
            "model": MODEL,
            "timeout_multiplier": 1,
            "native_agent_timeout_sec": timeout,
            "native_task_config": task,
            "policy_versions": order,
            "revision_source_tasks": args.revision_source,
            "task_role": args.role,
            "artifact_paths": args.artifact,
            "default_context": "COMMON_CONTEXT_FOR_WORKSPACE_ARMS",
            "selection_capability": (
                "METHOD_SPECIFIC_HIAGENT_VS_WORKSPACE"
                if method_arms.intersection(order)
                else "equal_all_arms"
            ),
            "hiagent_maintenance": (
                "SEPARATE_CALLS_COUNTED_IN_TRAJECTORY_CAP;MODE_EXPLICIT"
                if method_arms.intersection(order)
                else None
            ),
            "control_handoff_after": getattr(args, "control_handoff_after", None),
            "force_build_upstream_dockerfile": args.force_build,
            "compose_overrides": {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.compose_override
            },
            "concurrency": 1,
            "hidden_model_calls": 0,
            "implementation_sha256": {
                p: hashlib.sha256((lab / p).read_bytes()).hexdigest() for p in implementation
            },
        },
    )
    results = []
    for index, arm in enumerate(order):
        config = TrialConfig(
            task=TaskConfig(path=args.task),
            trial_name=f"{args.task.name}-{index}-{arm.lower()}",
            trials_dir=args.root / "trials",
            agent=AgentConfig(
                import_path=(
                    "workspace_terminus_reference:AccountedTerminus"
                    if arm == "TERMINUS_2"
                    else "hiagent_harbor_agent:HiAgentAgent"
                    if arm in method_arms
                    else "workspace_harbor_agent:WorkspaceAgent"
                ),
                model_name=MODEL,
                kwargs={
                    "arm": arm,
                    "run_root": str(args.root),
                    "wave_cap": generation_cap,
                    "task_timeout": timeout,
                    "smoke": args.smoke,
                    **({"max_calls": call_caps[index]} if arm != "TERMINUS_2" else {}),
                    **(
                        {"control_handoff_after": getattr(args, "control_handoff_after", None)}
                        if arm in {"CONTROL_0", "WORKSPACE_SIMPLE", "MILAI_RWC", "OM_SYNC_PORT",
                                   "ADAPTIVE_MEMORY_SIMPLE", "ADAPTIVE_MEMORY_CANDIDATE"}
                        else {}
                    ),
                    **(
                        {
                            "controller_output_tokens": getattr(
                                args, "controller_output_tokens", 2048
                            ),
                            "summary_output_tokens": getattr(args, "summary_output_tokens", 1024),
                            "om_observation_tokens": getattr(args, "om_observation_tokens", 12000),
                            "om_recent_events": getattr(args, "om_recent_events", 2),
                            "control_feedback_batch_size": getattr(
                                args, "control_feedback_batch_size", 1
                            ),
                        }
                        if arm in {"WORKSPACE_SIMPLE", "MILAI_RWC", "OM_SYNC_PORT",
                                   "ADAPTIVE_MEMORY_SIMPLE", "ADAPTIVE_MEMORY_CANDIDATE"}
                        else {}
                    ),
                },
            ),
            environment=EnvironmentConfig(
                type="docker",
                delete=True,
                override_gpus=0,
                force_build=args.force_build,
                extra_docker_compose=args.compose_override,
            ),
            artifacts=args.artifact,
        )
        dump(args.root / f"trial-config-{index}.json", config.model_dump(mode="json"))
        started = time.monotonic()
        try:
            trial = await Trial.create(config)
            result = await trial.run()
            record = result.model_dump(mode="json")
        except Exception as exc:
            record = {"exception_type": type(exc).__name__, "exception": str(exc)}
        state = accounting(read_events(args.root / "provider/provider-ledger.jsonl"))
        results.append(
            {
                "arm": arm,
                "wall_seconds": time.monotonic() - started,
                "result": record,
                "wave_accounting": state,
            }
        )
        dump(args.root / "results.json", results)
        print(
            json.dumps(
                {
                    "arm": arm,
                    "wall_seconds": results[-1]["wall_seconds"],
                    "wave_accounting": state,
                    "result_file": str(args.root / "results.json"),
                }
            ),
            flush=True,
        )
        if state["pending"] or state["violations"]:
            break
        if "exception_type" in record:
            break
        if record.get("exception_info"):
            # Harbor can wrap terminal timeouts in RuntimeError. Stop a failed
            # execution wave regardless of wrapper type; native low rewards still
            # continue normally. Inspect and settle effects before a new wave.
            break
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--force-build", action="store_true")
    budget = parser.add_mutually_exclusive_group()
    budget.add_argument(
        "--max-calls",
        type=int,
        choices=range(1, 769),
        default=64,
        metavar="1..768",
        help="Total calls per Workspace/HiAgent method trial",
    )
    budget.add_argument(
        "--hiagent-max-calls",
        type=int,
        choices=range(1, 65),
        metavar="1..64",
        help="Legacy HiAgent-only budget override",
    )
    parser.add_argument("--compose-override", type=Path, action="append", default=[])
    parser.add_argument(
        "--control-handoff-after",
        type=int,
        help="One explicit control-method fresh-Host handoff after N tool receipts; "
        "retains the live task environment and shared call budget",
    )
    parser.add_argument("--controller-output-tokens", type=int, default=2048)
    parser.add_argument("--summary-output-tokens", type=int, default=1024)
    parser.add_argument(
        "--control-feedback-batch-size", type=int, default=1,
        help="RWC/SIMPLE tool-feedback batch; 1 keeps per-feedback control; "
        "lifecycle boundaries force control",
    )
    parser.add_argument("--om-observation-tokens", type=int, default=12000)
    parser.add_argument("--om-recent-events", type=int, default=2)
    parser.add_argument(
        "--order",
        nargs="+",
        choices=[
            "NOTE",
            "REVIEW",
            "REGULATED_0",
            "REGULATED_1",
            "REGULATED_2",
            "TERMINUS_2",
            "HIAGENT",
            "H_ONCE",
            "EVIDENCE_0",
            "EVIDENCE_1",
            "INCREMENTAL",
            "CONTROL_0",
            "WORKSPACE_SIMPLE",
            "MILAI_RWC",
            "OM_SYNC_PORT",
            "ADAPTIVE_MEMORY_SIMPLE",
            "ADAPTIVE_MEMORY_CANDIDATE",
        ],
        default=["NOTE", "REVIEW", "REGULATED_0"],
    )
    parser.add_argument("--revision-source", action="append", default=[])
    parser.add_argument(
        "--role", choices=["development_source", "transfer_only"], default="development_source"
    )
    parser.add_argument("--artifact", action="append", default=[])
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
