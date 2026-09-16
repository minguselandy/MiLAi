"""Protocol-repair admission rejects truncation, unknown use, dirty cleanup and fake repros."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_v0218 as runner


def setup_reproducer(tmp_path, monkeypatch, mutation=None):
    monkeypatch.setattr(runner, "LAB", tmp_path / "lab")
    directory = tmp_path / "failed"
    tools = runner.LAB / "tools"
    tools.mkdir(parents=True)
    code = [
        "v0218_world.py",
        "v0218_checker.py",
        "v0218_memory.py",
        "v0213_provider.py",
        "v0218_host.py",
    ]
    for name in code:
        (tools / name).write_text("owned test stub")
    cost = {"requests": 0, "raw_tokens": 0, "pending": 0, "violations": 0}
    result = {
        "status": "E0_STOPPED_PRESERVED",
        "cost": cost,
        "cleanup": {"api_stopped": True, "compose_stop_returncode": 0},
    }
    manifest = {
        "system_prompt": runner.SYSTEM,
        "schema": runner.SCHEMA,
        "implementation": {"tools/" + name: runner.sha(tools / name) for name in code},
    }
    response = {
        "usage": {"completion_tokens": 1814},
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {"action": "save_note", "arguments_json": '{"note":"unfinished'}
                    )
                },
            }
        ],
    }
    if mutation == "truncated":
        response["choices"][0]["finish_reason"] = "length"
    elif mutation == "valid_arguments":
        response["choices"][0]["message"]["content"] = json.dumps(
            {"action": "save_note", "arguments_json": "{}"}
        )
    elif mutation == "unknown_usage":
        cost["pending"] = 1
    elif mutation == "not_cleaned":
        result["cleanup"]["api_stopped"] = False
    elif mutation == "changed_checker":
        manifest["implementation"]["tools/v0218_checker.py"] = "other"
    runner.save(directory / "result.json", result)
    runner.save(directory / "manifest.json", manifest)
    runner.save(
        directory / "episodes/test/request-http.json",
        {"status_code": 200, "body": json.dumps(response)},
    )
    path = tmp_path / "revision.json"
    runner.save(
        path,
        {
            "revision": "COMMON_HOST_V4_SETTLED_ENCODING_ERROR_FEEDBACK",
            "failed_batch": str(directory),
            "failed_episode": "test",
            "failed_request": "request",
            "expected_diagnosis": {"http_status": 200},
        },
    )
    return path


def test_verified_inner_encoding_failure_can_admit_bounded_general_repair(tmp_path, monkeypatch):
    path = setup_reproducer(tmp_path, monkeypatch)
    evidence = runner.verify_protocol_revision(path)
    assert evidence["config_sha256"] == runner.sha(path)
    assert evidence["previous_cost_reference_only_not_recharged"]["pending"] == 0


@pytest.mark.parametrize(
    "mutation", ["truncated", "valid_arguments", "unknown_usage", "not_cleaned", "changed_checker"]
)
def test_protocol_repair_does_not_bypass_other_failure_gates(tmp_path, monkeypatch, mutation):
    with pytest.raises(AssertionError):
        runner.verify_protocol_revision(setup_reproducer(tmp_path, monkeypatch, mutation))


def test_probe_plan_is_twenty_episodes_with_fresh_shared_A_not_twenty_roots():
    roots = [{"root": "profile1"}, {"root": "profile2"}]
    plan = runner.episode_plan(roots, ("N0", "N1", "N2"), ("helpful", "irrelevant", "unresolved"))
    assert len(plan) == 20 and sum(item["phase"] == "A" for item in plan) == 2
    assert len({item["root"] for item in plan}) == 2
    assert len({item["id"] for item in plan}) == 20
    assert 16 * len(plan) == 320
