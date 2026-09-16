from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_f0 as state

REGISTRY = ROOT / "scripts/dg10_workflow_status.json"
_LEGACY_IMPORT_TOKENS = (
    "audit",
    "receipt",
    "supersession",
    "post_r3_provider_gate",
)


class WorkflowError(RuntimeError):
    pass


def _imports(source: str) -> set[str]:
    tree = ast.parse(source)
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
            result.update(f"{node.module}.{alias.name}" for alias in node.names)
    return result


def validate(root: Path = ROOT, registry_path: Path = REGISTRY) -> dict[str, Any]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    required = {
        "schema",
        "goal_version",
        "development_ai_audits",
        "provider_authority",
        "active_entrypoints",
        "legacy_frozen_patterns",
        "legacy_execution",
        "final_review",
    }
    if not isinstance(registry, dict) or set(registry) != required:
        raise WorkflowError("workflow registry field set is invalid")
    if (
        registry["schema"] != "milai.dg10.workflow-status.v1"
        or registry["goal_version"] != "0.4.0"
        or registry["development_ai_audits"] != 0
        or registry["provider_authority"] != "DETERMINISTIC_DEV_RUN_CAPABILITY_ONLY"
        or registry["legacy_execution"] != "NOT_CALLED_BY_ACTIVE_DEVELOPMENT"
        or registry["final_review"]
        != {"enabled_before_freeze": False, "maximum_xhigh_calls_after_freeze": 2}
    ):
        raise WorkflowError("workflow registry policy is invalid")
    active = registry["active_entrypoints"]
    patterns = registry["legacy_frozen_patterns"]
    if (
        not isinstance(active, list)
        or not active
        or len(active) != len(set(active))
        or not all(isinstance(value, str) for value in active)
        or not isinstance(patterns, list)
        or not patterns
        or not all(isinstance(value, str) for value in patterns)
    ):
        raise WorkflowError("workflow registry lists are invalid")
    import_evidence: dict[str, list[str]] = {}
    for relative in active:
        path = root / relative
        if not path.is_file() or path.suffix != ".py":
            raise WorkflowError(f"active entrypoint is absent: {relative}")
        imports = sorted(_imports(path.read_text(encoding="utf-8")))
        forbidden = [
            name
            for name in imports
            if name.startswith("scripts.")
            and any(token in name.casefold() for token in _LEGACY_IMPORT_TOKENS)
        ]
        if forbidden:
            raise WorkflowError(f"active entrypoint imports legacy workflow: {relative}")
        import_evidence[relative] = imports
    return {
        "status": "PASS",
        "active_entrypoints": active,
        "active_entrypoint_count": len(active),
        "legacy_frozen_patterns": patterns,
        "legacy_imports": 0,
        "development_ai_audits": 0,
        "provider_authority": registry["provider_authority"],
        "registry_sha256": state._sha256(registry_path),
        "import_evidence_sha256": hashlib.sha256(
            json.dumps(import_evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def run(run_id: str) -> dict[str, Any]:
    if state._RUN_ID.fullmatch(run_id) is None:
        raise WorkflowError("run_id is invalid")
    run_dir = state.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise WorkflowError(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    evidence = validate()
    result = {
        "schema": "milai.dg10.functional-run-result.v1",
        "run_id": run_id,
        "status": "PASS",
        "cases": {"RM00-ACTIVE-WORKFLOW": "PASS"},
        "provider_requests": 0,
        "development_ai_audits": 0,
        "evidence": evidence,
        "finished_at": state._now(),
    }
    state._atomic_write(run_dir / "result.json", result)
    experiment = {
        "experiment_id": f"exp-{run_id}",
        "run_id": run_id,
        "timestamp": result["finished_at"],
        "rm_id": "RM-00",
        "rm_ids": ["RM-00"],
        "hypothesis": (
            "a machine-readable active workflow can freeze legacy audit dependencies while "
            "development remains controlled only by deterministic run capabilities"
        ),
        "code_identity": state._tree_identity([REGISTRY, Path(__file__).resolve()]),
        "model_identity": None,
        "dataset_identity": evidence["registry_sha256"],
        "prompt_identity": None,
        "budget": {"native_requests": 0, "prompt_tokens": 0, "completion_tokens": 0},
        "expected_delta": "zero active legacy imports and zero development AI audits",
        "functional_gate": "WORKFLOW",
        "functional_cases_passed": ["RM00-ACTIVE-WORKFLOW"],
        "functional_cases_failed": [],
        "actual_quality_delta": None,
        "actual_token_delta": 0,
        "actual_latency_delta": None,
        "prepare_context_calls": 0,
        "full_recall_calls": 0,
        "cache_validation_calls": 0,
        "validated_cache_hit_rate": None,
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": 0,
        "status": "PASS",
    }
    state._record_run(result, experiment)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the audit-free DG-10 development workflow")
    parser.add_argument(
        "--run-id",
        default=(
            "rm00-workflow-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    value = validate() if args.check_only else run(args.run_id)
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
