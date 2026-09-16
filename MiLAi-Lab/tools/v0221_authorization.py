"""Path-B authorization validation; no historical settlement or model calls.

The conversation grant is an operator-recorded provenance artifact, not a digital
signature. Its trusted digest must be supplied by the coordinator's frozen config.
"""

from __future__ import annotations

import time
from pathlib import Path

from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import read, sha
from v0220_provider_hardened import ProviderStop, historical_usage

REVISION = "V0221_EXACT_HISTORICAL_CARRY_V1"
BASE = Path("/cra/memory/mx_memory/evidence/v0220")
HISTORY = (
    BASE / "provider-compat-v1/provider-ledger.jsonl",
    BASE / "v2-candidate1-v1/episodes/v2c1-01/provider-ledger.jsonl",
)


def check_authorization(
    root: Path, expected_sha: str, source_sha: str, *, stage: str, now: float | None = None
) -> dict:
    root = root.resolve()
    path = root / "authorization.json"
    if not path.is_file() or sha(path) != expected_sha:
        raise ProviderStop("AUTHORIZATION_MISSING_OR_DRIFTED")
    auth = read(path)
    source = root / "authorization-source.json"
    if not source.is_file() or sha(source) != source_sha or auth["source_sha256"] != source_sha:
        raise ProviderStop("AUTHORIZATION_SOURCE_DRIFT")
    grant = read(source)
    if (
        grant.get("origin") != "USER_CONVERSATION"
        or grant.get("reply") != "授权"
        or grant.get("path") != "B"
        or grant.get("historical_unknown_explicit") is not True
        or set(auth["allowed_stages"]) - set(grant["allowed_stages"])
    ):
        raise ProviderStop("EXPLICIT_USER_GRANT_REQUIRED")
    if (
        auth.get("revision") != REVISION
        or auth.get("path") != "B"
        or auth.get("historical_usage_settled") is not False
        or auth.get("reconciliation") is not None
    ):
        raise ProviderStop("UNREVIEWED_RECONCILIATION_OR_POLICY")
    if auth["evidence_root"] != str(root) or auth["batch_id"] != root.name:
        raise ProviderStop("AUTHORIZATION_OTHER_BATCH_OR_DIRECTORY")
    now = time.time() if now is None else now
    if not auth["issued_unix"] <= now < auth["expires_unix"]:
        raise ProviderStop("AUTHORIZATION_NOT_CURRENT")
    if stage not in auth["allowed_stages"] or stage not in {"W1", "W2", "W3", "W4"}:
        raise ProviderStop("STAGE_NOT_AUTHORIZED")
    if (
        auth["endpoint"] != ENDPOINT
        or auth["model"] != MODEL
        or auth["request_caps"] != {"W1": 0, "W2": 16, "W3": 96, "W4": 0}
        or auth["model_concurrency"] != 1
        or auth["raw_token_cap"] is not None
        or auth.get("new_unknown_stops_batch") is not True
        or auth.get("automatic_retry") is not False
        or auth.get("shared_service_changes") is not False
        or auth.get("new_tasks_or_state") is not False
    ):
        raise ProviderStop("AUTHORIZATION_SCOPE_DRIFT")
    expected_history = [str(p.resolve()) for p in HISTORY]
    if [s["path"] for s in auth["historical"]["sources"]] != expected_history:
        raise ProviderStop("COMPLETE_OLD_HISTORY_REQUIRED")
    actual = historical_usage(HISTORY)
    if actual != auth["historical"] or actual["violations"]:
        raise ProviderStop("HISTORICAL_LEDGER_OR_UNKNOWN_SET_DRIFT")
    if auth["accepted_unknown"] != actual["unresolved_reservations"]:
        raise ProviderStop("HISTORICAL_EXCEPTION_NOT_EXACT")
    for name, expected in auth["implementation_sha256"].items():
        if sha(Path(name)) != expected:
            raise ProviderStop("AUTHORIZED_IMPLEMENTATION_DRIFT")
    return auth
