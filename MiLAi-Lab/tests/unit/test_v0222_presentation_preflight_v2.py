"""Real Gates/Core admission and receipt auditor; synthetic authority/source only.

No frozen instance or actual lineage is used. P4's prerequisite PASS rows/gate
are explicitly synthetic; their real SQL/claim/launch consistency is checked,
not asserted to be model successes. Every HTTP call uses MockTransport.
"""

import copy
import json
import socket
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0222_presentation_gates_v2 import install_review_prerequisites, put
from test_v0222_presentation_gates_v2 import setup as gates_setup

import preflight_v0222_presentation_v2 as module
import v0222_presentation_audit as audit
import v0222_presentation_http_v2 as identity_module
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0222_admission_read_scope import AdmissionReadScope
from v0222_diagnostic import request
from v0222_presentation_gates_v2 import SCOPE_PREREQUISITES


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("PREFLIGHT_MOCK_HTTP_ONLY")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def register_synthetic(batch, name, value):
    path = batch.root / ("fixture-" + name + ".json")
    digest = put(path, value)
    with batch.transaction() as db:
        db.execute(
            "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?)",
            (name, str(path), digest, json.dumps(value["files"])),
        )
    return path


def setup(tmp_path, monkeypatch, mode="valid"):
    batch, wall, pid, scopes, anchor = gates_setup.__wrapped__(tmp_path, monkeypatch)
    control_pins = install_review_prerequisites(batch, anchor)
    monotonic = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: monotonic[0])
    batch.plan["http_identity"] = {
        "endpoint": ENDPOINT,
        "model": MODEL,
        "context": 65536,
        "version": "MOCK_ONLY",
    }
    for index, spec in enumerate(batch.plan["P4"]):
        spec["actions"] = [{}] * (2 if index < 8 else 1)
    references = {}
    for stage in ("P3", "P4"):
        references[stage] = [
            {
                "episode": spec["id"],
                "turn": turn,
                "hashes": {"SYNTHETIC_SOURCE": "not-an-actual-reference"},
            }
            for spec in batch.plan[stage]
            for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3)
        ]
        register_synthetic(
            batch,
            stage + "_references",
            {"references": references[stage], "files": {str(anchor): sha(anchor)}},
        )
    pins = {str(batch.root / name): digest for name, digest in batch.binding.items()}
    pins[str(batch.root / "execution-binding.json")] = batch.binding_sha
    assert all(control_pins[path] == digest for path, digest in pins.items())
    with batch.transaction() as db:
        for name in SCOPE_PREREQUISITES:
            row = db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
            pins.update(
                {
                    row["path"]: row["sha256"],
                    **json.loads(row["dependencies"]),
                    **read(Path(row["path"]))["files"],
                }
            )
    review = {
        "status": "G_AUTH_SCOPE_REVIEW_PASS",
        "root": str(batch.root),
        "binding_sha256": batch.binding_sha,
        "review_is_not_user_consent": True,
        "files": pins,
    }
    review_path = batch.root / "scope-review.json"
    put(review_path, review)
    batch.freeze_artifact("scope_review", review_path)
    monkeypatch.setattr(module, "Batch", lambda *_: batch)
    _, wire = request("T1", "D00")
    raw = '{"original":"完整 Unicode 世界 \\n", "nested":[1,2,3]}'

    def source_reference(*args):
        return {}, {}, copy.deepcopy(wire), raw

    monkeypatch.setattr(module, "validate_reference", source_reference)
    monkeypatch.setattr(audit, "validate_reference", source_reference)
    calls, bodies, http_scopes = [], [], []
    error = httpx.ReadTimeout("SYNTHETIC_HTTP_TIMEOUT")

    def handle(req):
        assert scopes[-1].status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
        assert all(scopes[-1] is not old for old in http_scopes)
        http_scopes.append(scopes[-1])
        with sqlite3.connect(batch.path, timeout=0.1) as probe:
            probe.execute("BEGIN IMMEDIATE")
            probe.rollback()
        assert req.extensions["timeout"]["read"] <= 5
        calls.append(req.url.path)
        if mode == "stop_models" and len(calls) == 1:
            batch.stop("FIRST_MOCK_STOP")
        if mode == "stop_tokenize" and len(calls) == 3:
            batch.stop("FIRST_MOCK_STOP")
        if req.url.path == "/v1/models":
            return httpx.Response(
                201 if mode == "identity_201" else 200,
                json={"data": [{"id": MODEL, "max_model_len": 65536}]},
            )
        if req.url.path == "/version":
            return httpx.Response(
                200, json={"version": "DRIFT" if mode == "identity_drift" else "MOCK_ONLY"}
            )
        assert req.url.path == "/tokenize", "Generation is forbidden in preflight"
        body = json.loads(req.content)
        bodies.append(body)
        if "prompt" in body:
            assert body == {"model": MODEL, "prompt": raw, "add_special_tokens": False}
            count = 4096 if mode == "output_capacity" else 100
        else:
            assert body == {key: wire[key] for key in TOKENIZE_KEYS}
            count = 61441 if mode == "input_capacity" else 1000
        count = {"bool": True, "float": 1.0, "negative": -1}.get(mode, count)
        if mode == "timeout":
            raise error
        if mode == "duplicate":
            return httpx.Response(200, text='{"count":1,"count":2}')
        if mode == "nonfinite":
            return httpx.Response(200, text='{"count":NaN}')
        return httpx.Response(201 if mode == "tokenize_201" else 200, json={"count": count})

    return (
        batch,
        httpx.MockTransport(handle),
        calls,
        bodies,
        wall,
        monotonic,
        pid,
        scopes,
        anchor,
        error,
    )


def seed_p3_prerequisite(batch, pid, anchor, *, passed=16, gate=True):
    """Synthetic prior outcomes with actual coordinator/marker consistency only."""
    register_synthetic(
        batch, "P3_preflight", {"status": "G_PREFLIGHT_PASS", "files": {str(anchor): sha(anchor)}}
    )
    parent = pid[0]
    batch.launch_once("P3")
    for index, spec in enumerate(batch.plan["P3"][:passed], 1):
        pid[0] = parent + index
        batch.claim(spec["id"])
        with batch.transaction() as db:
            db.execute("UPDATE episodes SET status='PASS' WHERE id=?", (spec["id"],))
    pid[0] = parent
    if gate:
        register_synthetic(
            batch,
            "P3_gate",
            {
                "status": "G_P3_PASS",
                "SYNTHETIC_NOT_MODEL_PASS": True,
                "files": {str(anchor): sha(anchor)},
            },
        )


@pytest.mark.parametrize("stage,count,receipts", [("P3", 16, 104), ("P4", 80, 488)])
def test_complete_mock_capacity_real_scoped_admission_and_original_receipt_auditor(
    tmp_path, monkeypatch, stage, count, receipts
):
    batch, transport, calls, bodies, _, _, pid, scopes, anchor, _ = setup(tmp_path, monkeypatch)
    if stage == "P4":
        seed_p3_prerequisite(batch, pid, anchor)
    result = module.preflight(tmp_path, batch.binding_sha, stage, transport=transport)
    assert result["status"] == "G_PREFLIGHT_PASS" and batch.snapshot()["stop"] is None
    assert len(result["rows"]) == count and len(result["files"]) == receipts
    assert len(bodies) == calls.count("/tokenize") == 2 * count
    assert calls.count("/v1/models") == calls.count("/version") == 2
    assert result["model_requests"] == result["direct_device_calls"] == 0
    assert result["preflight_window_seconds"] == {"P3": 1200, "P4": 2400}[stage]
    assert batch.artifact(stage + "_preflight") == result
    assert all(scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS" for scope in scopes)
    assert all(sha(Path(path)) == digest for path, digest in result["files"].items())
    with pytest.raises((FileExistsError, ProviderStop)):
        module.preflight(tmp_path, batch.binding_sha, stage, transport=transport)
    assert len(calls) == 2 * count + 4
    assert read(tmp_path / (stage + "-preflight/result.json")) == result


@pytest.mark.parametrize(
    "mode,expected_calls",
    [
        ("identity_201", 1),
        ("identity_drift", 2),
        ("stop_models", 1),
        ("stop_tokenize", 3),
        ("tokenize_201", 3),
        ("bool", 3),
        ("float", 3),
        ("negative", 3),
        ("duplicate", 3),
        ("nonfinite", 3),
        ("timeout", 3),
        ("input_capacity", 4),
        ("output_capacity", 4),
    ],
)
def test_failure_stops_without_next_http_or_preflight_registration(
    tmp_path, monkeypatch, mode, expected_calls
):
    batch, transport, calls, *_ = setup(tmp_path, monkeypatch, mode)
    result = module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
    assert result["status"] == "NOT_MET" and batch.snapshot()["stop"]
    assert len(calls) == expected_calls
    with batch.transaction() as db:
        assert not db.execute("SELECT 1 FROM artifacts WHERE name='P3_preflight'").fetchone()
    before = list(calls)
    with pytest.raises(ProviderStop):
        module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
    assert calls == before


@pytest.mark.parametrize(
    "change",
    [
        "missing_prepared",
        "replace_references",
        "control_pin",
        "review_consent",
        "engineering_status",
    ],
)
def test_actual_admission_requires_current_full_review_closure(tmp_path, monkeypatch, change):
    batch, transport, calls, *_ = setup(tmp_path, monkeypatch)
    with batch.transaction() as db:
        if change == "missing_prepared":
            db.execute("DELETE FROM artifacts WHERE name='P_full_preparation'")
        else:
            name = (
                "P4_references"
                if change == "replace_references"
                else "engineering_checks"
                if change == "engineering_status"
                else "scope_review"
            )
            row = db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone()
            value = read(Path(row["path"]))
            if change == "control_pin":
                del value["files"][str(batch.root / "authorization-source.json")]
            elif change == "review_consent":
                value["review_is_not_user_consent"] = 1
            elif change == "engineering_status":
                value["status"] = "NOT_MET"
            replacement = batch.root / "replacement.json"
            digest = put(replacement, value)
            db.execute(
                "UPDATE artifacts SET path=?,sha256=?,dependencies=? WHERE name=?",
                (str(replacement), digest, json.dumps(value["files"]), name),
            )
    with pytest.raises((ProviderStop, ValueError)):
        module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
    assert not calls and batch.snapshot()["stop"]


@pytest.mark.parametrize("passed,gate", [(0, False), (15, True), (16, False)])
def test_p4_requires_sixteen_prior_pass_and_new_gate_before_http(
    tmp_path, monkeypatch, passed, gate
):
    batch, transport, calls, _, _, _, pid, _, anchor, _ = setup(tmp_path, monkeypatch)
    seed_p3_prerequisite(batch, pid, anchor, passed=passed, gate=gate)
    with pytest.raises(ProviderStop):
        module.preflight(tmp_path, batch.binding_sha, "P4", transport=transport)
    assert not calls and batch.snapshot()["stop"]


@pytest.mark.parametrize("active", [False, True])
def test_no_preflight_for_launched_stage_or_any_active_worker(tmp_path, monkeypatch, active):
    batch, transport, calls, _, _, _, pid, _, anchor, _ = setup(tmp_path, monkeypatch)
    seed_p3_prerequisite(batch, pid, anchor, passed=0)
    if active:
        pid[0] += 100
        batch.claim(batch.plan["P3"][0]["id"])
    stage = "P4" if active else "P3"
    with pytest.raises(ProviderStop, match=r"ACTIVE_WORKER|LAUNCHED_STAGE"):
        module.preflight(tmp_path, batch.binding_sha, stage, transport=transport)
    assert not calls


def test_expired_completed_p3_does_not_expire_p4_preflight(tmp_path, monkeypatch):
    batch, _, _, _, wall, mono, pid, _, anchor, _ = setup(tmp_path, monkeypatch)
    seed_p3_prerequisite(batch, pid, anchor)
    wall[0] = 2801.0
    claim = module.admit_preflight(batch, "P4", mono[0] + 2400)
    assert claim["deadline"] > wall[0] and batch.snapshot()["stop"] is None


@pytest.mark.parametrize("kind", ["window", "authorization"])
def test_scope_close_work_can_exhaust_required_five_seconds(tmp_path, monkeypatch, kind):
    batch, transport, calls, _, wall, mono, _, _, _, _ = setup(tmp_path, monkeypatch)
    original = AdmissionReadScope.__exit__

    def close(scope, *args):
        result = original(scope, *args)
        if kind == "window":
            mono[0] = 1196.0
        else:
            wall[0] = batch.auth["expires_unix"] - 4
        return result

    monkeypatch.setattr(AdmissionReadScope, "__exit__", close)
    with pytest.raises(ProviderStop, match="DEADLINE"):
        module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
    assert not calls and batch.snapshot()["stop"]


@pytest.mark.parametrize("point,expected", [("tokenize", 2), ("identity", 0)])
def test_attempt_save_stop_is_seen_before_http(tmp_path, monkeypatch, point, expected):
    batch, transport, calls, *_ = setup(tmp_path, monkeypatch)
    original = save

    def stopped(path, value):
        original(path, value)
        if path.name.endswith(".attempt.json") or path.name == "models-attempt.json":
            batch.stop("STOP_AFTER_ATTEMPT_SAVE")

    monkeypatch.setattr(module if point == "tokenize" else identity_module, "save", stopped)
    result = module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
    assert result["status"] == "NOT_MET" and len(calls) == expected
    assert batch.snapshot()["stop"] == "STOP_AFTER_ATTEMPT_SAVE"


def test_http_error_report_failure_keeps_primary_reason(tmp_path, monkeypatch):
    batch, transport, calls, *rest = setup(tmp_path, monkeypatch, "timeout")
    error = rest[-1]
    observed = []

    def persist(path, value):
        if path.name.endswith(".error.json"):
            observed.append(batch.snapshot()["stop"])
            raise OSError("SECONDARY_ERROR_REPORT_FAILURE")
        save(path, value)

    monkeypatch.setattr(module, "save", persist)
    result = module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
    assert result["status"] == "NOT_MET" and result["reason"] == "ReadTimeout"
    assert observed == ["ReadTimeout"] and batch.snapshot()["stop"] == "ReadTimeout"
    assert any("SECONDARY_HTTP_REPORT_FAILURE" in note for note in error.__notes__)
    assert len(calls) == 3


@pytest.mark.parametrize(
    "suffix,expected",
    [(".request.json", 2), (".attempt.json", 2), (".http.json", 3), ("result.json", 36)],
)
def test_persistence_failure_stops_before_any_later_http(tmp_path, monkeypatch, suffix, expected):
    batch, transport, calls, *_ = setup(tmp_path, monkeypatch)
    error = OSError("SYNTHETIC_PERSISTENCE_FAILURE")

    def persist(path, value):
        if path.name.endswith(suffix):
            raise error
        if path.name == "result.json":
            assert batch.snapshot()["stop"] == "OSError"
        save(path, value)

    monkeypatch.setattr(module, "save", persist)
    if suffix == "result.json":
        with pytest.raises(OSError) as caught:
            module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
        assert caught.value is error
    else:
        result = module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
        assert result["status"] == "NOT_MET" and result["reason"] == "OSError"
    assert len(calls) == expected and batch.snapshot()["stop"] == "OSError"
    with batch.transaction() as db:
        assert not db.execute("SELECT 1 FROM artifacts WHERE name='P3_preflight'").fetchone()


def test_deadline_after_successful_freeze_stops_not_retries(tmp_path, monkeypatch):
    batch, transport, calls, _, _, mono, *_ = setup(tmp_path, monkeypatch)
    original = batch.freeze_artifact

    def freeze(*args):
        result = original(*args)
        mono[0] = 1201
        return result

    monkeypatch.setattr(batch, "freeze_artifact", freeze)
    with pytest.raises(ProviderStop, match="DEADLINE"):
        module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
    assert len(calls) == 36 and batch.snapshot()["stop"]


@pytest.mark.parametrize("change", ["extra_file", "body", "count"])
def test_original_receipt_auditor_rejects_self_consistent_rehash(tmp_path, monkeypatch, change):
    batch, transport, _, *_ = setup(tmp_path, monkeypatch)
    result = module.preflight(tmp_path, batch.binding_sha, "P3", transport=transport)
    directory = tmp_path / "P3-preflight"
    if change == "extra_file":
        put(directory / "hidden-attempt.json", {})
    else:
        suffix = "request" if change == "body" else "http"
        path = directory / f"P3-00-01-input.{suffix}.json"
        value = read(path)
        if change == "body":
            value["messages"] = []
        else:
            value["body"] = '{"count":1000.0}'
        result["files"][str(path)] = put(path, value)
    # No Batch callback: use already captured refs so failure is old receipt
    # semantics, not merely a pinned-file drift found by the live Batch reader.
    from v0222_presentation_gates_v2 import AuditView

    view = AuditView(
        batch.root,
        batch.plan,
        {
            "P3": [
                {
                    "episode": s["id"],
                    "turn": 1,
                    "hashes": {"SYNTHETIC_SOURCE": "not-an-actual-reference"},
                }
                for s in batch.plan["P3"]
            ]
        },
    )
    with pytest.raises(ProviderStop):
        audit.validate_preflight(view, result, "P3")
