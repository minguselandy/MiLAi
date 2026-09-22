"""Seal, then execute the single authorized adoption-proxy batch; no replay.

Run with the pinned external lifelong venv and Lab src on PYTHONPATH. `seal`
is entirely offline. `run` requires the exact admission SHA printed by seal.
Raw tasks, responses, costs and snapshots remain outside Git.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from milai_lab.methods.bundle_adoption_proxy import digest, select_bundles
from milai_lab.methods.finite_research_budget import FiniteResearchBudget
from prepare_utility_proxy import ALLOCATION, ALLOCATION_SHA, BASE, LAB, prepare, sha
from reasoningbank_provider import NativeProvider
from reasoningbank_runtime_policy import action_budget, actor_runtime_context
from replay_v0213_cost import save
from v02_local_provider import append_event

ROOT = BASE / "post-cleanup-utility-proxy-20260922/admitted"
BENCH = Path(
    "/cra/memory/mx_memory/benchmarks/reasoningbank-transfer-20260915-_7fzz854/LifelongAgentBench"
)
BENCH_COMMIT = "d6f19b42eb358d9150379f0c68c2985c5a867520"
IMAGES = {
    "mysql:8.0": "sha256:6cd09145362dfe6831b14545de3d5fd6cc75c37cfd6ef8561429c1fc73518b39",
    "milai-research/lifelong-os:rb-20260915-7fzz854": (
        "sha256:5e15a2f08cc26aa936a131a39aadd0d1210049d6e23a11574b101b7873cd2ec7"
    ),
}
COMMON = {"action_budget_context": True, "action_aware_policy": True}
# Pre-outcome semantic review is an analysis denominator, NEVER selection routing.
REVIEW = {
    "428": (
        True,
        "Both bundles apply to dependent user/group/permission changes; the full "
        "bundle additionally verifies primary versus secondary membership.",
    ),
    "242": (
        False,
        "Single shell change: multi-step configuration and group-membership "
        "advice do not establish two substantively applicable alternatives.",
    ),
    "355": (
        False,
        "File groups/permissions are relevant to both cores, but secondary-user "
        "membership verification does not establish a meaningful competing bundle.",
    ),
    "467": (
        False,
        "Directory deletion: creation/copy prerequisites versus user/group "
        "configuration are weak transfers, not two established meaningful alternatives.",
    ),
}


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()  # noqa: S603


def verify_environment() -> None:
    if command("git", "-C", str(BENCH), "rev-parse", "HEAD") != BENCH_COMMIT:
        raise ValueError("NATIVE_COMMIT_CHANGED")
    if command("git", "-C", str(BENCH), "status", "--porcelain"):
        raise ValueError("NATIVE_CHECKOUT_DIRTY")
    for name, identity in IMAGES.items():
        if command("docker", "image", "inspect", name, "--format", "{{.Id}}") != identity:
            raise ValueError("NATIVE_IMAGE_CHANGED")


def freeze_plan(inputs: dict, allocation: dict) -> list[dict]:
    by_task = {(t["domain"], t["id"]): t for t in inputs["tasks"]}
    if len(by_task) != 24 or len(allocation["schedule"]) != 32:
        raise ValueError("FROZEN_POSITION_COUNT_CHANGED")
    plan = []
    for pair in allocation["schedule"]:
        row = by_task[pair["domain"], pair["task_id"]]
        if row["selection"] != select_bundles(row["candidates"]):
            raise ValueError("SELECTION_RECOMPUTATION_MISMATCH")
        changed = row["selection"]["STATIC"] != row["selection"]["UTILITY"]
        if changed and (pair["domain"] != "os_interaction" or row["id"] not in REVIEW):
            raise ValueError("PRE_OUTCOME_REVIEW_REQUIRED")
        eligible, note = (
            REVIEW[row["id"]]
            if changed
            else (False, "No selection difference; proxy not distinguishable or STATIC fallback.")
        )
        if not row["cached_query_available"]:
            note = "No cached instructed BGE query; common cache-only retrieval abstains."
        for arm in pair["arms"]:
            selected = row["selection"][arm]
            candidate = next((c for c in row["candidates"] if c["bundle_id"] == selected), None)
            plan.append(
                {
                    **pair,
                    "sequence": len(plan),
                    "arm": arm,
                    "attempt_id": f"pair-{pair['pair_index']:02d}-{arm}",
                    "query_sha256": row["query_sha256"],
                    "bundle_id": selected,
                    "versions": candidate["versions"] if candidate else [],
                    "context": candidate["context"] if candidate else "",
                    "available_bundle_ids": [c["bundle_id"] for c in row["candidates"]],
                    "selection_changed": changed,
                    "mechanism_eligible": eligible,
                    "pre_outcome_review": note,
                    "observable_use": "UNKNOWN",
                }
            )
    return plan


def seal() -> dict:
    verify_environment()
    ROOT.mkdir(parents=True, exist_ok=False)
    inputs = prepare(ROOT)
    allocation = json.loads(ALLOCATION.read_text())
    plan = freeze_plan(inputs, allocation)
    save(ROOT / "plan.json", plan)
    sources = dict(inputs["source_sha256"])
    sources[str(ROOT / "plan.json")] = sha(ROOT / "plan.json")
    sources[str(ROOT / "inputs.proposal.json")] = sha(ROOT / "inputs.proposal.json")
    # Only the authorized IDs reach native scoring. Gold is never a selector input.
    for domain, positions in allocation["domains"].items():
        path = BASE / f"experience-optimization-20260916/native/{domain}.json"
        data = json.loads(path.read_text())
        target = ROOT / f"native-{domain}.json"
        save(target, {p["id"]: data[p["id"]] for p in positions})
        sources[str(path)] = sha(path)
        sources[str(target)] = sha(target)
    # Bind executable closure without importing Product or Archive internals.
    for directory in (LAB / "src", LAB / "tools", LAB / "configs/policies"):
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".txt", ".json"}:
                sources[str(path)] = sha(path)
    protocol = LAB / "docs/UTILITY_PROXY_PROTOCOL.md"
    sources[str(protocol)] = sha(protocol)
    value = {
        "schema": "milai-utility-proxy-admission-v1",
        "status": "SEALED_BEFORE_FIRST_REQUEST",
        "arm_kind": "RESEARCH_PROTOTYPE",
        "root": str(ROOT),
        "allocation_sha256": ALLOCATION_SHA,
        "source_sha256": sources,
        "benchmark_commit": BENCH_COMMIT,
        "images": IMAGES,
        "common": COMMON,
        "solver": allocation["solver"],
        "limits": allocation["limits"],
        "embedding": "existing frozen bge-m3 vectors only; zero new requests",
        "arm_executions": len(plan),
        "sealed_at_unix": time.time(),
        "independent_mechanism_eligible": len(
            {(x["domain"], x["task_id"]) for x in plan if x["mechanism_eligible"]}
        ),
    }
    save(ROOT / "admission.json", value)
    return {
        "admission_sha256": sha(ROOT / "admission.json"),
        "root": str(ROOT),
        "executions": len(plan),
        "new_requests": 0,
    }


def verify_admission(expected_sha: str) -> tuple[dict, list[dict]]:
    path = ROOT / "admission.json"
    if sha(path) != expected_sha:
        raise ValueError("ADMISSION_SHA_MISMATCH")
    value = json.loads(path.read_text())
    if value["root"] != str(ROOT) or value["allocation_sha256"] != ALLOCATION_SHA:
        raise ValueError("WRONG_BATCH_ROOT_OR_ALLOCATION")
    for name, identity in value["source_sha256"].items():
        if sha(Path(name)) != identity:
            raise ValueError(f"FROZEN_SOURCE_CHANGED:{name}")
    verify_environment()
    return value, json.loads((ROOT / "plan.json").read_text())


def execute_arm(row: dict, provider: NativeProvider, budget: FiniteResearchBudget) -> dict:
    from src.agents.instance.language_model_agent import LanguageModelAgent
    from src.factories.chat_history_item import ChatHistoryItemFactory
    from src.language_models import LanguageModel
    from src.tasks.instance.db_bench import task as db_module
    from src.tasks.instance.os_interaction import task as os_module
    from src.typings import ChatHistoryItem, Role, SampleStatus, Session, TaskName

    arm_root = ROOT / "arms" / row["attempt_id"]
    arm_root.mkdir(parents=True, exist_ok=False)  # durable no-replay claim, before reset
    save(arm_root / "claim.json", row)
    started = time.monotonic()
    before = budget.status()
    task = None
    session = None
    result = {
        "attempt_id": row["attempt_id"],
        "sequence": row["sequence"],
        "status": "STARTED",
        "outcome": None,
        "observable_use": "UNKNOWN",
    }
    domain = row["domain"]
    try:
        klass = db_module.DBBench if domain == "db_bench" else os_module.OSInteraction
        kwargs = {
            "task_name": TaskName(domain),
            "chat_history_item_factory": ChatHistoryItemFactory(
                str(ROOT / "native-prompts" / f"{domain}.json")
            ),
            "data_file_path": str(ROOT / f"native-{domain}.json"),
            "max_round": 3 if domain == "db_bench" else 5,
        }
        if domain == "os_interaction":
            kwargs["command_execution_timeout"] = 20
        task = klass(**kwargs)
        session = Session(task_name=task.task_name, sample_index=row["task_id"])
        task.reset(session)
        if session.sample_status == SampleStatus.RUNNING:
            if digest(session.chat_history.get_item_deep_copy(-1).content) != row["query_sha256"]:
                raise ValueError("NATIVE_QUERY_CHANGED")

        class NativeLanguageModel(LanguageModel):
            def __init__(self):
                super().__init__({"user": "user", "agent": "assistant"})

            def _inference(self, batch_chat_history, inference_config_dict, system_prompt):
                responses = []
                for history in batch_chat_history:
                    runtime = actor_runtime_context(
                        LAB,
                        COMMON,
                        action_budget(
                            task.max_round, task.current_round, unit="native interaction"
                        ),
                    )
                    messages = [
                        {
                            "role": "system",
                            "content": system_prompt
                            + ("\n\n" + row["context"] if row["context"] else "")
                            + ("\n\n" + runtime if runtime else ""),
                        },
                        *self._convert_chat_history_to_message_list(history),
                    ]
                    message = provider.generate_message(row["attempt_id"], messages)
                    append_event(
                        arm_root / "exposures.jsonl",
                        {
                            "event": "PROTOTYPE_ACTOR_INPUT_SETTLED",
                            "bundle_id": row["bundle_id"],
                            "versions": row["versions"],
                            "receipt": provider.last_receipt,
                            "observable_use": "UNKNOWN",
                        },
                    )
                    content = message.get("content")
                    if not isinstance(content, str):
                        raise ValueError("NATIVE_TEXT_ACTOR_RETURNED_NO_TEXT")
                    responses.append(ChatHistoryItem(role=Role.AGENT, content=content))
                return responses

        agent = LanguageModelAgent(NativeLanguageModel())
        while session.sample_status == SampleStatus.RUNNING:
            budget.remaining_seconds()
            agent.inference(session)
            task.interact(session)
        task.complete(session)
        result.update(
            status=str(session.sample_status),
            outcome=str(session.evaluation_record.outcome),
            finish_reason=session.finish_reason,
        )
    except BaseException as error:
        result.update(status="FAILED", error_type=type(error).__name__, reason=str(error))
        raise
    finally:
        if session is not None:
            save(arm_root / "native-session.json", session.model_dump(mode="json"))
        try:
            if task is not None:
                task.release()
        finally:
            result.update(
                seconds=time.monotonic() - started,
                budget_before=before,
                budget_after=budget.status(),
                provider_usage=provider.task_usage(row["attempt_id"]),
            )
            save(arm_root / "result.json", result)
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in result.items()
                        if k not in {"budget_before", "budget_after", "provider_usage"}
                    }
                ),
                flush=True,
            )
    return result


def run(expected_sha: str) -> dict:
    _, plan = verify_admission(expected_sha)
    # Exclusive batch marker: process interruption is terminal, never a fresh budget.
    with (ROOT / "started.json").open("x") as handle:
        json.dump({"admission_sha256": expected_sha, "local_start_unix": time.time()}, handle)
        handle.flush()
    sys.path.insert(0, str(BENCH))
    from src.factories.chat_history_item.offline.construct import construct_offline
    from src.tasks.instance.db_bench import task as db_module
    from src.tasks.instance.os_interaction import task as os_module

    construct_offline(
        str(ROOT / "native-prompts"),
        "\n\nNow, I will give you the question that you need to solve.",
    )
    original_db, original_os = db_module.DBBenchContainer, os_module.OSInteractionContainer
    db_module.DBBenchContainer = lambda: original_db(image=IMAGES["mysql:8.0"])
    os_module.OSInteractionContainer = lambda timeout: original_os(
        timeout, image=IMAGES["milai-research/lifelong-os:rb-20260915-7fzz854"]
    )
    budget = FiniteResearchBudget(ROOT / "budget.sqlite", manifest_sha256=expected_sha)
    provider = NativeProvider(
        ROOT / "provider",
        max_tokens=3_000_000,
        max_requests=400,
        deadline=time.monotonic() + 14400,
        batch_budget=budget,
        request_timeout_seconds=180,
    )
    results = []
    terminal = "COMPLETED"
    reason = None
    try:
        provider.verify()  # FIRST external request; counted, starts the conservative 4h clock
        if provider.context != 65536:
            raise ValueError("MODEL_CONTEXT_IDENTITY_CHANGED")
        for row in plan:
            budget.remaining_seconds()
            results.append(execute_arm(row, provider, budget))
    except BaseException as error:
        terminal, reason = "STOPPED", f"{type(error).__name__}:{error}"
    finally:
        value = {
            "status": terminal,
            "reason": reason,
            "completed": results,
            "budget": budget.status(),
            "admission_sha256": expected_sha,
            "unfinished_attempts": [
                x["attempt_id"]
                for x in plan
                if not (ROOT / "arms" / x["attempt_id"] / "result.json").exists()
            ],
            "ended_at_unix": time.time(),
        }
        save(ROOT / "terminal.json", value)
        provider.close()
        budget.close()
        db_module.DBBenchContainer, os_module.OSInteractionContainer = original_db, original_os
    return {k: v for k, v in value.items() if k != "completed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("seal", "run"))
    parser.add_argument("--admission-sha256")
    args = parser.parse_args()
    if args.mode == "run" and not args.admission_sha256:
        parser.error("run requires the frozen admission SHA")
    print(json.dumps(seal() if args.mode == "seal" else run(args.admission_sha256)), flush=True)


if __name__ == "__main__":
    main()
