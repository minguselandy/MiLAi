"""Close one terminal phase and account its actual ledgers exactly once."""

from __future__ import annotations

import argparse
import collections
import json
from datetime import UTC, datetime
from pathlib import Path

from summarize_reasoningbank_evaluation import costs


def close(manifest_path: Path, phase_id: str):
    manifest = json.loads(manifest_path.read_text())
    phases = [*manifest.get("development_allocations", []),
              *manifest.get("evaluation_allocations", [])]
    phase = next(row for row in phases if row["id"] == phase_id)
    if phase["status"] != "RUNNING":
        raise ValueError("PHASE_NOT_RUNNING_NO_DOUBLE_ACCOUNTING")
    batch_path = Path(phase["batch"])
    batch = json.loads(batch_path.read_text())
    status_path = Path(phase.get("status_manifest", batch_path.with_name("batch-status.json")))
    status = json.loads(status_path.read_text())
    if any(job["id"] not in status["completed"] for job in batch["jobs"]):
        raise ValueError("PHASE_HAS_UNFINISHED_JOBS")
    totals = collections.Counter()
    roles = collections.defaultdict(collections.Counter)
    failures = []
    for job in batch["jobs"]:
        config = json.loads(Path(job["config"]).read_text())
        usage = costs(Path(config["output_root"]))
        for key in ("settled_requests", "settled_tokens", "unknown_requests",
                    "unknown_token_upper_bound"):
            totals[key] += usage[key]
        for key, value in usage["embedding"].items():
            totals["embedding_" + key] += value
        for role, value in usage["roles"].items():
            roles[role].update(value)
        terminal = status["completed"][job["id"]]
        if terminal.get("exit_code") != 0 or terminal.get("scoring_exit_code") not in (None, 0):
            failures.append(job["id"])
    phase.update(
        status="COMPLETED_WITH_FAILURES" if failures else "COMPLETED",
        closed_at=datetime.now(UTC).isoformat(),
        used_generations=totals["settled_requests"], used_raw_tokens=totals["settled_tokens"],
        unknown_requests=totals["unknown_requests"],
        unresolved_upper_bound=totals["unknown_token_upper_bound"],
        embedding={key.removeprefix("embedding_"): value for key, value in totals.items()
                   if key.startswith("embedding_")},
        roles={role: dict(value) for role, value in roles.items()}, failed_jobs=failures,
    )
    manifest["new_experiment_generations"] += totals["settled_requests"]
    manifest["new_settled_text_tokens"] += totals["settled_tokens"]
    manifest["unknown_text_requests"] += totals["unknown_requests"]
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(manifest_path)
    result = {"phase": phase_id, "totals": dict(totals), "failed_jobs": failures,
              "unused_capacity": "CLOSED_NOT_REUSED"}
    (batch_path.parent / "closure-summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    print(json.dumps(close(args.manifest, args.phase), ensure_ascii=False))


if __name__ == "__main__":
    main()
