from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .compressors import METHODS
from .models import load_fixtures
from .scorer import aggregate, score_one

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures" / "pilot.jsonl"
RESULT_JSON = ROOT / "results" / "pilot_metrics.json"
RESULT_MARKDOWN = ROOT / "results" / "pilot_report.md"
PRIMARY_EQUIVALENCE_FIELDS = (
    "identity_recall",
    "branch_recall",
    "representation_false_closure_rate",
    "decision_false_closure_rate",
    "legal_resolution_accuracy",
    "later_task_success",
    "unsupported_claim_rate",
    "infeasible_rate",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hard_falsifier(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ospc = metrics["ospc"]
    typed = metrics["typed_state"]
    static = metrics["static_open_issue"]
    typed_equivalent = all(
        typed[field] == ospc[field] for field in PRIMARY_EQUIVALENCE_FIELDS
    )
    static_equivalent = all(
        static[field] == ospc[field] for field in PRIMARY_EQUIVALENCE_FIELDS
    )
    reasons: list[str] = []
    if typed_equivalent:
        reasons.append("HF-01_STRONG_TYPED_STATE_EQUIVALENT")
    if static_equivalent:
        reasons.append("HF-02_STATIC_OPEN_ISSUE_EQUIVALENT")
    if (
        ospc["validator_checks_total"] > typed["validator_checks_total"]
        and typed_equivalent
    ):
        reasons.append("HF-06_VALIDATOR_COST_WITHOUT_MEASURED_GAIN")
    return {
        "decision": "ABANDON" if reasons else "HOLD",
        "novelty_claim": False,
        "primary_equivalence_fields": list(PRIMARY_EQUIVALENCE_FIELDS),
        "reasons": reasons or ["PILOT_SYNTHETIC_ONLY_NO_GO_EVIDENCE"],
        "scope": "OSPC novelty candidate only; Lean product behavior is unchanged.",
        "static_open_issue_equivalent": static_equivalent,
        "typed_state_equivalent": typed_equivalent,
    }


def render_markdown(report: dict[str, Any]) -> str:
    columns = (
        "method",
        "feasible",
        "identity",
        "branches",
        "pointers",
        "representation FC",
        "decision FC",
        "unsupported",
        "resolution",
        "task success",
        "tokens mean",
    )
    lines = [
        "# OSPC deterministic pilot result",
        "",
        "> Schema `0.1.x EXPERIMENTAL`  ",
        "> Implementation `CANDIDATE`  ",
        "> `NO-GO FOR SCHEMA FREEZE`",
        "",
        f"Decision: **{report['hard_falsifier']['decision']} novelty claim**.",
        "",
        "Primary metrics exclude explicit infeasible rows; infeasible rate is always reported beside them. ",
        "A method therefore cannot turn an insufficient budget into a zero-false-closure success.",
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for method, metric in report["metrics"].items():
        lines.append(
            "| "
            + " | ".join(
                (
                    method,
                    f"{metric['feasible_count']}/{metric['fixture_count']}",
                    str(metric["identity_recall"]),
                    str(metric["branch_recall"]),
                    str(metric["evidence_pointer_recall"]),
                    str(metric["representation_false_closure_rate"]),
                    str(metric["decision_false_closure_rate"]),
                    str(metric["unsupported_claim_rate"]),
                    str(metric["legal_resolution_accuracy"]),
                    str(metric["later_task_success"]),
                    str(metric["charged_tokens_mean"]),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Cost and failure distributions",
            "",
            (
                "| method | charged p50/p95 | wall ns p50/p95 | CPU ns p50/p95 | "
                "GPU ns | recovery/fallback/model | failures |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for method, metric in report["metrics"].items():
        failures = (
            ", ".join(
                f"{key}={value}"
                for key, value in metric["failure_distribution"].items()
            )
            or "none"
        )
        lines.append(
            f"| {method} | {metric['charged_tokens_p50']}/{metric['charged_tokens_p95']} "
            f"| {metric['wall_time_ns_p50']}/{metric['wall_time_ns_p95']} "
            f"| {metric['cpu_time_ns_p50']}/{metric['cpu_time_ns_p95']} "
            f"| {metric['gpu_time_ns_total']} "
            f"| {metric['recovery_calls']}/{metric['fallback_count']}/{metric['model_calls']} "
            f"| {failures} |"
        )
    lines.extend(
        [
            "",
            "## Hard-falsifier result",
            "",
            *[f"- `{reason}`" for reason in report["hard_falsifier"]["reasons"]],
            "",
            "The strongest typed-state and the static always-protect baseline match OSPC on every frozen ",
            "primary equivalence field. OSPC also performs deterministic validation work without a measured ",
            "task gain. This pilot therefore preserves the useful product invariant but abandons an OSPC ",
            "novelty claim. It does not establish a general scientific impossibility result.",
            "",
            "## Reproduction",
            "",
            "```bash",
            "runtime/.venv/bin/python -m research.ospc.generate_fixtures",
            "runtime/.venv/bin/python -m research.ospc.run_benchmark",
            "runtime/.venv/bin/python -m unittest discover -s research/ospc/tests -v",
            "```",
            "",
            f"Fixture SHA-256: `{report['fixture_sha256']}`  ",
            f"Scorer: `{report['scorer']}`  ",
            "All fixtures are synthetic; model calls, recovery calls and production credentials are zero.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    fixtures = load_fixtures(FIXTURES)
    detail: dict[str, list[dict[str, Any]]] = {}
    metrics: dict[str, dict[str, Any]] = {}
    for method, compressor in METHODS.items():
        rows = []
        for fixture in fixtures:
            wall_start = time.perf_counter_ns()
            cpu_start = time.process_time_ns()
            compressed = compressor(fixture)
            compressed = replace(
                compressed,
                cpu_time_ns=time.process_time_ns() - cpu_start,
                wall_time_ns=time.perf_counter_ns() - wall_start,
            )
            rows.append(score_one(fixture, compressed))
        detail[method] = rows
        metrics[method] = aggregate(rows)
    report = {
        "schema": "ospc.benchmark.result.v1",
        "fixture_sha256": sha256(FIXTURES),
        "fixture_count": len(fixtures),
        "synthetic_only": True,
        "tokenizer": "ospc.regex.v1",
        "scorer": "ospc.scorer.v1",
        "downstream_model": "frozen_rule_policy.v1",
        "fixed_prompt": "ospc.episode2-and-resolution-policy.v1",
        "initial_retrieval_access": "immutable_fixture_snapshot.v1",
        "maximum_recovery_calls": 0,
        "equal_budget": True,
        "initial_context_charged": True,
        "method_metadata_charged": True,
        "recovered_tokens_charged": True,
        "metrics": metrics,
        "hard_falsifier": hard_falsifier(metrics),
        "detail": detail,
    }
    RESULT_JSON.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    RESULT_MARKDOWN.write_text(render_markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
