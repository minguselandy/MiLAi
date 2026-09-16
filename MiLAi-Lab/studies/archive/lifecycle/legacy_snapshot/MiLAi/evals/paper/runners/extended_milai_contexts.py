"""Frozen DG11 MiLAi context worker for extended paper benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from tokenizers import Tokenizer

from evals.benchmark import lme_product_smoke as product
from evals.paper.contracts import (
    ContextRecord,
    read_context_archive,
    write_context_archive,
)
from evals.paper.datasets.extended import ExtendedCase, load_extended_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file
from evals.paper.runners import milai_contexts as core

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV = ROOT / "runtime/.env"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
DEFAULT_RUNTIME_WHEEL = (
    ROOT / "var/dg11/freeze/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl"
)
DEFAULT_INSTALL_MANIFEST = (
    ROOT
    / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/"
    "dg11-install-manifest.json"
)


class ExtendedMiLAiError(RuntimeError):
    pass


def _runtime_safe_text(value: str) -> str:
    """Remove PostgreSQL's sole forbidden text code point without rewriting prose."""

    return value.replace("\x00", " ")


def _retrieval_query(question: str, benchmark_id: str) -> str:
    """Fit the paper query to the frozen Runtime's 2,000-character contract."""

    if len(question) <= 2_000:
        return question
    if benchmark_id.startswith("HORIZON-"):
        lines = question.splitlines()
        stem = lines[0].strip()
        options = [line.strip() for line in lines[1:] if line[:2] in {"A:", "B:", "C:", "D:", "E:"}]
        if len(options) != 5:
            raise ExtendedMiLAiError("Horizon retrieval query options drifted")
        fixed = len(stem) + sum(len(option[:2]) + 2 for option in options) + len(options)
        per_option = max(1, (2_000 - fixed) // len(options))
        query = stem + "\n" + "\n".join(
            f"{option[:2]} {option[2:].strip()[:per_option]}" for option in options
        )
        return query[:2_000]
    return question[:2_000]


def _datetime(value: str, fallback_ordinal: int) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(
                value.strip(), "%Y/%m/%d (%a) %H:%M"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime(2026, 1, 1, fallback_ordinal % 24, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _product_case(case: ExtendedCase, benchmark_id: str) -> product.ProductSmokeCase:
    retrieval_query = _retrieval_query(case.question, benchmark_id)
    return product.ProductSmokeCase(
        case_id=f"{benchmark_id.casefold()}:{case.case_id}",
        source_case_id=case.case_id,
        dataset=benchmark_id,
        category=case.category,
        question=retrieval_query,
        answers=(),
        sessions=tuple(
            (
                session.session_id,
                "\n".join(
                    f"{turn.role}: {_runtime_safe_text(turn.content)}"
                    for turn in session.turns
                ),
            )
            for session in case.sessions
        ),
        question_at=_datetime(case.question_at, len(case.sessions) + 1),
        session_observed_at=tuple(
            _datetime(session.observed_at, ordinal)
            for ordinal, session in enumerate(case.sessions)
        ),
    )


def _identity(
    *,
    run_id: str,
    input_path: Path,
    env_file: Path,
    install_manifest: Path,
    import_successes: Path | None,
) -> dict[str, object]:
    return {
        "candidate_id": core.EXPECTED_CANDIDATE_ID,
        "core_worker_source_sha256": sha256_file(Path(core.__file__)),
        "dataset_loader_sha256": sha256_file(
            ROOT / "evals/paper/datasets/extended.py"
        ),
        "env_sha256": sha256_file(env_file),
        "input_sha256": sha256_file(input_path),
        "import_successes_sha256": (
            sha256_file(import_successes) if import_successes is not None else None
        ),
        "install_manifest_sha256": sha256_file(install_manifest),
        "mcp_host_python": str(Path(sys.executable).absolute()),
        "mcp_origin": core._mcp_origin(),
        "mcp_wheel_sha256": core.MCP_WHEEL_SHA256["DG11-FULL"],
        "method_id": "DG11-FULL",
        "run_id": run_id,
        "runner_source_sha256": sha256_file(Path(__file__)),
        "runtime_origin": core._runtime_origin(),
        "runtime_wheel_sha256": core.WHEEL_SHA256["DG11-FULL"],
    }


def _resume(
    path: Path, identity: dict[str, object], expected: set[str]
) -> dict[str, ContextRecord]:
    if not path.exists():
        return {}
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtendedMiLAiError("extended MiLAi checkpoint is invalid") from exc
    if not isinstance(envelope, dict) or envelope.get("worker_identity") != identity:
        raise ExtendedMiLAiError("extended MiLAi checkpoint identity drifted")
    records = read_context_archive(path)
    by_id = {record.case_id: record for record in records}
    if len(by_id) != len(records) or not set(by_id).issubset(expected):
        raise ExtendedMiLAiError("extended MiLAi checkpoint denominator drifted")
    return by_id


def _import_successes(
    path: Path,
    *,
    identity: dict[str, object],
    expected: set[str],
) -> dict[str, ContextRecord]:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    prior_identity = envelope.get("worker_identity") if isinstance(envelope, dict) else None
    if (
        not isinstance(prior_identity, dict)
        or envelope.get("paper_labels_opened") is not False
        or envelope.get("labels_accessed") is not False
        or envelope.get("candidate_id") != core.EXPECTED_CANDIDATE_ID
        or prior_identity.get("candidate_id") != identity["candidate_id"]
        or prior_identity.get("input_sha256") != identity["input_sha256"]
        or prior_identity.get("runtime_wheel_sha256")
        != identity["runtime_wheel_sha256"]
        or prior_identity.get("mcp_wheel_sha256") != identity["mcp_wheel_sha256"]
    ):
        raise ExtendedMiLAiError("imported extended successes drifted")
    records = read_context_archive(path)
    succeeded = {
        record.case_id: record
        for record in records
        if record.terminal_status == "SUCCEEDED"
    }
    if len(succeeded) != sum(
        record.terminal_status == "SUCCEEDED" for record in records
    ) or not set(succeeded).issubset(expected):
        raise ExtendedMiLAiError("imported extended success denominator drifted")
    return succeeded


def _validate_install(runtime_wheel: Path, install_manifest: Path) -> None:
    if sha256_file(runtime_wheel) != core.WHEEL_SHA256["DG11-FULL"]:
        raise ExtendedMiLAiError("frozen DG11 Runtime wheel drifted")
    try:
        install = json.loads(install_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtendedMiLAiError("frozen DG11 install manifest is invalid") from exc
    wheels = install.get("wheels") if isinstance(install, dict) else None
    runtime = wheels.get("runtime") if isinstance(wheels, dict) else None
    mcp = wheels.get("mcp") if isinstance(wheels, dict) else None
    if (
        install.get("schema") != "milai.dg11.paper-milai-install.v1"
        or install.get("status") != "PASS"
        or install.get("identity") != "dg11"
        or Path(str(install.get("environment"))).resolve() != Path(sys.prefix).resolve()
        or not isinstance(runtime, dict)
        or runtime.get("sha256") != core.WHEEL_SHA256["DG11-FULL"]
        or not isinstance(mcp, dict)
        or mcp.get("sha256") != core.MCP_WHEEL_SHA256["DG11-FULL"]
    ):
        raise ExtendedMiLAiError("frozen DG11 install identity drifted")


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    env_file: Path,
    runtime_wheel: Path,
    install_manifest: Path,
    tokenizer_path: Path,
    max_case_attempts: int,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
    import_successes: Path | None,
) -> dict[str, Any]:
    if output.exists():
        raise ExtendedMiLAiError("extended MiLAi output is write-once")
    if max_case_attempts not in {1, 2, 3}:
        raise ExtendedMiLAiError("extended MiLAi attempt bound is invalid")
    _validate_install(runtime_wheel, install_manifest)
    partition, cases = load_extended_inputs(input_path)
    if allow_unfrozen_smoke:
        if "SMOKE" not in partition:
            raise ExtendedMiLAiError("unfrozen execution is restricted to smoke inputs")
    else:
        require_paper_evaluation_ready(freeze_manifest)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    identity = _identity(
        run_id=run_id,
        input_path=input_path,
        env_file=env_file,
        install_manifest=install_manifest,
        import_successes=import_successes,
    )
    expected = {case.case_id for case in cases}
    checkpoint = output.with_suffix(output.suffix + ".partial")
    resumed = _resume(checkpoint, identity, expected)
    imported: dict[str, ContextRecord] = {}
    imported_count = 0
    if import_successes is not None:
        imported = _import_successes(
            import_successes, identity=identity, expected=expected
        )
        imported_count = len(imported)
        overlap = set(imported).intersection(resumed)
        if overlap and any(imported[key] != resumed[key] for key in overlap):
            raise ExtendedMiLAiError("checkpoint differs from imported success")
        imported.update(resumed)
        resumed = imported
    records: list[ContextRecord] = []
    for case in cases:
        existing = resumed.get(case.case_id)
        if existing is not None:
            records.append(existing)
            continue
        last_failure: Exception | None = None
        record: ContextRecord | None = None
        attempts_used = 0
        for attempt in range(1, max_case_attempts + 1):
            attempts_used = attempt
            try:
                benchmark_case = _product_case(case, partition)
                context, raw_trace = core._runtime_context_with_embedding_accounting(
                    case=benchmark_case, env_file=env_file
                )
                trace = core._trace_items(raw_trace)
                accounting = raw_trace.get("paper_embedding_accounting")
                if not isinstance(accounting, dict) or not isinstance(
                    accounting.get("total_calls"), int
                ):
                    raise ExtendedMiLAiError("embedding accounting is absent")
                context_tokens = len(tokenizer.encode(context.rendered).ids)
                record = ContextRecord(
                    case_id=case.case_id,
                    method_id="DG11-FULL",
                    track="CONTROLLED",
                    context=context.rendered,
                    source_ids=tuple(str(item["source_id"]) for item in trace),
                    trace=trace,
                    declared_tokens=context_tokens,
                    latency_ms=float(raw_trace.get("retrieval_ms", 0)),
                    usage={
                        "answer_calls": 0,
                        "attempts": attempt,
                        "embedding_calls": int(accounting["total_calls"]),
                        "history_sessions": len(case.sessions),
                        "ingest_extraction_calls": 0,
                        "judge_calls": 0,
                        "memory_query_model_calls": 0,
                        "nul_replacements": sum(
                            turn.content.count("\x00")
                            for session in case.sessions
                            for turn in session.turns
                        ),
                        "reranker_calls": int(
                            any(
                                isinstance(item, dict)
                                and isinstance(item.get("reranker"), dict)
                                for item in raw_trace.get("retrieved_items", [])
                            )
                        ),
                        "retrieval_query_chars": len(benchmark_case.question),
                        "retrieval_query_sha256": hashlib.sha256(
                            benchmark_case.question.encode()
                        ).hexdigest(),
                        "storage_bytes": sum(
                            len(turn.content.encode())
                            for session in case.sessions
                            for turn in session.turns
                        ),
                    },
                )
                break
            except Exception as exc:  # noqa: BLE001 - bounded terminal policy
                last_failure = exc
                retryable = any(
                    marker in str(exc)
                    for marker in (
                        "HTTP_500",
                        "HTTP_502",
                        "HTTP_503",
                        "HTTP_504",
                        "SMOKE_API_NOT_READY",
                        "database cleanup failed",
                        "endpoint is unavailable",
                    )
                )
                if not retryable or attempt == max_case_attempts:
                    break
        if record is None:
            assert last_failure is not None
            record = ContextRecord(
                case_id=case.case_id,
                method_id="DG11-FULL",
                track="CONTROLLED",
                context="",
                source_ids=(),
                trace=(),
                declared_tokens=0,
                latency_ms=0,
                usage={
                    "attempts": attempts_used,
                    "failure_class": type(last_failure).__name__,
                    "failure_message_sha256": hashlib.sha256(
                        str(last_failure).encode()
                    ).hexdigest(),
                },
                terminal_status="INFRASTRUCTURE_FAILURE",
            )
        records.append(record)
        write_context_archive(
            checkpoint,
            run_id=run_id,
            benchmark_id=partition,
            records=records,
            metadata={"paper_labels_opened": False, "worker_identity": identity},
        )
    failures = sum(record.terminal_status != "SUCCEEDED" for record in records)
    payload = write_context_archive(
        output,
        run_id=run_id,
        benchmark_id=partition,
        records=records,
        metadata={
            "answer_calls": 0,
            "candidate_id": core.EXPECTED_CANDIDATE_ID,
            "candidate_modified": False,
            "development_ai_reviews": 0,
            "failure_count": failures,
            "labels_accessed": False,
            "maximum_concurrent_requests": 1,
            "paper_labels_opened": False,
            "status": "PASS" if failures == 0 else "FAIL",
            "imported_successes": (
                {
                    "count": imported_count,
                    "path": str(import_successes),
                    "sha256": sha256_file(import_successes),
                }
                if import_successes is not None
                else None
            ),
            "worker_identity": identity,
        },
    )
    checkpoint.unlink(missing_ok=True)
    return cast(dict[str, Any], payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--runtime-wheel", type=Path, default=DEFAULT_RUNTIME_WHEEL)
    parser.add_argument("--install-manifest", type=Path, default=DEFAULT_INSTALL_MANIFEST)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--max-case-attempts", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    parser.add_argument("--import-successes", type=Path)
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        output=args.output.resolve(),
        env_file=args.env_file.resolve(),
        runtime_wheel=args.runtime_wheel.resolve(),
        install_manifest=args.install_manifest.resolve(),
        tokenizer_path=args.tokenizer.resolve(),
        max_case_attempts=args.max_case_attempts,
        freeze_manifest=args.freeze_manifest.resolve(),
        allow_unfrozen_smoke=args.allow_unfrozen_smoke,
        import_successes=(
            args.import_successes.resolve() if args.import_successes is not None else None
        ),
    )
    print(
        json.dumps(
            {
                "failure_count": result["failure_count"],
                "record_count": result["record_count"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
