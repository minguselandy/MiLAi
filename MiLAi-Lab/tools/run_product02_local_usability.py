#!/usr/bin/env python3
"""Run the final Product-02 baseline through the Product-01 usability fixtures."""

from __future__ import annotations

import run_product01_s3_local_usability as gate

gate.EXPECTED_PRODUCT_COMMIT = "1b5e4a7122da2b38b9a57bba143215cc0afa3387"
gate.EXPECTED_PRODUCT_LOCK_DIGEST = (
    "6f2869254659bf1c5f7710785a65016cb21b36d06b5411da978e9ffe98c68d1b"
)
gate.CANDIDATE_FLAG = "MILAI_BUDGET_INVARIANT_CONTEXT_V0_1"
gate.SELECTED_FLAG_VALUE = False
gate.ROLLBACK_FLAG_VALUE = True
gate.ROLLBACK_CHECK_MODE = "BUDGET_STABLE_CANDIDATE"
gate.RUN_PREFIX = "product02-u3-local"
gate.RUN_SCHEMA_VERSION = "milai-product02-u3-local-run-v1"
gate.METRICS_SCHEMA_VERSION = "milai-product02-u3-local-metrics-v1"
gate.TERMINAL_SCHEMA_VERSION = "milai-product02-u3-local-terminal-v1"
gate.PASS_TERMINAL = "PASS_PRODUCT02_U3_LOCAL_USABILITY"  # noqa: S105 -- status
gate.FAIL_TERMINAL = "FAIL_PRODUCT02_U3_LOCAL_REPAIR_REQUIRED"
gate.SELECTED_ARM = "B0_B1_EQUIVALENT_BASELINE"
gate.NEXT_SCOPE = "PRODUCT02_COMPLETE_KEEP_SIMPLER_BASELINE"


if __name__ == "__main__":
    raise SystemExit(gate.main())
