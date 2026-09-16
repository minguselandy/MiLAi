from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import milai

from evals.benchmark import dg11_holdout
from evals.benchmark import lme_product_smoke as benchmark

CHECKPOINT_SCHEMA = "milai.dg11.holdout-context-checkpoint.v1"


def _origin(identity: str) -> str:
    origin = Path(str(milai.__file__)).resolve()
    if identity == "frozen" and not origin.is_relative_to(Path(sys.prefix).resolve()):
        raise dg11_holdout.HoldoutError("DG10 worker did not import frozen Runtime")
    if identity == "current" and "runtime/src/milai" not in origin.as_posix():
        raise dg11_holdout.HoldoutError("DG11 worker did not import current Runtime")
    return str(origin)


def _resume_records(
    payload: dict[str, Any],
    *,
    identity: str,
    input_sha256: str,
    expected_source_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    if (
        payload.get("schema") != CHECKPOINT_SCHEMA
        or payload.get("identity") != identity
        or payload.get("input_sha256") != input_sha256
        or not isinstance(payload.get("records"), list)
    ):
        raise dg11_holdout.HoldoutError("context checkpoint identity drifted")
    records: dict[str, dict[str, Any]] = {}
    for record in payload["records"]:
        if not isinstance(record, dict) or not isinstance(record.get("source_id"), str):
            raise dg11_holdout.HoldoutError("context checkpoint record is invalid")
        source_id = str(record["source_id"])
        if source_id not in expected_source_ids or source_id in records:
            raise dg11_holdout.HoldoutError("context checkpoint source IDs drifted")
        records[source_id] = record
    return records


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _context_payload(context: Any) -> dict[str, Any]:
    return {
        "rendered": context.rendered,
        "status": context.status,
        "context_sha256": context.context_sha256,
        "compiler_version": getattr(context, "compiler_version", "DG10_LEGACY"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare label-free DG11 holdout contexts"
    )
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--identity", choices=("frozen", "current"), required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--expected-cases", type=int, default=dg11_holdout.CASE_COUNT)
    parser.add_argument("--recall-limit", type=int, default=3)
    parser.add_argument("--max-case-attempts", type=int, default=2)
    parser.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="Run only these already-opened source IDs, preserving argument order.",
    )
    args = parser.parse_args()
    if not 1 <= args.workers <= 2:
        raise dg11_holdout.HoldoutError("context workers must be 1 or 2")
    if not 1 <= args.expected_cases <= dg11_holdout.CASE_COUNT:
        raise dg11_holdout.HoldoutError("expected cases must be between 1 and 100")
    if not 1 <= args.recall_limit <= 20:
        raise dg11_holdout.HoldoutError("recall limit must be between 1 and 20")
    if not 1 <= args.max_case_attempts <= 3:
        raise dg11_holdout.HoldoutError("max case attempts must be between 1 and 3")
    payload = json.loads(args.inputs.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if (
        payload.get("schema") != "milai.dg11.holdout-inputs.v1"
        or payload.get("label_fields_present") is not False
        or not isinstance(cases, list)
    ):
        raise dg11_holdout.HoldoutError("holdout input package drifted")
    if any(
        not isinstance(raw, dict) or not isinstance(raw.get("source_id"), str)
        for raw in cases
    ):
        raise dg11_holdout.HoldoutError("holdout cases must expose source IDs")
    requested_source_ids = tuple(str(value) for value in args.source_id)
    if len(requested_source_ids) != len(set(requested_source_ids)):
        raise dg11_holdout.HoldoutError("requested source IDs must be unique")
    if requested_source_ids:
        cases_by_id = {str(raw["source_id"]): raw for raw in cases}
        missing = sorted(set(requested_source_ids).difference(cases_by_id))
        if missing:
            raise dg11_holdout.HoldoutError(
                f"requested source IDs are absent from the input package: {missing}"
            )
        cases = [cases_by_id[source_id] for source_id in requested_source_ids]
    if len(cases) != args.expected_cases:
        raise dg11_holdout.HoldoutError("holdout input package denominator drifted")
    source_ids = [str(raw["source_id"]) for raw in cases]
    if len(source_ids) != len(set(source_ids)):
        raise dg11_holdout.HoldoutError("holdout case source IDs must be unique")
    input_sha256 = hashlib.sha256(args.inputs.read_bytes()).hexdigest()
    checkpoint_path = args.output.with_suffix(args.output.suffix + ".partial")
    checkpoint_payload = (
        json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint_path.exists()
        else {}
    )
    resumed = _resume_records(
        checkpoint_payload,
        identity=args.identity,
        input_sha256=input_sha256,
        expected_source_ids=set(source_ids),
    )

    def prepare(index: int, raw: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        case = dg11_holdout.product_case(raw)
        for attempt in range(1, args.max_case_attempts + 1):
            try:
                context, trace = benchmark._runtime_context(
                    case=case,
                    env_file=args.env_file.resolve(),
                    recall_limit=args.recall_limit,
                )
                break
            except benchmark.BenchmarkSmokeError as exc:
                endpoint_unavailable = "MCP recall failed" in str(
                    exc
                ) and "endpoint is unavailable" in str(exc)
                cleanup_failed = "database cleanup failed" in str(exc)
                retryable = endpoint_unavailable or cleanup_failed
                if not retryable or attempt == args.max_case_attempts:
                    raise
                print(
                    json.dumps(
                        {
                            "identity": args.identity,
                            "phase": "context_retry",
                            "source_id": case.source_case_id,
                            "attempt": attempt + 1,
                            "reason": (
                                "MCP_ENDPOINT_UNAVAILABLE"
                                if endpoint_unavailable
                                else "DATABASE_CLEANUP_FAILED"
                            ),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
        return index, {
            "source_id": case.source_case_id,
            "context": _context_payload(context),
            "trace": trace,
        }

    results: list[dict[str, Any] | None] = [
        resumed.get(source_id) for source_id in source_ids
    ]
    with ThreadPoolExecutor(
        max_workers=args.workers, thread_name_prefix=f"dg11-{args.identity}"
    ) as pool:
        futures = {
            pool.submit(prepare, index, raw): index
            for index, raw in enumerate(cases)
            if isinstance(raw, dict) and results[index] is None
        }
        failures: list[Exception] = []
        for future in as_completed(futures):
            try:
                index, record = future.result()
            except Exception as exc:  # noqa: BLE001 - drain all futures before failing
                failures.append(exc)
                continue
            results[index] = record
            completed = sum(value is not None for value in results)
            _atomic_json(
                checkpoint_path,
                {
                    "schema": CHECKPOINT_SCHEMA,
                    "identity": args.identity,
                    "input_sha256": input_sha256,
                    "records": [value for value in results if value is not None],
                },
            )
            print(
                json.dumps(
                    {
                        "identity": args.identity,
                        "completed": completed,
                        "total": len(cases),
                        "workers": args.workers,
                        "source_id": record["source_id"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        if failures:
            raise failures[0]
    if any(record is None for record in results):
        raise dg11_holdout.HoldoutError("context worker lost a case")
    output = {
        "schema": "milai.dg11.holdout-contexts.v1",
        "identity": args.identity,
        "runtime_origin": _origin(args.identity),
        "records": results,
    }
    _atomic_json(args.output, output)
    checkpoint_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
