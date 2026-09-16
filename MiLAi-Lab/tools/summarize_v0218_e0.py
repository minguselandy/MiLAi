"""Recompute all E0 denominators; distinguish protocols, probes and independent roots."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from audit_v0218_baseline import audit_baseline
from run_v0218 import costs, sha


def read(path):
    return json.loads(path.read_text())


def summarize(base: Path, output: Path) -> dict:
    main = [base / f"e0-baseline-wave{wave}-v2" for wave in (1, 2, 3)]
    probes = base / "e0-probes-v4-v1"
    summaries, batches = [], []
    host_hashes, roots = set(), set()
    for batch in (*main, probes):
        manifest, result = read(batch / "manifest.json"), read(batch / "result.json")
        assert result["status"] == "E0_EXECUTED_REQUIRES_CHAIN_AND_BEHAVIOR_AUDIT"
        assert (
            manifest["protocol_revision"]["revision"]
            == "COMMON_HOST_V4_SETTLED_ENCODING_ERROR_FEEDBACK"
        )
        assert not result["cost"]["pending"] and not result["cost"]["violations"]
        assert (
            result["cleanup"]["api_stopped"] and result["cleanup"]["compose_stop_returncode"] == 0
        )
        audit = audit_baseline(batch)
        assert len(result["rows"]) == len(manifest["episodes"]) == (20 if batch == probes else 14)
        if batch != probes:
            batch_roots = {row["root"] for row in result["rows"]}
            assert len(batch_roots) == 2 and not batch_roots.intersection(roots)
            roots.update(batch_roots)
        host_hashes.add(manifest["implementation"]["tools/v0218_host.py"])
        summaries.append(audit)
        actions = [action for row in result["rows"] for action in row["actions"]]
        rejected = [
            action
            for action in actions
            if action.get("tool_result", {}).get("status") == "ACTION_REJECTED"
        ]
        batches.append(
            {
                "batch": batch.name,
                "path": str(batch),
                "stage": manifest["stage"],
                "manifest_sha256": sha(batch / "manifest.json"),
                "result_sha256": sha(batch / "result.json"),
                "audit_sha256": sha(batch / "baseline-audit-v1.json"),
                "cost": result["cost"],
                "execution_statuses": dict(Counter(row["status"] for row in result["rows"])),
                "rejections": dict(
                    Counter(action["tool_result"]["reason"].split(":", 1)[0] for action in rejected)
                ),
            }
        )
    assert len(host_hashes) == 1 and len(roots) == 6
    main_rows = [row for summary in summaries[:3] for row in summary["rows"]]
    probe_rows = summaries[3]["rows"]
    assert len(main_rows) == 42 and len(probe_rows) == 20
    assert {row["root"] for row in probe_rows}.issubset(roots)
    pairs = []
    for category, rows in (("standard", main_rows), ("probe", probe_rows)):
        for key, variant in sorted(
            {(row["root"], row["variant"]) for row in rows if row["phase"] == "B"}
        ):
            arms = {
                row["arm"]: row for row in rows if row["root"] == key and row["variant"] == variant
            }
            assert set(arms) == {"N0", "N1", "N2"}
            pairs.append(
                {
                    "category": category,
                    "root": key,
                    "variant": variant,
                    "arms": {
                        arm: {
                            field: row[field]
                            for field in (
                                "business_status",
                                "requests",
                                "raw_tokens",
                                "seconds",
                                "business_mutations",
                                "exact_redundant_business_writes",
                                "source_reads",
                                "cold_old_note",
                                "both_presented",
                            )
                        }
                        for arm, row in arms.items()
                    },
                }
            )
    all_cost, prior_batches = {"requests": 0, "raw_tokens": 0}, []
    historical = base.parent / "20260910"
    for batch in [
        *[
            historical / name
            for name in (
                "t3-note-chain-v1",
                "t3-note-chain-v2",
                "t3-note-chain-v3",
                "t4-note-chain-v1",
            )
        ],
        *[base / f"e0-baseline-wave{wave}-v1" for wave in (1, 2, 3)],
        *main,
        probes,
    ]:
        cost = costs(batch)
        assert (
            cost == read(batch / "result.json")["cost"]
            and not cost["pending"]
            and not cost["violations"]
        )
        for key in all_cost:
            all_cost[key] += cost[key]
        prior_batches.append(
            {"path": str(batch), "result_sha256": sha(batch / "result.json"), "cost": cost}
        )

    def denominators(rows):
        a_rows = [row for row in rows if row["phase"] == "A"]
        b_rows = [row for row in rows if row["phase"] == "B"]
        return {
            "A_attempts": len(a_rows),
            "A_self_note": sum(row["agent_note_writes"] > 0 for row in a_rows),
            "A_NO_WRITE": sum(row["agent_note_writes"] == 0 for row in a_rows),
            "B_attempts": len(b_rows),
            "B_all_16_opportunities_used": [
                row["episode_id"] for row in b_rows if row["requests"] == 16
            ],
            "B_resource_terminal_statuses": [
                {"episode_id": row["episode_id"], "status": row["execution_status"]}
                for row in b_rows
                if row["execution_status"] in ("EPISODE_DEADLINE", "GENERATION_CAP_REACHED")
            ],
            "B_cold_note": sum(row["cold_old_note"] for row in b_rows),
            "B_both_presented": sum(row["both_presented"] for row in b_rows),
            "business_statuses_all_attempts": dict(Counter(row["business_status"] for row in rows)),
            "business_statuses_B": dict(Counter(row["business_status"] for row in b_rows)),
            "B_by_arm": {
                arm: dict(Counter(row["business_status"] for row in b_rows if row["arm"] == arm))
                for arm in ("N0", "N1", "N2")
            },
            "shared_A_cost_once": {
                key: sum(row[key] for row in a_rows) for key in ("requests", "raw_tokens")
            },
            "B_cost": {key: sum(row[key] for row in b_rows) for key in ("requests", "raw_tokens")},
        }

    result = {
        "status": "E0_V4_STANDARD_AND_PROBES_ALL_ATTEMPT_AUDITED_SEMANTIC_REVIEW_SEPARATE",
        "standard_root_count": 6,
        "probe_root_count_not_additional": 2,
        "standard": denominators(main_rows),
        "probes": denominators(probe_rows),
        "pairs": pairs,
        "active_batches": batches,
        "all_batches": prior_batches,
        "all_goal_provider_cost": all_cost,
        "judge_requests": 0,
        "S_star": "REQUIRES_EXPLICIT_DEVELOPER_SELECTION_NOT_PER_ROOT_CHERRY_PICKING",
        "memory_causality": "NOT_INFERRED_FROM_AGGREGATE_TASK_FAILURE",
        "older_protocols": "Retained in total cost, not pooled into same-protocol main results",
        "whole_goal_complete": False,
    }
    if output.exists():
        assert read(output) == result
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.base, args.output)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("pairs", "active_batches", "all_batches")}
        )
    )
