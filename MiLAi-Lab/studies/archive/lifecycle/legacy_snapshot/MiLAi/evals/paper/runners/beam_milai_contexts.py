"""History-reused frozen DG11 context runner for BEAM."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from tokenizers import Tokenizer

from evals.paper.contracts import (
    ContextRecord,
    read_context_archive,
    write_context_archive,
)
from evals.paper.datasets.extended import ExtendedCase, load_beam_inputs
from evals.paper.datasets.memora import (
    MemoraCase,
    MemoraCohort,
    MemoraSession,
    MemoraTurn,
)
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file
from evals.paper.runners import memora_milai_contexts as cohort_worker
from evals.paper.runners.milai_contexts import (
    EXPECTED_CANDIDATE_ID,
    MCP_WHEEL_SHA256,
    WHEEL_SHA256,
    _mcp_origin,
    _runtime_origin,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/beam-128k-inputs.json"
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


class BeamMiLAiError(RuntimeError):
    pass


def _cohorts(
    cases: tuple[ExtendedCase, ...],
) -> tuple[tuple[MemoraCohort, ...], dict[str, list[MemoraCase]]]:
    by_session_ids: dict[tuple[str, ...], MemoraCohort] = {}
    cases_by_cohort: dict[str, list[MemoraCase]] = defaultdict(list)
    for case in cases:
        session_ids = tuple(session.session_id for session in case.sessions)
        if not session_ids:
            raise BeamMiLAiError("BEAM history has no sessions")
        cohort_id = "beam-history-" + hashlib.sha256(
            "\0".join(session_ids).encode()
        ).hexdigest()[:20]
        candidate = MemoraCohort(
            cohort_id=cohort_id,
            period="beam",
            persona="public-deidentified",
            sessions=tuple(
                MemoraSession(
                    observed_at=session.observed_at,
                    session_id=session.session_id,
                    turns=tuple(
                        MemoraTurn(actor=turn.role, content=turn.content)
                        for turn in session.turns
                    ),
                )
                for session in case.sessions
            ),
        )
        existing = by_session_ids.setdefault(session_ids, candidate)
        if existing != candidate:
            raise BeamMiLAiError("BEAM shared history content drifted")
        cases_by_cohort[cohort_id].append(
            MemoraCase(
                case_id=case.case_id,
                cohort_id=cohort_id,
                question=case.question,
                question_at=case.question_at,
                source_question_id=case.case_id,
                task=case.category,
            )
        )
    return tuple(by_session_ids.values()), dict(cases_by_cohort)


def _identity(
    *, run_id: str, input_path: Path, env_file: Path, install_manifest: Path
) -> dict[str, Any]:
    return {
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "cohort_worker_sha256": sha256_file(Path(cohort_worker.__file__)),
        "dataset_loader_sha256": sha256_file(
            ROOT / "evals/paper/datasets/extended.py"
        ),
        "env_sha256": sha256_file(env_file),
        "input_sha256": sha256_file(input_path),
        "install_manifest_sha256": sha256_file(install_manifest),
        "mcp_host_python": str(Path(sys.executable).absolute()),
        "mcp_origin": _mcp_origin(),
        "mcp_wheel_sha256": MCP_WHEEL_SHA256["DG11-FULL"],
        "method_id": "DG11-FULL",
        "run_id": run_id,
        "runner_sha256": sha256_file(Path(__file__)),
        "runtime_origin": _runtime_origin(),
        "runtime_wheel_sha256": WHEEL_SHA256["DG11-FULL"],
    }


def _checkpoint(
    path: Path,
    *,
    identity: dict[str, Any],
    expected_ids: set[str],
) -> tuple[dict[str, ContextRecord], list[dict[str, Any]]]:
    if not path.exists():
        return {}, []
    value = json.loads(path.read_text(encoding="utf-8"))
    records = read_context_archive(path)
    stats = value.get("cohort_stats") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("worker_identity") != identity
        or not isinstance(stats, list)
        or not {record.case_id for record in records}.issubset(expected_ids)
        or len({record.case_id for record in records}) != len(records)
    ):
        raise BeamMiLAiError("BEAM DG11 checkpoint drifted")
    return {record.case_id: record for record in records}, list(stats)


def _retryable(exc: Exception) -> bool:
    return any(
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


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    env_file: Path,
    runtime_wheel: Path,
    install_manifest: Path,
    tokenizer_path: Path,
    max_cohort_attempts: int,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    if output.exists():
        raise BeamMiLAiError("BEAM DG11 output is write-once")
    if max_cohort_attempts not in {1, 2, 3}:
        raise BeamMiLAiError("BEAM cohort attempt bound is invalid")
    cohort_worker._verify_install(
        method_id="DG11-FULL",
        runtime_wheel=runtime_wheel,
        install_manifest=install_manifest,
    )
    partition, extended_cases = load_beam_inputs(input_path)
    if allow_unfrozen_smoke:
        if "SMOKE" not in partition:
            raise BeamMiLAiError("unfrozen BEAM execution requires smoke inputs")
    else:
        require_paper_evaluation_ready(freeze_manifest)
    cohorts, cases_by_cohort = _cohorts(extended_cases)
    if not allow_unfrozen_smoke and (
        partition != "BEAM-128K-FULL"
        or len(cohorts) != 20
        or len(extended_cases) != 400
    ):
        raise BeamMiLAiError("formal BEAM 128K denominator drifted")
    identity = _identity(
        run_id=run_id,
        input_path=input_path,
        env_file=env_file,
        install_manifest=install_manifest,
    )
    checkpoint_path = output.with_suffix(output.suffix + ".partial")
    expected_ids = {case.case_id for case in extended_cases}
    records_by_id, cohort_stats = _checkpoint(
        checkpoint_path, identity=identity, expected_ids=expected_ids
    )
    completed_cohorts = {
        str(stat["cohort_id"])
        for stat in cohort_stats
        if isinstance(stat, dict) and isinstance(stat.get("cohort_id"), str)
    }
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    for cohort in cohorts:
        if cohort.cohort_id in completed_cohorts:
            continue
        cases = cases_by_cohort[cohort.cohort_id]
        last_failure: Exception | None = None
        attempts_used = 0
        cohort_records: list[ContextRecord] = []
        stat: dict[str, Any] | None = None
        for attempt in range(1, max_cohort_attempts + 1):
            attempts_used = attempt
            try:
                with cohort_worker._CohortRuntime(
                    cohort=cohort, env_file=env_file
                ) as runtime:
                    cohort_records = [runtime.query(case, tokenizer) for case in cases]
                    stat = runtime.stats(question_count=len(cases))
                break
            except Exception as exc:  # noqa: BLE001 - bounded terminal policy
                last_failure = exc
                if not _retryable(exc) or attempt == max_cohort_attempts:
                    break
        if stat is None:
            assert last_failure is not None
            failure_hash = hashlib.sha256(str(last_failure).encode()).hexdigest()
            cohort_records = [
                ContextRecord(
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
                        "failure_message_sha256": failure_hash,
                    },
                    terminal_status="INFRASTRUCTURE_FAILURE",
                )
                for case in cases
            ]
            stat = {
                "attempts": attempts_used,
                "cohort_id": cohort.cohort_id,
                "failure_class": type(last_failure).__name__,
                "failure_message_sha256": failure_hash,
                "question_count": len(cases),
                "status": "INFRASTRUCTURE_FAILURE",
            }
        else:
            stat["attempts"] = attempts_used
            stat["status"] = "SUCCEEDED"
        records_by_id.update({record.case_id: record for record in cohort_records})
        cohort_stats.append(stat)
        ordered = [
            records_by_id[case.case_id]
            for case in extended_cases
            if case.case_id in records_by_id
        ]
        write_context_archive(
            checkpoint_path,
            run_id=run_id,
            benchmark_id=partition,
            records=ordered,
            metadata={
                "cohort_stats": cohort_stats,
                "paper_labels_opened": False,
                "worker_identity": identity,
            },
        )
    records = tuple(records_by_id[case.case_id] for case in extended_cases)
    if len(records) != len(expected_ids):
        raise BeamMiLAiError("BEAM DG11 terminal denominator is incomplete")
    failures = sum(record.terminal_status != "SUCCEEDED" for record in records)
    payload = write_context_archive(
        output,
        run_id=run_id,
        benchmark_id=partition,
        records=records,
        metadata={
            "answer_calls": 0,
            "candidate_id": EXPECTED_CANDIDATE_ID,
            "candidate_modified": False,
            "cohort_count": len(cohorts),
            "cohort_reuse": True,
            "cohort_stats": cohort_stats,
            "development_ai_reviews": 0,
            "failure_count": failures,
            "labels_accessed": False,
            "maximum_concurrent_requests": 1,
            "paper_labels_opened": False,
            "status": "PASS" if failures == 0 else "FAIL",
            "worker_identity": identity,
        },
    )
    checkpoint_path.unlink(missing_ok=True)
    return cast(dict[str, Any], payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--runtime-wheel", type=Path, default=DEFAULT_RUNTIME_WHEEL)
    parser.add_argument("--install-manifest", type=Path, default=DEFAULT_INSTALL_MANIFEST)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--max-cohort-attempts", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        output=args.output.resolve(),
        env_file=args.env_file.resolve(),
        runtime_wheel=args.runtime_wheel.resolve(),
        install_manifest=args.install_manifest.resolve(),
        tokenizer_path=args.tokenizer.resolve(),
        max_cohort_attempts=args.max_cohort_attempts,
        freeze_manifest=args.freeze_manifest.resolve(),
        allow_unfrozen_smoke=args.allow_unfrozen_smoke,
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
