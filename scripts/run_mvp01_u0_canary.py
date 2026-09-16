#!/usr/bin/env python3
"""Run the exactly authorized MVP-01 U0 24-case context-only canary."""

from __future__ import annotations

import argparse
import functools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import (
    DEFAULT_CHAT_TEMPLATE,
    DEFAULT_TOKENIZER,
    EXPECTED_CHAT_TEMPLATE_SHA256,
    EXPECTED_TOKENIZER_SHA256,
)
from evals.gdpm.b0_canary_longmemeval import (
    load_runtime_cases,
    load_selection_inputs,
)
from evals.gdpm.b0_canary_runner import run_b0_context_only_canary
from evals.gdpm.b0_canary_runtime import execute_runtime_batch, execution_plan
from evals.mvp01.u0_canary_contract import (
    AUTHORIZED_RUN_ID,
    EVIDENCE_TOKEN_BUDGET,
    SCOPE_IDENTITY,
    assert_mvp01_u0_canary_authorized,
)

MASTER = ROOT / "MiLAi_Memory_Lifecycle_总_GOALS.md"
GOAL = ROOT / "MiLAi_MVP-01_高效可用Memory最小闭环_GOALS.md"
DEFAULT_RUN_ROOT = ROOT / "var/mvp01"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.run_id != AUTHORIZED_RUN_ID:
        raise SystemExit(
            f"run id is not authorized: expected {AUTHORIZED_RUN_ID}, got {args.run_id}"
        )
    output_root = DEFAULT_RUN_ROOT / args.run_id
    terminal = run_b0_context_only_canary(
        run_id=args.run_id,
        output_root=output_root,
        master_path=MASTER,
        goal_path=GOAL,
        metadata_loader=load_selection_inputs,
        case_loader=load_runtime_cases,
        context_batch_executor=functools.partial(
            execute_runtime_batch,
            run_id=args.run_id,
            runtime_root=output_root / "trace-bundle/runtime",
            expected_budget=EVIDENCE_TOKEN_BUDGET,
        ),
        execution_plan=execution_plan(
            evidence_token_budget=EVIDENCE_TOKEN_BUDGET
        ),
        tokenizer_path=DEFAULT_TOKENIZER,
        tokenizer_sha256=EXPECTED_TOKENIZER_SHA256,
        chat_template_path=DEFAULT_CHAT_TEMPLATE,
        chat_template_sha256=EXPECTED_CHAT_TEMPLATE_SHA256,
        code_paths=(
            Path(__file__),
            ROOT / "evals/mvp01/u0_canary_contract.py",
            ROOT / "evals/gdpm/b0_canary_contract.py",
            ROOT / "evals/gdpm/b0_canary_runner.py",
            ROOT / "evals/gdpm/b0_canary_longmemeval.py",
            ROOT / "evals/gdpm/b0_canary_runtime.py",
            ROOT / "evals/dg14/mcp_stdio.py",
            ROOT / "evals/dg14/milai_mcp_adapter.py",
            ROOT / "evals/dg15/milai_mcp_adapter.py",
            ROOT / "evals/dg15/mcp_stdio.py",
            ROOT / "evals/dg15/runtime_session.py",
            ROOT / "integrations/mcp/src/milai_mcp/server.py",
            ROOT / "runtime/src/milai/application/memory_context.py",
            ROOT / "runtime/src/milai/operations/smoke.py",
            ROOT / "runtime/src/milai/persistence/projection_repository.py",
            ROOT / "runtime/src/milai/workers/main.py",
            ROOT / "runtime/migrations/versions/0048_projection_lease_renewal.py",
            ROOT
            / "runtime/migrations/versions/0049_namespace_cleanup_terminal_counts.py",
        ),
        authority_validator=assert_mvp01_u0_canary_authorized,
        evidence_token_budget=EVIDENCE_TOKEN_BUDGET,
        scope_identity=SCOPE_IDENTITY,
        pass_terminal_status="PASS_MVP01_U0_24_CONTEXT_ONLY_CANARY",
        fail_terminal_status=(
            "FAIL_MVP01_U0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED"
        ),
        pass_next_scope="U0_100_REQUEST_WARM_RELIABILITY_SOAK",
        fail_next_scope="U0_24_CASE_CONTEXT_ONLY_CANARY_REPAIR",
    )
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True))
    return 0 if str(terminal["status"]).startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
