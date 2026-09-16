"""MOCK_HTTP/offline process tests; no device query, real inference or task score."""

import copy
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put

from v02_local_provider import append_event, read_events
from v0213_provider import ENDPOINT, MODEL, payload
from v0218_world import World, digest
from v0220_evidence import save, seal, sha
from v0220_provider_hardened import ProviderStop, historical_usage, usage_state
from v0220_session import Session
from v0220_wire_contract import compile_contract, encoded
from v0221_http_audit import audit
from v0221_http_batch import REVISION, Batch
from v0221_http_provider import AuthorizedWireProvider


def fixture(tmp_path, *, stages=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    history = (tmp_path / "compat.jsonl", tmp_path / "unknown.jsonl")
    history[0].touch()
    append_event(
        history[1],
        {
            "event": "RESERVED",
            "request_id": "old",
            "session": "old",
            "prompt_tokens": 100,
            "output_cap": 4096,
            "raw_upper_bound": 4196,
        },
    )
    root = tmp_path / "mock-batch"
    w2 = [
        {"id": f"w2-{i:02d}", "stage": "W2", "variant": "full", "expected": put()}
        for i in range(1, 3)
    ]
    initial = {
        **public(),
        "scope": "owned",
        "version": 0,
        "records": {},
        "pending": {},
        "history": [],
    }
    w3 = [
        {
            "id": "w3-01",
            "stage": "W3",
            "scope": "owned",
            "actions": [put(), put("right", 1)],
            "initial_state_sha256": digest(initial),
            "intent": {"ordered_writes": [put(), put("right", 1)]},
        }
    ]
    seal(
        root,
        entries=[Path(__file__)],
        inputs=list(history),
        contract={"historical_paths": [str(p) for p in history], "W2": w2, "W3": w3},
    )
    save(
        root / "authorization-source.json",
        {
            "origin": "USER_CONVERSATION",
            "fixture": "MOCK_ONLY",
            "explicit_historical_carry": True,
            "http_only": True,
            "stages": ["W1", "W2", "W3", "W4"],
        },
    )
    old = historical_usage(history)
    save(
        root / "authorization.json",
        {
            "revision": REVISION,
            "path": "B",
            "root": str(root),
            "batch_id": root.name,
            "issued_unix": time.time() - 1,
            "expires_unix": time.time() + 300,
            "stages": stages or ["W1", "W2", "W3", "W4"],
            "caps": {"W2": 16, "W3": 96},
            "endpoint": ENDPOINT,
            "model": MODEL,
            "concurrency": 1,
            "raw_cap": None,
            "automatic_retry": False,
            "new_unknown_stops_all": True,
            "historical_usage_settled": False,
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
    save(root / "preflight/result.json", {"status": "G_PREFLIGHT_PASS", "fixture": "MOCK_ONLY"})
    batch.allow_preflight(root / "preflight/result.json")
    return batch


def transport(actions, calls, failure=None):
    outputs = iter(actions)

    def handler(request):
        calls.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        assert request.url.path == "/v1/chat/completions"
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic private text", request=request)
        if failure == "500":
            return httpx.Response(500, json={"error": {"message": ""}})
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        value = {
            "id": "synthetic-response",
            "usage": None if failure == "missing_usage" else usage,
            "choices": [{"message": {"content": encoded(next(outputs))}}],
        }
        return httpx.Response(200, json=value)

    return httpx.MockTransport(handler)


def mock_provider(batch, episode, actions, calls, *, failure=None):
    def admission(original, wire):
        assert wire == compile_contract(
            original["response_format"]["json_schema"]["schema"]
        ).prepare(original)

    spec = next((s for s in batch.plan["W3"] if s["id"] == episode), None)
    return AuthorizedWireProvider(
        batch.root / "episodes" / episode / "provider",
        batch=batch,
        episode=episode,
        transport=transport(actions, calls, failure),
        admission=admission,
        intent_actions=spec["actions"] if spec else None,
        world=World(batch.root / "worlds" / (episode + ".sqlite"), spec["scope"]) if spec else None,
    )


def w2_body():
    from v0220_action_contract import ActionContract

    return payload(
        [{"role": "user", "content": "MOCK calibration"}],
        ActionContract.from_public(public()).action_schema(),
    )


def finish_w2(batch, episode):
    batch.claim(episode)
    calls = []
    provider = mock_provider(batch, episode, [put()], calls)
    provider.verify()
    assert json.loads(provider.generate(episode, w2_body())) == put()
    provider.close()
    batch.finish(episode)
    return calls


def test_historical_exception_integrates_without_rewriting_old_flag(tmp_path):
    batch = fixture(tmp_path)
    before = copy.deepcopy(batch.auth["historical"])
    calls = finish_w2(batch, "w2-01")
    assert len([r for r in calls if r.url.path.endswith("completions")]) == 1
    assert batch.snapshot()["cost"]["actual_total_raw_tokens"] == 120
    assert batch.authorize("W2")["historical"] == before
    assert before["new_generation_allowed"] is False and before["actual_total_raw_tokens"] is None


@pytest.mark.parametrize("failure", ["timeout", "500", "missing_usage"])
def test_new_unknown_stops_other_episode_and_survives_reopen(tmp_path, failure):
    batch = fixture(tmp_path)
    batch.claim("w2-01")
    calls = []
    provider = mock_provider(batch, "w2-01", [put()], calls, failure=failure)
    provider.verify()
    with pytest.raises(ProviderStop):
        provider.generate("w2-01", w2_body())
    provider.close()
    snapshot = batch.snapshot()
    assert snapshot["stop"] and snapshot["cost"]["actual_total_raw_tokens"] is None
    assert snapshot["cost"]["requests"] == 1
    reopened = Batch(batch.root, batch.binding_sha)
    with pytest.raises(ProviderStop, match="BATCH_STOPPED"):
        reopened.claim("w2-02")
    assert len([r for r in calls if r.url.path.endswith("completions")]) == 1


def test_full_schema_rejection_has_known_cost_no_effect_no_retry(tmp_path):
    batch = fixture(tmp_path)
    batch.claim("w2-01")
    bad = put()
    bad["arguments"]["data"]["amount"] = -1
    provider = mock_provider(batch, "w2-01", [bad], [])
    provider.verify()
    with pytest.raises(ProviderStop, match="OUTPUT_PUBLIC_CONTRACT_REJECTED"):
        provider.generate("w2-01", w2_body())
    provider.close()
    assert batch.snapshot()["cost"]["actual_total_raw_tokens"] == 120
    assert batch.snapshot()["stop"] and not (batch.root / "worlds").exists()


def test_duplicate_launch_directory_and_journal_do_not_reset_batch(tmp_path):
    batch = fixture(tmp_path)
    batch.launch_once()
    with pytest.raises(FileExistsError):
        Batch(batch.root, batch.binding_sha).launch_once()
    with pytest.raises(FileExistsError):
        batch.initialize()
    copied = tmp_path / "copied"
    shutil.copytree(batch.root, copied)
    with pytest.raises(ProviderStop, match="OTHER_BATCH"):
        Batch(copied, batch.binding_sha)


def test_another_provider_directory_cannot_bypass_global_scope(tmp_path):
    batch = fixture(tmp_path)
    batch.claim("w2-01")
    with pytest.raises(ProviderStop, match="DIRECTORY_OUTSIDE"):
        AuthorizedWireProvider(tmp_path / "alternate", batch=batch, episode="w2-01")


def test_w3_requires_both_scope_and_complete_w2(tmp_path):
    batch = fixture(tmp_path / "normal")
    with pytest.raises(ProviderStop, match="COMPLETE_W2"):
        batch.claim("w3-01")
    limited = fixture(tmp_path / "limited", stages=["W1", "W2", "W4"])
    with pytest.raises(ProviderStop, match="STAGE_NOT_AUTHORIZED"):
        limited.claim("w3-01")


def test_empty_episode_and_wrong_order_cannot_pass(tmp_path):
    batch = fixture(tmp_path)
    with pytest.raises(ProviderStop, match="OUT_OF_ORDER"):
        batch.claim("w2-02")
    batch.claim("w2-01")
    with pytest.raises(ProviderStop, match="INCOMPLETE_EPISODE"):
        batch.finish("w2-01")
    with pytest.raises(ProviderStop, match="SINGLE_ACTIVE"):
        batch.claim("w2-02")


@pytest.mark.parametrize("mutation", ["authorization", "source", "old_history", "preflight"])
def test_hash_drift_blocks_launch(tmp_path, mutation):
    batch = fixture(tmp_path)
    if mutation == "authorization":
        path = batch.root / "authorization.json"
    elif mutation == "source":
        path = batch.root / "authorization-source.json"
    elif mutation == "old_history":
        path = Path(batch.auth["historical"]["sources"][0]["path"])
    else:
        path = batch.root / "preflight/result.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ProviderStop):
        batch.claim("w2-01")


def test_actual_child_crash_reservation_blocks_parent_next_episode(tmp_path):
    batch = fixture(tmp_path)
    program = (
        "import sys; from pathlib import Path; from v0221_http_batch import Batch; "
        "b=Batch(Path(sys.argv[1]),sys.argv[2]); b.claim('w2-01'); "
        "b.record('w2-01',{'event':'RESERVED','request_id':'crash','session':'w2-01',"
        "'prompt_tokens':100,'output_cap':4096,'raw_upper_bound':4196})"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "tools")}
    child = subprocess.run(  # noqa: S603 - owned offline child, no HTTP
        [sys.executable, "-c", program, str(batch.root), batch.binding_sha],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert child.returncode == 0, child.stderr
    with pytest.raises(ProviderStop, match="NEW_BATCH_UNKNOWN"):
        Batch(batch.root, batch.binding_sha).claim("w2-02")
    assert batch.snapshot()["cost"]["actual_total_raw_tokens"] is None


def test_mock_http_wire_session_sqlite_and_independent_audit(tmp_path):
    batch = fixture(tmp_path)
    finish_w2(batch, "w2-01")
    finish_w2(batch, "w2-02")
    batch.claim("w3-01")
    spec = batch.plan["W3"][0]
    directory = batch.root / "episodes/w3-01"
    world = World.create(batch.root / "worlds/w3-01.sqlite", "owned", public())
    host = Session(
        world,
        directory,
        episode_id="w3-01",
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent=spec["intent"],
        validate_binding=lambda: batch.authorize("W3"),
    )
    save(directory / "initial-world.json", world.snapshot())
    outputs = [
        put(),
        put("right", 1),
        {"action": "read", "arguments": {"resource": "records"}},
        {"action": "finish", "arguments": {"message": "done"}},
    ]
    provider = mock_provider(batch, "w3-01", outputs, [])
    result = host.run(provider, deadline=time.monotonic() + 20)
    save(
        directory / "worker-result.json",
        {**result, "pid": os.getpid(), "unresolved_operations": []},
    )
    save(directory / "final-world.json", world.snapshot())
    save(directory / "final-ledger.json", world.ledger())
    verdict = audit(batch.root, spec)
    assert verdict["status"] == "PASS", verdict
    assert len(world.ledger()) == 2
    batch.finish("w3-01")
    assert batch.snapshot()["cost"]["requests"] == 6
    assert (
        usage_state(read_events(directory / "provider/provider-ledger-v2.jsonl"))["requests"] == 4
    )


def test_runtime_modules_never_call_device_or_container_tools():
    base = Path(__file__).resolve().parents[2] / "tools"
    for name in (
        "v0221_http_batch.py",
        "v0221_http_provider.py",
        "prepare_v0221_http.py",
        "preflight_v0221_http.py",
        "run_v0221_http.py",
        "v0221_http_worker.py",
    ):
        code = (base / name).read_text()
        assert "backend_identity(" not in code
        assert "/usr/bin/docker" not in code and "nvidia-smi" not in code and "cuInit(" not in code


@pytest.mark.parametrize("kind", ["expired", "fake_receipt", "self_signed", "clear_unknown"])
def test_semantic_authorization_rejections_even_with_current_file_hashes(tmp_path, kind):
    batch = fixture(tmp_path)
    auth_path = batch.root / "authorization.json"
    source_path = batch.root / "authorization-source.json"
    auth, source = json.loads(auth_path.read_text()), json.loads(source_path.read_text())
    if kind == "expired":
        auth["expires_unix"] = time.time() - 1
    elif kind == "fake_receipt":
        auth["reconciliation"] = {"actual_usage": 0, "source": "CPU_PASS"}
    elif kind == "self_signed":
        source["origin"] = "AGENT_SELF_APPROVAL"
    else:
        auth["accepted_unknown"] = []
    auth_path.write_text(json.dumps(auth))
    source_path.write_text(json.dumps(source))
    binding_path = batch.root / "execution-binding.json"
    binding_path.write_text(
        json.dumps(
            {
                n: sha(batch.root / n)
                for n in ("authorization.json", "authorization-source.json", "manifest.json")
            }
        )
    )
    with pytest.raises(ProviderStop):
        Batch(batch.root, sha(binding_path))


def test_new_transport_preserves_uniqueItems_rejection_after_known_usage(tmp_path):
    batch = fixture(tmp_path)
    batch.claim("w2-01")
    body = w2_body()
    for branch in body["response_format"]["json_schema"]["schema"]["anyOf"]:
        if branch["properties"]["action"].get("const") == "put_record":
            branch["properties"]["arguments"]["properties"]["data"]["properties"]["extra"][
                "properties"
            ]["items"]["uniqueItems"] = True
    bad = put()
    bad["arguments"]["data"]["extra"]["items"] = ["duplicate", "duplicate"]
    provider = mock_provider(batch, "w2-01", [bad], [])
    provider.verify()
    with pytest.raises(ProviderStop, match="OUTPUT_PUBLIC_CONTRACT_REJECTED"):
        provider.generate("w2-01", body)
    provider.close()
    assert batch.snapshot()["cost"]["actual_total_raw_tokens"] == 120
    assert batch.snapshot()["stop"]


def test_second_generation_cannot_exceed_single_probe_cap(tmp_path):
    batch = fixture(tmp_path)
    batch.claim("w2-01")
    calls = []
    provider = mock_provider(batch, "w2-01", [put(), put()], calls)
    provider.verify()
    provider.generate("w2-01", w2_body())
    with pytest.raises(ProviderStop, match="GENERATION_COUNT_LIMIT"):
        provider.generate("w2-01", w2_body())
    provider.close()
    assert batch.snapshot()["cost"]["requests"] == 1
    assert len([r for r in calls if r.url.path.endswith("completions")]) == 1


@pytest.mark.parametrize("failure", ["wrong_value", "premature_finish"])
def test_first_intent_failure_stops_before_dispatch_and_next_generation(tmp_path, failure):
    batch = fixture(tmp_path)
    finish_w2(batch, "w2-01")
    finish_w2(batch, "w2-02")
    batch.claim("w3-01")
    world = World.create(batch.root / "worlds/w3-01.sqlite", "owned", public())
    action = put()
    if failure == "wrong_value":
        action["arguments"]["data"]["amount"] = 999
    else:
        action = {"action": "finish", "arguments": {"message": "done"}}
    calls = []
    provider = mock_provider(batch, "w3-01", [action], calls)
    provider.verify()
    with pytest.raises(ProviderStop):
        provider.generate("w3-01", w2_body())
    provider.close()
    assert world.snapshot()["version"] == 0 and not world.ledger()
    snapshot = batch.snapshot()
    assert snapshot["stop"] in {
        "INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH",
        "FINISH_BEFORE_INTENT_AND_PUBLIC_READBACK",
    }
    assert snapshot["cost"]["actual_total_raw_tokens"] == 360
    assert len([r for r in calls if r.url.path.endswith("completions")]) == 1
