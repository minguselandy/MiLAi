"""Freeze the independent local evaluator model without starting inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_ROOT = Path("/cra/qwen38-27B-fp8")
DEFAULT_OUTPUT = ROOT / "var/dg11/paper/freeze/evaluator-identity.json"
MODEL_ID = "Qwen3.5-27B-FP8-INDEPENDENT-EVALUATOR"
PLANNED_ENDPOINT = "http://127.0.0.1:7870/v1"
SUPPORT_FILES = (
    "chat_template.jinja",
    "config.json",
    "configuration.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors.index.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "video_preprocessor_config.json",
    "vocab.json",
)


class EvaluatorIdentityError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluatorIdentityError(f"invalid evaluator JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvaluatorIdentityError(f"expected evaluator JSON object: {path}")
    return value


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise EvaluatorIdentityError("evaluator identity is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _record(path: Path, model_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(model_root):
        raise EvaluatorIdentityError(f"unsafe evaluator model file: {path}")
    return {
        "bytes": resolved.stat().st_size,
        "path": resolved.name,
        "sha256": sha256_file(resolved),
    }


def build_identity(
    *, model_root: Path, output: Path, workers: int = 2
) -> dict[str, Any]:
    model_root = model_root.resolve()
    if workers != 2:
        raise EvaluatorIdentityError(
            "evaluator identity requires exactly two hash workers"
        )
    if not model_root.is_dir():
        raise EvaluatorIdentityError("evaluator model root is absent")
    index = _object(model_root / "model.safetensors.index.json")
    weight_map = index.get("weight_map")
    if not isinstance(weight_map, dict) or not weight_map:
        raise EvaluatorIdentityError("evaluator weight map is absent")
    indexed_shards = sorted(set(weight_map.values()))
    if not all(
        isinstance(name, str) and name.endswith(".safetensors")
        for name in indexed_shards
    ):
        raise EvaluatorIdentityError(
            "evaluator weight map contains invalid shard names"
        )
    actual_shards = sorted(path.name for path in model_root.glob("*.safetensors"))
    if indexed_shards != actual_shards:
        raise EvaluatorIdentityError("evaluator indexed and actual shards differ")
    paths = [model_root / name for name in (*SUPPORT_FILES, *indexed_shards)]
    if len(paths) != len(set(paths)) or any(not path.is_file() for path in paths):
        raise EvaluatorIdentityError("evaluator loaded-file set is incomplete")
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="evaluator-hash"
    ) as pool:
        records = list(pool.map(lambda path: _record(path, model_root), paths))
    records.sort(key=lambda item: str(item["path"]))
    config = _object(model_root / "config.json")
    text_config = config.get("text_config")
    vision_config = config.get("vision_config")
    if (
        config.get("architectures") != ["Qwen3_5ForConditionalGeneration"]
        or config.get("model_type") != "qwen3_5"
        or not isinstance(text_config, dict)
        or text_config.get("max_position_embeddings") != 262144
        or not isinstance(vision_config, dict)
    ):
        raise EvaluatorIdentityError("independent evaluator architecture drifted")
    inventory_root = hashlib.sha256(_canonical(records)).hexdigest()
    payload: dict[str, Any] = {
        "answer_model_id": "Qwen3.6-35B-A3B-FP8",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_ai_reviews": 0,
        "file_count": len(records),
        "files": records,
        "generation_contract": {
            "chat_template_kwargs": {"enable_thinking": False},
            "include_reasoning": False,
            "max_completion_tokens": 512,
            "seed_policy": "SHA256(LOGICAL_JUDGE_REQUEST_ID)_MOD_2^63",
            "temperature": 0,
            "top_p": 1,
        },
        "identity_id": f"evaluator:{inventory_root}",
        "inventory_root_sha256": inventory_root,
        "loaded_file_policy": "INDEXED_SHARDS_PLUS_EXPLICIT_TOKENIZER_AND_CONFIG_FILES",
        "model_config": {
            "architecture": config["architectures"][0],
            "config_sha256": sha256_file(model_root / "config.json"),
            "has_vision_config": True,
            "max_position_embeddings": text_config["max_position_embeddings"],
            "model_type": config["model_type"],
        },
        "model_id": MODEL_ID,
        "model_root": str(model_root),
        "paper_labels_opened": False,
        "planned_endpoint": PLANNED_ENDPOINT,
        "role": "INDEPENDENT_PRIMARY_EVALUATOR_NOT_ANSWER_MODEL",
        "schema": "milai.dg11.paper-evaluator-identity.v1",
        "server_status_at_freeze": "NOT_STARTED_PRE_TEST",
        "shard_count": len(indexed_shards),
        "status": "FROZEN_PRE_TEST",
        "total_bytes": sum(int(record["bytes"]) for record in records),
        "weight_map_entry_count": len(weight_map),
        "workers": workers,
    }
    _atomic_json_once(output, payload)
    return payload


def verify_identity(identity_path: Path, *, workers: int = 2) -> dict[str, Any]:
    if workers != 2:
        raise EvaluatorIdentityError(
            "evaluator identity verification requires exactly two hash workers"
        )
    identity = _object(identity_path.resolve())
    records = identity.get("files")
    model_root = Path(str(identity.get("model_root"))).resolve()
    if (
        identity.get("schema") != "milai.dg11.paper-evaluator-identity.v1"
        or identity.get("status") != "FROZEN_PRE_TEST"
        or identity.get("paper_labels_opened") is not False
        or identity.get("workers") != 2
        or not isinstance(records, list)
        or identity.get("file_count") != len(records)
    ):
        raise EvaluatorIdentityError("evaluator identity envelope drifted")
    names = [
        record.get("path") if isinstance(record, dict) else None for record in records
    ]
    if not all(
        isinstance(name, str) and name == Path(name).name and name not in {".", ".."}
        for name in names
    ) or len(names) != len(set(names)):
        raise EvaluatorIdentityError("evaluator identity file names drifted")
    paths = [model_root / str(name) for name in names]
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="evaluator-verify"
    ) as pool:
        observed = list(pool.map(lambda path: _record(path, model_root), paths))
    observed.sort(key=lambda item: str(item["path"]))
    if observed != records:
        raise EvaluatorIdentityError("evaluator model bytes drifted")
    inventory_root = hashlib.sha256(_canonical(observed)).hexdigest()
    if (
        inventory_root != identity.get("inventory_root_sha256")
        or identity.get("identity_id") != f"evaluator:{inventory_root}"
        or identity.get("total_bytes")
        != sum(int(record["bytes"]) for record in observed)
    ):
        raise EvaluatorIdentityError("evaluator inventory root drifted")
    return {
        "identity_id": identity["identity_id"],
        "identity_sha256": sha256_file(identity_path),
        "schema": "milai.dg11.paper-evaluator-identity-verification.v1",
        "status": "PASS",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, choices=(2,), default=2)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = verify_identity(args.output.resolve(), workers=args.workers)
    else:
        result = build_identity(
            model_root=args.model_root,
            output=args.output.resolve(),
            workers=args.workers,
        )
    print(
        json.dumps(
            {
                "identity_id": result["identity_id"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
