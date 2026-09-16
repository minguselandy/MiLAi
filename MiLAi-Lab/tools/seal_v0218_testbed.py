"""Sign limited discovery readiness only after reviewed evidence and actual Lab gates."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

from check_v0218_testbed import LAB, read, save, sha

REQUIRED_REVIEW = frozenset(
    {
        "source_lineage_license_adaptations",
        "checker_semantic_counterexamples",
        "reset_clone_public_private_isolation",
        "public_note_cold_transport",
        "two_self_authored_dual_presentation_lineages",
        "mixed_note_claims_separated",
        "all_failures_and_costs_retained",
        "recovery_is_scripted_not_agent",
        "exposure_and_confirmation_gap",
        "remaining_E0_E5_required",
    }
)


def requirements(result, review):
    assert result["status"] == "STRUCTURAL_VALIDATION_PASSED_PENDING_T5_SIGNOFF"
    assert result["roots"] == 12 and result["coarse_families"] >= 3
    assert len(result["boundary_rows"]) == 12
    assert all(row["status"] == "PASS" for row in result["boundary_rows"])
    assert result["variants"]["stable"] == result["variants"]["superseded"] == 12
    assert result["variants"]["unresolved"] == 12 and result["variants"]["helpful"] >= 2
    assert len(set(result["actual_both_lineages"])) >= 2
    assert result["A_self_note_valid_protocol"] >= 2 and result["B_actual_both"] >= 2
    assert review["decision"] == "APPROVED_LIMITED_DISCOVERY"
    assert review["review_kind"] == "DEVELOPER_SELF_REVIEW_NOT_INDEPENDENT_HUMAN"
    assert set(review["accepted"]) == REQUIRED_REVIEW
    assert review["whole_goal_complete"] is False and review["unopened_C"] == 0


def execute(validation: Path, review_path: Path, output: Path):
    assert not output.exists()
    result = read(validation / "validation-result.json")
    review = read(review_path)
    requirements(result, review)
    inputs = read(validation / "validation-manifest.json")["input_files"]
    for name, expected in inputs.items():
        assert sha(validation / name) == expected
        if name.startswith("executed-source/"):
            assert sha(LAB / name.removeprefix("executed-source/")) == expected
    for item in review["documents"]:
        assert (LAB / item).is_file()
    output.mkdir(parents=True)
    shutil.copyfile(Path(__file__), output / Path(__file__).name)
    shutil.copyfile(review_path, output / "review.json")
    for index, name in enumerate(review["documents"]):
        shutil.copyfile(LAB / name, output / f"review-document-{index}.md")
    commands = [
        ["uv", "run", "milai-lab-check-boundary"],
        ["uv", "run", "pytest", "-q", f"--junitxml={output / 'pytest.xml'}"],
        ["uv", "run", "ruff", "check", "src", "tests", "tools"],
        ["uv", "run", "mypy", "src/milai_lab"],
        ["uv", "build"],
        ["git", "diff", "--check"],
    ]
    gates = []
    for index, command in enumerate(commands):
        started = time.monotonic()
        process = subprocess.run(  # noqa: S603 - fixed local required-gate commands, no shell
            command, cwd=LAB, capture_output=True, text=True, timeout=300, check=False
        )
        log = output / f"gate-{index}.log"
        log.write_text(process.stdout + process.stderr)
        gates.append(
            {
                "command": command,
                "exit_code": process.returncode,
                "seconds": time.monotonic() - started,
                "log": log.name,
                "log_sha256": sha(log),
            }
        )
        save(output / "gates.json", {"rows": gates})
        print(json.dumps(gates[-1]), flush=True)
        assert process.returncode == 0, "REQUIRED_GATE_FAILED_NO_SIGNOFF"
    # Recheck the immutable validation inputs after running the gates.
    for name, expected in inputs.items():
        assert sha(validation / name) == expected
        if name.startswith("executed-source/"):
            assert sha(LAB / name.removeprefix("executed-source/")) == expected
    manifest = {
        "status": "TESTBED_READY_FOR_DISCOVERY",
        "G_TESTBED": "PASSED_LIMITED_ADAPTED_PROFILE",
        "profile": "MILAI_ADAPTED_BEHAVIORAL_TESTBED",
        "native_rubric": False,
        "review_kind": review["review_kind"],
        "review_sha256": sha(review_path),
        "validation_path": str(validation),
        "cases": str(validation / "cases"),
        "validation_manifest_sha256": sha(validation / "validation-manifest.json"),
        "validation_result_sha256": sha(validation / "validation-result.json"),
        "checker_sha256": sha(LAB / "tools/v0218_checker.py"),
        "roots": read(validation / "cases/manifest.json")["roots"],
        "variants": result["variants"],
        "split": "12_EXPOSED_D_ZERO_UNOPENED_C",
        "gates": gates,
        "all_construction_model_cost": result["all_construction_model_cost"],
        "new_model_requests": 0,
        "judge_requests": 0,
        "limitations": review["limitations"],
        "E0_E5": "REQUIRED_NOT_COMPLETED",
        "whole_goal_complete": False,
        "product_schema": "UNCHANGED_NO_GO_FOR_FREEZE",
        "signed_artifacts": {
            str(p.relative_to(output)): sha(p) for p in output.iterdir() if p.is_file()
        },
    }
    save(output / "testbed-manifest.json", manifest)
    save(output / "testbed-manifest-sha256.json", {"sha256": sha(output / "testbed-manifest.json")})
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.validation, args.review, args.output)
    print(json.dumps({key: result[key] for key in ("status", "G_TESTBED", "whole_goal_complete")}))
