"""Versioned offline root binding for prospective V0223 CPU measurements.

This is NOT live authorization. The dedicated fresh process must install socket
denial before importing the replay stack. Construction and authorization retain
all scoped checks but bind a separate CPU contract. All dynamic journal, claim,
accounting, reference, terminal and parent-gate methods are inherited unchanged.
Only new CPU roots and coordinator marker differ from the V0222 binding.
Dynamic methods remain inherited unchanged; importing creates no instance.
"""

from __future__ import annotations

import os
from pathlib import Path

from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_batch_v2 import (
    BOUNDARY_BINDING,
    BOUNDARY_ROOT,
    IDENTITY,
    PARENT_BINDING,
    PARENT_ROOT,
    PRESENTATION_BINDING,
    PRESENTATION_ROOT,
    REVISION,
    ROOT,
    make_authorization,
)
from v0222_presentation_finish_v2 import Batch as LiveBatch
from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard
from v0222_scoped_evidence import _guard, verify_manifest

# Fixed prospective instances, never selected by model input.
CPU_BASE = Path("/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-diagnostic-v1")
INSTANCE_NAMES = frozenset({"d1-u1", "d1-s1", "d1-s2", "d1-u2", "d1-u3", "d1-s3"})
CPU_REVISION = "V0223_INVENTORY_DIAGNOSTIC_CPU_V1"


def selected_root() -> Path:
    name = os.environ.get("MILA_V0223_INSTANCE", "")
    if name not in INSTANCE_NAMES:
        raise ProviderStop("EXPLICIT_FROZEN_V0223_INSTANCE_REQUIRED")
    return CPU_BASE / ("diagv1-" + name)


def cpu_authorization_source() -> dict:
    return {
        "origin": "USER_DIRECTED_V0224_EXECUTION_SUBAGENT_REVIEWED",
        "execution_mode": CPU_MODE,
        "coordinator_revision": CPU_REVISION,
        "stages": ["PREP", "P3", "P4"],
        "real_http_allowed": False,
        "device_calls_allowed": False,
        "mock_cost_is_not_real_cost": True,
        "model_capability_or_live_admission": False,
    }


def make_cpu_authorization(root: Path, *, issued: float, expires: float, history: dict) -> dict:
    """Pure contract data, not a directory creation or a grant of HTTP authority."""
    if root != selected_root() or root.resolve() != root:
        raise ProviderStop("ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED")
    return {
        **make_authorization(ROOT, issued=issued, expires=expires, history=history),
        "root": str(root),
        "batch_id": root.name,
        "coordinator_revision": CPU_REVISION,
        "execution_mode": CPU_MODE,
        "real_http_allowed": False,
        "device_calls_allowed": False,
        "mock_cost_is_not_real_cost": True,
    }


class OfflineBatch(LiveBatch):
    def __init__(self, root: Path, binding_sha: str):
        require_cpu_network_guard()
        if root != selected_root() or root.resolve() != root:
            raise ProviderStop("ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED")
        self.root, self.binding_sha = root, binding_sha
        self.path = root / "batch.sqlite"
        with AdmissionReadScope() as scope:
            self.binding = scope.read_json(root / "execution-binding.json", binding_sha)
            self.auth, self.plan = self._authorize("PREP", scope)
        self._time_check(self.auth)

    def _authorize(self, stage: str, scope: AdmissionReadScope) -> tuple[dict, dict]:
        from v0222_presentation_lineage_v2 import verify_lineage

        require_cpu_network_guard()
        with _guard(scope):
            binding = scope.read_json(self.root / "execution-binding.json", self.binding_sha)
            if set(binding) != {"authorization.json", "authorization-source.json", "manifest.json"}:
                raise ProviderStop("EXACT_EXECUTION_BINDING_REQUIRED")
            if fingerprint(binding) != fingerprint(self.binding):
                raise ProviderStop("IN_MEMORY_BINDING_DRIFT")
            auth = scope.read_json(self.root / "authorization.json", binding["authorization.json"])
            grant = scope.read_json(
                self.root / "authorization-source.json", binding["authorization-source.json"]
            )
            history = verify_lineage(scope)
            expected = make_cpu_authorization(
                self.root, issued=auth["issued_unix"], expires=auth["expires_unix"], history=history
            )
            if fingerprint(auth) != fingerprint(expected):
                raise ProviderStop("EXACT_SCOPED_CPU_CONTRACT_AND_HISTORY_REQUIRED")
            if fingerprint(grant) != fingerprint(cpu_authorization_source()):
                raise ProviderStop("EXPLICIT_CPU_ONLY_SOURCE_REQUIRED")
            if stage not in auth["stages"]:
                raise ProviderStop("STAGE_NOT_AUTHORIZED")
            self._time_check(auth)
            manifest = verify_manifest(scope, self.root, binding["manifest.json"])
            plan = manifest["contract"]
            required = {
                "revision": REVISION,
                "coordinator_revision": CPU_REVISION,
                "execution_mode": CPU_MODE,
                "real_http_allowed": False,
                "device_calls_allowed": False,
                "mock_cost_is_not_real_cost": True,
                "selected_decoder": "D11",
                "selected_presentation": "B1",
                "parent_root": str(PARENT_ROOT),
                "parent_binding": PARENT_BINDING,
                "boundary_root": str(BOUNDARY_ROOT),
                "boundary_binding": BOUNDARY_BINDING,
                "presentation_root": str(PRESENTATION_ROOT),
                "presentation_binding": PRESENTATION_BINDING,
                "historical_paths": [row["path"] for row in history["sources"]],
                "http_identity": IDENTITY,
            }
            if any(fingerprint(plan.get(k)) != fingerprint(v) for k, v in required.items()):
                raise ProviderStop("FROZEN_SCOPED_CPU_CONTRACT_REQUIRED")
            if (hasattr(self, "plan") and fingerprint(plan) != fingerprint(self.plan)) or (
                hasattr(self, "auth") and fingerprint(auth) != fingerprint(self.auth)
            ):
                raise ProviderStop("IN_MEMORY_AUTHORIZATION_OR_PLAN_DRIFT")
            self._validate_plan(scope, plan)
            return auth, plan
