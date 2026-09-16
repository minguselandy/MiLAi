"""Real G artifact variants -> public save -> fresh Host -> mock transport input capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

import run_v02_local_vllm as runner
import run_v02_memory_flow as base
from v02_deadline import Deadline
from v02_e2e_state import save_layers
from v02_local_provider import LocalProvider, write_json
from v02_low_cost_public import observer


def variants(raw: str) -> list[dict]:
    fields = {f"part_{index:04d}": line for index, line in enumerate(raw.splitlines(keepends=True))}
    if len(fields) < 3:
        raise ValueError("Mother artifact needs at least three lines for deletion negative control")
    reverse = dict(reversed(list(fields.items())))
    deleted = dict(list(fields.items())[1:-1])
    return [
        {"name": "text", "format": "text", "content": raw, "kind": "MOTHER"},
        {
            "name": "wrapper",
            "format": "json",
            "content": json.dumps({"text": raw}),
            "kind": "TEXT_WRAPPER_ONLY",
        },
        {
            "name": "distributed",
            "format": "json",
            "content": json.dumps(fields),
            "kind": "ORDERED_TEXT_PARTS_IN_DISTINCT_FIELDS",
        },
        {
            "name": "reordered",
            "format": "json",
            "content": json.dumps(reverse),
            "kind": "JSON_KEY_ORDER_ONLY",
        },
        {
            "name": "deleted",
            "format": "json",
            "content": json.dumps(deleted),
            "kind": "INFORMATION_DELETION_NOT_EQUIVALENT",
        },
    ]


def restored_text(case: dict, value):
    if case["name"] == "text":
        return value
    if case["name"] == "wrapper":
        return value["text"]
    return "".join(value[key] for key in sorted(value))


def cold(root: Path, service: Path) -> None:
    def mock_provider(*args, **kwargs):
        def handle(request):
            if request.url.path == "/v1/models":
                return httpx.Response(
                    200, json={"data": [{"id": runner.read_json(root / "config.json")["model"]}]}
                )
            if request.url.path == "/tokenize":
                return httpx.Response(200, json={"count": 100})
            if request.url.path != "/v1/chat/completions":
                raise AssertionError("Unexpected mock route")
            return httpx.Response(
                200,
                json={
                    "id": "MOCK_INPUT_CAPTURE",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "tool": "finish",
                                        "answer": "Mock output; no task evaluation",
                                        "arguments_json": "{}",
                                    }
                                )
                            },
                        }
                    ],
                },
            )

        return LocalProvider(*args, **kwargs, transport=httpx.MockTransport(handle))

    # Test dependencies only: real public observer, network-ineligible mock model transport.
    runner.LocalProvider = mock_provider
    runner.observer = lambda _root, directory, project, task: observer(
        service, directory, project, task
    )
    runner._session(root, "B", Deadline(time.monotonic(), 30))


def run(root: Path) -> None:
    service = root / "e2e-branch-20260906b"
    base.assert_services(service)
    directory = root / "representation-chain"
    directory.mkdir(exist_ok=False)
    mother = base.LAB / "artifacts/v02-local-vllm-simulation/local-sim-20260906b/G/workspace"
    raw = (mother / "handoff.md").read_bytes().decode("utf-8")
    original_files = runner.manifest(mother)
    write_json(
        directory / "mother.json",
        {
            "files": original_files,
            "origin": "Actual closed SIM01 G artifacts",
            "new_generation_requests": 0,
        },
    )
    results = {}
    for case in variants(raw):
        target = directory / case["name"]
        host = target / "B"
        workspace = host / "workspace"
        shutil.copytree(mother, workspace)
        (workspace / "memory-view").write_bytes(case["content"].encode())
        config = {
            **base.read_json(runner.CONFIG),
            **base.read_json(base.LAB / "configs/v02-e2e-generality.json"),
            "l1_path": "memory-view",
            "l2_path": "release-plan.md",
            "l1_format": case["format"],
            "transport_kind": "MOCK_ONLY",
            "model_transport_enabled": True,
            "new_model_allocations_authorized": 1,
            "new_model_tokens_authorized": 20000,
            "session_timeout_seconds": 30,
        }
        write_json(target / "config.json", config)
        project = "representation-" + case["name"] + "-20260906b"
        with observer(service, target, project, project) as (call, _):
            saved = save_layers(call, workspace, config, original_files, project + "-save")
            assert saved["operation"]["outcome"] == "CONFIRMED"
            write_json(target / "save.json", saved)
        files = runner.manifest(workspace)
        write_json(host / "initial-files.json", files)
        write_json(
            host / "assignment.json",
            {
                "project": project,
                "task_ref": project,
                "task": "Inspect restored working memory. This is a mechanical input capture.",
                "file_evidence_refs": {name: [] for name in files},
            },
        )
        completed = subprocess.run(  # noqa: S603 -- fixed cold worker, mock generation only
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--cold",
                str(target),
                "--service",
                str(service),
            ],
            cwd=base.LAB,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        (target / "cold.log").write_text(completed.stdout + completed.stderr)
        assert completed.returncode == 0, completed.stderr
        finished = base.read_json(host / "result.json")
        assert finished["status"] == "COMPLETED", finished
        restored = base.read_json(host / "restored-head.json")
        assert restored["payload"] == saved["payload"]
        value = restored["payload"][config["state_field"]]["l1"]
        roundtrip = restored_text(case, value)
        assert (roundtrip == raw) is (case["name"] != "deleted")
        request = base.read_json(next(host.glob("*-request.json")))
        assert (
            json.dumps(base.read_json(host / "bootstrap.json"), ensure_ascii=False)
            in (request["messages"][1]["content"])
        )
        for name, version in original_files.items():
            assert runner.sha(workspace / name) == version
        results[case["name"]] = {
            "kind": case["kind"],
            "source_text_preserved": roundtrip == raw,
            "state_version_id": restored["state_version_id"],
            "l1_value": value,
            "actual_mock_input_sha256": hashlib.sha256(json.dumps(request).encode()).hexdigest(),
            "original_sources_intact": True,
            "cold_pid": finished["pid"],
        }
        write_json(target / "transformation.json", {"case": case, "result": results[case["name"]]})
    same = json.dumps(results["distributed"]["l1_value"]) == json.dumps(
        results["reordered"]["l1_value"]
    )
    write_json(
        directory / "result.json",
        {
            "status": "REPRESENTATION_ENGINEERING_CHAIN_COMPLETE",
            "new_generation_requests": 0,
            "mock_requests": len(results),
            "results": {
                name: {k: v for k, v in result.items() if k != "l1_value"}
                for name, result in results.items()
            },
            "json_key_order_eliminated_in_restored_l1": same,
            "attribution": "Compare restored L1 separately from full-input hashes and metadata",
            "model_representation_robustness": "NOT_RUN",
            "deletion_is_equivalence": False,
        },
    )
    print(
        json.dumps(
            {"variants": len(results), "model_requests": 0, "restored_key_order_eliminated": same}
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--cold", type=Path)
    parser.add_argument("--service", type=Path)
    args = parser.parse_args()
    if args.cold:
        cold(args.cold.resolve(), args.service.resolve())
    else:
        run(args.root.resolve())
