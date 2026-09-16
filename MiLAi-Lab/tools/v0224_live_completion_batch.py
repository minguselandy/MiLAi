"""Prospective B/C binding; original R04 fresh admissions and live deadlines.

Importing grants no HTTP authority. A concrete Gate A certificate and source
binding are required before construction. No CPU fixture can be resumed here.
"""

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
    make_authorization,
)
from v0222_presentation_batch_v2 import (
    ROOT as ORIGINAL_ROOT,
)
from v0222_presentation_batch_v2 import (
    Batch as OriginalJournal,
)
from v0222_scoped_evidence import _guard, verify_manifest
from v0224_k3_cpu_batch import OfflineBatch
from v0224_verified_digest_batch import StaticAuthority
from v0224_verified_digest_lineage import verify_lineage_r03

ROOT = Path("/cra/memory/mx_memory/evidence/v0224/20260913-live-completion-v1/livev1-bc")
LIVE_REVISION = "V0224_R03_R04_LIVE_COMPLETION_01"
LIVE_MODE = "LIVE_HTTP_B1_D11"
GATE_A_STATUS = "GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY"
AUXILIARY_LIMITS = {
    "P3": {"identity_get": 36, "tokenize_post": 48, "generation_post": 16},
    "P4": {"identity_get": 52, "tokenize_post": 256, "generation_post": 96},
}


def authorization_source():
    return {
        "origin": "USER_DIRECTED_V0224_EXECUTION_SUBAGENT_REVIEWED",
        "coordinator_revision": LIVE_REVISION,
        "execution_mode": LIVE_MODE,
        "stages": ["PREP", "P3", "P4"],
        "real_http_allowed": True,
        "device_calls_allowed": False,
        "prior_passes_do_not_offset_new_matrix": True,
        "unknown_usage_stops_all": True,
        "gate_a_required": GATE_A_STATUS,
    }


def make_live_authorization(root, *, issued, expires, history, gate_a):
    if root != ROOT or root.resolve() != root:
        raise ProviderStop("ONE_FIXED_FRESH_LIVE_ROOT_REQUIRED")
    return {
        **make_authorization(ORIGINAL_ROOT, issued=issued, expires=expires, history=history),
        "root": str(root),
        "batch_id": root.name,
        "coordinator_revision": LIVE_REVISION,
        "execution_mode": LIVE_MODE,
        "real_http_allowed": True,
        "device_calls_allowed": False,
        "auxiliary_limits": AUXILIARY_LIMITS,
        "gate_a": dict(gate_a),
    }


class Batch(OfflineBatch):
    # These original live methods share PHASE_SECONDS (1800/7200). They replace
    # all three CPU phase overrides together; claim 300 remains the original.
    launch_once = OriginalJournal.launch_once
    _check_journal = OriginalJournal._check_journal
    _check_claims = OriginalJournal._check_claims

    def __init__(self, root, binding_sha, *, static_authority, gate_a_path, gate_a_sha256):
        if root != ROOT or root.resolve() != root:
            raise ProviderStop("ONE_FIXED_FRESH_LIVE_ROOT_REQUIRED")
        if type(static_authority) is not StaticAuthority:
            raise ProviderStop("EXPLICIT_IMMUTABLE_STATIC_AUTHORITY_REQUIRED")
        gate_a_path = Path(gate_a_path)
        if not gate_a_path.is_absolute() or gate_a_path.resolve() != gate_a_path:
            raise ProviderStop("CANONICAL_EXTERNAL_GATE_A_REQUIRED")
        self._gate_a = {"path": str(gate_a_path), "sha256": gate_a_sha256}
        self._static_authority = static_authority
        self.root, self.binding_sha = root, binding_sha
        self.path = root / "batch.sqlite"
        with self._new_scope() as scope:
            self.binding = scope.read_json(root / "execution-binding.json", binding_sha)
            self.auth, self.plan = self._authorize("PREP", scope)
        self._time_check(self.auth)

    def _authorize(self, stage: str, scope: AdmissionReadScope) -> tuple[dict, dict]:
        with _guard(scope):
            gate = scope.read_json(Path(self._gate_a["path"]), self._gate_a["sha256"])
            if gate.get("status") != GATE_A_STATUS or gate.get("blocking_findings") != []:
                raise ProviderStop("COMPLETE_FUNCTIONAL_GATE_A_REQUIRED")
            if not gate.get("files"):
                raise ProviderStop("CURRENT_GATE_A_EVIDENCE_REQUIRED")
            for path, digest in gate["files"].items():
                with scope.physical_reads():
                    scope.read_bytes(Path(path), digest)
            binding = scope.read_json(self.root / "execution-binding.json", self.binding_sha)
            if set(binding) != {"authorization.json", "authorization-source.json", "manifest.json"}:
                raise ProviderStop("EXACT_EXECUTION_BINDING_REQUIRED")
            if fingerprint(binding) != fingerprint(self.binding):
                raise ProviderStop("IN_MEMORY_BINDING_DRIFT")
            auth = scope.read_json(self.root / "authorization.json", binding["authorization.json"])
            grant = scope.read_json(
                self.root / "authorization-source.json", binding["authorization-source.json"]
            )
            history = verify_lineage_r03(scope)
            expected = make_live_authorization(
                self.root,
                issued=auth["issued_unix"],
                expires=auth["expires_unix"],
                history=history,
                gate_a=self._gate_a,
            )
            if fingerprint(auth) != fingerprint(expected):
                raise ProviderStop("EXACT_LIVE_CONTRACT_AND_HISTORY_REQUIRED")
            if fingerprint(grant) != fingerprint(authorization_source()):
                raise ProviderStop("EXPLICIT_LIVE_SOURCE_REQUIRED")
            if stage not in auth["stages"]:
                raise ProviderStop("STAGE_NOT_AUTHORIZED")
            self._time_check(auth)
            manifest = verify_manifest(scope, self.root, binding["manifest.json"])
            plan = manifest["contract"]
            required = {
                "static_authority": self._static_authority.contract_value(),
                "gate_a": self._gate_a,
                "revision": REVISION,
                "coordinator_revision": LIVE_REVISION,
                "execution_mode": LIVE_MODE,
                "real_http_allowed": True,
                "device_calls_allowed": False,
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
                raise ProviderStop("FROZEN_LIVE_CONTRACT_REQUIRED")
            if (hasattr(self, "plan") and fingerprint(plan) != fingerprint(self.plan)) or (
                hasattr(self, "auth") and fingerprint(auth) != fingerprint(self.auth)
            ):
                raise ProviderStop("IN_MEMORY_AUTHORIZATION_OR_PLAN_DRIFT")
            self._validate_plan(scope, plan)
            return auth, plan
