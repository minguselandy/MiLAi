#!/usr/bin/env python3
"""Run and score the DG-14 LongMemEval opened-development characterization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import (
    ARMS,
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    METHOD_ID,
    OPENED_DEV_CASE_IDS,
    OPENED_DEV_INPUT_PATH,
    LocalDG14RuntimeSession,
    _atomic_json,
    run_milai_smoke,
    run_opened_dev,
    score_opened_dev,
    seal_opened_dev_run,
)
from evals.dg14.ledger import DG14StageLedger

DEFAULT_RUN_ROOT = ROOT / "var/dg14/runs"
OPENWORKER_METHOD_ID = "DG14-OPENWORKER-COMPOSITION-SMOKE"


class DG14CliError(RuntimeError):
    pass


def _run_dir(run_id: str, explicit: Path | None) -> Path:
    return explicit if explicit is not None else DEFAULT_RUN_ROOT / run_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the 50 label-free matched cells")
    run.add_argument("--run-id", required=True)
    run.add_argument("--inputs", type=Path, default=OPENED_DEV_INPUT_PATH)
    run.add_argument("--run-dir", type=Path)
    run.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    run.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    run.add_argument("--provider-workers", type=int, choices=(1, 2), default=1)
    run.add_argument("--dry-run", action="store_true")

    milai = commands.add_parser(
        "milai-smoke", help="run only real MiLA MCP contexts without provider calls"
    )
    milai.add_argument("--run-id", required=True)
    milai.add_argument("--inputs", type=Path, default=OPENED_DEV_INPUT_PATH)
    milai.add_argument("--run-dir", type=Path)
    milai.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    milai.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    milai.add_argument(
        "--case-id",
        action="append",
        choices=OPENED_DEV_CASE_IDS,
        dest="case_ids",
    )

    score = commands.add_parser(
        "score", help="score with an explicit five-row opened-dev fixture"
    )
    score.add_argument("--run-id", required=True)
    score.add_argument("--inputs", type=Path, default=OPENED_DEV_INPUT_PATH)
    score.add_argument("--run-dir", type=Path)
    score.add_argument("--scoring-fixture", type=Path, required=True)
    score.add_argument("--contexts", type=Path)
    score.add_argument("--generations", type=Path)

    verify = commands.add_parser("verify-ledger", help="verify the stage hash chain")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--run-dir", type=Path)

    seal = commands.add_parser(
        "seal-run", help="bind provider answers and run archives into the ledger"
    )
    seal.add_argument("--run-id", required=True)
    seal.add_argument("--run-dir", type=Path)

    integration = commands.add_parser(
        "integration-smoke",
        help="run real governance, scope, revocation, and MCP-restart checks",
    )
    integration.add_argument("--run-id", required=True)
    integration.add_argument("--run-dir", type=Path)
    integration.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    integration.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)

    real_composition = commands.add_parser(
        "openworker-composition-smoke",
        help="run a fresh real OpenWorker -> MCP -> MiLA -> vLLM composition",
    )
    real_composition.add_argument("--run-id", required=True)
    real_composition.add_argument("--run-dir", type=Path)
    real_composition.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    real_composition.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)

    dev_split = commands.add_parser(
        "build-dev-split",
        help="build a source-ID-only public/deidentified dev split",
    )
    dev_split.add_argument("--output", type=Path)
    dev_split.add_argument("--case-count", type=int, default=50)

    composition = commands.add_parser(
        "openworker-smoke",
        help="run an operator-supplied OpenWorker composition command",
    )
    composition.add_argument("--run-id", required=True)
    composition.add_argument("--run-dir", type=Path)
    composition.add_argument("--case-id", choices=OPENED_DEV_CASE_IDS, required=True)
    composition.add_argument("--command-config", type=Path, required=True)
    composition.add_argument("--timeout-seconds", type=int, default=300)
    return parser


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG14CliError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise DG14CliError(f"JSON object required: {path}")
    return value


def _openworker_smoke(
    *,
    run_id: str,
    run_dir: Path,
    case_id: str,
    command_config: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Validate and record a real, externally supplied composition smoke.

    The supplied process must create the fresh OpenWorker session and perform
    the real composition path.  This wrapper never synthesizes a passing result.
    """

    if timeout_seconds <= 0:
        raise ValueError("OpenWorker smoke timeout must be positive")
    manifest = _read_json(run_dir / "manifest.json")
    contexts = _read_json(run_dir / "contexts.json")
    if (
        manifest.get("run_id") != run_id
        or manifest.get("status") != "SUCCEEDED"
        or contexts.get("run_id") != run_id
        or not isinstance(contexts.get("records"), list)
        or not any(
            isinstance(record, dict)
            and record.get("case_id") == case_id
            and record.get("method_id") == METHOD_ID
            for record in contexts["records"]
        )
    ):
        raise DG14CliError(
            "OpenWorker smoke requires a completed MiLA context for the selected case"
        )
    config_bytes = command_config.read_bytes()
    try:
        config = json.loads(config_bytes)
    except json.JSONDecodeError as exc:
        raise DG14CliError("OpenWorker command config is invalid JSON") from exc
    if (
        not isinstance(config, dict)
        or set(config) != {"argv", "environment", "schema"}
        or config.get("schema") != "milai.dg14.openworker-command.v1"
        or not isinstance(config.get("argv"), list)
        or not config["argv"]
        or not all(isinstance(item, str) and item for item in config["argv"])
        or not isinstance(config.get("environment"), dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in config["environment"].items()
        )
    ):
        raise DG14CliError("OpenWorker command config contract drifted")
    environment = dict(os.environ)
    environment.update(config["environment"])
    process = subprocess.run(
        config["argv"],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if process.returncode != 0:
        stderr_sha256 = hashlib.sha256(process.stderr).hexdigest()
        raise DG14CliError(
            f"OpenWorker composition command failed; stderr_sha256={stderr_sha256}"
        )
    try:
        observed = json.loads(process.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DG14CliError("OpenWorker composition result is not JSON") from exc
    required = {
        "automatic_retry_count": 0,
        "case_id": case_id,
        "fresh_session": True,
        "mcp_resolve_calls": 1,
        "method_id": OPENWORKER_METHOD_ID,
        "provider_calls": 1,
        "retained_history": False,
        "run_id": run_id,
        "schema": "milai.dg14.openworker-composition-result.v1",
    }
    if not isinstance(observed, dict) or any(
        observed.get(key) != expected for key, expected in required.items()
    ):
        raise DG14CliError("OpenWorker composition invariants failed")
    if observed.get("method_id") in ARMS:
        raise DG14CliError("OpenWorker composition cannot be an algorithm arm")
    artifact = {
        **observed,
        "classification": "REPRESENTATIVE_COMPOSITION_SMOKE",
        "command_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "excluded_from_matched_comparison": True,
        "stderr_sha256": hashlib.sha256(process.stderr).hexdigest(),
    }
    _atomic_json(run_dir / "openworker-smoke.json", artifact)
    return artifact


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build-dev-split":
        from evals.dg14.dev_split import DEFAULT_SPLIT_PATH, build_public_dev_split

        result = build_public_dev_split(
            output_path=args.output or DEFAULT_SPLIT_PATH,
            case_count=args.case_count,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    run_dir = _run_dir(args.run_id, args.run_dir)
    if args.command == "run":
        session = LocalDG14RuntimeSession(
            output_root=run_dir,
            env_file=args.env_file,
        )
        result = run_opened_dev(
            run_id=args.run_id,
            input_path=args.inputs,
            output_root=run_dir,
            tokenizer_path=args.tokenizer,
            runtime_session=session,
            max_provider_workers=args.provider_workers,
            dry_run=args.dry_run,
        )
    elif args.command == "milai-smoke":
        session = LocalDG14RuntimeSession(
            output_root=run_dir,
            env_file=args.env_file,
        )
        result = run_milai_smoke(
            run_id=args.run_id,
            input_path=args.inputs,
            output_root=run_dir,
            tokenizer_path=args.tokenizer,
            case_ids=tuple(args.case_ids or OPENED_DEV_CASE_IDS),
            runtime_session=session,
        )
    elif args.command == "score":
        result = score_opened_dev(
            run_id=args.run_id,
            input_path=args.inputs,
            generation_path=args.generations or run_dir / "generations.json",
            context_path=args.contexts or run_dir / "contexts.json",
            scoring_fixture=args.scoring_fixture,
            output_root=run_dir,
        )
    elif args.command == "verify-ledger":
        verification = DG14StageLedger(run_dir / "stage-ledger.jsonl").verify()
        result = {
            "event_count": len(verification.events),
            "root_sha256": verification.root_sha256,
            "run_id": args.run_id,
            "status": "VERIFIED",
        }
    elif args.command == "seal-run":
        result = seal_opened_dev_run(run_id=args.run_id, output_root=run_dir)
    elif args.command == "integration-smoke":
        from evals.dg14.integration_smoke import run_governance_restart_smoke

        result = run_governance_restart_smoke(
            run_id=args.run_id,
            output_root=run_dir,
            env_file=args.env_file,
            tokenizer_path=args.tokenizer,
        )
    elif args.command == "openworker-composition-smoke":
        from evals.dg14.openworker_smoke import run_openworker_composition_smoke

        result = run_openworker_composition_smoke(
            run_id=args.run_id,
            output_root=run_dir,
            env_file=args.env_file,
            tokenizer_path=args.tokenizer,
        )
    elif args.command == "openworker-smoke":
        result = _openworker_smoke(
            run_id=args.run_id,
            run_dir=run_dir,
            case_id=args.case_id,
            command_config=args.command_config,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
