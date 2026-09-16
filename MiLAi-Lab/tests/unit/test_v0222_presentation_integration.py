"""NOT_ACTUAL_INSTANCE: synthetic pinned lineage/public roots, MockHTTP and PIDs.

Batch, history FSM, references, preflight raw audit, Transport, FullProvider,
worker, original Session/ActionAdapter/SQLite, effects and final auditor are real.
No acceptance, reference-validation or effects function is replaced.
"""

import copy
import json
import socket
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import test_v0222_presentation_batch as batch_fixture
from test_v0220_action_adapter import public, put

import preflight_v0222_presentation as preflight
import v0222_presentation_audit as audit
import v0222_presentation_batch as batch_module
import v0222_presentation_worker as worker
from prepare_v0221_http_v2 import FINISH, READBACK
from prepare_v0222_full import resolve_p4_spec
from v02_local_provider import read_events
from v0213_provider import MODEL, TOKENIZE_KEYS
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0222_presentation_provider import FullProvider
from v0222_presentation_references import prepare_p3, prepare_p4


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("SYNTHETIC_MOCK_HTTP_ONLY")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def environment():
    value = public()
    for schema in value["task"]["record_schemas"].values():
        schema["properties"]["text"].update(pattern=r"\S", minLength=1)
        schema["properties"]["extra"]["properties"]["items"]["uniqueItems"] = True
    return value


def setup(tmp_path, monkeypatch, *, stages=("P3", "P4")):
    public_root = tmp_path / "public-synthetic"
    source = environment()
    for index in range(4):
        save(public_root / f"root-{index}" / "public-initial.json", source)
    original_save, original_seal = batch_fixture.save, batch_fixture.seal

    def fixture_save(path, value):
        if path == tmp_path / "parent" / "manifest.json":
            for spec in value["contract"]["P3"]:
                spec["expected"] = copy.deepcopy(put() if spec["variant"] == "full" else FINISH)
            for spec in value["contract"]["P4"]:
                spec["actions"] = [put(), put("right", 1)][: len(spec["actions"])]
                spec["intent"] = {
                    "instruction": "Apply these complete writes, read records, then finish.",
                    "ordered_writes": [
                        {k: action["arguments"][k] for k in ("object_id", "data")}
                        for action in spec["actions"]
                    ],
                }
        original_save(path, value)

    def fixture_seal(root, *, entries, inputs, contract):
        contract["P4"] = [resolve_p4_spec(spec, source)[0] for spec in contract["P4"]]
        return original_seal(
            root,
            entries=[*entries, Path(__file__)],
            inputs=[*inputs, *public_root.rglob("public-initial.json")],
            contract=contract,
        )

    monkeypatch.setattr(batch_fixture, "save", fixture_save)
    monkeypatch.setattr(batch_fixture, "seal", fixture_seal)
    batch = batch_fixture.fixture(tmp_path, monkeypatch)
    # The reused fixture installs an unused synthetic auditor only at its end.
    # Restore the real module before ANY reference/acceptance/gate operation.
    monkeypatch.setitem(sys.modules, "v0222_presentation_audit", audit)
    monkeypatch.setattr(audit, "CASES", public_root)
    monkeypatch.setattr(worker, "CASES", public_root)
    monkeypatch.setattr(worker, "ROOT", batch.root)
    assert batch_module.historical_usage_presentation.__module__ == batch_module.__name__
    anchor = batch.root / "manifest.json"
    for name, status in (
        ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
        ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
    ):
        path = batch.root / (name + ".json")
        save(
            path,
            {
                "status": status,
                "TEST_ONLY_NOT_ACTUAL_ADMISSION": True,
                "files": {str(anchor): sha(anchor)},
            },
        )
        batch.freeze_artifact(name, path, status)
    calls = []
    for stage in stages:
        rows, files = [], {}
        for spec in batch.plan[stage]:
            directory = batch.root / "full-reference" / stage / spec["id"]
            if stage == "P3":
                refs = prepare_p3(directory, spec, source, lambda: batch.authorize("PREP"))
            else:
                refs, prepared = prepare_p4(
                    directory, spec, source, lambda: batch.authorize("PREP")
                )
                assert prepared["spec"] == spec
            rows.extend(refs)
            files.update({str(p): sha(p) for p in directory.rglob("*") if p.is_file()})
        path = batch.root / (stage + "-references.json")
        save(path, {"references": rows, "files": files})
        batch.freeze_artifact(stage + "_references", path)
        result = preflight.preflight(
            batch.root, batch.binding_sha, stage, transport=mocked([], calls)
        )
        assert result["status"] == "G_PREFLIGHT_PASS"
    if "P4" in stages:
        path = batch.root / "P4-resolved-specs.json"
        save(path, {"specs": batch.plan["P4"], "files": {str(anchor): sha(anchor)}})
        batch.freeze_artifact("P4_resolved_specs", path)
    return batch, calls


def mocked(outputs, calls):
    queue, counted = iter(outputs), None

    def handle(request):
        nonlocal counted
        calls.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "0.27.1"})
        if request.url.path == "/tokenize":
            counted = json.loads(request.content)
            return httpx.Response(200, json={"count": 100})
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert counted == {key: body[key] for key in TOKENIZE_KEYS}
        output = next(queue)
        # Deliberately differ from static reference serialization. Subsequent
        # requests must be reconstructed from actual raw history, not ref bytes.
        raw = output if isinstance(output, str) else json.dumps(output, ensure_ascii=True, indent=1)
        return httpx.Response(
            200,
            json={
                "id": "MOCK_ONLY",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
                "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
            },
        )

    return httpx.MockTransport(handle)


def execute(batch, monkeypatch, spec, calls, *, outputs=None, finish=True):
    if outputs is None:
        outputs = (
            [spec["expected"]] if spec["stage"] == "P3" else [*spec["actions"], READBACK, FINISH]
        )
    index = [s["id"] for stage in ("P3", "P4") for s in batch.plan[stage]].index(spec["id"])
    pid = 90000000 + index
    transport = mocked(outputs, calls)

    def provider(*args, **kwargs):
        return FullProvider(*args, **kwargs, transport=transport)

    with monkeypatch.context() as patch:
        patch.setattr(batch_module.os, "getpid", lambda: pid)
        patch.setattr(worker, "FullProvider", provider)
        result = worker.run(batch.root, batch.binding_sha, spec["id"])
        assert result["pid"] == pid
    return batch.finish(spec["id"]) if finish else result


def test_real_complete_16_gate_then_24_sessions(tmp_path, monkeypatch):
    batch, calls = setup(tmp_path, monkeypatch)
    with pytest.raises(ProviderStop):
        batch.launch_once("P4")
    batch.launch_once("P3")
    for spec in batch.plan["P3"]:
        assert execute(batch, monkeypatch, spec, calls)["status"] == "PASS"
    assert not (batch.root / "worlds").exists()
    gate = batch.p3_gate()
    assert gate["full_passed"] == gate["finish_passed"] == 8
    path = batch.root / "P3-gate.json"
    save(path, gate)
    batch.freeze_p3_gate(path)
    batch.launch_once("P4")
    for spec in batch.plan["P4"]:
        result = execute(batch, monkeypatch, spec, calls)
        assert result["status"] == "PASS" and all(result["checks"].values())
        assert result["cost"]["requests"] == len(spec["actions"]) + 2
    snap = batch.snapshot()
    assert not snap["stop"] and all(row["status"] == "PASS" for row in snap["episodes"])
    assert snap["cost"]["requests"] == 96 and snap["cost"]["known_raw_tokens"] == 11520
    assert batch.auth["historical"]["requests"] == 45
    assert batch.auth["historical"]["known_raw_tokens"] == 526
    assert batch.auth["historical"]["reserved_raw_upper_bound"] == 28284
    assert snap["cost"]["actual_total_raw_tokens"] == 11520
    assert batch.auth["caps"] == {"P3": 16, "P4": 96}
    assert calls.count("/v1/chat/completions") == 96
    assert calls.count("/tokenize") == 192 + 96
    assert calls.count("/v1/models") == calls.count("/version") == 44
    assert len({row["pid"] for row in snap["episodes"]}) == 40
    assert len(list((batch.root / "worlds").glob("*.sqlite"))) == 24
    assert not list((batch.root / "episodes").rglob("note-*.json"))
    assert batch.artifact("P3_gate")["status"] == "G_P3_PASS"


def test_first_real_wrong_intent_permanently_blocks_p4(tmp_path, monkeypatch):
    batch, calls = setup(tmp_path, monkeypatch, stages=("P3",))
    batch.launch_once("P3")
    spec = batch.plan["P3"][0]
    wrong = copy.deepcopy(spec["expected"])
    wrong["arguments"]["object_id"] = "right"
    with pytest.raises(ProviderStop, match="FULL_INTENT_FIDELITY"):
        execute(batch, monkeypatch, spec, calls, outputs=[wrong])
    snap = batch.snapshot()
    assert snap["stop"] == "FULL_INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH"
    assert snap["cost"]["requests"] == 1 and snap["cost"]["known_raw_tokens"] == 120
    assert not (batch.root / "worlds").exists()
    before = len(calls)
    with pytest.raises(ProviderStop):
        batch.launch_once("P4")
    assert len(calls) == before and not (batch.root / "live-launch-P4.json").exists()
    assert not list((batch.root / "episodes").rglob("turn-*.json"))


@pytest.mark.parametrize("tamper", ["identity", "raw", "tokenize"])
def test_actual_receipt_drift_cannot_finish(tmp_path, monkeypatch, tamper):
    batch, calls = setup(tmp_path, monkeypatch, stages=("P3",))
    batch.launch_once("P3")
    spec = batch.plan["P3"][0]
    execute(batch, monkeypatch, spec, calls, finish=False)
    provider = batch.root / "episodes" / spec["id"] / "provider"
    events = read_events(provider / "provider-ledger-v2.jsonl")
    key = next(e["request_id"] for e in events if e["event"] == "RESERVED")
    if tamper == "identity":
        path = next(provider.glob("identity-*/version.json"))
        value = read(path)
        value["body"] = '{"version":"forged"}'
    elif tamper == "tokenize":
        path = provider / (key + "-tokenize-request.json")
        value = read(path)
        value["messages"] = []
    else:
        path = provider / (key + "-http.json")
        value = read(path)
        body = json.loads(value["body"])
        body["choices"][0]["message"]["content"] = json.dumps(put("right"))
        value["body"] = json.dumps(body)
        visible = provider / (key + "-visible.json")
        row = read(visible)
        row["content"] = body["choices"][0]["message"]["content"]
        visible.write_text(json.dumps(row))
    # Corruption is confined to this synthetic, not-yet-finished temporary episode.
    path.write_text(json.dumps(value))
    with pytest.raises(ProviderStop):
        batch.finish(spec["id"])
    snap = batch.snapshot()
    assert snap["stop"] and snap["episodes"][0]["status"] == "FAIL"
    assert calls.count("/v1/chat/completions") == 1
    assert not (batch.root / "episodes" / spec["id"] / "independent-audit.json").exists()
    assert sys.modules["v0222_presentation_audit"] is audit
