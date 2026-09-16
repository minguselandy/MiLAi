"""One-way verifier for the DG-12 protocol-v3 successor freeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
LME_METHODS = (
    "CTRL-NONE",
    "CTRL-FULL",
    "CTRL-TRUNC-FULL",
    "CTRL-CUSTOM-LEX1",
    "LME-BM25-S",
    "LME-BM25-T",
    "LME-DENSE",
    "DG10-FROZEN",
    "DG11-FULL",
    "DG12-BATCH",
    "LME-ORACLE",
)
LABEL_DATASET_SHA256 = (
    "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
)
ANSWER_TOKENIZER_SHA256 = (
    "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
)
FORMAL_HOLDOUT_SHA256 = (
    "d419086ea2c7d4aec65ec0bd0bb2a6e482a0d735be2c48cc8ef50721f21242f9"
)


class FreezeError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_paper_v3_ready(
    manifest_path: Path, *, workspace_root: Path = ROOT
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"invalid DG12 v3 freeze manifest: {manifest_path}") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "milai.dg12.paper-freeze-manifest.v3"
        or manifest.get("status") != "PAPER_PROTOCOL_V3_FROZEN"
        or manifest.get("paper_labels_opened_at_freeze") is not False
        or manifest.get("formal_scores_opened_at_freeze") is not False
        or manifest.get("formal_method_outputs_generated_at_freeze") is not False
        or manifest.get("candidate_modified") is not False
        or manifest.get("training_performed") is not False
    ):
        raise FreezeError("DG12 v3 freeze guards are not satisfied")
    identities = manifest.get("frozen_files")
    if not isinstance(identities, list) or not identities:
        raise FreezeError("DG12 v3 frozen file inventory is absent")
    seen: set[str] = set()
    root = workspace_root.resolve()
    for item in identities:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not isinstance(item["path"], str)
            or not isinstance(item["sha256"], str)
            or item["path"] in seen
        ):
            raise FreezeError("DG12 v3 frozen file identity is invalid")
        seen.add(item["path"])
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise FreezeError(f"DG12 v3 frozen file is absent: {item['path']}")
        if sha256_file(path) != item["sha256"]:
            raise FreezeError(f"DG12 v3 frozen file drifted: {item['path']}")
    execution = manifest.get("execution")
    annotation = manifest.get("annotation")
    if (
        not isinstance(execution, dict)
        or execution.get("longmemeval_formal_matrix") != "LME_CONTROLLED"
        or execution.get("longmemeval_method_count") != 11
        or execution.get("longmemeval_methods") != list(LME_METHODS)
        or execution.get("label_dataset_sha256") != LABEL_DATASET_SHA256
        or execution.get("answer_tokenizer_sha256") != ANSWER_TOKENIZER_SHA256
        or execution.get("schedule_namespace") != "milai-dg12-paper-v2"
        or execution.get("retain_all_method_case_terminals") is not True
        or execution.get("answer_workers_max") != 8
        or execution.get("judge_workers_max") != 8
        or execution.get("prompt_build_workers_max") != 8
        or execution.get("stateless_context_workers_max") != 8
        or execution.get("stateful_context_processes_max") != 4
        or execution.get("stateful_context_workers_per_process") != 1
        or execution.get("dense_context_processes_max") != 2
        or execution.get("parallelism_fixed_before_labels") is not True
        or execution.get("method_specific_dynamic_concurrency") is not False
        or not isinstance(annotation, dict)
        or annotation.get("annotator_count") != 2
        or annotation.get("method_outputs_visible") is not False
        or annotation.get("formal_labels_visible") is not False
    ):
        raise FreezeError("DG12 v3 execution or annotation contract drifted")
    return manifest


def require_formal_execution_ready(
    manifest_path: Path,
    authorization_path: Path | None,
    *,
    workspace_root: Path = ROOT,
) -> dict[str, Any]:
    """Require separately sealed PASS receipts from both no-label gates."""

    require_paper_v3_ready(manifest_path, workspace_root=workspace_root)
    if authorization_path is None:
        raise FreezeError("formal execution authorization is absent")
    try:
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError("formal execution authorization is invalid") from exc
    gates = (
        authorization.get("gate_terminals") if isinstance(authorization, dict) else None
    )
    if (
        not isinstance(authorization, dict)
        or authorization.get("schema") != "milai.dg12.formal-execution-authorization.v3"
        or authorization.get("status") != "PE01_PE02_NO_LABEL_GATES_PASS"
        or authorization.get("paper_labels_opened_at_authorization") is not False
        or authorization.get("formal_method_outputs_generated_at_authorization")
        is not False
        or authorization.get("freeze_manifest_sha256") != sha256_file(manifest_path)
        or not isinstance(gates, list)
        or [item.get("gate") for item in gates if isinstance(item, dict)]
        != ["DG12-PE01V3", "DG12-PE02V3"]
    ):
        raise FreezeError("formal execution authorization guards are not satisfied")
    root = workspace_root.resolve()
    for item in gates:
        if not isinstance(item, dict) or set(item) != {"gate", "path", "sha256"}:
            raise FreezeError("formal gate terminal identity is invalid")
        path = (root / str(item["path"])).resolve()
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or sha256_file(path) != item["sha256"]
        ):
            raise FreezeError(f"formal gate terminal drifted: {item['gate']}")
    return authorization


def require_formal_holdout_authorized(
    *,
    input_path: Path,
    manifest_path: Path,
    authorization_path: Path | None,
) -> None:
    if sha256_file(input_path) == FORMAL_HOLDOUT_SHA256:
        require_formal_execution_ready(manifest_path, authorization_path)
