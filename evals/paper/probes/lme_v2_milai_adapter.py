"""Label-free synthetic smoke for the LongMemEval-V2 MiLAi adapter."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.identity import sha256_file
from evals.paper.lme_v2_adapter import (
    EXPECTED_CANDIDATE_ID,
    MiLAiLMEV2Memory,
    memory_context_identity,
    official_contract_identity,
)
from evals.paper.probes.lme_v2_modality import _two_band_png

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = (
    ROOT / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-002/result.json"
)
DEFAULT_OFFICIAL_PYTHON = Path(
    "/tmp/milai-dg11-pe06-official-interface-20260824-001/bin/python"
)
MODALITY_ARTIFACT = ROOT / "var/dg11/paper/freeze/lme-v2-modality-feasibility.json"
SUPERSEDED_FAILURE = (
    ROOT
    / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-001/failure-disclosure.json"
)
CANDIDATE_MANIFEST = ROOT / "var/dg11/freeze/candidate/candidate-manifest.json"
CANDIDATE_INVENTORY = ROOT / "var/dg11/final/candidate/inventory.json"


class LMEV2AdapterSmokeError(RuntimeError):
    pass


def _atomic_bytes_once(path: Path, value: bytes) -> None:
    if path.exists():
        raise LMEV2AdapterSmokeError(f"synthetic smoke asset is write-once: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise LMEV2AdapterSmokeError("PE06 adapter smoke result is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _trajectory(
    *,
    trajectory_id: str,
    environment: str,
    goal: str,
    state_specs: list[dict[str, str | int | None]],
) -> dict[str, object]:
    states: list[dict[str, object]] = []
    for state_index, spec in enumerate(state_specs):
        states.append(
            {
                "accessibility_tree": spec["accessibility_tree"],
                "action": spec["action"],
                "screenshot": spec["screenshot"],
                "state_index": state_index,
                "step": spec["step"],
                "thought": spec["thought"],
                "url": spec["url"],
            }
        )
    return {
        "domain": "web",
        "environment": environment,
        "goal": goal,
        "id": trajectory_id,
        "outcome": "success",
        "start_url": str(state_specs[0]["url"]),
        "states": states,
    }


def _create_synthetic_inputs(
    output: Path, *, reuse_identical_assets: bool = False
) -> dict[str, Any]:
    asset_root = output.parent / "synthetic"
    paths = {
        "question": asset_root / "question/0000.png",
        "target_initial": asset_root / "screenshots/trajectory-target/0000.png",
        "target_confirmation": asset_root / "screenshots/trajectory-target/0001.png",
        "calendar": asset_root / "screenshots/trajectory-calendar/0000.png",
        "billing": asset_root / "screenshots/trajectory-billing/0000.png",
    }
    images = {
        "question": _two_band_png(
            width=96,
            height=64,
            first=(0, 255, 0),
            second=(255, 255, 0),
            vertical=False,
        ),
        "target_initial": _two_band_png(
            width=96,
            height=64,
            first=(128, 128, 128),
            second=(255, 255, 255),
            vertical=True,
        ),
        "target_confirmation": _two_band_png(
            width=96,
            height=64,
            first=(255, 0, 0),
            second=(0, 0, 255),
            vertical=True,
        ),
        "calendar": _two_band_png(
            width=96,
            height=64,
            first=(0, 0, 0),
            second=(255, 255, 255),
            vertical=False,
        ),
        "billing": _two_band_png(
            width=96,
            height=64,
            first=(0, 255, 255),
            second=(255, 0, 255),
            vertical=True,
        ),
    }
    for name, path in paths.items():
        if path.exists() and reuse_identical_assets:
            if path.read_bytes() != images[name]:
                raise LMEV2AdapterSmokeError(
                    f"existing synthetic asset bytes drifted: {path}"
                )
        else:
            _atomic_bytes_once(path, images[name])

    def relative(path: Path) -> str:
        return str(path.relative_to(asset_root))

    trajectories = [
        _trajectory(
            trajectory_id="trajectory-target",
            environment="synthetic-backup-settings",
            goal="Configure backups to use Vault Alpha and confirm the saved setting",
            state_specs=[
                {
                    "accessibility_tree": (
                        "heading 'Backup settings'\n"
                        "combobox 'Destination' value='Vault Alpha'\n"
                        "button 'Save backup setting'"
                    ),
                    "action": "Click Save backup setting",
                    "screenshot": relative(paths["target_initial"]),
                    "step": 10,
                    "thought": "Save Vault Alpha as the backup destination",
                    "url": "https://synthetic.invalid/settings/backup",
                },
                {
                    "accessibility_tree": (
                        "heading 'Backup confirmation'\n"
                        "status 'Backup destination saved'\n"
                        "text 'Vault Alpha'"
                    ),
                    "action": None,
                    "screenshot": relative(paths["target_confirmation"]),
                    "step": 11,
                    "thought": "Verify the backup confirmation for Vault Alpha",
                    "url": "https://synthetic.invalid/settings/backup/confirmation",
                },
            ],
        ),
        _trajectory(
            trajectory_id="trajectory-calendar",
            environment="synthetic-calendar",
            goal="Review the team calendar for next week",
            state_specs=[
                {
                    "accessibility_tree": "heading 'Team calendar'\nbutton 'Next week'",
                    "action": "Click Next week",
                    "screenshot": relative(paths["calendar"]),
                    "step": 3,
                    "thought": "Open the next calendar page",
                    "url": "https://synthetic.invalid/calendar",
                }
            ],
        ),
        _trajectory(
            trajectory_id="trajectory-billing",
            environment="synthetic-billing",
            goal="Download the latest billing invoice",
            state_specs=[
                {
                    "accessibility_tree": "heading 'Invoices'\nlink 'Download PDF'",
                    "action": "Click Download PDF",
                    "screenshot": relative(paths["billing"]),
                    "step": 5,
                    "thought": "Download the most recent invoice",
                    "url": "https://synthetic.invalid/billing/invoices",
                }
            ],
        ),
    ]
    return {
        "asset_root": asset_root,
        "paths": paths,
        "trajectories": trajectories,
    }


def _official_registration_proof(python: Path) -> dict[str, Any]:
    if not python.is_file():
        raise LMEV2AdapterSmokeError("official interface Python is unavailable")
    code = """
import json
import sys
from evals.paper.lme_v2_adapter import MiLAiLMEV2Memory, register_with_official_harness
identity = register_with_official_harness()
from memory_modules.memory import MEMORY_TYPES
assert MEMORY_TYPES.get('milai') is MiLAiLMEV2Memory
print(json.dumps({'commit': identity['commit'], 'paper_data_opened': identity['paper_data_opened'], 'python_executable': sys.executable, 'python_prefix': sys.prefix, 'question_rows_read': identity['question_rows_read'], 'registered_type': 'milai'}, sort_keys=True))
""".strip()
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [str(python), "-c", code],
        cwd=Path("/cra/memory/mx_memory/benchmarks/LongMemEval-V2"),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise LMEV2AdapterSmokeError(
            "official Memory registration failed: " + completed.stderr[-1000:]
        )
    try:
        value = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise LMEV2AdapterSmokeError(
            "official registration receipt is invalid"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("registered_type") != "milai"
        or value.get("paper_data_opened") is not False
        or value.get("question_rows_read") != 0
    ):
        raise LMEV2AdapterSmokeError("official registration contract drifted")
    expected_prefix = str(python.absolute().parent.parent)
    if Path(str(value.get("python_prefix"))).absolute() != Path(expected_prefix):
        raise LMEV2AdapterSmokeError("official registration used the wrong environment")
    value["python_invocation"] = str(python.absolute())
    return value


def run(output: Path, official_python: Path) -> dict[str, Any]:
    if output.exists():
        raise LMEV2AdapterSmokeError("PE06 adapter smoke result is write-once")
    if not MODALITY_ARTIFACT.is_file():
        raise LMEV2AdapterSmokeError("LME-V2 modality feasibility is absent")
    if not SUPERSEDED_FAILURE.is_file():
        raise LMEV2AdapterSmokeError("superseded PE06 failure disclosure is absent")
    modality = json.loads(MODALITY_ARTIFACT.read_text(encoding="utf-8"))
    if not isinstance(modality, dict) or modality.get("status") != (
        "PASS_ADAPTER_IMPLEMENTATION_PENDING"
    ):
        raise LMEV2AdapterSmokeError("LME-V2 modality feasibility drifted")

    candidate_before = {
        "candidate_manifest_sha256": sha256_file(CANDIDATE_MANIFEST),
        "candidate_inventory_sha256": sha256_file(CANDIDATE_INVENTORY),
    }
    official = official_contract_identity()
    registration = _official_registration_proof(official_python)
    synthetic = _create_synthetic_inputs(output)
    memory = MiLAiLMEV2Memory(
        {
            "candidate_id": EXPECTED_CANDIDATE_ID,
            "env_file": str(ROOT / "runtime/.env"),
            "max_case_attempts": 2,
            "max_retrieved_screenshots": 3,
            "mcp_wheel": str(
                ROOT
                / "var/dg11/freeze/candidate/packages/milai_mcp-0.1.0-py3-none-any.whl"
            ),
            "method_id": "DG11-FULL",
            "recall_limit": 3,
            "runtime_wheel": str(
                ROOT
                / "var/dg11/freeze/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl"
            ),
            "trajectories_root_dir": str(synthetic["asset_root"]),
        }
    )
    for trajectory in synthetic["trajectories"]:
        memory.insert(trajectory)
    query = "What is shown in the backup confirmation for Vault Alpha?"
    memory.set_query_context(query_invocation_id="pe06-synthetic-query-001")
    context_items = memory.query(
        query,
        query_image=str(synthetic["paths"]["question"]),
    )
    metadata = memory.post_query_hook(
        query=query,
        query_image=str(synthetic["paths"]["question"]),
        memory_context=context_items,
    )
    memory.clear_query_context()
    if metadata is None:
        raise LMEV2AdapterSmokeError("MiLAi adapter metadata is absent")
    retrieved_screenshots = metadata.get("retrieved_screenshots")
    retrieved_trajectory_ids = metadata.get("retrieved_trajectory_ids")
    expected_target = synthetic["paths"]["target_confirmation"].resolve()
    if (
        not isinstance(retrieved_trajectory_ids, list)
        or "trajectory-target" not in retrieved_trajectory_ids
        or not isinstance(retrieved_screenshots, list)
        or not any(
            isinstance(item, dict)
            and Path(str(item.get("path"))).resolve() == expected_target
            and item.get("state_index") == 1
            for item in retrieved_screenshots
        )
    ):
        raise LMEV2AdapterSmokeError(
            "MiLAi did not return the exact target confirmation screenshot"
        )
    lossiness = metadata.get("modality_lossiness")
    if lossiness != {
        "question_image_passed_to_memory_query": True,
        "question_image_used_for_visual_retrieval": False,
        "reader_receives_question_image_independently": True,
        "retrieved_screenshot_pixels_preserved": True,
        "visual_only_retrieval_supported": False,
    }:
        raise LMEV2AdapterSmokeError("adapter modality disclosure drifted")
    query_image = metadata.get("query_image")
    if not isinstance(query_image, dict) or query_image.get("sha256") != sha256_file(
        synthetic["paths"]["question"]
    ):
        raise LMEV2AdapterSmokeError("question image identity was not preserved")
    candidate_after = {
        "candidate_manifest_sha256": sha256_file(CANDIDATE_MANIFEST),
        "candidate_inventory_sha256": sha256_file(CANDIDATE_INVENTORY),
    }
    if candidate_before != candidate_after:
        raise LMEV2AdapterSmokeError("frozen candidate changed during PE06 smoke")

    assets = [
        {
            "bytes": path.stat().st_size,
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
        }
        for path in synthetic["paths"].values()
    ]
    payload = {
        "adapter": {
            "memory_type": "milai",
            "source": "evals/paper/lme_v2_adapter.py",
            "source_sha256": sha256_file(ROOT / "evals/paper/lme_v2_adapter.py"),
            "wrapper": "evals/paper/runners/lme_v2.py",
            "wrapper_sha256": sha256_file(ROOT / "evals/paper/runners/lme_v2.py"),
        },
        "candidate_after": candidate_after,
        "candidate_before": candidate_before,
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "context_identity": memory_context_identity(context_items),
        "labels_accessed": False,
        "modality_feasibility": {
            "path": str(MODALITY_ARTIFACT.relative_to(ROOT)),
            "sha256": sha256_file(MODALITY_ARTIFACT),
            "status": modality["status"],
        },
        "official_contract": official,
        "official_registration": registration,
        "paper_question_rows_read": 0,
        "query_metadata": metadata,
        "schema": "milai.dg11.pe06-milai-adapter-smoke.v1",
        "status": "PASS",
        "synthetic_assets": assets,
        "synthetic_contract": {
            "expected_screenshot_sha256": sha256_file(expected_target),
            "expected_state_index": 1,
            "expected_trajectory_id": "trajectory-target",
            "query": query,
            "trajectory_count": len(synthetic["trajectories"]),
        },
        "superseded_smoke": {
            "path": str(SUPERSEDED_FAILURE.relative_to(ROOT)),
            "result_use": "EXCLUDED_DEVELOPMENT_SMOKE",
            "sha256": sha256_file(SUPERSEDED_FAILURE),
        },
        "test_data_only": True,
    }
    _atomic_json_once(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--official-python", type=Path, default=DEFAULT_OFFICIAL_PYTHON)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.official_python.absolute())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "schema": result["schema"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
