"""Offline whole-Goal closure audit; no model calls or Product mutations."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

from run_v0218 import LAB, costs, save, sha
from summarize_v0218_e2 import summarize


def read(path):
    return json.loads(path.read_text())


def verify_closed(root: Path, expected_hash: str) -> dict:
    assert sha(root / "result.json") == expected_hash
    result = read(root / "result.json")
    cost = costs(root)
    assert cost == result["cost"] and cost["pending"] == cost["violations"] == 0
    if (root / "product").exists():
        cleanup = read(root / "product/cleanup.json")
        assert cleanup["api_stopped"] and cleanup["compose_stop_returncode"] == 0
        assert cleanup["owned_volume"] == "RETAINED"
        assert result["cleanup"] == cleanup
    manifest = read(root / "manifest.json")
    assert sha(root / "manifest.json") == read(root / "manifest-sha256.json")["sha256"]
    for name, expected in manifest["input_files"].items():
        assert sha(root / name) == expected
    for name, expected in manifest["implementation"].items():
        assert sha(root / "executed-source" / Path(name).name) == expected
    return {
        "path": str(root),
        "result_sha256": expected_hash,
        "status": result["status"],
        "cost": cost,
        "cleanup": result.get("cleanup"),
    }


def finalize(base: Path, output: Path) -> dict:
    assert not output.exists(), "Preserve a previous closure audit"
    e2_root = base / "e2-controls-v1"
    e2 = summarize(e2_root)
    e0_path = base / "e0-v4-summary-v1.json"
    assert sha(e0_path) == "1b469d4318ca993dca96ee2b59e7d3e2fed915caa7f3276fb5bb7e0a4d13f643"
    references = (
        read(e0_path)["all_batches"] + read(e2_root / "manifest.json")["preceding_evidence"]
    )
    references.append({"path": str(e2_root), "result_sha256": e2["result_sha256"]})
    assert len(references) == len({r["path"] for r in references}) == 14
    batches = [verify_closed(Path(r["path"]), r["result_sha256"]) for r in references]
    total = {
        field: sum(r["cost"][field] for r in batches)
        for field in ("requests", "raw_tokens", "pending", "violations")
    }
    assert total == {"requests": 1340, "raw_tokens": 3353114, "pending": 0, "violations": 0}
    assert all(total[k] == v for k, v in e2["all_goal_provider_cost"].items())
    seal_path = base / "t5-seal-v1/testbed-manifest.json"
    assert sha(seal_path) == "b2b0937bc4167a4276986264069ee158fd07fb1b40a71bcb9cb1497caa71d5a9"
    seal = read(seal_path)
    assert seal["G_TESTBED"] == "PASSED_LIMITED_ADAPTED_PROFILE"
    assert len(seal["roots"]) == 12 and len({r["coarse_family"] for r in seal["roots"]}) == 9
    assert seal["split"] == "12_EXPOSED_D_ZERO_UNOPENED_C"
    assert sha(LAB / "tools/v0218_checker.py") == seal["checker_sha256"]
    validation = Path(seal["validation_path"])
    assert sha(validation / "validation-manifest.json") == seal["validation_manifest_sha256"]
    assert sha(validation / "validation-result.json") == seal["validation_result_sha256"]
    reasons, max_output = {}, 0
    for path in e2_root.glob("episodes/*/*-http.json"):
        response = read(path)
        assert response["status_code"] == 200
        body = json.loads(response["body"])
        reason = body["choices"][0]["finish_reason"]
        reasons[reason] = reasons.get(reason, 0) + 1
        max_output = max(max_output, body["usage"]["completion_tokens"])
    assert sum(reasons.values()) == 130 and reasons == {"stop": 130} and max_output < 4096
    assert all(not r["final_reservation_reached"] for r in e2["rows"])
    output.mkdir(parents=True, mode=0o700)
    gates = []
    commands = [
        ["uv", "run", "milai-lab-check-boundary"],
        ["uv", "run", "pytest", "-q", "--junitxml=" + str(output / "pytest.xml")],
        ["uv", "run", "ruff", "check", "src", "tests", "tools"],
        ["uv", "run", "mypy", "src/milai_lab"],
        ["uv", "build"],
        ["git", "diff", "--check"],
    ]
    for index, command in enumerate(commands):
        tick = time.monotonic()
        log = output / f"gate-{index}.log"
        with log.open("w") as stream:
            result = subprocess.run(  # noqa: S603 -- fixed local gates
                command, cwd=LAB, stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=False
            )
        gates.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "seconds": time.monotonic() - tick,
                "log_sha256": sha(log),
            }
        )
        save(output / "gates.json", {"gates": gates})
        assert result.returncode == 0, str(log)
    artifacts = [
        "studies/active/MILA_V0218_行为真值测试床建设_GOAL_20260910.md",
        "studies/active/MILA_V0218_E2_RESULTS_20260911.md",
        "studies/active/MILA_V0218_INNOVATION_DECISION_20260911.md",
        "studies/active/MILA_V0218_PRIOR_ART_20260911.md",
        "tools/finalize_v0218.py",
        "tools/summarize_v0218_e2.py",
    ]
    for name in artifacts:
        destination = output / "reviewed-source" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(LAB / name, destination)
    result = {
        "status": "WHOLE_GOAL_COMPLETE_BOUNDED_NEGATIVE_ENGINEERING_DECISION",
        "stages": {
            **{f"T{i}": "COMPLETE_LIMITED_ADAPTED_PROFILE" for i in range(6)},
            "E0": "COMPLETE",
            "E1": "COMPLETE",
            "E2": "COMPLETE",
            "E3": "NOT_TRIGGERED_ZERO_QUALIFIED_CANDIDATES",
            "E4": "NOT_TRIGGERED_ZERO_CANDIDATES_AND_NO_UNOPENED_C",
            "E5": "COMPLETE",
        },
        "decision_kind": "NONBLIND_DEVELOPER_RESEARCH_JUDGMENT_NOT_AUTOMATIC_SCORE_SELECTION",
        "decisions": [
            "KEEP_SIMPLE_NO_CANDIDATE",
            "ENGINEERING_GAIN_ONLY",
            "TESTBED_CONTRIBUTION_CANDIDATE_REQUIRES_EXTERNAL_REVIEW",
        ],
        "selected_mechanism_candidates": [],
        "unopened_C": 0,
        "causal_mechanism_or_novelty_established": False,
        "batches": batches,
        "all_goal_provider_cost": total,
        "raw_token_cap": None,
        "new_Judge_requests": 0,
        "active_allocation": 0,
        "e2_finish_reasons": reasons,
        "e2_max_completion_tokens": max_output,
        "testbed_manifest_sha256": sha(seal_path),
        "e2_summary_sha256": sha(e2_root / "control-summary-v1.json"),
        "reviewed_artifacts": {name: sha(LAB / name) for name in artifacts},
        "gates": gates,
        "product_deployment_A0_schema_changes": "NONE",
    }
    save(output / "completion-audit.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = finalize(args.base, args.output)
    print(json.dumps({k: result[k] for k in ("status", "all_goal_provider_cost", "decisions")}))
