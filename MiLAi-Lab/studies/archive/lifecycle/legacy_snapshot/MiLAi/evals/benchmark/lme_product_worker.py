from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Any

import milai
import milai_client
import milai_mcp
import milai_openworker_mcp

from evals.benchmark import lme_product_smoke


class InstalledProductWorkerError(RuntimeError):
    pass


def _module_origin(module: Any) -> str:
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str) or not raw:
        raise InstalledProductWorkerError("installed product module origin is absent")
    origin = Path(raw).resolve()
    prefix = Path(sys.prefix).resolve()
    if not origin.is_relative_to(prefix):
        raise InstalledProductWorkerError(
            f"product module imported outside installed environment: {origin}"
        )
    return str(origin)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run LongMemEval through a fresh-installed MiLAi product"
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--dataset-path", type=Path, required=True)
    parser.add_argument("--provider-manifest", type=Path, required=True)
    parser.add_argument("--provider-ledger", type=Path, required=True)
    parser.add_argument("--provider-endpoint", required=True)
    parser.add_argument("--source-ids-json", required=True)
    parser.add_argument(
        "--phase",
        choices=lme_product_smoke.BENCHMARK_PHASES,
        required=True,
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    args = parser.parse_args()

    raw_source_ids = json.loads(args.source_ids_json)
    if not isinstance(raw_source_ids, list) or not all(
        isinstance(value, str) and value for value in raw_source_ids
    ):
        raise InstalledProductWorkerError("source IDs are invalid")
    origins = {
        "runtime": _module_origin(milai),
        "client": _module_origin(milai_client),
        "mcp": _module_origin(milai_mcp),
        "openworker": _module_origin(milai_openworker_mcp),
    }
    report, sidecar = lme_product_smoke.run(
        env_file=args.env_file.resolve(),
        dataset_path=args.dataset_path.resolve(),
        provider_manifest=args.provider_manifest.resolve(),
        provider_ledger=args.provider_ledger.resolve(),
        provider_endpoint=args.provider_endpoint,
        source_ids=tuple(raw_source_ids),
        phase=args.phase,
    )
    report["installed_product"] = {
        "python": str(Path(sys.executable).resolve()),
        "prefix": str(Path(sys.prefix).resolve()),
        "module_origins": origins,
        "embedding_dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "onnxruntime", "tokenizers")
        },
    }
    _write_json(args.report.resolve(), report)
    _write_json(args.sidecar.resolve(), sidecar)


if __name__ == "__main__":
    main()
