"""Execute a predeclared bounded batch of native benchmark worker processes.

Independent banks may run concurrently. A dependent job inherits only its own
declared predecessor's latest completed checkpoint. Failed jobs are never retried.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import time
from pathlib import Path


def run(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text())
    lab = Path(__file__).resolve().parents[1]
    jobs = {job["id"]: job for job in manifest["jobs"]}
    pending, running, completed = list(jobs), {}, {}
    status_path = manifest_path.with_name(manifest_path.stem + "-status.json")
    if status_path.exists():
        raise ValueError("BATCH_ALREADY_STARTED_NO_AUTOMATIC_REPLAY")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join([str(lab / "src"), str(lab / "tools")])

    def worker(job, parent):
        config_path = Path(job["config"])
        config = json.loads(config_path.read_text())
        root = Path(config["output_root"])
        if parent and parent.get("bank"):
            config["bank_input"] = parent["bank"]
        actual = config_path.with_name(config_path.stem + "-resolved.json")
        actual.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        travel = config["domain"] == "travel"
        interpreter = Path(config["benchmark_root"]) / (
            "travel-venv/bin/python" if travel else "lifelong-venv/bin/python"
        )
        script = lab / "tools" / (
            "run_reasoningbank_travel.py" if travel else "run_reasoningbank_lifelong.py"
        )
        begin = time.monotonic()
        with root.with_suffix(".log").open("w") as log:
            result = subprocess.run(  # noqa: S603 -- predeclared local runner and environment
                [str(interpreter), str(script), "--config", str(actual)],
                cwd=lab, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False,
            )
        if travel:
            with root.with_suffix(".scoring.log").open("w") as log:
                scoring = subprocess.run(  # noqa: S603 -- evaluator only, same fixed environment
                    [str(interpreter), str(lab / "tools/score_reasoningbank_travel.py"),
                     "--config", str(actual)],
                    cwd=lab, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False,
                )
        banks = [root / "bank.json"]
        if travel:
            banks += [root / f"group-{config['ids'][0]}" / "bank.json"]
        bank = next((str(path) for path in banks if path.exists()), None)
        if bank is None and parent:
            bank = parent.get("bank")
        return {
            "id": job["id"], "exit_code": result.returncode,
            "scoring_exit_code": scoring.returncode if travel else None,
            "seconds": time.monotonic() - begin, "bank": bank,
            "config": str(actual), "root": str(root),
        }

    def save():
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "planned": len(jobs), "workers": manifest["workers"],
            "running": list(running.values()), "pending": pending,
            "completed": completed,
        }, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(status_path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=manifest["workers"]) as pool:
        while pending or running:
            for identifier in list(pending):
                if len(running) >= manifest["workers"]:
                    break
                job = jobs[identifier]
                parent = job.get("parent")
                if parent and parent not in completed:
                    continue
                pending.remove(identifier)
                running[pool.submit(worker, job, completed.get(parent))] = identifier
            save()
            if not running:
                raise ValueError("UNRESOLVED_BATCH_DEPENDENCY")
            ready, _ = concurrent.futures.wait(
                running, timeout=10, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in ready:
                identifier = running.pop(future)
                try:
                    completed[identifier] = future.result()
                except Exception as error:
                    completed[identifier] = {"id": identifier, "worker_error": str(error)}
                print(json.dumps(completed[identifier], ensure_ascii=False), flush=True)
            save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    run(parser.parse_args().manifest)


if __name__ == "__main__":
    main()
