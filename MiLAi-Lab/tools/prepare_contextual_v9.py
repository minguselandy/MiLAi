"""Prepare a pinned MERIT run from the v9 or v10 task template."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import run_contextual_merit as merit
from milai_lab.harness.contextual_artifacts import digest, read_json, write_json

LAB = Path(__file__).resolve().parents[1]
TEMPLATE = LAB / "configs/contextual-memory-v9-template.json"
V10_TEMPLATES = (
    "configs/contextual-memory-v10-notes-template.json",
    "configs/contextual-memory-v10-basis-template.json",
)
PINNED_SELECTION = LAB / "data/manifests/contextual-memory-v7-e0-selection-final.json"
PINNED_MERIT_COMMIT = "293933d96b1d1849e1f20d1bb324def5de9ed33f"
ARC_SHA256 = "32e50fc25c1ce473eccb5c0653e3867072d792c9aed80148236f9b0baff5d12f"
WORLD_SHA256 = "221f4be1976ff8bc44ddc97b121dea6e15c22d79eff15dfe551a914342569b29"
SOURCE_FILES = (
    "src/milai_lab/datasets/contextual.py",
    "src/milai_lab/datasets/memsyco.py",
    "src/milai_lab/datasets/stale.py",
    "src/milai_lab/scorers/contextual.py",
    "src/milai_lab/scorers/memsyco.py",
    "src/milai_lab/scorers/stale.py",
    "src/milai_lab/methods/contextual_user_memory.py",
    "src/milai_lab/methods/controlled_workspace.py",
    "src/milai_lab/methods/reasoning_bank.py",
    "src/milai_lab/methods/state_attention.py",
    "src/milai_lab/methods/state_focus.py",
    "src/milai_lab/providers/contextual_capacity.py",
    "src/milai_lab/providers/contextual_embeddings.py",
    "src/milai_lab/providers/contextual_vllm.py",
    "src/milai_lab/runners/contextual.py",
    "src/milai_lab/runners/contextual_agent_tasks.py",
    "src/milai_lab/runners/contextual_delivery.py",
    "src/milai_lab/runners/contextual_host.py",
    "src/milai_lab/runners/contextual_ingestion.py",
    "src/milai_lab/runners/contextual_maintenance.py",
    "src/milai_lab/runners/contextual_profiles.py",
    "src/milai_lab/runners/contextual_runtime_store.py",
    "src/milai_lab/runners/contextual_scoring.py",
    "src/milai_lab/runners/contextual_session.py",
    "src/milai_lab/harness/contextual_artifacts.py",
    "tools/prepare_contextual_v9.py",
    "tools/run_contextual_merit.py",
    "tools/run_contextual_user_memory.py",
    "examples/contextual_document.py",
    "configs/contextual-memory-v9-template.json",
    "data/manifests/contextual-memory-v9-document-sequence.json",
    "pyproject.toml",
    "uv.lock",
)
WEIGHT_SUFFIXES = {".safetensors", ".bin", ".pt", ".gguf"}
METADATA_NAMES = (
    "config.json", "configuration.json", "tokenizer_config.json",
    "chat_template.jinja", "generation_config.json", "model.safetensors.index.json",
)


def file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def model_files(root: Path, *, weights: bool) -> dict[str, Any]:
    if not root.is_dir():
        raise ValueError(f"MODEL_DIRECTORY_MISSING: {root}")
    files = sorted(path for path in root.iterdir() if path.is_file()
                   and ((path.suffix in WEIGHT_SUFFIXES) if weights
                        else (path.name in METADATA_NAMES)))
    if not files:
        raise ValueError(f"MODEL_{'WEIGHTS' if weights else 'METADATA'}_MISSING: {root}")
    return {
        path.name: {"size": path.stat().st_size, "sha256": file_sha256(path)}
        if weights else file_sha256(path)
        for path in files
    }


def source_mapping(*, v10: bool = False) -> dict[str, str]:
    paths = [*SOURCE_FILES, *(V10_TEMPLATES if v10 else ()), *(
        str(path.relative_to(LAB))
        for path in sorted((LAB / "src/milai_lab/methods/contextual_memory").glob("*.py"))
    )]
    return {relative: file_sha256(LAB / relative) for relative in paths}


def _within_lab(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(LAB))
    except ValueError as error:
        raise ValueError("PREPARATION_OUTPUT_OUTSIDE_LAB") from error


def prepare(
    *, output_dir: Path, merit_root: Path, host_dir: Path, embedding_dir: Path,
    host_url: str, embedding_url: str, budget_path: Path,
    host_model: str | None = None, embedding_model: str | None = None,
    embedding_tokenizer: Path | None = None, template_path: Path = TEMPLATE,
) -> dict[str, str]:
    output_dir = output_dir.resolve()
    merit_root = merit_root.resolve()
    host_dir = host_dir.resolve()
    embedding_dir = embedding_dir.resolve()
    budget_path = budget_path.resolve()
    config_key = _within_lab(output_dir / "config.json")
    if not config_key.startswith("artifacts/contextual-user-memory/"):
        raise ValueError("PREPARATION_OUTPUT_NOT_MANAGED")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("PREPARATION_OUTPUT_NOT_EMPTY")
    commit = subprocess.check_output(  # noqa: S603
        ["git", "-C", str(merit_root), "rev-parse", "HEAD"], text=True,  # noqa: S607
    ).strip()
    if commit != PINNED_MERIT_COMMIT:
        raise ValueError("MERIT_SOURCE_COMMIT_CHANGED")
    template = read_json(template_path)
    version = template.get("config_version")
    if version == "contextual-task-v10":
        policy = template.get("decision_policy")
        if (policy not in {"notes", "basis"} or template.get("state_policy") != "off"
                or template.get("maintenance_protocol") != "turn-maintenance-v3"
                or template.get("host", {}).get("tool_mode") != "json_action"
                or type(template.get("decision_feedback")) is not bool
                or type(template.get("decision_gap_focus")) is not bool
                or (policy == "notes" and (template["decision_feedback"]
                                           or template["decision_gap_focus"]))):
            raise ValueError("V10_TEMPLATE_DECISION_CONTRACT_MISMATCH")
        arm = "react_notes_v10_off" if policy == "notes" else "decision_basis_v10_off"
        label = "V10"
    elif version == "contextual-task-v9":
        arm, label = "ordinary_v9_off", "V9"
    else:
        raise ValueError("TEMPLATE_VERSION_MISMATCH")
    host_tokenizers = {
        name: file_sha256(host_dir / name)
        for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")
    }
    embedding_tokenizer = (embedding_tokenizer or embedding_dir / "tokenizer.json").resolve()
    embed_tokenizer_sha = file_sha256(embedding_tokenizer)
    weights = {
        "host": model_files(host_dir, weights=True),
        "embedding": model_files(embedding_dir, weights=True),
    }
    metadata = {
        "host": model_files(host_dir, weights=False),
        "embedding": model_files(embedding_dir, weights=False),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    weights_path = output_dir / "model-weights.json"
    metadata_path = output_dir / "model-metadata.json"
    write_json(weights_path, weights)
    write_json(metadata_path, metadata)
    config = copy.deepcopy(template)
    config["host"]["base_url"] = host_url
    config["embedding"]["base_url"] = embedding_url
    if host_model is not None:
        config["host"]["model"] = host_model
        config["capacity"]["model"] = host_model
    if embedding_model is not None:
        config["embedding"]["model"] = embedding_model
    config["capacity"]["tokenizer_path"] = str(host_dir)
    config["capacity"]["tokenizer_files_sha256"] = host_tokenizers
    config["embedding_window"]["tokenizer_path"] = str(embedding_tokenizer)
    config["embedding_window"]["tokenizer_sha256"] = embed_tokenizer_sha
    config["budget_path"] = str(budget_path)
    config["model_identity"] = {
        "artifacts": [
            {"path": str(path), "sha256": file_sha256(path)}
            for path in (weights_path, metadata_path, embedding_tokenizer)
        ],
        "host": {
            "local_path": str(host_dir), "weights_sha256": digest(weights["host"]),
            "metadata": metadata["host"], "served_model": config["host"]["model"],
            "chat_template_kwargs": {"enable_thinking": config["host"]["enable_thinking"]},
            "max_model_len": config["capacity"]["context_tokens"],
        },
        "embedding": {
            "local_path": str(embedding_dir),
            "weights_sha256": digest(weights["embedding"]),
            "metadata": metadata["embedding"],
            "served_model": config["embedding"]["model"],
        },
        "verification": (
            f"Local weights and metadata hashed during {label.lower()} preparation; "
            "manifests checked on run."
        ),
    }
    config_path = output_dir / "config.json"
    write_json(config_path, config)
    template_key = _within_lab(template_path)
    if version == "contextual-task-v10" and template_key not in V10_TEMPLATES:
        raise ValueError("V10_TEMPLATE_PATH_NOT_PINNED")
    mapping = source_mapping(v10=version == "contextual-task-v10")
    freeze = {
        "status": "DEVELOPMENT_COMPLETE_READY_FOR_BENCHMARK_SELECTION",
        "source_sha256": mapping, "source_mapping_sha256": digest(mapping),
        "config_sha256": {config_key: file_sha256(config_path)},
    }
    freeze_path = output_dir / "freeze.json"
    write_json(freeze_path, freeze)
    selection = copy.deepcopy(read_json(PINNED_SELECTION))
    selection["status"] = f"{label}_PINNED_ORIGINAL_ARC"
    selection["selection_role"] = (
        "Previously exposed fixed arc for continuous validation; not a new independent sample."
    )
    selection["external_root"] = str(merit_root)
    selection["source_commit"] = PINNED_MERIT_COMMIT
    selection["execution_plan"]["arms"] = [arm]
    selection["execution_plan"]["status"] = f"{label}_CONTINUOUS_VALIDATION"
    selection["config_path"] = config_key
    selection["config_sha256"] = file_sha256(config_path)
    selection["development_freeze_sha256"] = freeze["source_mapping_sha256"]
    for key in (
        "repair_freeze_sha256", "previous_selection_sha256", "previous_selection_path",
        "development_freeze_path", "repair_reason", "goal_design_revision", "plan_revision",
        "previous_selection_status", "selected_at",
    ):
        selection.pop(key, None)
    upstream_arcs, _, _, _ = merit.pinned_merit(selection)
    (arc,) = upstream_arcs.generate_suite(**selection["generator_arguments"])
    arc_bytes = json.dumps(
        asdict(arc), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    if arc.arc_id != "arc0-000" or hashlib.sha256(arc_bytes).hexdigest() != ARC_SHA256:
        raise ValueError("MERIT_ARC_IDENTITY_MISMATCH")
    arc_path = output_dir / "merit-d1-hard-arc0-000.original.json"
    arc_path.write_bytes(arc_bytes)
    world = arc.make_world()
    try:
        world_bytes = world.dump_json().encode()
    finally:
        world.conn.close()
    if hashlib.sha256(world_bytes).hexdigest() != WORLD_SHA256:
        raise ValueError("MERIT_INITIAL_WORLD_CHANGED")
    world_path = output_dir / "merit-d1-hard-arc0-000.initial-world.json"
    world_path.write_bytes(world_bytes)
    selection["private_artifacts"].update(
        arc=str(arc_path), arc_sha256=ARC_SHA256,
        initial_world=str(world_path), initial_world_sha256=WORLD_SHA256,
    )
    selection_path = output_dir / "selection.json"
    write_json(selection_path, selection)
    merit.prepared_inputs(selection_path, config_path, freeze_path)
    return {
        "selection": str(selection_path), "config": str(config_path),
        "freeze": str(freeze_path), "run_output": str(output_dir / "run"),
        "budget_path": str(budget_path), "arc_sha256": ARC_SHA256,
        "initial_world_sha256": WORLD_SHA256,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=LAB / "artifacts/contextual-user-memory/v9-prepared")
    parser.add_argument("--merit-root", type=Path, required=True)
    parser.add_argument("--host-dir", type=Path, required=True)
    parser.add_argument("--embedding-dir", type=Path, required=True)
    parser.add_argument("--host-url", default="http://127.0.0.1:7860/v1/")
    parser.add_argument("--embedding-url", default="http://127.0.0.1:7861/v1/")
    parser.add_argument("--host-model")
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-tokenizer", type=Path)
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    parser.add_argument("--budget-path", type=Path,
                        default=LAB / "artifacts/contextual-user-memory/v9-budget.json")
    parser.add_argument("--live", action="store_true",
                        help="Run the real vLLM workflow after zero-model preparation")
    args = parser.parse_args()
    result = prepare(
        output_dir=args.output_dir, merit_root=args.merit_root,
        host_dir=args.host_dir, embedding_dir=args.embedding_dir,
        host_url=args.host_url, embedding_url=args.embedding_url,
        budget_path=args.budget_path, host_model=args.host_model,
        embedding_model=args.embedding_model,
        embedding_tokenizer=args.embedding_tokenizer,
        template_path=args.template,
    )
    print(json.dumps({"status": "PREPARED_ZERO_MODEL", **result}, ensure_ascii=False))
    if args.live:
        subprocess.run([  # noqa: S603
            sys.executable, str(LAB / "tools/run_contextual_merit.py"),
            "--selection", result["selection"], "--config", result["config"],
            "--freeze", result["freeze"], "--output", result["run_output"],
        ], check=True)


if __name__ == "__main__":
    main()
