"""Official LongMemEval-V2 native-memory runner for label-free paper smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from memory_modules.memory import MEMORY_TYPES  # type: ignore[import-not-found]

EMBEDDING_MODEL = "/cra/memory/mx_memory/MiLAi/runtime/var/models/all-MiniLM-L6-v2"
CONTROLLER_MODEL = "Qwen3.6-35B-A3B-FP8"
QUERY = "What is shown in the backup confirmation for Vault Alpha?"


class NativeRunnerError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _controller_params(base_url: str) -> dict[str, object]:
    return {
        "model": CONTROLLER_MODEL,
        "base_url": base_url.rstrip("/") + "/v1",
        "api_key_env": "PAPER_CONTROLLER_KEY",
        "api_key_file": None,
        "max_completion_tokens": 8192,
        "timeout_seconds": 600.0,
        "max_retries": 3,
        "disable_thinking": False,
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
    }


def _embedding_params(base_url: str) -> dict[str, object]:
    return {
        "model": EMBEDDING_MODEL,
        "base_url": base_url.rstrip("/") + "/v1",
        "api_key_env": "PAPER_EMBEDDING_KEY",
        "api_key_file": None,
        "max_input_tokens": 256,
        "query_instruction": (
            "Given a question about past agent trajectories, retrieve relevant "
            "memory entries that help answer it."
        ),
    }


def _config(
    method: str,
    *,
    workspace: Path,
    asset_root: Path,
    embedding_base_url: str,
    controller_base_url: str,
) -> dict[str, Any]:
    common = {
        "trajectory_pool_root": None,
        "workspace_dir": str(workspace),
        "trajectories_root_dir": str(asset_root),
        "controller_params": _controller_params(controller_base_url),
        "embedding_params": _embedding_params(embedding_base_url),
        "index_params": {"raw_state_slice_radius": 1},
    }
    if method == "rag_query_to_slice_notes":
        return {
            **common,
            "retrieval_params": {
                "enable_notes": True,
                "raw_state_search_top_k": 6,
                "note_search_top_k_per_type": 3,
            },
        }
    if method == "agentrunbook_r":
        return {
            **common,
            "query_params": {
                "max_raw_state_queries": 5,
                "query_generation_disable_thinking": False,
            },
            "retrieval_params": {
                "raw_state_search_top_k_per_query": 6,
                "event_search_top_k": 6,
                "note_search_top_k_per_type": 3,
                "raw_state_result_merge_budget": 6,
                "raw_state_result_merge_per_query_cap": 2,
                "rerank_candidate_limit": 8,
                "enable_rerank": False,
            },
        }
    raise NativeRunnerError(f"unsupported method: {method}")


def _item_records(
    items: list[dict[str, str]], target_sha256: str
) -> tuple[list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []
    selected_target = False
    for item in items:
        if item.get("type") == "image":
            path = Path(item["value"]).resolve()
            digest = _sha256(path)
            selected_target = selected_target or digest == target_sha256
            records.append(
                {
                    "bytes": path.stat().st_size,
                    "sha256": digest,
                    "type": "image",
                }
            )
        elif item.get("type") == "text":
            raw = item["value"].encode()
            records.append(
                {
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "type": "text",
                }
            )
        else:
            raise NativeRunnerError("official memory returned an unknown context item")
    return records, selected_target


def run(
    *,
    method: str,
    trajectories_path: Path,
    asset_root: Path,
    question_image: Path,
    target_screenshot: Path,
    embedding_base_url: str,
    controller_base_url: str,
) -> dict[str, Any]:
    trajectories = json.loads(trajectories_path.read_text(encoding="utf-8"))
    if not isinstance(trajectories, list) or len(trajectories) != 3:
        raise NativeRunnerError("synthetic trajectory fixture drifted")
    memory_type = "rag" if method == "rag_query_to_slice_notes" else "agentrunbook_r"
    memory_class = MEMORY_TYPES[memory_type]
    with tempfile.TemporaryDirectory(
        prefix=f"milai-pe06-{method}-workspace-"
    ) as directory:
        memory = memory_class(
            _config(
                method,
                workspace=Path(directory),
                asset_root=asset_root.resolve(),
                embedding_base_url=embedding_base_url,
                controller_base_url=controller_base_url,
            )
        )
        memory.configure_runtime()
        for trajectory in trajectories:
            memory.insert(trajectory)
        items = memory.query(QUERY, query_image=str(question_image.resolve()))
        item_records, selected_target = _item_records(
            items, _sha256(target_screenshot.resolve())
        )
        raw_dimensions = int(memory.raw_state_embeddings.shape[1])
        note_dimensions = int(memory.procedure_note_embeddings.shape[1])
        value: dict[str, Any] = {
            "embedding_dimensions": {
                "procedure_notes": note_dimensions,
                "raw_states": raw_dimensions,
            },
            "entry_counts": {
                "events": len(getattr(memory, "event_entries", [])),
                "hint_notes": len(memory.hint_note_entries),
                "procedure_notes": len(memory.procedure_note_entries),
                "raw_states": len(memory.raw_state_entries),
            },
            "inserted_trajectory_ids": list(memory.inserted_trajectory_ids),
            "item_records": item_records,
            "memory_type": memory_type,
            "method": method,
            "paper_data_opened": False,
            "query_image_passed": True,
            "question_rows_read": 0,
            "selected_target_screenshot": selected_target,
        }
    if (
        value["inserted_trajectory_ids"]
        != ["trajectory-target", "trajectory-calendar", "trajectory-billing"]
        or raw_dimensions != 128
        or note_dimensions != 128
        or value["entry_counts"]["procedure_notes"] != 3
        or value["entry_counts"]["hint_notes"] != 3
        or not item_records
        or not selected_target
    ):
        raise NativeRunnerError(f"official {method} synthetic contract failed")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--method",
        choices=("rag_query_to_slice_notes", "agentrunbook_r"),
        required=True,
    )
    parser.add_argument("--trajectories", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--question-image", type=Path, required=True)
    parser.add_argument("--target-screenshot", type=Path, required=True)
    parser.add_argument("--embedding-base-url", required=True)
    parser.add_argument("--controller-base-url", required=True)
    args = parser.parse_args()
    result = run(
        method=args.method,
        trajectories_path=args.trajectories.resolve(),
        asset_root=args.asset_root.resolve(),
        question_image=args.question_image.resolve(),
        target_screenshot=args.target_screenshot.resolve(),
        embedding_base_url=args.embedding_base_url,
        controller_base_url=args.controller_base_url,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
