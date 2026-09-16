"""Read-only recomputation of admission, actual payloads, costs and frozen scores."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

from check_v0210_control import LAB, write
from milai_lab.methods.horizon_diagnostic import score
from milai_lab.methods.prospective_admission import (
    OrderContract,
    Qualification,
    admit,
    fixed_prefix,
)
from milai_lab.methods.state_control import digest
from v02_local_provider import accounting, read_events


def audit(root: Path) -> dict:
    p0 = root / "p0-20260909"
    a, b = [json.loads((p0 / name).read_text()) for name in ("seal-a.json", "seal-b.json")]
    for name in ("seal-a", "seal-b"):
        assert (
            digest((p0 / f"{name}.json").read_bytes())
            == json.loads((p0 / f"{name}-sha256.json").read_text())["sha256"]
        )
    for name, sha in a["pins"].items():
        assert digest((p0 / name).read_bytes()) == sha, name
    contract = OrderContract(**a["contract"])
    clusters = json.loads((p0 / "cluster-manifest.json").read_text())
    allowed = tuple(c for c in clusters if not clusters[c]["prior_excluded"])
    assert contract.partition(allowed) == (tuple(a["discovery"]), tuple(a["confirmation"]))
    screening = json.loads((p0 / "screening-ledger.json").read_text())
    receipts = {
        row["cluster"]: Qualification(
            "ELIGIBLE" if row["status"] == "ACCEPTED" else row["status"],
            tuple(row["reasons"]),
            tuple(row["evidence"]),
        )
        for row in screening
        if row["status"] != "NOT_SCREENED"
    }
    replay = admit(tuple(a["discovery"]), receipts, target=12, screening_cap=60)
    assert fixed_prefix(replay, 12) == tuple(b["accepted_clusters"])
    accepted_keys = [
        row["query"] for c in b["accepted_clusters"] for row in b["accepted_queries"][c]
    ]
    for key in accepted_keys:
        ep = p0 / "evaluation" / f"{key}.json"
        assert digest(ep.read_bytes()) == b["evaluation_hashes"][ep.name]
        evaluation = json.loads(ep.read_text())
        source = p0 / "online" / key
        assert digest((source / "history.txt").read_bytes()) == evaluation["source_sha256"]
        assert set(json.loads((source / "question.json").read_text())) == {"question"}
        assert set(json.loads((source / "source-index.json").read_text())) == {"history.txt"}
    rows, waves, pids = [], [], set()
    for wave in ("p2-20260909", "p3-20260909"):
        path = root / wave
        execution = json.loads((path / "result.json").read_text())
        review = json.loads((path / "semantic-adjudication.json").read_text())
        reviewed = {row["query"]: row for row in review["rows"]}
        for name, sha in json.loads((path / "implementation-pin.json").read_text()).items():
            actual = LAB / name
            if digest(actual.read_bytes()) != sha:
                assert name == "tools/run_v0212_recurrence.py"
                snapshot = path / "run_v0212_recurrence.executed.py"
                assert digest(snapshot.read_bytes()) == sha
                assert ast.dump(ast.parse(snapshot.read_text())) == ast.dump(
                    ast.parse(actual.read_text())
                )
        for key, result in execution["queries"].items():
            directory = path / key
            state = accounting(read_events(directory / "provider-ledger.jsonl"))
            assert (
                state == result["accounting"] and not state["pending"] and not state["violations"]
            )
            assert state["requests"] <= 3 and state["raw_tokens"] <= 20000
            assert result["source_immutable"]
            assert result["pid"] not in pids
            pids.add(result["pid"])
            source = p0 / "online" / key
            raw = (source / "history.txt").read_bytes()
            events = read_events(directory / "provider-ledger.jsonl")
            for event in events:
                if event["event"] != "RESERVED":
                    continue
                request = directory / f"{event['request_id']}-request.json"
                assert digest(request.read_bytes()) == event["payload_sha256"]
                body = json.loads(request.read_text())
                assert event["prompt_tokens"] <= 8192 and body["max_tokens"] == 1024
                online = json.loads(body["messages"][1]["content"])
                assert set(online) == {
                    "question",
                    "source_files",
                    "source_view",
                    "memory_tools",
                    "source_tools",
                }
                assert (
                    online["question"]
                    == json.loads((source / "question.json").read_text())["question"]
                )
                page = online["source_view"]
                assert page["text"].encode() == raw[page["offset"] : page["end_offset"]]
                assert page["source_sha256"] == digest(raw)
            evaluation = json.loads((p0 / "evaluation" / f"{key}.json").read_text())
            scoring = (
                score(
                    result["answer"],
                    evaluation["official_correct_letter"],
                    evaluation["official_distractor_letter"],
                )
                if result["answer"] is not None
                else None
            )
            row = {
                "query": key,
                "wave": wave,
                "execution_status": result["status"],
                "scoring": scoring,
                "attribution": reviewed[key]["verdict"],
                "has_evolved": evaluation["has_evolved"],
                "preference_domain": evaluation["preference_domain"],
                "generations": state["requests"],
                "raw_tokens": state["raw_tokens"],
                "agent_memory_mutations": result["memory_mutations"],
                "relation_failure_established": reviewed[key].get(
                    "relation_or_applicability_mechanism_failure_established", False
                ),
            }
            rows.append(row)
        assert execution["actual_generations"] <= 12 and execution["actual_raw_tokens"] <= 80000
        cleanup = json.loads((path / "product/cleanup.json").read_text())
        assert cleanup["api_stopped"] and cleanup["compose_stop_returncode"] == 0
        services = json.loads((path / "product/services.json").read_text())
        assert all(not Path(f"/proc/{pid}").exists() for pid in services.values())
        waves.append(
            {
                "wave": wave,
                "generations": execution["actual_generations"],
                "raw_tokens": execution["actual_raw_tokens"],
                "seconds": execution["seconds"],
            }
        )
    assert [row["query"] for row in rows] == accepted_keys[:8]
    scored = [row for row in rows if row["scoring"] is not None]
    supported_wrong = [row for row in rows if row["attribution"] == "PRESENTED_SUPPORT_WRONG"]
    relation_wrong = [row for row in supported_wrong if row["relation_failure_established"]]
    result = {
        "status": "A0_DIAGNOSTIC_COMPLETE_KEEP_BASELINE",
        "scope": "Horizon discovery first wave plus one conditional fixed-prefix recurrence wave",
        "score_label": "NONSTANDARD_LOCAL_DIAGNOSTIC_NOT_OFFICIAL_LEADERBOARD",
        "admission": {
            "pool_clusters": a["pool_clusters"],
            "pool_queries": a["pool_queries"],
            "prior_excluded_clusters": len(a["prior_excluded_clusters"]),
            "prior_excluded_queries": a["prior_excluded_queries"],
            "discovery_clusters": len(a["discovery"]),
            "discovery_queries": a["discovery_queries"],
            "confirmation_clusters": len(a["confirmation"]),
            "confirmation_queries": a["confirmation_queries"],
            **b["counts"],
            "accepted_selected_queries": len(accepted_keys),
        },
        "screening_query_counts": {
            status: sum(
                len(a["preselected_probes"][row["cluster"]]["queries"])
                for row in screening
                if row["status"] == status
            )
            for status in ("ACCEPTED", "REJECTED", "UNRESOLVED", "NOT_SCREENED")
        },
        "execution": {
            "attempted_clusters": 4,
            "attempted_queries": len(rows),
            "valid_final_answers": len(scored),
            "scored": len(scored),
            "correct": sum(row["scoring"]["official_correct"] for row in scored),
            "incorrect": sum(not row["scoring"]["official_correct"] for row in scored),
            "unscored_no_final_answer": len(rows) - len(scored),
            "accepted_not_run_queries": len(accepted_keys) - len(rows),
        },
        "conditional_relation_fraction": {
            "n": len(relation_wrong),
            "N": len(supported_wrong),
            "meaning": ("Established relation/applicability failures among reviewed "
                        "support-presented wrong; limited diagnosis, not a population rate"),
        },
        "recurrence": {
            "first_wave_supported_wrong": sum(
                row["wave"] == "p2-20260909" for row in supported_wrong
            ),
            "second_wave_supported_wrong": sum(
                row["wave"] == "p3-20260909" for row in supported_wrong
            ),
            "mechanism_candidate_gate": False,
        },
        "waves": waves,
        "rows": rows,
        "actual_generations": sum(wave["generations"] for wave in waves),
        "actual_raw_tokens": sum(wave["raw_tokens"] for wave in waves),
        "paid_requests": 0,
        "benchmark_judge_requests": 0,
        "dataset_generation_requests": 0,
        "confirmation_opened": False,
        "predecessor_reopened": False,
        "agent_memory_mutations": sum(row["agent_memory_mutations"] for row in rows),
        "pool_ready": {
            "STALE": "FIXED_PACKAGE_UNAVAILABLE_IN_PINNED_OFFICIAL_TREE_AND_RELEASES",
            "HorizonBench": "READY_AND_EXECUTED_DISCOVERY_ONLY",
            "FactConsolidation": "FALLBACK_NOT_ENTERED_NO_ALLOCATION",
        },
        "limitations": [
            "Only visible lineage/exposure checks; hidden or pretraining overlap not excluded",
            "Two queries had no final answer because third-request full reservation exceeded 20k",
            "Six final answers used the initial partial final page without source-file retrieval",
            "MCP reads returned MISS or ABSENT; no Product source ingestion or benefit measured",
            "Subagent adjudication is model-assisted labour, not human gold or free evaluation",
        ],
    }
    assert result["recurrence"]["second_wave_supported_wrong"] == 0
    write(root / "terminal-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "execution",
                    "actual_generations",
                    "actual_raw_tokens",
                    "recurrence",
                )
            }
        )
    )
