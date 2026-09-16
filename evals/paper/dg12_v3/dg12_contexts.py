"""DG12-BATCH LongMemEval context producer bound to the frozen product wheels."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from evals.paper.contracts import (
    ContextRecord,
    read_context_archive,
    write_context_archive,
)
from evals.paper.datasets.longmemeval import load_inputs
from evals.paper.parallelism import STATEFUL_CONTEXT_PROCESS_LANE

from .freeze import (
    ANSWER_TOKENIZER_SHA256,
    require_formal_holdout_authorized,
    require_paper_v3_ready,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[3]
PRODUCT_MANIFEST_SHA256 = (
    "cdf3d942aadeaa8e57743bf2691758303852c5f5047244a0acfe638f811bd16a"
)
RUNTIME_WHEEL_SHA256 = (
    "bb79f03de0f51833b592234addd002defced202d74df33e8c8c8851ee57271db"
)
MCP_WHEEL_SHA256 = "9f83b7186951fe07f49eee21e82f4d76ca7faccd703c5502af641bebc3779dca"
PRODUCT_ADAPTER_SHA256 = (
    "b69a65280cdeeb6c9ece91cf96c759632961b4e1506755e818090da2d8c04fa9"
)
MCP_HOST_SHA256 = "eca20a37abdea47b9205be8a40dd365cfe1bb97b630536d2ca09c23cac588588"


class DG12ContextError(RuntimeError):
    pass


def _select_shard(cases: tuple[Any, ...], *, index: int, count: int) -> tuple[Any, ...]:
    STATEFUL_CONTEXT_PROCESS_LANE.validate(count)
    if not 0 <= index < count:
        raise DG12ContextError("DG12 context shard index is outside the shard count")
    return tuple(case for ordinal, case in enumerate(cases) if ordinal % count == index)


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG12ContextError(f"invalid identity object: {path}") from exc
    if not isinstance(value, dict):
        raise DG12ContextError(f"expected identity object: {path}")
    return value


def _verify_product_environment(
    *,
    product_manifest: Path,
    clean_install: Path,
    runtime_wheel: Path,
    mcp_wheel: Path,
    env_file: Path,
) -> dict[str, Any]:
    if sha256_file(product_manifest) != (
        "05cd221b706ea88f6773536c087305d7f50f2aa051ca9c91fa638e65717cf5e8"
    ):
        raise DG12ContextError("product package manifest drifted")
    product = _object(product_manifest)
    install = _object(clean_install)
    if (
        product.get("schema") != "milai.dg12.product-package-manifest.v2"
        or product.get("status") != "FROZEN"
        or product.get("manifest_identity", {}).get("sha256") != PRODUCT_MANIFEST_SHA256
        or install.get("schema") != "milai.dg12.eh04-clean-install.v1"
        or install.get("status") != "PASS"
        or install.get("product_manifest_sha256") != PRODUCT_MANIFEST_SHA256
        or Path(str(install.get("python"))).absolute().parents[1]
        != Path(sys.prefix).absolute()
        or install.get("repository_working_directory_used_for_install") is not False
        or sha256_file(runtime_wheel) != RUNTIME_WHEEL_SHA256
        or sha256_file(mcp_wheel) != MCP_WHEEL_SHA256
        or sha256_file(env_file) != product.get("runtime_environment", {}).get("sha256")
        or sha256_file(ROOT / "evals/benchmark/lme_product_smoke.py")
        != PRODUCT_ADAPTER_SHA256
        or sha256_file(ROOT / "evals/agent_integration/mcp_host.py") != MCP_HOST_SHA256
    ):
        raise DG12ContextError("DG12 frozen product environment drifted")
    return {
        "clean_install_sha256": sha256_file(clean_install),
        "env_sha256": sha256_file(env_file),
        "mcp_wheel_sha256": MCP_WHEEL_SHA256,
        "product_manifest_sha256": PRODUCT_MANIFEST_SHA256,
        "runtime_wheel_sha256": RUNTIME_WHEEL_SHA256,
    }


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    tokenizer_path: Path,
    env_file: Path,
    product_manifest: Path,
    clean_install: Path,
    runtime_wheel: Path,
    mcp_wheel: Path,
    freeze_manifest: Path,
    shard_index: int = 0,
    shard_count: int = 1,
    execution_authorization: Path | None = None,
) -> dict[str, Any]:
    """Execute each case once; every failure becomes a retained context terminal."""

    freeze = require_paper_v3_ready(freeze_manifest)
    require_formal_holdout_authorized(
        input_path=input_path,
        manifest_path=freeze_manifest,
        authorization_path=execution_authorization,
    )
    STATEFUL_CONTEXT_PROCESS_LANE.validate(
        shard_count,
        frozen_ceiling=int(freeze["execution"]["stateful_context_processes_max"]),
    )
    environment = _verify_product_environment(
        product_manifest=product_manifest,
        clean_install=clean_install,
        runtime_wheel=runtime_wheel,
        mcp_wheel=mcp_wheel,
        env_file=env_file,
    )
    if sha256_file(tokenizer_path) != ANSWER_TOKENIZER_SHA256:
        raise DG12ContextError("answer tokenizer drifted from the freeze")
    # These imports must resolve from the isolated product environment. They are
    # deliberately delayed so no-label planning does not import product internals.
    import milai
    from milai.config import load_settings
    from tokenizers import Tokenizer

    from evals.paper.runners import milai_contexts as legacy

    runtime_origin = Path(str(milai.__file__)).resolve()
    if not runtime_origin.is_relative_to(Path(sys.prefix).resolve()):
        raise DG12ContextError(
            "DG12 worker imported Runtime outside the frozen environment"
        )
    product_backend = legacy._legacy_product_module()
    product_backend._load_environment_file(env_file.resolve())
    settings = load_settings()
    if int(settings.embedding_batch_size) != 32:
        raise DG12ContextError("DG12 embedding batch size drifted from 32")
    partition, all_cases = load_inputs(input_path)
    cases = _select_shard(all_cases, index=shard_index, count=shard_count)
    expected_ids = {case.source_id for case in cases}
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    identity = {
        **environment,
        "input_sha256": sha256_file(input_path),
        "method_id": "DG12-BATCH",
        "paper_worker_sha256": sha256_file(Path(__file__)),
        "product_adapter_sha256": PRODUCT_ADAPTER_SHA256,
        "mcp_host_sha256": MCP_HOST_SHA256,
        "run_id": run_id,
        "runtime_origin": str(runtime_origin),
        "embedding_batch_size": 32,
        "formal_attempts_per_method_case": 1,
        "process_shard_count": shard_count,
        "process_shard_index": shard_index,
    }
    if output.exists():
        existing = _object(output)
        records = read_context_archive(output)
        if (
            existing.get("worker_identity") != identity
            or {record.case_id for record in records} != expected_ids
            or len(records) != len(expected_ids)
        ):
            raise DG12ContextError("completed DG12 context archive drifted")
        return existing
    checkpoint = output.with_suffix(output.suffix + ".partial")
    completed: dict[str, ContextRecord] = {}
    if checkpoint.exists():
        partial = _object(checkpoint)
        if partial.get("worker_identity") != identity:
            raise DG12ContextError("DG12 context checkpoint identity drifted")
        completed = {
            record.case_id: record for record in read_context_archive(checkpoint)
        }
        if len(completed) != int(partial.get("record_count", -1)) or not set(
            completed
        ).issubset(expected_ids):
            raise DG12ContextError("DG12 context checkpoint denominator drifted")
    for case in cases:
        if case.source_id in completed:
            continue
        try:
            product_case = legacy._product_case(case)
            context, raw_trace = legacy._runtime_context_with_embedding_accounting(
                case=product_case, env_file=env_file
            )
            trace = legacy._trace_items(raw_trace)
            embedding = raw_trace.get("paper_embedding_accounting")
            if not isinstance(embedding, dict) or not isinstance(
                embedding.get("total_calls"), int
            ):
                raise DG12ContextError("DG12 embedding accounting is absent")
            record = ContextRecord(
                case_id=case.source_id,
                method_id="DG12-BATCH",
                track="CONTROLLED_MECHANISM_AND_EQUIVALENCE",
                context=context.rendered,
                source_ids=tuple(str(item["source_id"]) for item in trace),
                trace=trace,
                declared_tokens=len(tokenizer.encode(context.rendered).ids),
                latency_ms=float(raw_trace.get("retrieval_ms", 0.0)),
                usage={
                    "adapter_storage_bytes": sum(
                        len(turn.content.encode())
                        for session in case.sessions
                        for turn in session.turns
                    ),
                    "embedding_batch_size": 32,
                    "embedding_calls": int(embedding["total_calls"]),
                    "memory_query_model_calls": 0,
                    "hidden_model_calls": 0,
                    "retriever_calls": 1,
                    "reranker_calls": int(
                        any(
                            isinstance(item, dict)
                            and isinstance(item.get("reranker"), dict)
                            for item in raw_trace.get("retrieved_items", [])
                        )
                    ),
                    "attempts": 1,
                },
            )
        except Exception as exc:  # noqa: BLE001 - terminal retained by protocol
            record = ContextRecord(
                case_id=case.source_id,
                method_id="DG12-BATCH",
                track="CONTROLLED_MECHANISM_AND_EQUIVALENCE",
                context="",
                source_ids=(),
                trace=(),
                declared_tokens=0,
                latency_ms=0.0,
                usage={
                    "attempts": 1,
                    "failure_class": type(exc).__name__,
                    "failure_message_sha256": hashlib.sha256(
                        str(exc).encode()
                    ).hexdigest(),
                },
                terminal_status="INFRASTRUCTURE_FAILURE",
            )
        completed[case.source_id] = record
        write_context_archive(
            checkpoint,
            run_id=run_id,
            benchmark_id=partition,
            records=tuple(
                completed[item.source_id]
                for item in cases
                if item.source_id in completed
            ),
            metadata={
                "paper_labels_opened": False,
                "worker_identity": identity,
            },
        )
    records = tuple(completed[case.source_id] for case in cases)
    failures = sum(record.terminal_status != "SUCCEEDED" for record in records)
    payload = write_context_archive(
        output,
        run_id=run_id,
        benchmark_id=partition,
        records=records,
        metadata={
            "failure_count": failures,
            "labels_accessed": False,
            "paper_labels_opened": False,
            "status": "PASS" if failures == 0 else "COMPLETE_WITH_RETAINED_FAILURES",
            "process_shard_count": shard_count,
            "process_shard_index": shard_index,
            "worker_count": 1,
            "worker_identity": identity,
        },
    )
    checkpoint.unlink(missing_ok=True)
    return payload
