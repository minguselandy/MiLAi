"""Run the label-free DG11-PE03 feasibility contract against Mem0 OSS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from mem0 import Memory


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _models(base_url: str) -> dict[str, Any]:
    with urlopen(f"{base_url.rstrip('/')}/models", timeout=10) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise TypeError("vLLM models response must be an object")
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise FileExistsError(f"fresh workspace already exists: {workspace}")
    workspace.mkdir(parents=True)
    model_listing = _models(args.vllm_base_url)
    advertised_models = [str(item.get("id")) for item in model_listing.get("data", [])]
    if args.model not in advertised_models:
        raise ValueError(f"frozen model not advertised by local vLLM: {args.model}")

    config: dict[str, Any] = {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "dg11_pe03_mem0",
                "embedding_model_dims": 384,
                "path": str(workspace / "qdrant"),
            },
        },
        "llm": {
            "provider": "vllm",
            "config": {
                "api_key": "vllm-api-key",
                "max_tokens": 64,
                "model": args.model,
                "temperature": 0,
                "vllm_base_url": args.vllm_base_url,
            },
        },
        "embedder": {
            "provider": "fastembed",
            "config": {
                "embedding_dims": 384,
                "model": args.embedding_model,
            },
        },
        "history_db_path": str(workspace / "history.db"),
    }
    memory = Memory.from_config(config)
    completions: list[dict[str, Any]] = []
    create = memory.llm.client.chat.completions.create

    def tracked_create(*call_args: Any, **call_kwargs: Any) -> Any:
        response = create(*call_args, **call_kwargs)
        usage = response.usage.model_dump() if response.usage is not None else None
        completions.append(
            {
                "completion_id": response.id,
                "finish_reason": response.choices[0].finish_reason,
                "model": response.model,
                "usage": usage,
            }
        )
        return response

    memory.llm.client.chat.completions.create = tracked_create
    provider_started = time.perf_counter()
    connectivity_response = memory.llm.generate_response(
        [{"role": "user", "content": "Reply with exactly PE03_MEM0_OK."}]
    )
    provider_latency_ms = (time.perf_counter() - provider_started) * 1000

    user_id = "dg11-pe03-user"
    add_one = memory.add(
        "On 2026-08-01 I stored my blue kayak in the garage.",
        user_id=user_id,
        metadata={"observed_at": "2026-08-01T09:00:00Z", "sequence": 1},
        infer=False,
    )
    add_two = memory.add(
        "On 2026-08-02 I moved my red bicycle into the attic.",
        user_id=user_id,
        metadata={"observed_at": "2026-08-02T09:00:00Z", "sequence": 2},
        infer=False,
    )
    search_before = memory.search(
        "Where is the blue kayak stored?",
        top_k=2,
        filters={"user_id": user_id},
        threshold=0,
    )
    before_results = search_before.get("results", [])
    if not before_results:
        raise RuntimeError("Mem0 query returned no memories")
    kayak = next(
        (
            item
            for item in before_results
            if "kayak" in str(item.get("memory", "")).lower()
        ),
        None,
    )
    if kayak is None:
        raise RuntimeError("Mem0 query did not return the kayak memory")
    deleted_id = str(kayak["id"])
    delete_result = memory.delete(deleted_id)
    search_after = memory.search(
        "Where is the blue kayak stored?",
        top_k=2,
        filters={"user_id": user_id},
        threshold=0,
    )
    after_results = search_after.get("results", [])
    deleted_absent = all(str(item.get("id")) != deleted_id for item in after_results)
    memory.delete_all(user_id=user_id)
    post_cleanup = memory.get_all(filters={"user_id": user_id})
    memory.close()

    usage_totals = {
        key: sum(int((item.get("usage") or {}).get(key, 0)) for item in completions)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    gates = {
        "chronological_ingest_two_events": len(add_one.get("results", [])) == 1
        and len(add_two.get("results", [])) == 1,
        "cleanup_empty": post_cleanup.get("results", []) == [],
        "deletion_product_api": delete_result.get("message")
        == "Memory deleted successfully!",
        "deleted_memory_absent": deleted_absent,
        "fresh_workspace": True,
        "local_vllm_advertised_frozen_model": args.model in advertised_models,
        "local_vllm_native_usage_captured": len(completions) == 1
        and usage_totals["total_tokens"] > 0,
        "query_found_kayak": kayak is not None,
    }
    finished_at = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "adapter_mode": "official-python-api",
        "capabilities": {
            "chronological_order": "CALL_ORDER_WITH_OBSERVED_AT_METADATA",
            "delete": "SUPPORTED_PRODUCT_API",
            "oss_timestamp_parameter": "UNSUPPORTED_BY_UPSTREAM",
        },
        "config": {
            "embedding_dims": 384,
            "embedding_model": args.embedding_model,
            "llm_model": args.model,
            "vector_store": "qdrant-local",
            "vllm_base_url": args.vllm_base_url,
        },
        "development_ai_reviews": 0,
        "duration_ms": round((finished_at - started_at).total_seconds() * 1000, 3),
        "finished_at": finished_at.isoformat(),
        "gates": gates,
        "operations": {
            "add_one": add_one,
            "add_two": add_two,
            "connectivity_response_sha256": hashlib.sha256(
                connectivity_response.encode()
            ).hexdigest(),
            "delete": delete_result,
            "deleted_id": deleted_id,
            "post_cleanup": post_cleanup,
            "search_after": search_after,
            "search_before": search_before,
        },
        "paper_labels_opened": False,
        "provider": {
            "completions": completions,
            "latency_ms": round(provider_latency_ms, 3),
            "request_count": len(completions),
            "usage_totals": usage_totals,
        },
        "schema": "milai.dg11.pe03.mem0-feasibility.v1",
        "started_at": started_at.isoformat(),
        "status": "PASS" if all(gates.values()) else "FAIL",
        "system_id": "MEM0-OSS",
        "work_package": "DG11-PE03",
    }
    _atomic_json(args.output, payload)
    shutil.rmtree(workspace)
    payload["workspace_removed"] = not workspace.exists()
    _atomic_json(args.output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding-model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--model", default="Qwen3.6-35B-A3B-FP8")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:7860/v1")
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    result = run(args)
    print(
        json.dumps(
            {"status": result["status"], "system_id": result["system_id"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
