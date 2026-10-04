"""Root orchestration: one frozen first-attempt trajectory, then offline review.

This is not a runtime scorer, an independent judge, or a global HTTP owner.
Actual use requires a new separately accepted/frozen/published cohort.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ACTUAL_LEDGER = Path("/cra/memory/mx_memory/MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json")
HARD_STOP_KEYS = {
    "leak",
    "gold_contamination",
    "shared_owner_pollution",
    "false_durable_save",
    "original_results_corruption",
}


class Refused(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Refused(reason)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def immutable_json(path: Path, value: Any) -> None:
    with path.open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def immutable_bytes(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def filemap(path: Path) -> dict[str, str]:
    return {str(p.relative_to(path)): sha(p) for p in path.rglob("*") if p.is_file()}


def now() -> str:
    return datetime.now(UTC).isoformat()


class Controller:
    def __init__(self, manifest: Path) -> None:
        self.manifest_path = manifest.resolve()
        self.meta = read(self.manifest_path)
        self.job = Path(self.meta["job_root"]).resolve()
        self.lab = Path(self.meta["lab_root"]).resolve()
        self.cohort = Path(self.meta["cohort_root"]).resolve()
        self.ledger = Path(self.meta["continuous_ledger_path"]).resolve(strict=True)
        self.state_path = self.job / "state.json"
        require(
            self.job != self.cohort and not self.job.is_relative_to(self.cohort),
            "STATE_INSIDE_RAW_COHORT",
        )

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.job.mkdir(parents=True, exist_ok=True)
        with (self.job / "controller.lock").open("a+b") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Refused("LOCAL_PARENT_CONTROLLER_ALREADY_RUNNING") from error
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def save_state(self, state: dict[str, Any]) -> None:
        temporary = self.job / "state.next.json"
        with temporary.open("w") as stream:
            stream.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.state_path)
        descriptor = os.open(self.job, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def verify(self) -> dict[str, Any]:
        m = self.meta
        require(m["kind"] == "ROOT_STAGED_E0_FROZEN_CONTROLLER", "WRONG_CONTROLLER_CONTRACT")
        require(sha(Path(__file__).resolve()) == m["parent_driver_sha256"], "PARENT_DRIVER_CHANGED")
        domain = m["execution_domain"]
        require(
            domain in {"actual_frozen_e0", "scripted_local_control"}, "UNKNOWN_EXECUTION_DOMAIN"
        )
        if domain == "actual_frozen_e0":
            require(
                self.ledger == ACTUAL_LEDGER.resolve(strict=True),
                "ACTUAL_LEDGER_REPLACEMENT_FORBIDDEN",
            )
            require(m["source_owner"] == "HOLD", "SOURCE_NOT_FROZEN_HOLD")
            require(
                m["expected_trajectories"] == 24 and m["expected_messages"] == 48,
                "ACTUAL_E0_PLAN_CHANGED",
            )
            require(
                Path(m["python_executable"]).resolve()
                == Path("/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python").resolve(),
                "ACTUAL_PYTHON_CHANGED",
            )
        else:
            require(self.ledger.is_relative_to(self.job), "SYNTHETIC_LEDGER_OUTSIDE_CONTROL")
            require(
                self.ledger != ACTUAL_LEDGER.resolve(), "SYNTHETIC_CONTROL_ACTUAL_LEDGER_FORBIDDEN"
            )
            require(m.get("socket_denial_active") is True, "SYNTHETIC_SOCKET_DENIAL_REQUIRED")
        freeze_path = self.cohort / "input-freeze.json"
        require(sha(freeze_path) == m["input_freeze_sha256"], "INPUT_FREEZE_CHANGED")
        frozen = read(freeze_path)
        runtime_path = Path(m["runtime_manifest_path"])
        require(sha(runtime_path) == m["runtime_manifest_sha256"], "RUNTIME_MANIFEST_CHANGED")
        runtime = read(runtime_path)
        require(
            runtime["status"] == "FROZEN_READY" and runtime["source_owner"] == "HOLD",
            "RUNTIME_NOT_READY_HOLD",
        )
        actual_paths = {*self.lab.glob("src/milai_lab/**/*.py"), self.lab / "tools/run_v13_1_d0.py"}
        actual = {str(p.relative_to(self.lab)): sha(p) for p in actual_paths if p.is_file()}
        require(
            actual == frozen["source_sha256"] == runtime["source_sha256"],
            "RUNTIME_PATH_SET_OR_BYTES_CHANGED",
        )
        require(len(actual) == runtime["source_file_count"], "RUNTIME_COUNT_CHANGED")
        for kind in ["fixture", "config"]:
            require(
                sha(Path(frozen[kind + "_path"]))
                == frozen[kind + "_sha256"]
                == runtime[kind + "_sha256"],
                kind.upper() + "_CHANGED",
            )
        require(
            runtime["input_freeze_sha256"] == m["input_freeze_sha256"],
            "RUNTIME_INPUT_BINDING_CHANGED",
        )
        order = m["execution_order"]
        cases = frozen["fixture"]["cases"]
        require(
            len(order) == len(set(order)) == len(cases) == m["expected_trajectories"],
            "ORDER_OR_CASE_COUNT_CHANGED",
        )
        require(set(order) == {c["case_id"] for c in cases}, "ORDER_CASE_SET_CHANGED")
        require(
            sum(len(c["messages"]) for c in cases) == m["expected_messages"],
            "MESSAGE_COUNT_CHANGED",
        )
        proof_path = Path(m["publication_proof_path"])
        require(sha(proof_path) == m["publication_proof_sha256"], "PUBLICATION_PROOF_CHANGED")
        proof = read(proof_path)
        require(
            proof["kind"] == "ROOT_COHORT_FROZEN_PRE_FIRST_HTTP_GITHUB_VERIFIED",
            "WRONG_PUBLICATION_PROOF",
        )
        require(proof["execution_domain"] == domain, "PUBLICATION_EXECUTION_DOMAIN_CHANGED")
        require(
            proof["synthetic_control"] is (domain == "scripted_local_control"),
            "SYNTHETIC_PUBLICATION_MISCLAIM",
        )
        require(
            len(proof["head_sha"]) == 40 and set(proof["head_sha"]) <= set("0123456789abcdef"),
            "INVALID_PUBLICATION_HEAD_SHA",
        )
        require(
            proof["head_sha"] == proof["pr"]["head_sha"] == proof["remote_head_sha"],
            "REMOTE_PR_HEAD_MISMATCH",
        )
        require(
            proof["body_exact"] is True
            and proof["pr"]["draft"] is True
            and proof["pr"]["merged"] is False,
            "PUBLICATION_STATE_CHANGED",
        )
        require(
            proof["frozen_bindings"]
            == {
                k: m[k]
                for k in ["parent_driver_sha256", "runtime_manifest_sha256", "input_freeze_sha256"]
            },
            "PUBLICATION_FREEZE_BINDINGS_CHANGED",
        )
        require(
            runtime["ledger_before_sha256"] == m["ledger_before_sha256"],
            "INITIAL_LEDGER_BINDING_CHANGED",
        )
        return cast(dict[str, Any], frozen)

    def evidence(self, rows: list[dict[str, Any]]) -> None:
        require(bool(rows), "REVIEW_EVIDENCE_REQUIRED")
        for row in rows:
            p = Path(row["path"]).resolve(strict=True)
            require(sha(p) == row["sha256"], "REVIEW_EVIDENCE_CHANGED")

    def initialize(self) -> dict[str, Any]:
        frozen = self.verify()
        require(not self.state_path.exists(), "EXISTING_ATTEMPT_STATE_NEVER_REINITIALIZED")
        require(
            sha(self.ledger) == self.meta["ledger_before_sha256"], "INITIAL_LEDGER_ALREADY_CHANGED"
        )
        for case in frozen["fixture"]["cases"]:
            folder = self.cohort / hashlib.sha256(case["case_id"].encode()).hexdigest()[:16]
            require(
                not folder.exists() or not any(folder.iterdir()),
                "PRIOR_CASE_EXECUTION_ARTIFACTS_NEVER_REPLAYED",
            )
        state = {
            "kind": "ROOT_STAGED_E0_STATE",
            "phase": "READY_NEXT_UNRUN",
            "manifest_sha256": sha(self.manifest_path),
            "started_at_utc": now(),
            "attempts": [],
            "ledger_expected_sha256": sha(self.ledger),
            "cohort_expected_files": filemap(self.cohort),
            "next_index": 0,
        }
        self.save_state(state)
        return {
            "status": state["phase"],
            "planned": len(self.meta["execution_order"]),
            "model_dispatched": False,
        }

    def check_review(self, state: dict[str, Any]) -> str:
        last = state["attempts"][-1]
        p = self.job / "reviews" / (str(last["index"]).zfill(3) + ".json")
        if not p.exists():
            return "REVIEW_REQUIRED"
        review = read(p)
        require(review["kind"] == "ROOT_DEVELOPMENT_DIAGNOSTIC_CHECKPOINT", "WRONG_REVIEW_KIND")
        require(
            review["reviewer"] == "Root" and review["independent_review"] is False,
            "REVIEW_INDEPENDENCE_MISCLAIM",
        )
        require(
            review["original_attempt_sha256"] == last["receipt_sha256"],
            "REVIEW_WRONG_ORIGINAL_ATTEMPT",
        )
        require(review["case_id"] == last["case_id"], "REVIEW_WRONG_CASE")
        require(
            isinstance(review.get("review_explanation"), str)
            and bool(review["review_explanation"].strip()),
            "EXPLICIT_ROOT_EXPLANATION_REQUIRED",
        )
        require(set(review["hard_stop_findings"]) == HARD_STOP_KEYS, "INCOMPLETE_HARD_STOP_REVIEW")
        require(
            set(review["hard_stop_findings"].values())
            <= {"DETECTED", "NOT_DETECTED", "UNRESOLVED"},
            "INVALID_HARD_STOP_STATE",
        )
        self.evidence(review["original_evidence"])
        if set(review["hard_stop_findings"].values()) != {"NOT_DETECTED"}:
            return "HOLD_AFFECTED_COHORT"
        require(
            review["development_verdict"] in {"PASS", "FAIL", "UNKNOWN"},
            "INVALID_DEVELOPMENT_VERDICT",
        )
        require(
            review["decision"] in {"CONTINUE_NEXT_UNRUN", "HOLD_AFFECTED_COHORT"},
            "INVALID_ROOT_DECISION",
        )
        if review["decision"] == "HOLD_AFFECTED_COHORT":
            return "HOLD_AFFECTED_COHORT"
        if last["returncode"] != 0 or review["development_verdict"] != "PASS":
            self.evidence(review["primary_method_design_reflection"])
            require(
                review["continuing_tasks_independent"] is True,
                "FAILED_CASE_REQUIRES_INDEPENDENT_CONTINUATION",
            )
        require(not last["postcheck_error"], "POSTCHILD_FREEZE_DRIFT_CANNOT_CONTINUE")
        if "review_sha256" in last:
            require(last["review_sha256"] == sha(p), "ACKNOWLEDGED_REVIEW_CHANGED")
        else:
            last["review_path"] = str(p)
            last["review_sha256"] = sha(p)
        return "ROOT_REVIEWED"

    def check_original_attempts(self, state: dict[str, Any]) -> None:
        for attempt in state["attempts"]:
            receipt = Path(attempt["receipt_path"])
            require(
                filemap(receipt.parent) == attempt["original_files_sha256"],
                "ORIGINAL_ATTEMPT_OUTPUT_BYTES_CHANGED",
            )
            require(sha(receipt) == attempt["receipt_sha256"], "ORIGINAL_ATTEMPT_RECEIPT_CHANGED")
            if "review_sha256" in attempt:
                review_path = Path(attempt["review_path"])
                require(sha(review_path) == attempt["review_sha256"], "ACKNOWLEDGED_REVIEW_CHANGED")
                review = read(review_path)
                self.evidence(review["original_evidence"])
                if attempt["returncode"] != 0 or review["development_verdict"] != "PASS":
                    self.evidence(review["primary_method_design_reflection"])

    def next(self) -> dict[str, Any]:
        frozen = self.verify()
        require(self.state_path.exists(), "INITIALIZE_FRESH_COHORT_FIRST")
        state = read(self.state_path)
        require(state["manifest_sha256"] == sha(self.manifest_path), "CONTROLLER_MANIFEST_CHANGED")
        require(state["phase"] != "DISPATCHING", "PRIOR_DISPATCH_OUTCOME_UNKNOWN_NO_REDISPATCH")
        require(
            state["phase"] not in {"HOLD_AFFECTED_COHORT", "ATTEMPTS_COLLECTED_ROOT_REVIEWED"},
            state["phase"],
        )
        require(
            sha(self.ledger) == state["ledger_expected_sha256"],
            "LEDGER_CHANGED_SINCE_ORIGINAL_STEP",
        )
        require(
            filemap(self.cohort) == state["cohort_expected_files"], "ORIGINAL_COHORT_BYTES_CHANGED"
        )
        self.check_original_attempts(state)
        if state["attempts"]:
            last = state["attempts"][-1]
            require(
                sha(Path(last["receipt_path"])) == last["receipt_sha256"],
                "ORIGINAL_ATTEMPT_RECEIPT_CHANGED",
            )
            verdict = self.check_review(state)
            if verdict != "ROOT_REVIEWED":
                if verdict == "HOLD_AFFECTED_COHORT":
                    state["phase"] = verdict
                    self.save_state(state)
                return {
                    "status": verdict,
                    "finished_attempts": len(state["attempts"]),
                    "not_started": len(self.meta["execution_order"]) - state["next_index"],
                    "model_dispatched": False,
                }
        index = state["next_index"]
        if index == len(self.meta["execution_order"]):
            state["phase"] = "ATTEMPTS_COLLECTED_ROOT_REVIEWED"
            self.save_state(state)
            return {
                "status": state["phase"],
                "quality_gate_passed": False,
                "full_plan_completed": False,
                "model_dispatched": False,
            }
        case_id = self.meta["execution_order"][index]
        case = next(c for c in frozen["fixture"]["cases"] if c["case_id"] == case_id)
        folder = self.job / "attempts" / str(index).zfill(3)
        folder.mkdir(parents=True, exist_ok=False)
        command = [
            self.meta["python_executable"],
            str(self.lab / "tools/run_v13_1_d0.py"),
            "run",
            "--run-root",
            str(self.cohort),
            "--case-id",
            case_id,
        ]
        before_cohort = filemap(self.cohort)
        immutable_bytes(folder / "ledger-before.json", self.ledger.read_bytes())
        require(
            sha(folder / "ledger-before.json")
            == sha(self.ledger)
            == state["ledger_expected_sha256"],
            "LEDGER_CHANGED_BEFORE_DISPATCH",
        )
        issued = {
            "kind": "IMMUTABLE_FIRST_ATTEMPT_ISSUED",
            "index": index,
            "case_id": case_id,
            "actual_planned_messages": len(case["messages"]),
            "command": command,
            "issued_at_utc": now(),
            "ledger_before_sha256": sha(self.ledger),
            "cohort_before_files": before_cohort,
            "manifest_sha256": sha(self.manifest_path),
        }
        immutable_json(folder / "issued.json", issued)
        state["phase"] = "DISPATCHING"
        state["inflight"] = {
            "index": index,
            "case_id": case_id,
            "issued_sha256": sha(folder / "issued.json"),
        }
        self.save_state(state)
        child_env = {**os.environ, "PYTHONPATH": str(self.lab / "src")}
        if self.meta["execution_domain"] == "scripted_local_control":
            child_env["PYTHONPATH"] = (
                self.meta["socket_denial_directory"] + os.pathsep + child_env["PYTHONPATH"]
            )
            child_env["PYTHONDONTWRITEBYTECODE"] = "1"
        # Trusted Root manifest, fixed CLI argv, exact frozen source checks above; no shell.
        result = subprocess.run(command, cwd=self.lab, capture_output=True, env=child_env)  # noqa: S603
        immutable_bytes(folder / "stdout.log", result.stdout)
        immutable_bytes(folder / "stderr.log", result.stderr)
        immutable_bytes(folder / "ledger-after.json", self.ledger.read_bytes())
        after_cohort = filemap(self.cohort)
        post_error = None
        try:
            self.verify()
            current_prefix = hashlib.sha256(case_id.encode()).hexdigest()[:16] + "/"
            for p in before_cohort:
                require(
                    p.startswith(current_prefix)
                    or p == "process-results.json"
                    or after_cohort.get(p) == before_cohort[p],
                    "PRIOR_CASE_OR_FROZEN_FILE_CHANGED_BY_CHILD",
                )
            for p in set(after_cohort) - set(before_cohort):
                require(
                    p.startswith(current_prefix) or p == "process-results.json",
                    "UNCLAIMED_COHORT_FILE_CREATED_BY_CHILD",
                )
        except Exception as error:
            post_error = {"type": type(error).__name__, "message": str(error)}
        # Do not infer missing finals, usage, semantic correctness or native effects.
        receipt = {
            **issued,
            "kind": "ORIGINAL_FIRST_ATTEMPT_CHILD_RECEIPT",
            "finished_at_utc": now(),
            "returncode": result.returncode,
            "stdout_sha256": sha(folder / "stdout.log"),
            "stderr_sha256": sha(folder / "stderr.log"),
            "ledger_after_sha256": sha(folder / "ledger-after.json"),
            "cohort_after_files": after_cohort,
            "postcheck_error": post_error,
            "root_review": "REQUIRED_UNRATED",
            "execution_domain": self.meta["execution_domain"],
        }
        if (self.cohort / "process-results.json").exists():
            immutable_bytes(
                folder / "original-process-results.json",
                (self.cohort / "process-results.json").read_bytes(),
            )
            receipt["original_process_results_sha256"] = sha(
                folder / "original-process-results.json"
            )
        immutable_json(folder / "receipt.json", receipt)
        state["attempts"].append(
            {
                "index": index,
                "case_id": case_id,
                "returncode": result.returncode,
                "receipt_path": str(folder / "receipt.json"),
                "receipt_sha256": sha(folder / "receipt.json"),
                "postcheck_error": post_error,
                "original_files_sha256": filemap(folder),
            }
        )
        state.pop("inflight")
        state["next_index"] += 1
        state["phase"] = "REVIEW_REQUIRED"
        state["ledger_expected_sha256"] = sha(folder / "ledger-after.json")
        state["cohort_expected_files"] = after_cohort
        self.save_state(state)
        return {
            "status": state["phase"],
            "case_id": case_id,
            "returncode": result.returncode,
            "finished_attempts": len(state["attempts"]),
            "not_started": len(self.meta["execution_order"]) - state["next_index"],
            "original_receipt_path": str(folder / "receipt.json"),
            "execution_domain": self.meta["execution_domain"],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["initialize", "next"])
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        controller = Controller(args.manifest)
        with controller.lock():
            answer = controller.initialize() if args.command == "initialize" else controller.next()
        print(json.dumps(answer, ensure_ascii=False))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "REFUSED_NO_AUTOMATIC_REDISPATCH",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
