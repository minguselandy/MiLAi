"""Offline scope validation only, not a batch coordinator or live dispatch admission."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0221_authorization as policy
from v02_local_provider import append_event
from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop, historical_usage


def fixture(tmp_path, monkeypatch):
    paths = (tmp_path / "old-compat.jsonl", tmp_path / "old-failed.jsonl")
    paths[0].touch()
    append_event(
        paths[1],
        {
            "event": "RESERVED",
            "request_id": "old-unknown",
            "session": "old",
            "prompt_tokens": 100,
            "output_cap": 4096,
            "raw_upper_bound": 4196,
        },
    )
    monkeypatch.setattr(policy, "HISTORY", paths)
    root = tmp_path / "owned-batch"
    root.mkdir()
    grant = {
        "origin": "USER_CONVERSATION",
        "reply": "授权",
        "path": "B",
        "historical_unknown_explicit": True,
        "allowed_stages": ["W1", "W2", "W3", "W4"],
    }
    save(root / "authorization-source.json", grant)
    history = historical_usage(paths)
    auth = {
        "source_sha256": sha(root / "authorization-source.json"),
        "revision": policy.REVISION,
        "path": "B",
        "historical_usage_settled": False,
        "reconciliation": None,
        "evidence_root": str(root),
        "batch_id": root.name,
        "issued_unix": 100,
        "expires_unix": 200,
        "allowed_stages": ["W1", "W2", "W3", "W4"],
        "endpoint": ENDPOINT,
        "model": MODEL,
        "request_caps": {"W1": 0, "W2": 16, "W3": 96, "W4": 0},
        "model_concurrency": 1,
        "raw_token_cap": None,
        "new_unknown_stops_batch": True,
        "automatic_retry": False,
        "shared_service_changes": False,
        "new_tasks_or_state": False,
        "historical": history,
        "accepted_unknown": history["unresolved_reservations"],
        "implementation_sha256": {str(Path(policy.__file__)): sha(Path(policy.__file__))},
    }
    return root, paths, auth


def validate(root, auth, *, stage="W2", now=150):
    save(root / "authorization.json", auth)
    return policy.check_authorization(
        root,
        sha(root / "authorization.json"),
        sha(root / "authorization-source.json"),
        stage=stage,
        now=now,
    )


def test_exact_grant_preserves_old_unknown_not_settled(tmp_path, monkeypatch):
    root, paths, auth = fixture(tmp_path, monkeypatch)
    before = [p.read_bytes() for p in paths]
    observed = validate(root, auth)
    assert observed["historical_usage_settled"] is False
    assert observed["historical"]["actual_total_raw_tokens"] is None
    assert not observed["historical"]["new_generation_allowed"]
    assert [p.read_bytes() for p in paths] == before


@pytest.mark.parametrize(
    "mutation",
    [
        "path_a",
        "fake_receipt",
        "settle_zero",
        "other_batch",
        "other_directory",
        "stage",
        "wrong_model",
        "wrong_endpoint",
        "extra_requests",
        "concurrency",
        "retry",
        "unknown_waiver",
        "service_change",
        "new_state",
        "omit_history",
        "wrong_unknown",
        "code_hash",
    ],
)
def test_authorization_scope_and_exact_history_negative_controls(tmp_path, monkeypatch, mutation):
    root, _, auth = fixture(tmp_path, monkeypatch)
    if mutation == "path_a":
        auth["path"] = "A"
    elif mutation == "fake_receipt":
        auth["reconciliation"] = {"usage": 0, "source": "CPU_PASS"}
    elif mutation == "settle_zero":
        auth["historical_usage_settled"] = True
    elif mutation == "other_batch":
        auth["batch_id"] = "different"
    elif mutation == "other_directory":
        auth["evidence_root"] = str(root.parent / "different")
    elif mutation == "stage":
        auth["allowed_stages"] = ["W1", "W2"]
    elif mutation == "wrong_model":
        auth["model"] = "different"
    elif mutation == "wrong_endpoint":
        auth["endpoint"] = "http://example.invalid"
    elif mutation == "extra_requests":
        auth["request_caps"]["W3"] = 97
    elif mutation == "concurrency":
        auth["model_concurrency"] = 2
    elif mutation == "retry":
        auth["automatic_retry"] = True
    elif mutation == "unknown_waiver":
        auth["new_unknown_stops_batch"] = False
    elif mutation == "service_change":
        auth["shared_service_changes"] = True
    elif mutation == "new_state":
        auth["new_tasks_or_state"] = True
    elif mutation == "omit_history":
        auth["historical"]["sources"].pop(0)
    elif mutation == "wrong_unknown":
        auth["accepted_unknown"] = []
    else:
        auth["implementation_sha256"][str(Path(policy.__file__))] = "wrong"
    with pytest.raises(ProviderStop):
        validate(root, auth, stage="W3")


@pytest.mark.parametrize("now", [99, 200, 201])
def test_not_yet_valid_and_expired_grants(tmp_path, monkeypatch, now):
    root, _, auth = fixture(tmp_path, monkeypatch)
    with pytest.raises(ProviderStop, match="NOT_CURRENT"):
        validate(root, auth, now=now)


def test_missing_and_changed_authorization_cannot_be_used(tmp_path, monkeypatch):
    root, _, auth = fixture(tmp_path, monkeypatch)
    with pytest.raises(ProviderStop, match="MISSING_OR_DRIFTED"):
        policy.check_authorization(root, "missing", "missing", stage="W2", now=150)
    validate(root, auth)
    expected, source = sha(root / "authorization.json"), sha(root / "authorization-source.json")
    (root / "authorization.json").write_text("{}")
    with pytest.raises(ProviderStop, match="MISSING_OR_DRIFTED"):
        policy.check_authorization(root, expected, source, stage="W2", now=150)


def test_new_historical_unknown_cannot_join_existing_exception(tmp_path, monkeypatch):
    root, paths, auth = fixture(tmp_path, monkeypatch)
    append_event(
        paths[1],
        {
            "event": "RESERVED",
            "request_id": "new-unknown",
            "session": "other",
            "prompt_tokens": 2,
            "output_cap": 4096,
            "raw_upper_bound": 4098,
        },
    )
    with pytest.raises(ProviderStop, match="HISTORICAL_LEDGER_OR_UNKNOWN_SET_DRIFT"):
        validate(root, auth)


def test_old_violations_not_waived_even_if_recorded_in_grant(tmp_path, monkeypatch):
    root, paths, auth = fixture(tmp_path, monkeypatch)
    append_event(paths[1], {"event": "BOUND_VIOLATION", "request_id": "old-unknown"})
    auth["historical"] = historical_usage(paths)
    with pytest.raises(ProviderStop, match="HISTORICAL_LEDGER_OR_UNKNOWN_SET_DRIFT"):
        validate(root, auth)


def test_source_drift_and_self_signed_grant_rejected(tmp_path, monkeypatch):
    root, _, auth = fixture(tmp_path, monkeypatch)
    source = root / "authorization-source.json"
    grant = copy.deepcopy(read(source))
    grant["origin"] = "AGENT_SELF_APPROVAL"
    source.write_text(__import__("json").dumps(grant))
    with pytest.raises(ProviderStop, match="SOURCE_DRIFT"):
        validate(root, auth)
    # An operator-updated companion alone still lacks the required user origin.
    auth["source_sha256"] = sha(source)
    root2 = root.parent / "other"
    root2.mkdir()
    save(root2 / "authorization-source.json", grant)
    auth["source_sha256"] = sha(root2 / "authorization-source.json")
    with pytest.raises(ProviderStop, match="EXPLICIT_USER_GRANT"):
        validate(root2, auth)


def test_corrupt_historical_ledger_fails_closed(tmp_path, monkeypatch):
    root, paths, auth = fixture(tmp_path, monkeypatch)
    append_event(paths[1], {"event": "FORGED_SETTLEMENT", "request_id": "old-unknown"})
    with pytest.raises(ProviderStop, match="CORRUPT_HISTORICAL"):
        validate(root, auth)
