"""Run the label-free DG11-PE03 feasibility contract against Hindsight OSS."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from hindsight_client import Hindsight


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json", by_alias=True))
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object from {url}")
    return value


async def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    health_before = _get_json(f"{args.base_url.rstrip('/')}/health")
    model_listing = _get_json(f"{args.vllm_base_url.rstrip('/')}/models")
    advertised_models = [str(item.get("id")) for item in model_listing.get("data", [])]
    client = Hindsight(base_url=args.base_url, timeout=180)
    bank_id = "dg11-pe03-hindsight"

    retain_started = time.perf_counter()
    retain_one = await client.aretain(
        bank_id=bank_id,
        content="The blue kayak is stored in the garage.",
        timestamp=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        context="chronological feasibility event one",
        document_id="kayak-event",
        metadata={"sequence": "1"},
        retain_async=False,
    )
    retain_two = await client.aretain(
        bank_id=bank_id,
        content="The red bicycle was moved into the attic.",
        timestamp=datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc),
        context="chronological feasibility event two",
        document_id="bicycle-event",
        metadata={"sequence": "2"},
        retain_async=False,
    )
    retain_latency_ms = (time.perf_counter() - retain_started) * 1000
    recall_before = await client.arecall(
        bank_id=bank_id,
        query="Where is the blue kayak stored?",
        max_tokens=512,
        budget="low",
        include_chunks=True,
    )
    delete_document = await client.documents.delete_document(
        bank_id,
        "kayak-event",
        _request_timeout=180,
    )
    recall_after = await client.arecall(
        bank_id=bank_id,
        query="Where is the blue kayak stored?",
        max_tokens=512,
        budget="low",
        include_chunks=True,
    )
    delete_bank = await client.adelete_bank(bank_id)
    await client.aclose()
    health_after = _get_json(f"{args.base_url.rstrip('/')}/health")

    retain_one_value = _jsonable(retain_one)
    retain_two_value = _jsonable(retain_two)
    recall_before_value = _jsonable(recall_before)
    recall_after_value = _jsonable(recall_after)
    delete_document_value = _jsonable(delete_document)
    delete_bank_value = _jsonable(delete_bank)
    before_text = json.dumps(recall_before_value, ensure_ascii=False).lower()
    after_text = json.dumps(recall_after_value, ensure_ascii=False).lower()
    usages = [retain_one_value.get("usage") or {}, retain_two_value.get("usage") or {}]
    usage_totals = {
        key: sum(int(item.get(key, 0) or 0) for item in usages)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    gates = {
        "chronological_ingest_two_events": bool(retain_one_value.get("success"))
        and bool(retain_two_value.get("success")),
        "cleanup_product_delete_bank": bool(delete_bank_value),
        "delete_document_product_api": bool(delete_document_value),
        "deleted_kayak_absent_after": "blue kayak" not in after_text,
        "fresh_isolated_server_healthy": health_before.get("status") == "healthy"
        and health_after.get("status") == "healthy",
        "local_vllm_advertised_frozen_model": args.model in advertised_models,
        "local_vllm_native_usage_captured": usage_totals["total_tokens"] > 0,
        "query_found_kayak": "blue kayak" in before_text,
    }
    payload: dict[str, Any] = {
        "adapter_mode": "official-python-client",
        "capabilities": {
            "chronological_order": "NATIVE_TIMESTAMP",
            "delete_bank": "SUPPORTED_PRODUCT_API",
            "delete_document": "SUPPORTED_PRODUCT_API",
        },
        "config": {
            "api_base_url": args.base_url,
            "embedding_model": "bge-m3",
            "llm_model": args.model,
            "reranker": "rrf",
            "vllm_base_url": args.vllm_base_url,
        },
        "development_ai_reviews": 0,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "gates": gates,
        "health_after": health_after,
        "health_before": health_before,
        "operations": {
            "delete_bank": delete_bank_value,
            "delete_document": delete_document_value,
            "recall_after": recall_after_value,
            "recall_before": recall_before_value,
            "retain_one": retain_one_value,
            "retain_two": retain_two_value,
        },
        "paper_labels_opened": False,
        "provider": {
            "retain_latency_ms": round(retain_latency_ms, 3),
            "usage_totals": usage_totals,
        },
        "schema": "milai.dg11.pe03.hindsight-feasibility.v1",
        "started_at": started_at.isoformat(),
        "status": "PASS" if all(gates.values()) else "FAIL",
        "system_id": "HINDSIGHT-OSS",
        "work_package": "DG11-PE03",
    }
    _atomic_json(args.output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:28888")
    parser.add_argument("--model", default="Qwen3.6-35B-A3B-FP8")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:7860/v1")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(
        json.dumps(
            {"status": result["status"], "system_id": result["system_id"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
