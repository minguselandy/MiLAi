"""Execute the frozen two-wave WMA comparison, retaining every stage terminal."""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
MANIFEST = LAB / "configs/v0224-native-wma.json"
RAW = LAB.parent / "evidence/v0224/20260913-native-wma-v1"


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def revision_suffix(m):
    revision = m.get("execution_revision", "v1")
    if revision not in ("v1", "v2", "v3", "v4"):
        raise ValueError("UNSUPPORTED_EXECUTION_REVISION")
    return "-" + revision if revision != "v1" else ""


def latest_scored(rows):
    return {row["id"]: row for row in rows if row.get("status") == "SCORED"}


def stage(m, manifest_sha, command, root=None, arm=None, *, batch_deadline):
    label = "-".join(str(x) for x in (command, root, arm) if x)
    suffix = revision_suffix(m)
    directory = RAW / "stages" / (label + suffix)
    directory.mkdir(parents=True, exist_ok=False)
    if time.monotonic() >= batch_deadline:
        raise TimeoutError("BATCH_TIME_GUARD")
    reuse = m.get("reuse_stages", {}).get(label)
    if reuse is not None:
        first, second = (spec["root"] for spec in m["roots"][:2])
        allowed = {
            "calibrate": (
                "calibrate",
                RAW / "judge-calibration/terminal.json",
                "JUDGE_CALIBRATION_PASS",
            ),
            f"answer-{first}-B_native": (
                f"answer-{first}-B_native",
                RAW / "runs" / first / "B_native/terminal.json",
                "ANSWER_COMPLETE",
            ),
            f"answer-{second}-B_native": (
                f"answer-{second}-B_native-v2",
                RAW / "runs" / second / "B_native/terminal.json",
                "ANSWER_COMPLETE",
            ),
            f"judge-{first}-B_native": (
                f"judge-{first}-B_native-v2",
                RAW / "runs" / first / "B_native/judge-terminal-v2.json",
                "JUDGE_COMPLETE",
            ),
            f"judge-{second}-B_native": (
                f"judge-{second}-B_native-v3",
                RAW / "runs" / second / "B_native/judge-terminal-v3.json",
                "JUDGE_COMPLETE",
            ),
            f"answer-{first}-M_note": (
                f"answer-{first}-M_note-v3",
                RAW / "runs" / first / "M_note/terminal.json",
                "ANSWER_COMPLETE",
            ),
        }
        if (
            suffix != "-v4"
            or label not in allowed
            or set(reuse) != {"stage_terminal", "worker_result"}
        ):
            raise ValueError("STAGE_REUSE_NOT_ALLOWED")
        prior_label, result, expected = allowed[label]
        prior_terminal = RAW / "stages" / prior_label / "terminal.json"
        for field, path in (("stage_terminal", prior_terminal), ("worker_result", result)):
            pin = reuse[field]
            if pin["path"] != str(path) or sha(path) != pin["sha256"]:
                raise ValueError("REUSED_STAGE_PIN_DRIFT")
        previous = json.loads(prior_terminal.read_text())
        if (
            previous["stage"] != label
            or type(previous["exit_code"]) is not int
            or previous["exit_code"] != 0
            or previous["timed_out"] is not False
            or json.loads(result.read_text())["status"] != expected
        ):
            raise ValueError("REUSED_STAGE_NOT_COMPLETE")
        write(
            directory / "reused.json",
            {
                "stage": label,
                "status": "VERIFIED_PRIOR_STAGE_REUSED",
                "pins": reuse,
                "new_worker_spawned": False,
            },
        )
        return
    argv = [
        str(RAW / "venv/bin/python"),
        str(LAB / "tools/run_v0224_native_wma.py"),
        command,
        "--manifest-sha256",
        manifest_sha,
    ]
    if root:
        argv += ["--root", root, "--arm", arm]
    started = time.monotonic()
    with (directory / "stdout").open("x") as stdout, (directory / "stderr").open("x") as stderr:
        process = subprocess.Popen(argv, cwd=LAB, stdout=stdout, stderr=stderr)  # noqa: S603
        write(
            directory / "started.json",
            {"argv": argv, "pid": process.pid, "worker_seconds": m["worker_seconds"]},
        )
        timed_out = False
        try:
            remaining = min(m["worker_seconds"], batch_deadline - time.monotonic())
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, 0)
            code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                code = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait(timeout=30)
    terminal = {
        "stage": label,
        "exit_code": code,
        "timed_out": timed_out,
        "elapsed_seconds": time.monotonic() - started,
        "pid": process.pid,
    }
    write(directory / "terminal.json", terminal)
    print(json.dumps(terminal), flush=True)
    if timed_out or code != 0:
        raise RuntimeError("STAGE_FAILED: " + label)
    expected = "JUDGE_COMPLETE" if command == "judge" else "ANSWER_COMPLETE"
    if command == "calibrate":
        path = RAW / "judge-calibration/terminal.json"
        expected = "JUDGE_CALIBRATION_PASS"
    else:
        name = "judge-terminal" + suffix + ".json" if command == "judge" else "terminal.json"
        path = RAW / "runs" / root / arm / name
    if json.loads(path.read_text())["status"] != expected:
        raise RuntimeError("STAGE_INCOMPLETE: " + label)


def review_decision(m):
    signals = []
    for spec in m["roots"]:
        root = spec["root"]
        base = RAW / "runs" / root
        b = latest_scored(read_rows(base / "B_native/scores.jsonl"))
        a = {r["id"]: r for r in read_rows(base / "B_native/answers.jsonl")}
        answers = {r["id"]: r for r in read_rows(base / "M_note/answers.jsonl")}
        for r in latest_scored(read_rows(base / "M_note/scores.jsonl")).values():
            e = r.get("evidence_judge")
            if (
                r["id"] in b
                and r["id"] in answers
                and r["id"] in a
                and b[r["id"]]["answer_judge"]["evaluation_result"] == "Correct"
                and r["answer_judge"]["evaluation_result"] != "Correct"
                and answers[r["id"]]["answer"] != a[r["id"]]["answer"]
                and e
                and e["covered_count"] == e["total"]
                and e["total"] > 0
            ):
                signals.append({"root": root, "id": r["id"]})
    roots = [s["root"] for s in m["roots"] if any(x["root"] == s["root"] for x in signals)]
    triggered = len(roots) >= 2
    decision = {
        "rule": m["review_trigger"],
        "signals": signals,
        "roots": roots if triggered else [],
        "triggered": triggered,
    }
    write(RAW / ("review-decision" + revision_suffix(m) + ".json"), decision)
    return decision["roots"]


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    if sha(MANIFEST) != args.manifest_sha256:
        raise ValueError("MANIFEST_DRIFT")
    m = json.loads(MANIFEST.read_text())
    if m["status"] != "NATIVE_WMA_FROZEN_FOR_EXECUTION":
        raise ValueError("MANIFEST_NOT_FROZEN")
    for name, digest in {**m["local_sources"], **m["upstream_files"]}.items():
        if sha(name) != digest:
            raise ValueError("STARTUP_SOURCE_DRIFT: " + name)
    suffix = revision_suffix(m)
    for field in ("worker_seconds", "batch_seconds"):
        value = m[field]
        if type(value) not in (int, float) or not 0 < value < float("inf"):
            raise ValueError("INVALID_TIME_BUDGET")
    batch_deadline = started + m["batch_seconds"]
    write(
        RAW / ("batch-started" + suffix + ".json"),
        {
            "pid": os.getpid(),
            "manifest_sha256": sha(MANIFEST),
            "started_unix": time.time(),
            "batch_seconds": m["batch_seconds"],
        },
    )
    terminal = {"status": "NATIVE_BATCH_FAILED"}
    try:
        stage(m, args.manifest_sha256, "calibrate", batch_deadline=batch_deadline)
        for offset in (0, 2):
            roots = m["roots"][offset : offset + 2]
            for arm in ("B_native", "M_note"):
                for root in roots:
                    if time.monotonic() >= batch_deadline:
                        raise TimeoutError("BATCH_TIME_GUARD")
                    if arm == "M_note":
                        service = json.loads((RAW / "service/owned-state.json").read_text())
                        isolation = json.loads(
                            (RAW / "service/isolation/terminal.json").read_text()
                        )
                        if (
                            service["status"] != "TCP_READY_NOT_INTEGRATION_VALIDATED"
                            or isolation["status"] != "PASS"
                        ):
                            raise RuntimeError("ISOLATED_PUBLIC_NOTE_SERVICE_REQUIRED")
                    stage(
                        m,
                        args.manifest_sha256,
                        "answer",
                        root["root"],
                        arm,
                        batch_deadline=batch_deadline,
                    )
                    stage(
                        m,
                        args.manifest_sha256,
                        "judge",
                        root["root"],
                        arm,
                        batch_deadline=batch_deadline,
                    )
        for root in review_decision(m):
            stage(
                m, args.manifest_sha256, "answer", root, "R_review", batch_deadline=batch_deadline
            )
            stage(m, args.manifest_sha256, "judge", root, "R_review", batch_deadline=batch_deadline)
        terminal["status"] = "NATIVE_BATCH_COMPLETE"
    except BaseException as exc:
        terminal.update({"error": type(exc).__name__, "reason": str(exc)})
        raise
    finally:
        terminal.update({"elapsed_seconds": time.monotonic() - started, "pid": os.getpid()})
        write(RAW / ("batch-terminal" + suffix + ".json"), terminal)


if __name__ == "__main__":
    main()
