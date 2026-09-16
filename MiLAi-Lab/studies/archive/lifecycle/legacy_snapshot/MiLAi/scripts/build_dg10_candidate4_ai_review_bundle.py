from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scan_ua_secrets import _secrets

from scripts import dg10_ai_provenance as ai_provenance
from scripts import dg10_remediation as remediation

SOURCE_INVENTORY = ROOT / "docs/reports/DG-10-candidate-source-inventory-candidate.4.21-2026-08-22.json"
CLOSURE_REPORT = ROOT / "docs/reports/DG-10-benchmark-worker-closure-candidate.4.28-2026-08-22.json"
BFCL_ROOT = ROOT.parent / "benchmarks/gorilla-bfcl/berkeley-function-call-leaderboard"
DEFAULT_CAPTURE_ROOT = ROOT.parent / "evidence/dg10-remediation-worker-closure"
DEFAULT_OUTPUT_ROOT = ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r0-r2-review"
DEFAULT_RECEIPT = ROOT / "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.18-2026-08-22.json"

EVIDENCE_PATHS = (
    "docs/reports/DG-10-remediation-baseline-candidate.4.3-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.28-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.21-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.21-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.21-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.21-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.21-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.17-2026-08-22.json",
    "var/dg10/stage-ledger-candidate.4.17.jsonl",
    "docs/reports/DG-10-dg10-r0-stage-author-binding-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-dg10-r0-stage-review-binding-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-author-binding-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-review-binding-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-author-binding-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-review-binding-candidate.4.17-2026-08-22.json",
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.18.json",
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.18.json",
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.18.json",
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.15-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.18-2026-08-22.json",
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.18-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.18-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-r1-validation-supersession-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.27-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.20-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.20-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.20-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.20-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.20-2026-08-22.json",
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.17-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.16-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.26-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.19-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.19-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.19-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.19-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.19-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.25-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.24-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.23-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.12-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.18-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.18-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.18-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.18-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.18-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.14-2026-08-22.json",
    "var/dg10/stage-ledger-candidate.4.14.jsonl",
    "docs/reports/DG-10-dg10-r0-stage-author-binding-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-dg10-r0-stage-review-binding-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-author-binding-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-review-binding-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-author-binding-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-review-binding-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.14-2026-08-22.json",
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.14.json",
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.14.json",
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.14.json",
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.14-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.12-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.15-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.22-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.13-2026-08-22.json",
    "var/dg10/stage-ledger-candidate.4.13.jsonl",
    "docs/reports/DG-10-dg10-r0-stage-author-binding-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-dg10-r0-stage-review-binding-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-author-binding-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-review-binding-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-author-binding-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-review-binding-candidate.4.13-2026-08-22.json",
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.13-2026-08-22.json",
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.13.json",
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.13.json",
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.13.json",
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.13-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.19-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.15-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.15-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.15-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.15-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.15-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.11-2026-08-22.json",
    "var/dg10/stage-ledger-candidate.4.11.jsonl",
    "docs/reports/DG-10-dg10-r0-stage-author-binding-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-dg10-r0-stage-review-binding-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-author-binding-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-review-binding-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-author-binding-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-review-binding-candidate.4.11-2026-08-22.json",
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.11-2026-08-22.json",
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.11.json",
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.11.json",
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.11.json",
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.11-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.12-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.18-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.8-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.10-2026-08-22.json",
    "var/dg10/stage-ledger-candidate.4.10.jsonl",
    "docs/reports/DG-10-dg10-r0-stage-author-binding-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-dg10-r0-stage-review-binding-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-author-binding-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-review-binding-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-author-binding-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-review-binding-candidate.4.10-2026-08-22.json",
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.10-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.10-2026-08-22.json",
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.10.json",
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.10.json",
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.10.json",
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.10-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.8-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.17-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.9-2026-08-22.json",
    "var/dg10/stage-ledger-candidate.4.9.jsonl",
    "docs/reports/DG-10-dg10-r0-stage-author-binding-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-dg10-r0-stage-review-binding-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-author-binding-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-review-binding-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-author-binding-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-review-binding-candidate.4.9-2026-08-22.json",
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.9-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.9-2026-08-22.json",
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.9.json",
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.9.json",
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.9-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.8-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.6-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.16-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.15-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.14-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.13-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.12-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.6-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.5-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.4-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.3-2026-08-22.json",
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.2-2026-08-22.json",
    "docs/reports/DG-10-model-probe-candidate.4-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.12-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.12-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.12-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.12-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.12-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.11-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.10-2026-08-22.json",
    "docs/reports/DG-10-candidate-source-inventory-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-environment-identity-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-model-identity-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-authorization-identities-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-identity-supersession-candidate.4.9-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.8-2026-08-22.json",
    "var/dg10/stage-ledger-candidate.4.8.jsonl",
    "docs/reports/DG-10-dg10-r0-stage-author-binding-candidate.4.8-2026-08-22.json",
    "docs/reports/DG-10-dg10-r0-stage-review-binding-candidate.4.8-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-author-binding-candidate.4.8-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-review-binding-candidate.4.8-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-author-binding-candidate.4.8-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-review-binding-candidate.4.8-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.7-2026-08-22.json",
    "var/dg10/stage-ledger-candidate.4.7.jsonl",
    "docs/reports/DG-10-dg10-r0-stage-author-binding-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-dg10-r0-stage-review-binding-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-author-binding-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-review-binding-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-author-binding-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-review-binding-candidate.4.7-2026-08-22.json",
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.6-2026-08-22.json",
    "var/dg10/stage-ledger-candidate.4.6.jsonl",
    "docs/reports/DG-10-dg10-r0-stage-author-binding-candidate.4.6-2026-08-22.json",
    "docs/reports/DG-10-dg10-r0-stage-review-binding-candidate.4.6-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-author-binding-candidate.4.6-2026-08-22.json",
    "docs/reports/DG-10-dg10-r1-stage-review-binding-candidate.4.6-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-author-binding-candidate.4.6-2026-08-22.json",
    "docs/reports/DG-10-dg10-r2-stage-review-binding-candidate.4.6-2026-08-22.json",
    "docs/reports/DG-10-r0-archive-replay-candidate.4-2026-08-22.json",
    "docs/reviews/DG-10-r0-r2-ai-blind-semantic-audit-receipt-candidate.3-2026-08-22.json",
    "docs/contracts/DG-10-ai-audit-policy-override-candidate.4.json",
    "docs/contracts/DG-10-ai-audit-reasoning-amendment-candidate.4.2.json",
    "docs/reviews/DG-10-r0-r2-ai-audit-interruption-candidate.4-max-2026-08-22.json",
    "docs/reviews/DG-10-candidate3-ai-finding-register-materialized-candidate.4-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.3-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.4-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.5-2026-08-22.json",
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.8-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.8-2026-08-22.json",
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.7-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.7-2026-08-22.json",
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.6-2026-08-22.json",
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-candidate.4.6-2026-08-22.json",
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.8.json",
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.7.json",
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.6.json",
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.8-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.7-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.6-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.6-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.5-2026-08-22.json",
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.4-2026-08-22.json",
    "docs/reports/DG-10-final-completion-audit-candidate.2-2026-08-22.json",
    "docs/reviews/DG-10-sol-final-audit-disposition-candidate.1-2026-08-22.json",
    "dist/DG-10-experiment-results-candidate.2-2026-08-22.receipt.json",
)

PARENT_FINDINGS = (
    *(f"DG10-C3-AI-{index:03d}" for index in range(1, 13)),
    *(f"DG10-C4-AI-{index:03d}" for index in range(13, 29)),
)

REVIEW_PROMPT = """# DG-10 candidate.4 R0-R2 independent AI semantic audit

You are a primary independent AI adversarial auditor running in a new ephemeral
Codex session with gpt-5.6-sol and xhigh reasoning. The user explicitly authorized
AI audit in place of human audit for candidate.4. Your authority is therefore
AI_INDEPENDENT_PER_USER_POLICY, never HUMAN. You may decide only DG10-R0, R1,
and R2. You cannot authorize release, full-test access, or any model call directly.

Audit only this closed, read-only working directory. Do not access any path outside
it. Do not use network, Runtime sockets, environment secrets, raw benchmark sidecars,
test labels, or current model outputs. Do not modify any file. The historical
candidate.2 package has been safely materialized under historical-candidate2/ and
is part of the closed bundle; inspect it as needed, but do not seek any external
protected archive.

The immutable reasoning amendment in evidence supersedes only the parent policy's
old max setting: every audit started under this bundle must use xhigh. The prior
max process was interrupted and has no review, acceptance, or authorization effect.
The materialized parent-finding registers are permitted semantic inputs: they
preserve finding definitions only and do not expose or confer a prior verdict. For
DG10-C3-AI-009, candidate.4.5 supersedes the older required-action wording; for
DG10-C3-AI-012 and DG10-C4-AI-015, candidate.4.4 remains the wording successor.
Candidate.4.5 also adds DG10-C4-AI-021 through 023; none supersedes history.
Candidate.4.6 adds DG10-C4-AI-024 and successor remediation evidence for
DG10-C3-AI-006, DG10-C3-AI-007, and DG10-C4-AI-023; none erases history.
Candidate.4.7 adds fail-closed successor evidence for DG10-C3-AI-005 and
DG10-C4-AI-021; its historical unbound inspected-path citation has no acceptance
effect and must not be repeated. None of these registers erases history.
Candidate.4.8 adds successor evidence for DG10-C3-AI-006: the active closures
must contain every Runtime wheel source input, including py.typed, CSS, JavaScript,
and HTML package data, with exact wheel/source path and byte equality.
Candidate.4.9 adds successor evidence for DG10-C3-AI-002/007/008 and
DG10-C4-AI-014/024/025/026: AI attempts now require a pinned Codex executable,
pidfd plus /proc exe/argv replay before output reads, a per-launch child nonce,
direct pipes, fixed scope roots, and deep authorization replay. Generic R3
acceptance is denied in favor of the fixed protected R3 importer. The test-access
CLI parser and phase-specific post-R3 success exit also have regression coverage.
Candidate.4.10 records that this V1 process metadata was insufficient because the
workspace identity could forge it after execution. Active attempts must instead be
launched and signed by the fixed separate-UID authority in the frozen authority
policy. Importers must verify its Ed25519 signature over the complete process
claims and live runtime observations, reject V1 or unsigned metadata, and require
authority ownership of the fixed attempt directory and terminal output.
Candidate.4.11 records that primary-013 was an invalid execution with no acceptance
effect: the isolated Codex installation lacked its adjacent code-mode host, so the
auditor could not read the bundle. The active authority now pins that helper's
path, SHA-256, root ownership, and non-writable mode, and signs the same identity
in every runtime observation. Treat primary-013 only as historical failure evidence.
Candidate.4.12 records that primary-014 was also an invalid execution with no
acceptance effect: the isolated installation still lacked the complete sandbox
resource closure. The active authority now pins bwrap, rg, and a host-compatible
zsh by path, SHA-256, root ownership, and mode 0555; it also freezes every parent
resource directory, signs the complete resource mapping, and explicitly disables
zsh-fork and shell-snapshot execution paths. Treat primary-014 only as historical
failure evidence. A model-list refresh timeout is nonfatal only when it is the sole
exact known diagnostic; every additional stderr line remains fail-closed.
Candidate.4.13 records that primary-015 was an invalid execution with no acceptance
effect because it emitted five copies of the otherwise known model-list refresh
diagnostic. The active classifier now permits only empty stderr or one exact ASCII
diagnostic with one canonical six-fraction UTC timestamp and one LF; duplicates,
prefixes, suffixes, CRLF, and undecodable bytes fail closed. The active authority
policy also freezes root UID/GID and mode 0555 for both the Codex executable and
its adjacent code-mode host, signs both GIDs, and replays every field. Treat
primary-015 and its observed output only as historical execution-failure evidence.
Candidate.4.14 additionally freezes a canonical local model catalog as a root-owned,
read-only authority resource. Its absolute path, SHA-256, UID, GID, and mode are
bound in policy, included in the signed live runtime observations, replayed by all
importers, and injected into the exact Codex command through model_catalog_json.
This selects the static model manager and prevents periodic remote model-list
refresh diagnostics without weakening the strict stderr classifier.
Candidate.4.17 preserves the valid protected primary-017 REVISE result without
acceptance effect. It adds DG10-C4-AI-027 and DG10-C4-AI-028: the V2 signer still
imported unfrozen workspace modules, and the Codex child inherited the host
environment. Candidate.4.18 responds with a root-owned content-addressed four-file
authority package; Python -I -B, an exact sys.path, complete distribution/venv tree
digests, and hashes for every externally mapped library; exact env-i authority and
Codex allowlists with /proc environment replay; and adversarial module, runtime,
library, extra-variable, secret-variable, and descendant-environment tests. The
active acceptance, BFCL manifest, scoring module, and BFCL execution identity now
name the same candidate.4.13 execution identity. Re-evaluate these controls from
the actual bytes; the historical REVISE receipt does not itself close any finding.
Candidate.4.19 is retained without acceptance effect because its R1 receipt was
generated with contract-only scope. Candidate.4.20 supersedes it: the active R1
receipt uses scope=all, replays the complete active source inventory, and binds the
same source root used by the stage ledger. Primary-018 validly returned REVISE and
reopened DG10-C3-AI-007 and DG10-C4-AI-024 because buffered HTTP and OpenCode
completion helpers were directly callable without a local post-R3 gate.
Candidate.4.21 responds by requiring the same fixed post-R3 replay at the entry of
all three serving completion transports, before HTTP or subprocess side effects,
with direct-helper I/O-spy tests and function-level gate-before-I/O checks. Treat
the contract-only R1 receipt and all superseded R2/identity sets as historical
fail-closed evidence; the primary-018 REVISE receipt has no acceptance effect.
Do not semantically read any other prior candidate.4 review or review conclusion.

First read review-manifest.json. Recompute every listed size and SHA-256, then
recompute bundle_entries_sha256 as SHA-256 of canonical compact JSON
{"entries": entries} plus one trailing newline, with UTF-8, sorted keys, and no
ASCII escaping. Verify the source inventory independently from current-source/.

Perform a skeptical semantic review:

1. R0: exact candidate.2 archive/receipt/control-file/member replay, immutable
   historical NO-GO, complete parent finding register, and candidate succession.
2. R1: claim/stage semantics, artifact-derived authorization, append-only call
   ledger, AI policy truthfulness, test-access and release fail-closed behavior.
3. R2: content-addressed Runtime wheel, independent wheel rebuild, fresh install,
   full collection/pytest/Ruff captures, complete executed source/config closure,
   upstream BFCL tracked-tree replay, source/environment/model identity consistency.
4. Verify that the fixed BFCL preregistration predates any candidate.4 result
   access, serving gates rebuild only from raw receipts and the attempt ledger,
   and the R0-R2 stage ledger is one reconciled append-only state source.
5. Re-evaluate every parent finding DG10-C3-AI-001 through 012 and
   DG10-C4-AI-013 through 028 against the actual candidate.4 bytes. Mark CLOSED
   only with concrete paths and semantics.
6. Search for new bypasses or contradictions. Report every P0/P1 and material P2.
7. ACCEPTED is permitted only if manifest/source replay passes, every parent P0/P1
   is closed, open P0/P1 are both zero, and the stage itself is semantically closed.
8. The only acceptable bootstrap disposition when all stages pass is
   CANDIDATE4_R0_R2_ACCEPTS_EXACT_24_CALL_T2_BOOTSTRAP. It permits a later importer
   to create bound R0-R2 AI receipts; the separate authorization gate still limits
   the next phase to exactly 24 preallocated T2 calls with no test access.

Return exactly one JSON object conforming to audit-response.schema.json. Do not
wrap it in Markdown. In inspected_paths list every file whose semantic content you
used. Every evidence_paths and inspected_paths value must be an exact file path
listed in review-manifest.json (or review-manifest.json itself). Never cite a
directory such as bfcl-upstream, current-source, or evidence. reproduction_commands
must be read-only commands relative to this bundle.
"""


def response_schema() -> dict[str, Any]:
    stage = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {"enum": ["ACCEPTED", "REVISE"]},
            "rationale": {"type": "string"},
            "evidence_paths": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["decision", "rationale", "evidence_paths"],
    }
    finding = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "finding_id": {"type": "string", "minLength": 1},
            "severity": {"enum": ["P0", "P1", "P2", "P3"]},
            "status": {"enum": ["OPEN", "CLOSED", "ACCEPTED_RISK"]},
            "category": {"type": "string"},
            "title": {"type": "string"},
            "rationale": {"type": "string"},
            "evidence_paths": {"type": "array", "items": {"type": "string"}},
            "affected_stages": {"type": "array", "items": {"type": "string"}},
            "required_action": {"type": "string"},
        },
        "required": [
            "finding_id",
            "severity",
            "status",
            "category",
            "title",
            "rationale",
            "evidence_paths",
            "affected_stages",
            "required_action",
        ],
    }
    closure = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "finding_id": {"type": "string", "enum": list(PARENT_FINDINGS)},
            "status": {"enum": ["CLOSED", "OPEN"]},
            "rationale": {"type": "string"},
            "evidence_paths": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["finding_id", "status", "rationale", "evidence_paths"],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": "1.0"},
            "review_type": {"type": "string", "const": "AI_BLIND_SEMANTIC_AUDIT"},
            "authority": {"type": "string", "const": "AI_INDEPENDENT_PER_USER_POLICY"},
            "candidate_id": {"type": "string", "const": "candidate.4"},
            "model_requested": {"type": "string", "const": "gpt-5.6-sol"},
            "audit_role": {"type": "string", "const": "PRIMARY"},
            "bundle_entries_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "closed_set_boundary": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "repository_accessed": {"type": "boolean", "const": False},
                    "network_accessed": {"type": "boolean", "const": False},
                    "runtime_or_socket_accessed": {"type": "boolean", "const": False},
                    "external_protected_archive_accessed": {"type": "boolean", "const": False},
                    "materialized_historical_archive_inspected": {"type": "boolean"},
                    "prior_candidate4_review_read": {"type": "boolean", "const": False},
                    "semantic_scope_compliant": {"type": "boolean"},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "repository_accessed",
                    "network_accessed",
                    "runtime_or_socket_accessed",
                    "external_protected_archive_accessed",
                    "materialized_historical_archive_inspected",
                    "prior_candidate4_review_read",
                    "semantic_scope_compliant",
                    "limitations",
                ],
            },
            "manifest_validation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {"enum": ["PASS", "FAIL"]},
                    "entry_count": {"type": "integer", "minimum": 0},
                    "bundle_entries_sha256_recomputed": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "review_manifest_sha256_recomputed": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "mismatches": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "status",
                    "entry_count",
                    "bundle_entries_sha256_recomputed",
                    "review_manifest_sha256_recomputed",
                    "mismatches",
                ],
            },
            "source_inventory_validation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {"enum": ["PASS", "FAIL"]},
                    "entry_count": {"type": "integer", "minimum": 0},
                    "canonical_entries_sha256_recomputed": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "mismatches": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "status",
                    "entry_count",
                    "canonical_entries_sha256_recomputed",
                    "mismatches",
                ],
            },
            "parent_finding_closures": {"type": "array", "items": closure},
            "stage_assessments": {
                "type": "object",
                "additionalProperties": False,
                "properties": {stage_id: stage for stage_id in ("DG10-R0", "DG10-R1", "DG10-R2")},
                "required": ["DG10-R0", "DG10-R1", "DG10-R2"],
            },
            "bootstrap_policy_disposition": {
                "enum": [
                    "CANDIDATE4_R0_R2_ACCEPTS_EXACT_24_CALL_T2_BOOTSTRAP",
                    "REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL",
                ]
            },
            "findings": {"type": "array", "items": finding},
            "open_p0_count": {"type": "integer", "minimum": 0},
            "open_p1_count": {"type": "integer", "minimum": 0},
            "open_p2_count": {"type": "integer", "minimum": 0},
            "overall_disposition": {"enum": ["ACCEPT_R0_R2_FOR_T2_BOOTSTRAP", "REVISE"]},
            "inspected_paths": {"type": "array", "items": {"type": "string"}},
            "reproduction_commands": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "schema_version",
            "review_type",
            "authority",
            "candidate_id",
            "model_requested",
            "audit_role",
            "bundle_entries_sha256",
            "closed_set_boundary",
            "manifest_validation",
            "source_inventory_validation",
            "parent_finding_closures",
            "stage_assessments",
            "bootstrap_policy_disposition",
            "findings",
            "open_p0_count",
            "open_p1_count",
            "open_p2_count",
            "overall_disposition",
            "inspected_paths",
            "reproduction_commands",
        ],
    }


class ReviewBundleError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ReviewBundleError(reason)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewBundleError(f"invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def _destination_safe(value: str) -> None:
    parsed = PurePosixPath(value)
    _require(
        bool(parsed.parts)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
        and not {".git", ".env", "raw-sidecars"}.intersection(parsed.parts),
        f"unsafe review destination: {value}",
    )


def _add(
    materials: dict[str, tuple[str, bytes]], destination: str, source_class: str, raw: bytes
) -> None:
    _destination_safe(destination)
    existing = materials.get(destination)
    _require(existing is None or existing == (source_class, raw), f"review destination collision: {destination}")
    materials[destination] = (source_class, raw)


def _source_materials(materials: dict[str, tuple[str, bytes]]) -> dict[str, Any]:
    inventory = _load_object(SOURCE_INVENTORY)
    entries = inventory.get("entries")
    _require(
        inventory.get("schema") == "milai.dg10.candidate-source-inventory.v1"
        and inventory.get("candidate_id") == remediation.CANDIDATE
        and isinstance(entries, list)
        and inventory.get("entry_count") == len(entries),
        "candidate.4 source inventory invalid",
    )
    observed: list[dict[str, Any]] = []
    source_paths: list[Path] = []
    for entry in entries:
        _require(isinstance(entry, Mapping) and isinstance(entry.get("path"), str), "source entry invalid")
        relative = str(entry["path"])
        source = (ROOT / relative).resolve()
        _require(source.is_relative_to(ROOT) and source.is_file() and not source.is_symlink(), "source unsafe")
        raw = source.read_bytes()
        row = {"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
        _require(row == dict(entry), f"source inventory drift: {relative}")
        observed.append(row)
        source_paths.append(source)
        _add(materials, f"current-source/{relative}", "CANDIDATE4_SOURCE", raw)
    canonical = remediation.canonical_inventory(source_paths)["canonical_entries_sha256"]
    _require(canonical == inventory.get("canonical_entries_sha256"), "source aggregate drift")
    return inventory


def _archive_materials(materials: dict[str, tuple[str, bytes]]) -> int:
    seen: set[str] = set()
    with tarfile.open(remediation.BASELINE_ARCHIVE, mode="r:gz") as archive:
        for member in archive.getmembers():
            parsed = PurePosixPath(member.name)
            _require(
                member.isfile()
                and not parsed.is_absolute()
                and ".." not in parsed.parts
                and "\\" not in member.name
                and member.name not in seen,
                "historical archive member unsafe",
            )
            seen.add(member.name)
            handle = archive.extractfile(member)
            _require(handle is not None, "historical archive member unreadable")
            raw = handle.read()
            _require(len(raw) == member.size, "historical archive member size drift")
            _add(materials, f"historical-candidate2/{member.name}", "FROZEN_CANDIDATE2_ARCHIVE", raw)
    _require(len(seen) == 201, "historical archive denominator drift")
    return len(seen)


def _capture_materials(
    materials: dict[str, tuple[str, bytes]], capture_root: Path
) -> int:
    closure = _load_object(CLOSURE_REPORT)
    receipts: list[Mapping[str, Any]] = []
    fresh = closure.get("fresh_install")
    verification = closure.get("verification")
    _require(isinstance(fresh, Mapping) and isinstance(verification, Mapping), "R2 captures absent")
    captures = fresh.get("captures")
    _require(isinstance(captures, Mapping), "fresh-install captures absent")
    receipts.extend(value for value in captures.values() if isinstance(value, Mapping))
    for key in ("collection", "pytest", "ruff"):
        row = verification.get(key)
        _require(isinstance(row, Mapping) and isinstance(row.get("capture"), Mapping), "test capture absent")
        receipts.append(row["capture"])
    bfcl = closure.get("bfcl")
    _require(isinstance(bfcl, Mapping), "BFCL closure absent")
    bfcl_captures = bfcl.get("captures")
    _require(isinstance(bfcl_captures, Mapping), "BFCL captures absent")
    receipts.extend(
        value for value in bfcl_captures.values() if isinstance(value, Mapping)
    )
    seen: set[str] = set()
    for receipt in receipts:
        capture_id = receipt.get("capture_id")
        _require(isinstance(capture_id, str) and capture_id not in seen, "capture ID invalid")
        seen.add(capture_id)
        parsed = PurePosixPath(capture_id)
        _require(not parsed.is_absolute() and ".." not in parsed.parts, "capture path unsafe")
        source = (capture_root / capture_id).resolve()
        _require(source.is_relative_to(capture_root) and source.is_file() and not source.is_symlink(), "capture missing")
        raw = source.read_bytes()
        _require(
            hashlib.sha256(raw).hexdigest() == receipt.get("sha256")
            and len(raw) == receipt.get("size")
            and stat.S_IMODE(source.stat().st_mode) == 0o600,
            "capture receipt drift",
        )
        _add(materials, f"r2-captures/{capture_id}", "R2_SANITIZED_CAPTURE", raw)
    return len(seen)


def _bfcl_source_materials(
    materials: dict[str, tuple[str, bytes]],
) -> dict[str, Any]:
    closure = _load_object(CLOSURE_REPORT)
    bfcl = closure.get("bfcl")
    _require(isinstance(bfcl, Mapping), "BFCL source closure absent")
    entries = bfcl.get("entries")
    _require(
        isinstance(entries, list)
        and bfcl.get("tracked_file_count") == len(entries) == 192,
        "BFCL source denominator drift",
    )
    aggregate = hashlib.sha256()
    previous: str | None = None
    for entry in entries:
        _require(
            isinstance(entry, Mapping)
            and set(entry) == {"path", "sha256", "size"},
            "BFCL source entry shape drift",
        )
        relative = entry.get("path")
        _require(
            isinstance(relative, str)
            and relative
            and (previous is None or previous < relative),
            "BFCL source order or path drift",
        )
        previous = relative
        parsed = PurePosixPath(relative)
        _require(
            not parsed.is_absolute() and ".." not in parsed.parts,
            "BFCL source path unsafe",
        )
        source = (BFCL_ROOT / parsed).absolute()
        _require(
            source.is_relative_to(BFCL_ROOT.absolute())
            and not remediation.has_symlink_component(source)
            and source.is_file(),
            "BFCL tracked source is missing or unsafe",
        )
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        _require(
            digest == entry.get("sha256") and len(raw) == entry.get("size"),
            f"BFCL tracked source drift: {relative}",
        )
        aggregate.update(relative.encode())
        aggregate.update(b"\0")
        aggregate.update(digest.encode())
        aggregate.update(b"\0")
        _add(
            materials,
            f"bfcl-upstream/{relative}",
            "UPSTREAM_BFCL_TRACKED_SOURCE",
            raw,
        )
    root = aggregate.hexdigest()
    _require(
        root == bfcl.get("canonical_entries_sha256"),
        "BFCL tracked source aggregate drift",
    )
    return {"entry_count": len(entries), "canonical_entries_sha256": root}


def _materials(capture_root: Path) -> tuple[dict[str, tuple[str, bytes]], dict[str, Any]]:
    materials: dict[str, tuple[str, bytes]] = {}
    inventory = _source_materials(materials)
    for relative in EVIDENCE_PATHS:
        source = (ROOT / relative).resolve()
        _require(source.is_relative_to(ROOT) and source.is_file() and not source.is_symlink(), f"evidence absent: {relative}")
        _add(materials, f"evidence/{relative}", "BOUND_EVIDENCE", source.read_bytes())
    archive_count = _archive_materials(materials)
    capture_count = _capture_materials(materials, capture_root.resolve())
    bfcl_source = _bfcl_source_materials(materials)
    _add(materials, "audit-prompt.md", "AUDIT_PROTOCOL", REVIEW_PROMPT.encode())
    _add(
        materials,
        "audit-response.schema.json",
        "AUDIT_PROTOCOL",
        remediation.encoded_json(response_schema()),
    )
    return materials, {
        "source_entry_count": inventory["entry_count"],
        "source_entries_sha256": inventory["canonical_entries_sha256"],
        "archive_member_count": archive_count,
        "r2_capture_count": capture_count,
        "bfcl_tracked_source_entry_count": bfcl_source["entry_count"],
        "bfcl_tracked_source_sha256": bfcl_source["canonical_entries_sha256"],
    }


def build_bundle(
    *, output_root: Path, capture_root: Path, secret_source: Path
) -> tuple[Path, dict[str, Any]]:
    materials, closure = _materials(capture_root)
    secrets = _secrets(secret_source)
    entries: list[dict[str, Any]] = []
    for destination, (source_class, raw) in sorted(materials.items()):
        _require(not any(secret in raw for secret in secrets), f"secret value in review material: {destination}")
        entries.append(
            {
                "path": destination,
                "source_class": source_class,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    entries_sha256 = remediation.sha256_bytes(remediation.encoded_json({"entries": entries}))
    manifest = {
        "schema": "milai.dg10.candidate4-ai-review-manifest.v1",
        "candidate_id": remediation.CANDIDATE,
        "created_at": datetime.now(UTC).isoformat(),
        "review_scope": ["DG10-R0", "DG10-R1", "DG10-R2", "T2_BOOTSTRAP_POLICY"],
        "bundle_entries_sha256": entries_sha256,
        "entry_count": len(entries),
        "entries": entries,
        "closure": closure,
        "boundaries": {
            "read_only": True,
            "closed_set_only": True,
            "repository_access_forbidden": True,
            "network_forbidden": True,
            "runtime_socket_forbidden": True,
            "raw_current_benchmark_sidecars_included": False,
            "test_labels_or_outputs_included": False,
            "historical_sanitized_archive_materialized": True,
            "upstream_bfcl_tracked_source_materialized": True,
            "human_evidence_claimed": False,
            "ai_authority_per_user_policy": True,
            "model_calls_authorized_by_bundle": False,
            "full_test_access_authorized": False,
            "release_authorized": False,
        },
    }
    manifest_raw = remediation.encoded_json(manifest)
    output_root = output_root.resolve()
    if output_root == DEFAULT_OUTPUT_ROOT.resolve():
        policy = ai_provenance.load_authority_policy()
        output_root.mkdir(parents=True, exist_ok=True, mode=0o750)
        root_stat = output_root.stat()
        _require(
            not output_root.is_symlink()
            and root_stat.st_uid == 0
            and root_stat.st_gid == policy["authority_gid"]
            and stat.S_IMODE(root_stat.st_mode) == 0o750,
            "fixed review root is not root-controlled and authority-readable",
        )
    else:
        output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        output_root.chmod(0o700)
    final = output_root / f"sha256-{entries_sha256}"
    _require(not final.exists(), f"refusing to overwrite review bundle: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=".candidate4-ai-review-", dir=output_root))
    try:
        for destination, (_source_class, raw) in materials.items():
            target = temporary / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        manifest_path = temporary / "review-manifest.json"
        descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(manifest_raw)
            stream.flush()
            os.fsync(stream.fileno())
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(0o555)
        temporary.chmod(0o555)
        os.replace(temporary, final)
    except BaseException:
        if temporary.exists():
            for path in sorted(temporary.rglob("*"), reverse=True):
                path.chmod(0o755 if path.is_dir() else 0o644)
            temporary.chmod(0o755)
            shutil.rmtree(temporary)
        raise
    files = [path for path in final.rglob("*") if path.is_file()]
    directories = [path for path in final.rglob("*") if path.is_dir()]
    _require(
        all(stat.S_IMODE(path.stat().st_mode) == 0o444 for path in files)
        and all(stat.S_IMODE(path.stat().st_mode) == 0o555 for path in [final, *directories]),
        "materialized AI review bundle is not read-only",
    )
    receipt = {
        "schema": "milai.dg10.candidate4-ai-review-bundle-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "status": "R0_R2_AI_REVIEW_BUNDLE_READY",
        "bundle_directory_id": final.name,
        "bundle_path_class": "REPO_EXTERNAL_READ_ONLY_MATERIALIZED_WORKSPACE",
        "bundle_entries_sha256": entries_sha256,
        "entry_count": len(entries),
        "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "closure": closure,
        "secret_scan": {
            "status": "PASS",
            "secret_value_count": len(secrets),
            "matching_files": [],
        },
        "filesystem": {
            "file_mode": "0444",
            "directory_mode": "0555",
            "file_count_including_manifest": len(files),
        },
        "boundaries": manifest["boundaries"],
        "minimum_primary_ai_audits": 2,
        "accepted_stages": [],
        "model_run_authorized": False,
        "test_access_authorized": False,
        "release_authorized": False,
        "independent_acceptance": False,
    }
    return final, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Build candidate.4 R0-R2 AI review bundle")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--capture-root", type=Path, default=DEFAULT_CAPTURE_ROOT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--secret-source", type=Path, default=ROOT / "runtime/.env")
    args = parser.parse_args()
    _require(args.candidate == remediation.CANDIDATE, "candidate identity mismatch")
    bundle, receipt = build_bundle(
        output_root=args.output,
        capture_root=args.capture_root,
        secret_source=args.secret_source.resolve(),
    )
    remediation.atomic_write_new(args.receipt.resolve(), remediation.encoded_json(receipt))
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "bundle": str(bundle),
                "bundle_entries_sha256": receipt["bundle_entries_sha256"],
                "receipt": str(args.receipt.resolve()),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
