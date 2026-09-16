from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts import dg10_authorization as authorization
from scripts import dg10_remediation as remediation
from scripts import dg10_stage_ledger as stage_ledger

ACTIVE_POST_R3_AUTHORIZATION = remediation.ROOT / (
    "docs/reports/DG-10-model-run-authorization-post-r3-candidate.4-2026-08-22.json"
)


class PostR3ProviderGateError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise PostR3ProviderGateError(reason)


def require_post_r3_provider_access() -> dict[str, Any]:
    """Revalidate the fixed accepted R3 state before non-bootstrap completion I/O."""

    path = ACTIVE_POST_R3_AUTHORIZATION.absolute()
    fixed = remediation.ROOT / (
        "docs/reports/DG-10-model-run-authorization-post-r3-candidate.4-2026-08-22.json"
    )
    _require(
        path == fixed.absolute()
        and path.is_relative_to(remediation.ROOT.absolute())
        and not remediation.has_symlink_component(path)
        and path.is_file(),
        "fixed post-R3 model authorization is absent or unsafe",
    )
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PostR3ProviderGateError("post-R3 model authorization is invalid") from exc
    required = {
        "schema",
        "candidate_id",
        "phase",
        "status",
        "provider_requests",
        "model_outputs_opened",
        "test_access_authorized",
        "authorization",
    }
    _require(
        isinstance(envelope, Mapping)
        and set(envelope) == required
        and envelope.get("schema") == "milai.dg10.post-r3-model-preflight.v1"
        and envelope.get("candidate_id") == remediation.CANDIDATE
        and envelope.get("phase") == authorization.POST_R3_PHASE
        and envelope.get("status") == "AUTHORIZED_READY_FOR_POST_R3_EXECUTION"
        and envelope.get("provider_requests") == 0
        and envelope.get("model_outputs_opened") is False
        and envelope.get("test_access_authorized") is False
        and isinstance(envelope.get("authorization"), Mapping),
        "post-R3 model authorization envelope drift",
    )
    bound = dict(envelope["authorization"])
    try:
        authorization.require_first_model_authorization(bound)
        reconciliation = stage_ledger.reconcile_stage_ledger()
    except (authorization.AuthorizationError, stage_ledger.StageLedgerError) as exc:
        raise PostR3ProviderGateError("post-R3 acceptance replay failed") from exc
    _require(
        bound.get("phase") == authorization.POST_R3_PHASE,
        "provider authorization is not post-R3",
    )
    stage_receipts = bound.get("stage_receipts")
    r3 = reconciliation.get("current_entries", {}).get("DG10-R3")
    _require(
        isinstance(stage_receipts, list)
        and len(stage_receipts) == 4
        and isinstance(stage_receipts[-1], Mapping)
        and isinstance(r3, Mapping)
        and r3.get("stage_state") == "ACCEPTED"
        and r3.get("receipt")
        == {key: stage_receipts[-1][key] for key in ("path", "sha256")},
        "post-R3 authorization is not the active accepted R3 ledger state",
    )
    return dict(envelope)


def materialize_container_capability(output_path: Path) -> dict[str, Any]:
    """Create a one-run, read-only bearer capability after full host replay."""

    envelope = require_post_r3_provider_access()
    authorization_value = envelope["authorization"]
    _require(
        isinstance(authorization_value, Mapping),
        "post-R3 authorization payload is absent",
    )
    stage_receipts = authorization_value.get("stage_receipts")
    identities = authorization_value.get("identities")
    _require(
        isinstance(stage_receipts, list)
        and len(stage_receipts) == 4
        and isinstance(stage_receipts[-1], Mapping)
        and isinstance(identities, Mapping)
        and isinstance(identities.get("source_inventory_sha256"), str),
        "post-R3 container capability inputs are incomplete",
    )
    fixed_authorization = ACTIVE_POST_R3_AUTHORIZATION.absolute()
    capability = {
        "schema": "milai.dg10.post-r3-provider-capability.v1",
        "candidate_id": remediation.CANDIDATE,
        "phase": authorization.POST_R3_PHASE,
        "authorization_sha256": remediation.sha256_file(fixed_authorization),
        "r3_stage_receipt_sha256": stage_receipts[-1].get("sha256"),
        "source_inventory_root_sha256": identities["source_inventory_sha256"],
        "provider_access": "ALLOW_FIXED_LOCAL_VLLM_ONLY",
    }
    for key in (
        "authorization_sha256",
        "r3_stage_receipt_sha256",
        "source_inventory_root_sha256",
    ):
        remediation._require_sha256(capability[key], f"provider capability {key}")
    remediation.atomic_write_new(
        output_path.absolute(), remediation.encoded_json(capability), mode=0o400
    )
    return capability
