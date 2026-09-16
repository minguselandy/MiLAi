"""Offline coordinator tests; synthetic receipts are not model evidence."""

import copy
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_batch as module
from v02_local_provider import append_event
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS, payload
from v0220_evidence import read, save, seal, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_batch import CAPS, P1_SCHEMA, REVISION, Batch, historical_usage_v0222


def fixture(tmp_path, monkeypatch):
    history = tuple(tmp_path / name for name in ("compat.jsonl", "old.jsonl", "latest.jsonl"))
    history[0].touch()
    append_event(
        history[1],
        {
            "event": "RESERVED",
            "request_id": "old",
            "session": "old",
            "prompt_tokens": 24188,
            "output_cap": 4096,
            "raw_upper_bound": 28284,
        },
    )
    latest = [
        {
            "event": "RESERVED",
            "request_id": "known",
            "session": "known",
            "prompt_tokens": 27779,
            "output_cap": 4096,
            "raw_upper_bound": 31875,
        },
        {"event": "DISPATCH_STARTED", "request_id": "known"},
        {"event": "RESPONSE_RECEIVED", "request_id": "known", "status_code": 200},
        {
            "event": "USAGE_KNOWN",
            "request_id": "known",
            "usage": {"prompt_tokens": 27779, "completion_tokens": 85, "total_tokens": 27864},
        },
    ]
    for event in latest:
        append_event(history[2], event)
    monkeypatch.setattr(module, "HISTORICAL_SOURCES", tuple((str(p), sha(p)) for p in history))
    p1 = []
    for repeat in (1, 2):
        for name in ("T1", "T2", "T3"):
            for condition in (
                ("D00", "D10", "D01", "D11") if repeat == 1 else ("D11", "D01", "D10", "D00")
            ):
                p1.append(
                    {
                        "id": f"p1-{len(p1) + 1:02d}",
                        "stage": "P1",
                        "pass": repeat,
                        "fixture": name,
                        "condition": condition,
                        "target": f" exact {name} ",
                    }
                )
    root = tmp_path / "mock-batch"
    seal(
        root,
        entries=[Path(__file__)],
        inputs=list(history),
        contract={
            "historical_paths": [str(p) for p in history],
            "P1": p1,
            "P3": [{"id": f"p3-{i:02d}", "stage": "P3"} for i in range(1, 17)],
            "P4": [{"id": f"p4-{i:02d}", "stage": "P4"} for i in range(1, 25)],
        },
    )
    stages = ["P0", "P1", "P2", "P3", "P4"]
    save(
        root / "authorization-source.json",
        {
            "origin": "USER_CONVERSATION",
            "explicit_historical_carry": True,
            "http_only": True,
            "diagnostic_content_failures_continue": True,
            "execute_goal_and_followup": True,
            "subagent_review_delegated": True,
            "user_instruction": "MOCK_ONLY: execute both plans; delegate review, not consent",
            "stages": stages,
        },
    )
    old = historical_usage_v0222(history)
    save(
        root / "authorization.json",
        {
            "revision": REVISION,
            "path": "B",
            "root": str(root),
            "batch_id": root.name,
            "issued_unix": time.time() - 1,
            "expires_unix": time.time() + 3000,
            "stages": stages,
            "caps": CAPS,
            "endpoint": ENDPOINT,
            "model": MODEL,
            "concurrency": 1,
            "raw_cap": None,
            "automatic_retry": False,
            "new_unknown_stops_all": True,
            "historical_usage_settled": False,
            "diagnostic_content_failures_continue": True,
            "reconciliation": None,
            "historical": old,
            "accepted_unknown": old["unresolved_reservations"],
        },
    )
    save(
        root / "execution-binding.json",
        {
            n: sha(root / n)
            for n in ("authorization.json", "authorization-source.json", "manifest.json")
        },
    )
    batch = Batch(root, sha(root / "execution-binding.json"))
    batch.initialize()
    freeze(batch, "scope_review", {"status": "G_AUTH_SCOPE_REVIEW_PASS"})
    references = []
    for spec in batch.plan["P1"]:
        canonical = payload(
            [
                {
                    "role": "system",
                    "content": "MOCK_ONLY exact copy. Authority: " + json.dumps(P1_SCHEMA),
                },
                {"role": "user", "content": json.dumps({"target": spec["target"]})},
            ],
            copy.deepcopy(P1_SCHEMA),
        )
        wire = copy.deepcopy(canonical)
        rules = wire["response_format"]["json_schema"]["schema"]["properties"]["text"]
        if spec["condition"] in {"D10", "D11"}:
            rules.pop("pattern")
        if spec["condition"] in {"D01", "D11"}:
            rules.pop("minLength")
        row = {
            "episode": spec["id"],
            "stage": "P1",
            "fixture": spec["fixture"],
            "condition": spec["condition"],
            "target_sha256": fingerprint(spec["target"]),
            "hashes": {},
        }
        for kind, obj in (
            ("canonical", canonical),
            ("wire", wire),
            ("output", {"raw": json.dumps({"text": spec["target"]})}),
        ):
            path = root / "fixture-references" / (spec["id"] + "." + kind + ".json")
            save(path, obj)
            row[kind], row["hashes"][kind] = str(path), sha(path)
        references.append(row)
    freeze(batch, "P1_references", references)
    freeze(batch, "P1_preflight", {"status": "G_PREFLIGHT_PASS"})
    batch.launch_once("P1")
    return batch


def freeze(batch, name, value):
    path = batch.root / "artifacts" / (name + ".json")
    save(path, value)
    batch.freeze_artifact(name, path)
    return path


def event(batch, ep, value):
    batch.record(ep, value)
    (batch.root / "episodes" / ep / "provider").mkdir(parents=True, exist_ok=True)
    append_event(batch.root / "episodes" / ep / "provider/provider-ledger-v2.jsonl", value)


def settle(batch, ep, content, *, exact=False, request_mutation=None, evidence_mutation=None):
    key = ep + "-synthetic"
    provider = batch.root / "episodes" / ep / "provider"
    reference = next(r for r in batch.references() if r["episode"] == ep)
    wire = read(Path(reference["wire"]))
    actual = copy.deepcopy(wire)
    if request_mutation is not None:
        request_mutation(actual)
    save(provider / (key + "-request.json"), actual)
    save(provider / (key + "-tokenize-request.json"), {k: actual[k] for k in TOKENIZE_KEYS})
    save(provider / (key + "-tokenize-http.json"), {"status_code": 200, "body": '{"count":100}'})
    save(provider / (key + "-tokenize.json"), {"count": 100})
    request_hash = sha(provider / (key + "-request.json"))
    reserved = {
        "event": "RESERVED",
        "session": ep,
        "request_id": key,
        "prompt_tokens": 100,
        "output_cap": 4096,
        "raw_upper_bound": 4196,
        "payload_sha256": request_hash,
        "cumulative_raw_cap": None,
    }
    event(batch, ep, reserved)
    event(batch, ep, {"event": "DISPATCH_STARTED", "request_id": key})
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    body = {"id": key, "usage": usage, "choices": [{"message": {"content": content}}]}
    save(
        provider / (key + "-http.json"),
        {
            "client_request_id": key,
            "status_code": 200,
            "body": json.dumps(body),
            "request_wire_sha256": request_hash,
        },
    )
    event(batch, ep, {"event": "RESPONSE_RECEIVED", "request_id": key, "status_code": 200})
    event(batch, ep, {"event": "USAGE_KNOWN", "request_id": key, "usage": usage})
    save(provider / (key + "-visible.json"), {"content": content})
    if evidence_mutation is not None:
        evidence_mutation(provider, key)
    freeze(
        batch,
        ep + "_observation",
        {
            "id": ep,
            "request_id": key,
            "status": "OBSERVED",
            "http_usage_audit": "PASS",
            "exact_fidelity": exact,
        },
    )


def observe(batch, spec, monkeypatch, success):
    with monkeypatch.context() as patch:
        patch.setattr(os, "getpid", lambda: 50000 + int(spec["id"].split("-")[1]))
        batch.claim(spec["id"])
        content = json.dumps({"text": spec["target"]}) if success else '{"text":"x"}'
        settle(batch, spec["id"], content, exact=success)
        batch.finish(spec["id"], "OBSERVED")


def first_pass(batch, monkeypatch, rule):
    for spec in batch.plan["P1"][:12]:
        observe(batch, spec, monkeypatch, rule(spec))
    path = batch.root / "first-decision.json"
    save(path, batch.p1_decision())
    batch.set_p1_decision(path)
    return read(path)


def test_three_formats_keep_unknown_and_latest_cost(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    assert batch.auth["historical"]["known_raw_tokens"] == 27864
    assert batch.auth["historical"]["reserved_raw_upper_bound"] == 28284
    assert batch.auth["historical"]["actual_total_raw_tokens"] is None
    assert len(batch.auth["accepted_unknown"]) == 1
    assert len(batch.auth["historical"]["sources"]) == 3
    assert batch.snapshot()["cost"]["requests"] == 0


@pytest.mark.parametrize(
    "content",
    ['{"text":"x"}', "not JSON", '{"text":"  "}', '{"text":"x","text":" exact T1 "}', "null"],
)
def test_known_usage_content_failure_is_observation(tmp_path, monkeypatch, content):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    settle(batch, "p1-01", content)
    batch.finish("p1-01", "OBSERVED")
    assert batch.snapshot()["stop"] is None
    assert batch.snapshot()["episodes"][0]["status"] == "OBSERVED"
    assert batch.snapshot()["cost"]["known_raw_tokens"] == 120


def test_fake_observation_rejected_from_actual_output(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    settle(batch, "p1-01", '{"text":"x"}', exact=True)
    with pytest.raises(ProviderStop, match="NOT_DERIVED_FROM_RAW"):
        batch.finish("p1-01", "OBSERVED")


def test_deep_json_content_remains_diagnostic_observation(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    content = "[" * 1100 + "0" + "]" * 1100
    assert len(content) < 4096
    settle(batch, "p1-01", content, exact=False)
    batch.finish("p1-01", "OBSERVED")
    state = batch.snapshot()
    assert state["stop"] is None
    assert state["episodes"][0]["status"] == "OBSERVED"
    assert state["cost"]["known_raw_tokens"] == 120
    with batch.transaction() as db:
        assert batch._observation(db, batch.plan["P1"][0])["exact_fidelity"] is False


def test_diagnostic_cannot_be_business_pass(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    settle(batch, "p1-01", '{"text":"x"}')
    with pytest.raises(ProviderStop, match="OBSERVATION_NOT_BUSINESS"):
        batch.finish("p1-01")


def test_no_signal_skips_second_pass(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    assert first_pass(batch, monkeypatch, lambda _: True) == {
        "status": "NO_DIFFERENTIAL_SIGNAL",
        "repeat_required": False,
    }
    with pytest.raises(ProviderStop, match="SECOND_PASS_NOT_TRIGGERED"):
        batch.claim("p1-13")
    with pytest.raises(ProviderStop):
        batch.launch_once("P3")
    assert batch.snapshot()["cost"]["requests"] == 12


@pytest.mark.parametrize(
    "successful,selected",
    [({"D10", "D01", "D11"}, "D10"), ({"D01", "D11"}, "D01"), ({"D11"}, "D11")],
)
def test_complete_second_pass_minimal_selector(tmp_path, monkeypatch, successful, selected):
    batch = fixture(tmp_path, monkeypatch)
    assert first_pass(batch, monkeypatch, lambda s: s["condition"] in successful)["repeat_required"]
    for spec in batch.plan["P1"][12:]:
        observe(batch, spec, monkeypatch, spec["condition"] in successful)
    assert batch.p1_decision(final=True) == {
        "status": "STRING_RULE_SIGNAL",
        "selected_condition": selected,
    }
    path = batch.root / "selection.json"
    save(path, batch.p1_decision(final=True))
    batch.set_p1_decision(path, final=True)
    assert batch.artifact("P1_final_selection")["selected_condition"] == selected
    assert batch.snapshot()["cost"]["requests"] == 24
    with pytest.raises(ProviderStop):
        batch.claim("p1-01")


def test_nonrepeatable_improvement_not_selected(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    first_pass(batch, monkeypatch, lambda s: s["condition"] != "D00")
    for spec in batch.plan["P1"][12:]:
        observe(batch, spec, monkeypatch, True)
    assert batch.p1_decision(final=True)["selected_condition"] is None


def test_fake_final_gate_cannot_be_frozen_directly(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    with pytest.raises(ProviderStop, match="COMPLETE_P1"):
        freeze(
            batch,
            "P1_final_selection",
            {"status": "STRING_RULE_SIGNAL", "selected_condition": "D10"},
        )


@pytest.mark.parametrize("kind", ["USAGE_UNKNOWN", "pending"])
def test_unknown_or_abandoned_reservation_blocks_whole_batch(tmp_path, monkeypatch, kind):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    event(
        batch,
        "p1-01",
        {
            "event": "RESERVED",
            "request_id": "new",
            "session": "p1-01",
            "prompt_tokens": 100,
            "output_cap": 4096,
            "raw_upper_bound": 4196,
        },
    )
    if kind != "pending":
        event(batch, "p1-01", {"event": kind, "request_id": "new"})
    reopened = Batch(batch.root, batch.binding_sha)
    for action in (
        lambda: reopened.admit("p1-01"),
        lambda: reopened.claim("p1-02"),
        lambda: reopened.launch_once("P3"),
    ):
        with pytest.raises(ProviderStop, match=r"UNKNOWN|STOPPED"):
            action()
    assert reopened.snapshot()["cost"]["actual_total_raw_tokens"] is None
    assert len(reopened.auth["accepted_unknown"]) == 1


def test_no_launch_reinit_copy_or_duplicate_artifact(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    with pytest.raises(ProviderStop, match="ALREADY_LAUNCHED"):
        batch.launch_once("P1")
    with pytest.raises(FileExistsError):
        batch.initialize()
    with pytest.raises(ProviderStop, match="ALREADY_FROZEN"):
        batch.freeze_artifact("P1_preflight", batch.root / "artifacts/P1_preflight.json")
    copied = tmp_path / "different-batch"
    shutil.copytree(batch.root, copied)
    with pytest.raises(ProviderStop, match="OTHER_BATCH"):
        Batch(copied, batch.binding_sha)


def test_single_writer_and_fresh_process(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    with pytest.raises(ProviderStop, match="SINGLE_ACTIVE"):
        batch.claim("p1-02")
    with monkeypatch.context() as patch:
        patch.setattr(os, "getpid", lambda: 123456)
        with pytest.raises(ProviderStop, match="NOT_OWNED"):
            batch.admit("p1-01")
    settle(batch, "p1-01", '{"text":"x"}')
    batch.finish("p1-01", "OBSERVED")
    with pytest.raises(ProviderStop, match="FRESH_CLIENT"):
        batch.claim("p1-02")


def test_phase_deadline_cannot_restart(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    with batch.transaction() as db:
        deadline = float(db.execute("SELECT value FROM meta WHERE key='P1_deadline'").fetchone()[0])
    monkeypatch.setattr(module.time, "time", lambda: deadline + 1)
    with pytest.raises(ProviderStop, match="PHASE_DEADLINE"):
        batch.claim("p1-01")
    with pytest.raises(ProviderStop, match="ALREADY_LAUNCHED"):
        Batch(batch.root, batch.binding_sha).launch_once("P1")


@pytest.mark.parametrize(
    "filename",
    [
        "manifest.json",
        "authorization.json",
        "authorization-source.json",
        "execution-binding.json",
        "artifacts/P1_preflight.json",
    ],
)
def test_frozen_input_drift_blocks(tmp_path, monkeypatch, filename):
    batch = fixture(tmp_path, monkeypatch)
    path = batch.root / filename
    # Test-only corruption is deliberate; never changes an actual evidence path.
    path.write_text(path.read_text() + " ")
    with pytest.raises((ProviderStop, ValueError), match="DRIFT"):
        batch.claim("p1-01")


def test_missing_ledger_mirror_blocks(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    settle(batch, "p1-01", '{"text":"x"}')
    mirror = batch.root / "episodes/p1-01/provider/provider-ledger-v2.jsonl"
    mirror.rename(mirror.with_suffix(".saved"))
    with pytest.raises(ProviderStop, match="DIVERGED"):
        batch.finish("p1-01", "OBSERVED")


def test_exact_historical_sources_cannot_add_new_unknown(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    paths = tuple(Path(s["path"]) for s in batch.auth["historical"]["sources"])
    append_event(
        paths[2],
        {
            "event": "RESERVED",
            "request_id": "new-unknown",
            "session": "new",
            "prompt_tokens": 100,
            "output_cap": 4096,
            "raw_upper_bound": 4196,
        },
    )
    with pytest.raises(ProviderStop, match="EXACT_THREE"):
        batch.authorize("P1")


def test_reservation_must_keep_frozen_capacity(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    reserved = {
        "event": "RESERVED",
        "request_id": "new",
        "session": "p1-01",
        "prompt_tokens": 100,
        "output_cap": 4095,
        "raw_upper_bound": 4195,
    }
    with pytest.raises(ProviderStop, match="FROZEN_REQUEST_CAP"):
        batch.record("p1-01", reserved)


def test_history_helper_rejects_missing_duplicate_sources(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    paths = tuple(Path(s["path"]) for s in batch.auth["historical"]["sources"])
    for invalid in (paths[:2], (paths[0], paths[0], paths[2])):
        with pytest.raises(ProviderStop, match="THREE_DISTINCT"):
            historical_usage_v0222(invalid)


def test_arbitrary_agent_review_cannot_replace_user_authorization(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    grant = copy.deepcopy(read(batch.root / "authorization-source.json"))
    grant["origin"] = "SUBAGENT"
    (batch.root / "authorization-source.json").write_text(json.dumps(grant))
    binding = copy.deepcopy(batch.binding)
    binding["authorization-source.json"] = sha(batch.root / "authorization-source.json")
    (batch.root / "execution-binding.json").write_text(json.dumps(binding))
    with pytest.raises(ProviderStop, match="EXPLICIT_USER"):
        Batch(batch.root, sha(batch.root / "execution-binding.json"))


def test_actual_child_exit_with_reservation_prevents_next_process(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    code = """
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import v0222_batch as module
from v02_local_provider import append_event
module.HISTORICAL_SOURCES = tuple(tuple(r) for r in json.loads(sys.argv[4]))
batch = module.Batch(Path(sys.argv[2]), sys.argv[3])
batch.claim('p1-01')
event = {'event':'RESERVED','request_id':'abandoned','session':'p1-01',
         'prompt_tokens':100,'output_cap':4096,'raw_upper_bound':4196}
batch.record('p1-01', event)
path = batch.root / 'episodes/p1-01/provider/provider-ledger-v2.jsonl'
path.parent.mkdir(parents=True)
append_event(path, event)
os._exit(0)
"""
    result = subprocess.run(  # noqa: S603 - fixed test-only child and owned temporary paths
        [
            sys.executable,
            "-c",
            code,
            str(Path(__file__).resolve().parents[2] / "tools"),
            str(batch.root),
            batch.binding_sha,
            json.dumps(module.HISTORICAL_SOURCES),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    snapshot = batch.snapshot()
    assert snapshot["episodes"][0]["pid"] != os.getpid()
    assert snapshot["cost"]["requests"] == 1
    assert not snapshot["cost"]["new_generation_allowed"]
    with pytest.raises(ProviderStop, match="NEW_BATCH_UNKNOWN"):
        Batch(batch.root, batch.binding_sha).claim("p1-02")


def test_each_diagnostic_attempt_has_cap_one(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    settle(batch, "p1-01", '{"text":"x"}')
    with pytest.raises(ProviderStop, match="COUNT_OR_TIME_BOUND"):
        batch.record(
            "p1-01",
            {
                "event": "RESERVED",
                "request_id": "extra",
                "session": "p1-01",
                "prompt_tokens": 100,
                "output_cap": 4096,
                "raw_upper_bound": 4196,
            },
        )
    assert batch.snapshot()["cost"]["requests"] == 1


def test_p4_cannot_use_p1_signal_as_full_fidelity(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    first_pass(batch, monkeypatch, lambda s: s["condition"] != "D00")
    for spec in batch.plan["P1"][12:]:
        observe(batch, spec, monkeypatch, spec["condition"] != "D00")
    selection = batch.root / "selection.json"
    save(selection, batch.p1_decision(final=True))
    batch.set_p1_decision(selection, final=True)
    freeze(batch, "P2_gate", {"status": "G_P2_PASS"})
    for stage in ("P3", "P4"):
        freeze(batch, stage + "_references", [])
        freeze(batch, stage + "_preflight", {"status": "G_PREFLIGHT_PASS"})
    with pytest.raises(ProviderStop, match="P4_REQUIRES_COMPLETE_P3_PASS"):
        batch.launch_once("P4")
    batch.launch_once("P3")
    batch.claim("p3-01")
    with pytest.raises(ProviderStop, match="EMPTY_OR_INCOMPLETE"):
        batch.finish("p3-01")
    batch.stop("MOCK_FULL_FIDELITY_FAILURE")
    with pytest.raises(ProviderStop, match="STOPPED"):
        batch.launch_once("P4")


def test_observation_raw_files_are_immutably_bound(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")
    settle(batch, "p1-01", '{"text":"x"}')
    batch.finish("p1-01", "OBSERVED")
    raw = batch.root / "episodes/p1-01/provider/p1-01-synthetic-http.json"
    raw.write_text(raw.read_text() + " ")
    with pytest.raises(ProviderStop, match="RAW_EVIDENCE_DRIFT"):
        batch.admit("p1-01")


@pytest.mark.parametrize("mutation", ["message", "condition", "parameter_type"])
def test_self_consistent_actual_request_hash_cannot_replace_frozen_wire(
    tmp_path, monkeypatch, mutation
):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")

    def alter(body):
        if mutation == "message":
            body["messages"][-1]["content"] = json.dumps({"target": "different synthetic input"})
        elif mutation == "condition":
            body["response_format"]["json_schema"]["schema"]["properties"]["text"].pop("pattern")
        else:
            body["stream"] = 0  # Python equality is insufficient: False == 0.

    settle(batch, "p1-01", '{"text":"x"}', request_mutation=alter)
    # Actual bytes, reservation and HTTP receipt all agree; the frozen reference does not.
    with pytest.raises(ProviderStop, match="ACTUAL_REQUEST_DIFFERS_FROM_FROZEN_P1_WIRE"):
        batch.finish("p1-01", "OBSERVED")


@pytest.mark.parametrize(
    "mutation",
    [
        "request",
        "response_count",
        "boolean_count",
        "status",
        "saved_count",
        "nonobject_count",
        "saved_count_type",
        "request_type",
    ],
)
def test_tokenize_receipts_are_independently_bound(tmp_path, monkeypatch, mutation):
    batch = fixture(tmp_path, monkeypatch)
    batch.claim("p1-01")

    def alter(provider, key):
        if mutation in {"request", "request_type"}:
            path = provider / (key + "-tokenize-request.json")
            value = read(path)
            if mutation == "request":
                value["messages"][-1]["content"] = "different tokenize input"
            else:
                value["add_special_tokens"] = 0
        elif mutation == "saved_count":
            path, value = provider / (key + "-tokenize.json"), {"count": 99}
        elif mutation == "saved_count_type":
            path, value = provider / (key + "-tokenize.json"), {"count": 100.0}
        else:
            path = provider / (key + "-tokenize-http.json")
            value = read(path)
            if mutation == "status":
                value["status_code"] = 500
            else:
                value["body"] = {
                    "response_count": '{"count":99}',
                    "boolean_count": '{"count":true}',
                    "nonobject_count": "[]",
                }[mutation]
        path.write_text(json.dumps(value))

    settle(batch, "p1-01", '{"text":"x"}', evidence_mutation=alter)
    with pytest.raises(ProviderStop, match="P1_ACTUAL_TOKENIZE_REQUEST_OR_USAGE_MISMATCH"):
        batch.finish("p1-01", "OBSERVED")


@pytest.mark.parametrize(
    "field,value", [("fixture", "T2"), ("condition", "D10"), ("target_sha256", "bad-target-hash")]
)
def test_reference_metadata_cannot_reassign_an_observation(tmp_path, monkeypatch, field, value):
    batch = fixture(tmp_path, monkeypatch)
    reference = copy.deepcopy(batch.references()[0])
    reference[field] = value
    with pytest.raises(ProviderStop, match="P1_REFERENCE_SPEC_BINDING_MISMATCH"):
        batch._p1_reference(reference, batch.plan["P1"][0])
