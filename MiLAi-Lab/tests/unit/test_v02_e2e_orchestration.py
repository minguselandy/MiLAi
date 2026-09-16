from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
chain = importlib.import_module("run_v02_e2e_generality")
host = importlib.import_module("run_v02_local_vllm")


@pytest.mark.parametrize("scenario", ["missing_l1", "empty_l1", "missing_l2", "eligible"])
def test_completed_task_without_candidate_stops_only_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str,
) -> None:
    config = {
        "experiment_id": "orchestration-control", "generator_task": "Produce the task report",
        "l1_path": "handoff.md", "l2_path": "details.md", "state_field": "memory-view",
        "model_transport_enabled": False, "new_model_allocations_authorized": 0,
        "new_model_tokens_authorized": 0,
    }
    sources = {"source.txt": "首部要求\n完整普通来源\n尾部要求\n"}
    host.write_json(tmp_path / "config.json", config)
    host.write_json(tmp_path / "initial-source-files.json", sources)
    host.write_json(tmp_path / "input-source.json", {
        "question": "Continue the work", "question_date": "2026/09/06 (Sun) 10:00",
    })
    launched, calls = [], []
    current = {
        "schema_version": "host-cognitive-state-v1", "authority": "HOST_WORKING",
        "scope": "TASK", "status": "ABSENT", "version": 0,
        "state_id": None, "payload": {}, "warnings": [],
    }

    def public_call(tool, arguments):
        calls.append(tool)
        if tool.endswith("update"):
            assert scenario == "eligible", "ineligible memory triggered a write"
            current.update(
                status="ACTIVE", version=1, state_id="state", state_version_id="v1",
                payload=arguments["payload"],
            )
        return copy.deepcopy(current)

    def scripted_worker(root, arm, task, files, payload):
        launched.append(arm)
        if arm != "G":
            assert scenario == "eligible"
            assert files is None and payload == current["payload"]
            assert task == "Continue the work\n\nQuestion date: 2026/09/06 (Sun) 10:00"
            return {"status": "COMPLETED", "worker_kind": "SCRIPTED_NO_MODEL"}
        assert task == config["generator_task"]
        assert files == sources and payload is None
        workspace = root / "G/workspace"
        workspace.mkdir(parents=True)
        for name, text in files.items():
            (workspace / name).write_text(text)
        frozen = host.manifest(workspace)
        host.write_json(root / "G/initial-files.json", frozen)
        host.write_json(root / "G/assignment.json", {"project": "project", "task_ref": "task"})
        host.write_artifact(workspace, "report.md", "已交付的正常任务产物\n", frozen)
        if scenario != "missing_l1":
            host.write_artifact(
                workspace, "handoff.md",
                " \r\n" if scenario == "empty_l1" else "恢复入口\n", frozen,
            )
        if scenario != "missing_l2":
            host.write_artifact(workspace, "details.md", "完整细节\n", frozen)
        host.write_json(root / "G/file-evidence-refs.json", {
            name: [] for name in host.manifest(workspace)
        })
        host.write_json(root / "G/final-delivery.json", {"answer": "Delivered report.md"})
        saved = host.checkpoint(root, config, call=public_call)
        host.write_json(root / "checkpoint-result.json", saved)
        assert (workspace / "source.txt").read_text() == sources["source.txt"]
        return {"status": "COMPLETED", "task_delivered": True, "answer": "Delivered report.md",
                "worker_kind": "SCRIPTED_NO_MODEL"}

    monkeypatch.setattr(host, "LocalProvider", lambda *a, **k: pytest.fail("Provider constructed"))
    result = chain.run_chain(tmp_path, launch=scripted_worker)
    assert result["sessions"]["G"]["status"] == "COMPLETED"
    assert result["sessions"]["G"]["task_delivered"] is True
    assert (tmp_path / "G/workspace/report.md").read_text() == "已交付的正常任务产物\n"
    assert result["semantic_task_effect"] == "NOT_EVALUATED"
    assert result["formal_D4_D5"] == "NOT_ENTERED"
    assert not (tmp_path / "allocations.jsonl").exists()
    assert not (tmp_path / "provider-ledger.jsonl").exists()
    if scenario == "eligible":
        assert launched == ["G", "A", "B"]
        assert result["status"] == "LOCAL_CHAIN_COMPLETED_EFFECT_UNEVALUATED"
        assert result["checkpoint"]["comparison_opportunity"] is True
        assert calls == ["milai_working_state_get", "milai_working_state_update",
                         "milai_working_state_get"]
    else:
        assert launched == ["G"]
        assert result["status"] == "NO_COMPARISON_OPPORTUNITY"
        assert result["checkpoint"]["operation"]["attempted"] is False
        assert result["checkpoint"]["comparison_opportunity"] is False
        assert calls == ["milai_working_state_get"]
        assert not (tmp_path / "frozen-g-files.json").exists()
    assert json.loads((tmp_path / "chain-result.json").read_text()) == result
