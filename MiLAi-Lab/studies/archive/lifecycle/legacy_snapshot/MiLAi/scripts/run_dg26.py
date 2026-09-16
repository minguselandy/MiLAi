#!/usr/bin/env python3
"""Run and terminalize the frozen DG-26 matched experiment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.domain.requirement_state import canonical_sha256

from evals.dg26.stateview_reranking import (
    derive_decision,
    execute_once,
    sha256_file,
)

RUN_LOCK = ROOT / "var/dg26/run-lock.json"
RESULTS = ROOT / "var/dg26/results.json"
TERMINAL = ROOT / "var/dg26/terminal.json"
GOLD = (
    ROOT
    / "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "gold-equivalence-registry-v0.1.json"
)
PROOF = (
    ROOT
    / "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "proof-obligation-registry-v0.1.json"
)
ATTRIBUTION = (
    ROOT
    / "var/dg24/s6/dg24-s6-scoring-20260829-003/"
    "requirement-loss-attributions.json"
)
IMPLEMENTATION_PATHS = (
    "runtime/src/milai/domain/ranking_state_view.py",
    "runtime/src/milai/adapters/state_aware_reranker.py",
    "evals/dg26/stateview_reranking.py",
    "scripts/run_dg26.py",
    "tests/test_dg26_stateview_reranking.py",
)


class DG26RunnerError(RuntimeError):
    pass


def run_experiment(
    *,
    run_lock: Path = RUN_LOCK,
    results_path: Path = RESULTS,
    gold_path: Path = GOLD,
    proof_path: Path = PROOF,
    attribution_path: Path = ATTRIBUTION,
) -> dict[str, Any]:
    if results_path.exists():
        raise DG26RunnerError("DG26_RESULTS_ALREADY_EXIST_NO_RERUN")
    authoritative = execute_once(
        ROOT,
        run_lock,
        gold_path,
        proof_path,
        attribution_path,
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(RUNTIME_SRC), str(ROOT), environment.get("PYTHONPATH", "")]
    )
    environment["TOKENIZERS_PARALLELISM"] = "false"
    environment["OMP_NUM_THREADS"] = "1"
    replay = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "replay",
            "--run-lock",
            str(run_lock),
            "--gold",
            str(gold_path),
            "--proof",
            str(proof_path),
            "--attribution",
            str(attribution_path),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    replay_value = json.loads(replay.stdout)
    if not isinstance(replay_value, dict):
        raise DG26RunnerError("DG26_FRESH_PROCESS_REPLAY_INVALID")
    authoritative_cost = authoritative["cost"]
    replay_cost = replay_value.get("cost", {})
    budget_exact = (
        authoritative_cost.get("model_batches") == 45
        and authoritative_cost.get("model_pairs") == 981
        and replay_cost.get("model_batches") == 45
        and replay_cost.get("model_pairs") == 981
    )
    exact = (
        replay_value.get("semantic_digest") == authoritative.get("semantic_digest")
        and budget_exact
    )
    decision = derive_decision(authoritative, fresh_process_exact_match=exact)
    lock = _object(run_lock)
    result: dict[str, Any] = {
        "schema": "milai.dg26.results.v0.1",
        "goal_id": "DG-26",
        "run_id": lock["run_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "run_lock": _identity(run_lock),
        "run_lock_digest": lock["lock_digest"],
        "config_digest": lock["config_digest"],
        "execution_order": [
            "LOAD_LABEL_FREE_FIXED_INPUTS",
            "EXECUTE_R0_R1_R2_R3_AND_RUNTIME_BINDING",
            "OPEN_SCORER_ONLY_REGISTRIES",
            "SCORE_ALL_ARMS",
            "FRESH_PROCESS_REPLAY",
        ],
        "authoritative": authoritative,
        "fresh_process_replay": {
            "executions": 1,
            "fresh_process": True,
            "semantic_digest": replay_value.get("semantic_digest"),
            "exact_match": exact,
            "budget_exact": budget_exact,
            "model_batches": replay_cost.get("model_batches"),
            "model_pairs": replay_cost.get("model_pairs"),
            "automatic_retries": 0,
        },
        "decision": decision,
        "source_identities": [_identity(ROOT / value) for value in IMPLEMENTATION_PATHS],
        "scorer_identities": {
            "gold_registry": _identity(gold_path),
            "proof_registry": _identity(proof_path),
            "loss_attribution": _identity(attribution_path),
        },
        "safety": {
            **dict(authoritative["safety"]),
            "fresh_process_exact_match": exact,
            "formal_holdout_used": False,
            "candidate_feature_flag": "OFF",
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
        },
    }
    result["results_digest"] = canonical_sha256(result)
    _write_exclusive(results_path, result)
    return result


def build_terminal(
    *,
    run_lock: Path = RUN_LOCK,
    results_path: Path = RESULTS,
    terminal_path: Path = TERMINAL,
    targeted_tests: str,
    typecheck: str,
    lint: str,
) -> dict[str, Any]:
    if terminal_path.exists():
        raise DG26RunnerError("DG26_TERMINAL_ALREADY_EXISTS")
    results = _object(results_path)
    material = dict(results)
    observed = material.pop("results_digest", None)
    if observed != canonical_sha256(material):
        raise DG26RunnerError("DG26_RESULTS_DIGEST_MISMATCH")
    lock = _object(run_lock)
    if results.get("run_lock_digest") != lock.get("lock_digest"):
        raise DG26RunnerError("DG26_TERMINAL_RUN_LOCK_MISMATCH")
    decision = dict(results["decision"])
    quality_passed = all(value.startswith("PASS") for value in (targeted_tests, typecheck, lint))
    status = str(decision["status"]) if quality_passed else "FAIL"
    reason = str(decision["reason_code"]) if quality_passed else "SAFETY_OR_PROTOCOL"
    r2 = results["authoritative"]["arms"]["R2"]["metrics"]
    safety = results["safety"]
    stateview_claim_status = "SUPPORTED" if status == "PASS" else "NOT_SUPPORTED"
    safety_claim_status = (
        "SUPPORTED"
        if (
            int(r2["wrong_complete"]) == 0
            and int(safety["authority_violations"]) == 0
            and int(safety["canonical_mutation"]) == 0
            and int(safety["automatic_retries"]) == 0
            and int(safety["acquisition_call_delta"]) == 0
            and safety["candidate_feature_flag"] == "OFF"
            and safety["formal_holdout_used"] is False
        )
        else "NOT_SUPPORTED"
    )
    terminal: dict[str, Any] = {
        "schema": "milai.dg26.terminal.v0.1",
        "goal_id": "DG-26",
        "run_id": lock["run_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "status": status,
        "reason_code": reason,
        "claims": [
            {
                "claim_id": "C1_STATEVIEW_INDEPENDENT_RANKING_GAIN",
                "status": stateview_claim_status,
            },
            {
                "claim_id": "C2_NO_ACQUISITION_OR_SAFETY_RELAXATION",
                "status": safety_claim_status,
            },
        ],
        "results_path": str(results_path.relative_to(ROOT)),
        "run_lock_path": str(run_lock.relative_to(ROOT)),
        "results_identity": _identity(results_path),
        "run_lock_identity": _identity(run_lock),
        "decision_checks": decision["checks"],
        "safety": {
            "wrong_complete": int(r2["wrong_complete"]),
            "authority_violation": int(safety["authority_violations"]),
            "correct_case_regression": int(r2["baseline_correct_groups_lost"]),
            "canonical_mutation": int(safety["canonical_mutation"]),
            "automatic_retry": int(safety["automatic_retries"]),
            "acquisition_call_delta": int(safety["acquisition_call_delta"]),
            "formal_holdout_used": False,
            "candidate_feature_flag": "OFF",
        },
        "quality": {
            "targeted_tests": targeted_tests,
            "typecheck": typecheck,
            "lint": lint,
        },
        "known_limitations": [
            "opened-development diagnostic only; no formal holdout was used",
            "one frozen English MS MARCO cross-encoder and one fixed K=8 pool were tested",
            "R3 is a within-view synthetic semantic permutation, not cross-user state",
            "ranking-only execution does not satisfy proof obligations or authorize COMPLETE",
        ],
        "rollback": {
            "state_aware_reranker_flag": "OFF",
            "baseline_ordering_restored": True,
            "results_retained": True,
        },
    }
    terminal["terminal_digest"] = canonical_sha256(terminal)
    _write_exclusive(terminal_path, terminal)
    return terminal


def _identity(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        label = str(resolved.relative_to(ROOT))
    except ValueError:
        label = str(resolved)
    return {
        "path": label,
        "sha256": sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG26RunnerError(f"JSON object required: {path}")
    return value


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    experiment = subparsers.add_parser("experiment")
    experiment.add_argument("--run-lock", type=Path, default=RUN_LOCK)
    experiment.add_argument("--results", type=Path, default=RESULTS)
    experiment.add_argument("--gold", type=Path, default=GOLD)
    experiment.add_argument("--proof", type=Path, default=PROOF)
    experiment.add_argument("--attribution", type=Path, default=ATTRIBUTION)
    replay = subparsers.add_parser("replay")
    replay.add_argument("--run-lock", type=Path, required=True)
    replay.add_argument("--gold", type=Path, required=True)
    replay.add_argument("--proof", type=Path, required=True)
    replay.add_argument("--attribution", type=Path, required=True)
    terminal = subparsers.add_parser("terminal")
    terminal.add_argument("--run-lock", type=Path, default=RUN_LOCK)
    terminal.add_argument("--results", type=Path, default=RESULTS)
    terminal.add_argument("--terminal", type=Path, default=TERMINAL)
    terminal.add_argument("--targeted-tests", required=True)
    terminal.add_argument("--typecheck", required=True)
    terminal.add_argument("--lint", required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.command == "experiment":
        result = run_experiment(
            run_lock=arguments.run_lock,
            results_path=arguments.results,
            gold_path=arguments.gold,
            proof_path=arguments.proof,
            attribution_path=arguments.attribution,
        )
        print(
            json.dumps(
                {
                    "status": result["decision"]["status"],
                    "reason_code": result["decision"]["reason_code"],
                    "results_digest": result["results_digest"],
                },
                sort_keys=True,
            )
        )
        return 0
    if arguments.command == "replay":
        result = execute_once(
            ROOT,
            arguments.run_lock,
            arguments.gold,
            arguments.proof,
            arguments.attribution,
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 0
    terminal = build_terminal(
        run_lock=arguments.run_lock,
        results_path=arguments.results,
        terminal_path=arguments.terminal,
        targeted_tests=arguments.targeted_tests,
        typecheck=arguments.typecheck,
        lint=arguments.lint,
    )
    print(
        json.dumps(
            {
                "status": terminal["status"],
                "reason_code": terminal["reason_code"],
                "terminal_digest": terminal["terminal_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
