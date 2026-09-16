"""Zero-model native-function counterexamples and explicitly simulated event/reset fixtures."""

from __future__ import annotations
import __future__

import argparse
import ast
import asyncio
import builtins
import csv
import hashlib
import importlib.util
import json
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def extract(path: Path, names: list[str], globals_: dict | None = None) -> dict:
    """Only explicitly reviewed functions, no task loader or module-level side effects."""
    tree = ast.parse(path.read_text())
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    assert {node.name for node in nodes} == set(names)
    namespace = dict(globals_ or {})
    module = ast.Module(body=nodes, type_ignores=[])
    exec(  # noqa: S102 -- reviewed pinned AST functions
        compile(
            module,
            str(path),
            "exec",
            flags=__future__.annotations.compiler_flag,
        ),
        namespace,
    )
    return namespace


def reviewed_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class EventContext:
    """Deterministic substitute, NOT live Notion/email or benchmark runtime validation."""

    def __init__(self, candidate: str = "C04"):
        self.email = self.notion = self
        self.messages = []
        self.rows = [
            {
                "id": "fixture-row",
                "properties": {"Candidate ID": {"title": [{"plain_text": candidate}]}},
            }
        ]

    async def send_email(self, **kwargs):
        self.messages.append(kwargs)

    async def query_db(self, _name):
        return self.rows

    async def update_db_row(self, row_id, properties):
        assert row_id == "fixture-row"
        self.rows[0]["properties"].update(properties)


def check(root: Path, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    rows = []

    def record(candidate, fixture, actual, expected, **extra):
        rows.append(
            {
                "candidate": candidate,
                "fixture": fixture,
                "actual": actual,
                "intended_semantic": expected,
                "agrees": actual == expected,
                **extra,
            }
        )

    reward_path = root / "supersede/src/supersede/reward.py"
    reward = reviewed_module(reward_path, "v0217_native_reward")
    cases = [
        ("positive", "I now live in Boston.", True, 0),
        ("negative_stale", "I still live in Seattle.", False, 1),
        ("negated_current", "I do not live in Boston. I still live in Seattle.", False, 1),
        ("quoted_corrected_stale", "I used to live in Seattle, but now I live in Boston.", True, 0),
        ("unresolved_two_values", "I live in Boston or Seattle; I cannot tell which.", False, 0),
        ("clarification", "I cannot determine the current city from these records.", False, 0),
        ("quoted_not_asserted", "The old note says Boston, but I cannot verify it.", False, 0),
        ("empty_partial", "", False, 0),
    ]
    for name, answer, matches, stale in cases:
        record("Supersede", name + ":answer", reward.answer_matches(answer, "Boston"), matches)
        record("Supersede", name + ":stale", reward.stale_use_penalty(answer, ["Seattle"]), stale)
    rollout_path = root / "supersede/src/supersede/rollout.py"
    rollout = reviewed_module(rollout_path, "v0217_native_rollout")
    ro = rollout.MemoryRollout(["ORIGINAL_ONLY", "NEW_UPDATE"], "Current city?", budget=12)
    ro.step("abcdefghijklmno")
    record("Supersede", "hard_truncation", ro.notes, "abcdefghijkl")
    record(
        "Supersede", "prior_source_not_resupplied", "ORIGINAL_ONLY" in ro.current_prompt(), False
    )
    ro.step("Boston")
    record(
        "Supersede",
        "answer_has_notes_not_sessions",
        "Boston" in ro.current_prompt() and "NEW_UPDATE" not in ro.current_prompt(),
        True,
    )
    ro.step("Boston")
    record("Supersede", "terminal_has_no_recovery_turn", ro.done, True)

    # Reproduce the unmodified default answer function's no-key branch with a stub config.
    config = SimpleNamespace(
        is_base_model_baseline=lambda _: False,
        is_harness_baseline=lambda _: False,
        resolve_baseline_param=lambda *args: None,
        resolve_base_model_max_image_bytes=lambda: 0,
        resolve_base_model_max_images=lambda: 0,
        resolve_base_model_mode=lambda: "text",
    )

    def import_config(name, *args, **kwargs):
        if name == "eval_framework.config":
            return config
        raise RuntimeError("UNEXPECTED_IMPORT_BLOCKED:" + name)

    local_builtins = dict(vars(builtins), __import__=import_config)
    wma_path = root / "wma/eval_framework/cli.py"
    native = extract(
        wma_path,
        ["build_default_answer_fn"],
        {
            "__builtins__": local_builtins,
            "target_for_baseline": lambda _: SimpleNamespace(api_key=""),
        },
    )
    fn = native["build_default_answer_fn"]()
    response = fn(
        SimpleNamespace(gold_answer="PRIVATE_GOLD_CANARY", question="Public question"),
        SimpleNamespace(raw_trace={}),
    )
    record(
        "WMA",
        "default_no_key_gold_fallback",
        response == "PRIVATE_GOLD_CANARY",
        False,
        execution_kind="NATIVE_FUNCTION_WITH_CONFIG_STUB_NO_PROVIDER",
    )

    executive = root / "clawmark/tasks/executive_assistant/task2/task.py"
    names = [
        "_read_csv",
        "_find_csv_rows",
        "_parse_time",
        "_has_time_overlap",
        "_s0_no_conflicts",
        "_s1_c05_rescheduled",
        "_s2_c03_online",
        "_s2_c04_rescheduled",
        "_notion_text",
        "_get_notion_field",
        "_find_notion_candidate",
        "stage2",
    ]
    e = extract(
        executive, names, {"csv": csv, "StringIO": StringIO, "CANDIDATE_DB_NAME": "candidate_db"}
    )
    insurance = root / "clawmark/tasks/insurance/task3/task.py"
    names = [
        "_read_json",
        "_s3_actual_departure_from_image",
        "_s3_actual_delay_correct",
        "_s3_verified_reason_integrated",
        "_s3_delay_not_covered",
        "_s3_redline_decision_rejected",
        "_notion_text",
        "_notion_select",
        "stage2",
        "stage3",
    ]
    ins = extract(insurance, names, {"json": json, "CRM_DB": "flt_claims_crm"})
    with asyncio.Runner() as loop:
        for case, candidate, mode, expected in [
            ("current", "C03", "online", True),
            ("stale", "C03", "in-person", False),
            ("wrong_object", "C02", "online", False),
            ("negated_current", "C03", "not online", False),
        ]:
            workspace = output / ("executive-" + case)
            workspace.mkdir()
            (workspace / "final_schedule.csv").write_text(
                f"candidate_id,mode\n{candidate},{mode}\n"
            )
            record(
                "ClawMark/executive",
                case,
                loop.run(e["_s2_c03_online"](SimpleNamespace(workspace=workspace))),
                expected,
            )
        workspace = output / "executive-missing-time"
        workspace.mkdir()
        (workspace / "final_schedule.csv").write_text(
            "candidate_id,date,start_time\nC04,2026-03-26,\n"
        )
        record(
            "ClawMark/executive",
            "partial_missing_required_time",
            loop.run(e["_s2_c04_rescheduled"](SimpleNamespace(workspace=workspace))),
            False,
        )
        for case, rows_, expected in [
            ("overlap", "C03,A,D,09:00,10:00\nC04,A,D,09:30,10:30", False),
            ("non_overlap", "C03,A,D,09:00,10:00\nC04,A,D,10:00,11:00", True),
        ]:
            workspace = output / ("executive-" + case)
            workspace.mkdir()
            (workspace / "interview_schedule.csv").write_text(
                "candidate_id,interviewer,date,start_time,end_time\n" + rows_ + "\n"
            )
            record(
                "ClawMark/executive",
                case,
                loop.run(e["_s0_no_conflicts"](SimpleNamespace(workspace=workspace))),
                expected,
            )
        cases = [
            (
                "positive",
                {"actual_departure_from_image": "22:47"},
                "_s3_actual_departure_from_image",
                True,
            ),
            (
                "negative",
                {"actual_departure_from_image": "23:10"},
                "_s3_actual_departure_from_image",
                False,
            ),
            (
                "negation",
                {"actual_departure_from_image": "Not 22:47; actually 23:10"},
                "_s3_actual_departure_from_image",
                False,
            ),
            (
                "corrected_stale",
                {"actual_departure_from_image": "Old 23:10 corrected to 22:47"},
                "_s3_actual_departure_from_image",
                True,
            ),
            (
                "wrong_object",
                {"claim_id": "OTHER", "actual_departure_from_image": "22:47"},
                "_s3_actual_departure_from_image",
                False,
            ),
            ("minutes_positive", {"actual_delay_minutes": 167}, "_s3_actual_delay_correct", True),
            ("minutes_negative", {"actual_delay_minutes": 300}, "_s3_actual_delay_correct", False),
            (
                "clarification",
                {"decision_status": "pending"},
                "_s3_redline_decision_rejected",
                False,
            ),
            ("missing_amount", {"delay_reason_covered": False}, "_s3_delay_not_covered", False),
            (
                "negated_reason",
                {"verified_delay_reason": "not operational; weather"},
                "_s3_verified_reason_integrated",
                False,
            ),
        ]
        for name, data, checker, expected in cases:
            workspace = output / ("insurance-" + name)
            workspace.mkdir()
            (workspace / "claim_decision.json").write_text(json.dumps(data))
            record(
                "ClawMark/insurance",
                name,
                loop.run(ins[checker](SimpleNamespace(workspace=workspace))),
                expected,
                checker=checker,
            )
        event_receipts = []
        for name, functions in [
            ("executive", [e["stage2"]]),
            ("insurance", [ins["stage2"], ins["stage3"]]),
        ]:
            outputs = []
            for _repeat in range(2):
                ctx = EventContext()
                events = [loop.run(function(ctx)) for function in functions]
                outputs.append({"events": events, "messages": ctx.messages, "state": ctx.rows})
            record(
                "ClawMark/" + name,
                "deterministic_event_reset",
                outputs[0] == outputs[1],
                True,
                backend="SIMULATED_STUB_NOT_NATIVE_SERVICES",
            )
            event_receipts.append({"family": name, "replays": outputs})
        (output / "event-replays.json").write_text(json.dumps(event_receipts, indent=2))
    pins = {
        str(path.relative_to(root)): sha(path.read_bytes())
        for path in (reward_path, rollout_path, wma_path, executive, insurance)
    }
    report = {
        "status": "FIXTURE_EVIDENCE_RECORDED_NOT_BENCHMARK_SCORE",
        "fixtures": rows,
        "total": len(rows),
        "counterexamples": sum(not row["agrees"] for row in rows),
        "code_pins": pins,
        "model_requests": 0,
        "judge_requests": 0,
        "runtime_verified_native_benchmarks": 0,
        "kind": "Reviewed native functions; filesystem fixtures; simulated external event backends",
        "warning": "Checker-local object/partial counterexamples need full-rubric review; "
        "not all partial guard passes imply full-task false positive",
    }
    (output / "result.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.root, args.output)
    print(json.dumps({key: result[key] for key in ("status", "total", "counterexamples")}))
