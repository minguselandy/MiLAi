#!/usr/bin/env python3
"""Run the authorized GDPM B0 24-case context-only Runtime canary."""

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
from evals.gdpm.b0_canary_runtime import (
    execute_runtime_batch,
    execution_plan,
    run_environment_witness,
)

MASTER = ROOT / "MiLAi_Memory_Lifecycle_总_GOALS.md"
GOAL = ROOT / "MiLAi_GDPM-01_受治理双过程Memory分阶段开发与验证_GOALS.md"
DEFAULT_RUN_ROOT = ROOT / "var/gdpm"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--environment-witness", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    output_root = args.output_root or DEFAULT_RUN_ROOT / args.run_id
    if args.environment_witness:
        receipt = run_environment_witness(
            run_id=args.run_id,
            output_root=output_root,
        )
        receipt_path = output_root / "environment-witness.json"
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if receipt["status"] == "PASS":
            print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
            return 0
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 1

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
        ),
        execution_plan=execution_plan(),
        tokenizer_path=DEFAULT_TOKENIZER,
        tokenizer_sha256=EXPECTED_TOKENIZER_SHA256,
        chat_template_path=DEFAULT_CHAT_TEMPLATE,
        chat_template_sha256=EXPECTED_CHAT_TEMPLATE_SHA256,
        code_paths=(
            Path(__file__),
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
        ),
    )
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True))
    return 0 if str(terminal["status"]).startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
