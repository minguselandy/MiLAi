#!/usr/bin/env python3
"""Assemble the isolated Lab contextual-memory benchmark and resumable artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.datasets.contextual import EvaluationCase
from milai_lab.datasets.registry import load_dataset_manifest
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    digest,
    read_json,
    write_json,
)
from milai_lab.methods.contextual_memory.material_view import VIEW_PROTOCOL
from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.methods.contextual_memory.operations import OPERATION_CONTRACT_VERSION
from milai_lab.methods.contextual_memory.write_contract import WRITE_CONTRACT_VERSION
from milai_lab.methods.contextual_user_memory import METHOD_VERSION, TOOLS, ContextualMemory
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_embeddings import embed_texts_windowed
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.contextual import (
    COMMON_PROMPT,
    CONTEXT_PROMPT,
    LAB,
    CachedEmbedding,
    answer_case,
    answer_group,
    answer_query,
    build_history,
    chunks,
    deletion_ledger,
    execute_batches,
    failed_operation,
    freeze_answers,
    ingest_with_forget_cleanup,
    load_cases,
    memory_tools,
    minimal_host_result,
    minimal_ingestion_result,
    publish_history,
    record_answer_failure,
    revision_signals,
    run_answers,
    scrub_history_artifacts,
    summarize,
)
from milai_lab.runners.contextual_host import ContextualHost
from milai_lab.runners.contextual_ingestion import INGESTION_PROMPT, PROTOCOL_VERSION, ingest_chunk
from milai_lab.runners.contextual_profiles import resolve_profile, validate_history_owners
from milai_lab.runners.contextual_scoring import score_case, score_stale_group
from milai_lab.scorers import stale as stale_scoring

__all__ = [
    "COMMON_PROMPT",
    "CONTEXT_PROMPT",
    "LAB",
    "TOOLS",
    "CachedEmbedding",
    "ContextualHost",
    "ContextualMemory",
    "Observation",
    "RunBudget",
    "RunLimits",
    "Trace",
    "VLLMClient",
    "VLLMConfig",
    "answer_case",
    "answer_group",
    "answer_query",
    "build_history",
    "chunks",
    "deletion_ledger",
    "digest",
    "embed_texts_windowed",
    "execute_batches",
    "failed_operation",
    "freeze_answers",
    "ingest_chunk",
    "ingest_with_forget_cleanup",
    "load_cases",
    "main",
    "memory_tools",
    "minimal_host_result",
    "minimal_ingestion_result",
    "parser",
    "publish_history",
    "read_json",
    "record_answer_failure",
    "resolve_profile",
    "revision_signals",
    "run_answers",
    "score_case",
    "score_stale_group",
    "scrub_history_artifacts",
    "summarize",
    "validate_history_owners",
    "write_json",
]


def open_run_budget(config: dict[str, Any], output: Path, limits: RunLimits) -> RunBudget:
    """Bind a v4 run directory to one external cumulative budget and fixed scope."""
    if "history_capacity" not in config:
        return RunBudget(limits, output / "budget.json")
    raw_path = config.get("cumulative_budget_path")
    scope = config.get("cumulative_budget_scope")
    if not isinstance(raw_path, str) or not raw_path or not Path(raw_path).is_absolute():
        raise ValueError("V4_REQUIRES_ABSOLUTE_CUMULATIVE_BUDGET_PATH")
    if not isinstance(scope, str) or not scope:
        raise ValueError("V4_REQUIRES_CUMULATIVE_BUDGET_SCOPE")
    path = Path(raw_path).resolve()
    output = output.resolve()
    if path == output or output in path.parents:
        raise ValueError("CUMULATIVE_BUDGET_MUST_BE_OUTSIDE_RUN_DIRECTORY")
    scope_path = path.with_name(path.name + ".scope.json")
    frozen = {"scope": scope, "limits": asdict(limits)}
    if scope_path.exists():
        if read_json(scope_path) != frozen:
            raise ValueError("CUMULATIVE_BUDGET_SCOPE_OR_LIMITS_CHANGED")
    elif path.exists():
        raise ValueError("CUMULATIVE_BUDGET_HAS_NO_FROZEN_SCOPE")
    else:
        write_json(scope_path, frozen)
    return RunBudget(limits, path)


def execution_identity(config: dict[str, Any]) -> dict[str, Any]:
    """Explicit protocol, prompt, capacity and model identities for the run manifest."""
    return {
        "method_version": METHOD_VERSION,
        "ingestion_protocol": PROTOCOL_VERSION,
        "operation_contract": OPERATION_CONTRACT_VERSION,
        "write_contract": WRITE_CONTRACT_VERSION,
        "material_view_protocol": VIEW_PROTOCOL,
        "prompt_sha256": {
            "common": hashlib.sha256(COMMON_PROMPT.encode()).hexdigest(),
            "ingestion": hashlib.sha256(INGESTION_PROMPT.encode()).hexdigest(),
            "context": hashlib.sha256(CONTEXT_PROMPT.encode()).hexdigest(),
        },
        "config_sha256": digest(config),
        "model_identity_sha256": digest(config["model_identity"]),
        "models": {
            key: config[key]["model"]
            for key in ("host", "embedding", "judge") if key in config
        },
        "host_capacity": (
            HostCapacity(config["history_capacity"]).identity
            if "history_capacity" in config else None
        ),
    }

def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument(
        "--phase", choices=["ingest", "develop", "evaluate", "score", "report"],
        default="develop",
    )
    return result


def main() -> None:
    args = parser().parse_args()
    config = read_json(args.config)
    if args.phase == "evaluate" and config["phase"] != "formal":
        raise ValueError("Formal evaluation requires a frozen formal configuration")
    if args.phase in {"ingest", "develop"} and config["phase"] != "development":
        raise ValueError("Ingestion and development require a development configuration")
    for artifact in config["model_identity"]["artifacts"]:
        if hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest() != artifact["sha256"]:
            raise ValueError("Pinned model identity artifact changed")
    verified: set[str] = set()
    for spec in config["datasets"]:
        manifest = LAB / spec["manifest"]
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != spec["data_manifest_sha256"]:
            raise ValueError("Pinned dataset manifest changed")
        if str(manifest) not in verified:
            if spec["dataset"] in {"memsyco", "stale"}:
                selection = read_json(manifest)
                errors = []
                for entry in selection["source_files"]:
                    relative_path = entry.get("relative_path", entry.get("path"))
                    with (Path(spec["root"]) / relative_path).open("rb") as stream:
                        actual = hashlib.file_digest(stream, "sha256").hexdigest()
                    if actual != entry["sha256"]:
                        errors.append(relative_path)
            else:
                errors = load_dataset_manifest(manifest).verify()
            if errors:
                raise ValueError("Dataset verification failed: " + "; ".join(errors))
            verified.add(str(manifest))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # One immutable run manifest prevents accidental resume under changed methods or budgets.
    source_files = [
        "tools/run_contextual_user_memory.py",
        "tools/contextual_host_adapter.py",
        "tools/contextual_embeddings.py",
        "tools/contextual_ingestion.py",
        "src/milai_lab/runners/contextual.py",
        "src/milai_lab/runners/contextual_ingestion.py",
        "src/milai_lab/providers/contextual_embeddings.py",
        "src/milai_lab/providers/contextual_capacity.py",
        "src/milai_lab/methods/contextual_user_memory.py",
        "src/milai_lab/datasets/contextual.py",
        "src/milai_lab/scorers/contextual.py",
        "src/milai_lab/datasets/memsyco.py",
        "src/milai_lab/scorers/memsyco.py",
        "src/milai_lab/datasets/stale.py",
        "src/milai_lab/scorers/stale.py",
        "src/milai_lab/runners/contextual_scoring.py",
        "src/milai_lab/providers/contextual_vllm.py",
        "src/milai_lab/runners/contextual_host.py",
        "src/milai_lab/runners/contextual_session.py",
        "src/milai_lab/runners/contextual_agent_tasks.py",
        "src/milai_lab/runners/contextual_maintenance.py",
        "src/milai_lab/runners/contextual_runtime_store.py",
        "src/milai_lab/runners/contextual_delivery.py",
        "src/milai_lab/runners/contextual_profiles.py",
        "src/milai_lab/harness/contextual_artifacts.py",
        "src/milai_lab/methods/controlled_workspace.py",
        "src/milai_lab/methods/reasoning_bank.py",
        "src/milai_lab/methods/state_attention.py",
        "src/milai_lab/methods/state_focus.py",
        "pyproject.toml",
        "uv.lock",
    ]
    source_files += [
        str(path.relative_to(LAB))
        for path in sorted((LAB / "src/milai_lab/methods/contextual_memory").glob("*.py"))
    ]
    run_manifest = {
        "config": config,
        "arm_kind": "RESEARCH_PROTOTYPE",
        "execution_identity": execution_identity(config),
        "source_sha256": {
            path: hashlib.sha256((LAB / path).read_bytes()).hexdigest() for path in source_files
        },
    }
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        if read_json(manifest_path) != run_manifest:
            raise ValueError("Resume requires the original fixed source and configuration")
    else:
        write_json(manifest_path, run_manifest)
    source_snapshot = output / "sources.json"
    if not source_snapshot.exists():
        write_json(source_snapshot, {path: (LAB / path).read_text() for path in source_files})
    limits = RunLimits(**config["budget"])
    for profile_name in config["profiles"].values():
        resolve_profile(profile_name)
    batches: list[tuple[dict[str, Any], list[EvaluationCase], list[str], Path]] = []
    for spec in config["datasets"]:
        cases = load_cases(spec, development=config["phase"] == "development")
        count = len(cases)
        if spec["dataset"] == "personamem-v2":
            csv_path = (
                Path(spec["root"])
                / "benchmark"
                / "text"
                / (spec["split"].removesuffix("_text") + ".csv")
            )
            with csv_path.open() as stream:
                count = sum(1 for _ in csv.DictReader(stream))
        if count != spec["expected_count"]:
            raise ValueError("Pinned upstream question count changed")
        if config["phase"] == "development":
            selected = set(spec["development_ids"])
            if spec["dataset"] == "stale":
                by_scenario: dict[str, set[str]] = {}
                for case in cases:
                    by_scenario.setdefault(case.metadata["scenario_id"], set()).add(case.case_id)
                if any(
                    selected & member_ids and not member_ids <= selected
                    for member_ids in by_scenario.values()
                ):
                    raise ValueError("STALE development must select all three probes per scenario")
            cases = [case for case in cases if case.case_id in selected]
            if len(cases) != len(selected):
                raise ValueError("Development ID not present in pinned artifact")
        arms = spec.get("arms", config["arms"])
        if len(arms) > limits.arms or config["reference_arm"] not in arms:
            raise ValueError("Arm budget exceeded or reference arm absent")
        validate_history_owners(
            arms,
            {arm: config["profiles"][arm] for arm in arms},
            config.get("history_owner", {}),
        )
        dataset_output = output / spec["dataset"] / spec["split"]
        dataset_output.mkdir(parents=True, exist_ok=True)
        batches.append((spec, cases, arms, dataset_output))
    if sum(len(cases) for _, cases, _, _ in batches) > limits.questions:
        raise ValueError("Question budget exceeded before model execution")
    if any(cases[0].dataset == "stale" for _, cases, _, _ in batches):
        if config["judge"].get("max_tokens", 2048) < stale_scoring.JUDGE_MAX_TOKENS:
            raise ValueError("STALE Judge max_tokens below its three-dimension output budget")
    budget = open_run_budget(config, output, limits)
    execute_batches(batches, config=config, output=output, budget=budget, phase=args.phase)

if __name__ == "__main__":
    main()
