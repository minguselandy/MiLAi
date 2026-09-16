#!/usr/bin/env python3
"""Run DG-16 Q5 against the existing bge-m3 and bge-reranker services."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import DEFAULT_TOKENIZER, _atomic_json, _local_token_counter
from evals.dg14.provider import MatchedVllmProvider, full_provider_contract
from evals.dg16.q5 import VllmDenseClient, VllmRerankerClient, run_q5_ablation
from evals.paper.provider import MODEL_ID

DENSE_MODEL_PATH = Path("/data/models/embed")
RERANK_MODEL_PATH = Path("/data/models/bge-reranker-v2-m3")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _process_identity(port: int) -> dict[str, Any]:
    marker = str(port)
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            arguments = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        except (OSError, UnicodeDecodeError):
            continue
        if marker in arguments and "vllm" in arguments:
            return {"pid": int(entry.name), "command": arguments.strip()}
    return {"pid": None, "command": "UNAVAILABLE"}


def _gpu_identity() -> dict[str, Any]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,memory.total,driver_version",
            "--format=csv,noheader",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "UNSET"),
        "devices": completed.stdout.strip().splitlines(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument("--dense-url", default="http://127.0.0.1:7861")
    parser.add_argument("--reranker-url", default="http://127.0.0.1:7961")
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    args = parser.parse_args()

    dense_identity = {
        "model_id": "BAAI/bge-m3",
        "served_model_name": "bge-m3",
        "revision": "LOCAL_REVISION_UNAVAILABLE",
        "artifact_sha256": _sha256(DENSE_MODEL_PATH / "pytorch_model.bin"),
        "config_sha256": _sha256(DENSE_MODEL_PATH / "config.json"),
        "dimensions": 1_024,
        "max_model_len": 8_192,
        "projection_version": "dg16-q5-chunk-bge-m3-dense-v1",
        "endpoint": args.dense_url,
        "process": _process_identity(7861),
    }
    reranker_identity = {
        "model_id": "BAAI/bge-reranker-v2-m3",
        "served_model_name": "bge-reranker",
        "revision": "LOCAL_REVISION_UNAVAILABLE",
        "artifact_sha256": _sha256(RERANK_MODEL_PATH / "model.safetensors"),
        "config_sha256": _sha256(RERANK_MODEL_PATH / "config.json"),
        "max_model_len": 8_192,
        "projection_version": "QUERY_TIME_ONLY_NOT_PERSISTED",
        "endpoint": args.reranker_url,
        "process": _process_identity(7961),
    }
    dense = VllmDenseClient(
        args.dense_url,
        model_id="bge-m3",
        artifact_identity=dense_identity,
    )
    reranker = VllmRerankerClient(
        args.reranker_url,
        model_id="bge-reranker",
        artifact_identity=reranker_identity,
    )
    provider = MatchedVllmProvider(args.reader_url)
    receipt = run_q5_ablation(
        run_id=args.run_id,
        dense=dense,
        reranker=reranker,
        provider=provider,
        token_count=_local_token_counter(args.tokenizer),
        execution_identity={
            "hostname": platform.node(),
            "gpu": _gpu_identity(),
            "reader": {
                "model_id": MODEL_ID,
                "endpoint": args.reader_url,
                "process": _process_identity(7860),
                "provider_contract": full_provider_contract(),
            },
            "automatic_retries": 0,
        },
    )
    output_dir = ROOT / "var/dg16/q5" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / "receipt.json"
    _atomic_json(output_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "run_id": args.run_id,
                "receipt": str(output_path.relative_to(ROOT)),
                "receipt_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
                "decision": receipt["decision"],
                "summaries": receipt["summaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
