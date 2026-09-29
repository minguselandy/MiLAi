"""Synthetic trace inputs and existing writer graph contract replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

SELECTED = [
    "test_host_both_uses_actual_toolnode_and_terminal_ack_only_for_seen_sources",
    "test_boundary_reads_then_writes_and_host_trigger_returns_real_receipts",
    "test_overlap_waits_for_host_answer_then_uses_actual_memory_receipt",
    "test_empty_boundary_is_no_change_not_host_answer",
    "test_native_host_policy_keeps_the_original_memory_business_catalog",
    "test_three_writer_policies_receive_same_actual_record_ids_bodies_and_sources",
    "test_host_both_actual_update_nochange_then_delete_and_owner_scope",
    "test_host_failure_keeps_partial_writes_and_unacknowledged_sources",
    "test_boundary_capacity_failure_keeps_pending_and_host_continues",
    "test_boundary_partial_write_keeps_real_commit_and_pending",
    "test_partial_automatic_receipts_reach_explicit_trigger_proposal",
]


def accounting_contract(accounting, temporary):
    output = {}
    base_events = [
        {
            "event": "vllm_response",
            "role": "state_control",
            "control_stage": "update_selector",
            "usage": {"total_tokens": 11, "prompt_tokens": 7},
            "capacity": {"prompt_tokens": 7},
        },
        {
            "event": "vllm_response",
            "role": "state_control",
            "control_stage": "maintenance",
            "usage": {"total_tokens": 17, "prompt_tokens": 10},
            "capacity": {"prompt_tokens": 10},
        },
        {
            "event": "vllm_error",
            "role": "state_control",
            "control_stage": "read_selector",
            "usage": None,
        },
        {
            "event": "vllm_response",
            "role": "task_host",
            "usage": {"total_tokens": 23, "prompt_tokens": 18},
            "capacity": {"prompt_tokens": 18},
        },
    ]
    full_events = [
        *base_events,
        {"event": "lsa_view", "extra": {"unknown": [1, "x"]}, "state_ids": ["s1"]},
        {"event": "lsa_history_view", "unknown": "preserved"},
        {"event": "lsa_history_summary_call", "query": "actual"},
        {"event": "lsa_history_summary_result", "status": "FAILED", "unknown": 7},
        {
            "event": "lsa_history_checkpoint_read",
            "calls": 2,
            "logical_bytes": 13,
            "cpu_ns": 3,
            "wall_ns": 4,
        },
        {"event": "lsa_history_checkpoint_read", "logical_bytes": 5},
        {"event": "lsa_epoch_snapshot", "reused": False, "body_bytes": 8},
        {"event": "lsa_epoch_snapshot", "reused": True, "body_bytes": 3},
        {
            "event": "lsa_epoch_checkpoint_read",
            "calls": 99,
            "logical_bytes": 21,
            "cpu_ns": 7,
            "wall_ns": 11,
        },
        {"event": "lsa_epoch_checkpoint_read"},
        {
            "event": "lsa_turn_close",
            "message_key": "thread:0",
            "user_id": "alice",
            "degraded": True,
            "reason": "actual failure",
            "receipts": [{"unknown": 1}],
            "pending_event_ids": ["e1"],
            "extra": 2,
        },
        {"event": "lsa_turn_close"},
        {"event": "lsa_store_stats", "operations": {"get": {"calls": 2, "cpu_ns": 8}}},
        {
            "event": "lsa_history_store_stats",
            "operations": {
                "get": {"calls": 1, "cpu_ns": 9},
                "search": {"calls": 3, "logical_bytes": 13},
            },
        },
        {
            "event": "vllm_response",
            "path": "embeddings",
            "role": "ignored_role",
            "usage": {"total_tokens": 5, "prompt_tokens": 2},
            "capacity": {"prompt_tokens": 3},
        },
        {
            "event": "vllm_response",
            "usage": {"total_tokens": True, "prompt_tokens": False},
            "capacity": {"prompt_tokens": True},
        },
        {
            "event": "vllm_budget_rejected",
            "role": "state_control",
            "control_stage": "maintenance",
            "usage": [4, 5],
            "capacity": "unknown",
        },
        {
            "event": "vllm_capacity_rejected",
            "role": "state_control",
            "control_stage": 19,
            "usage": {"total_tokens": -3, "prompt_tokens": -2},
            "capacity": {"prompt_tokens": -1},
        },
        {"event": "unknown", "role": "ignored", "usage": {"total_tokens": 999}},
    ]
    cases = [
        ("missing_trace_budget", None, None),
        ("empty_trace_unknown_budget", "", '{"calls":2,"unknown":{"x":[1,"q"]}}\n'),
        (
            "original_role_substage_test",
            base_events,
            '{"known_total_tokens":51,"unknown_usage":1}\n',
        ),
        (
            "all_existing_branches_and_unknown_fields",
            full_events,
            '{"arbitrary_status":"PAUSED","extra":null}\n',
        ),
        (
            "missing_event_and_usage",
            [{}, {"event": "vllm_response"}, {"event": "vllm_error", "role": None}],
            None,
        ),
        (
            "unknown_usage_types",
            [
                {"event": "vllm_response", "usage": {"total_tokens": "5", "prompt_tokens": 2.0}},
                {"event": "vllm_error", "usage": {"total_tokens": 5.0}, "capacity": {}},
            ],
            None,
        ),
        ("missing_epoch_reused", [{"event": "lsa_epoch_snapshot"}], None),
        ("missing_store_operations", [{"event": "lsa_store_stats"}], None),
        (
            "late_store_stat_field",
            [
                {"event": "lsa_store_stats", "operations": {"put": {"calls": 1}}},
                {"event": "lsa_store_stats", "operations": {"put": {"new_field": 2}}},
            ],
            None,
        ),
        (
            "non_numeric_checkpoint_value",
            [{"event": "lsa_history_checkpoint_read", "calls": None}],
            None,
        ),
        ("malformed_trace", "{broken\n", None),
        ("blank_trace_line", "\n", None),
        ("scalar_trace_event", "null\n", None),
        ("malformed_budget", "", "{broken\n"),
    ]
    for name, events, budget in cases:
        root = Path(temporary) / "accounting" / name
        root.mkdir(parents=True)
        trace = root / "trace.jsonl"
        budget_path = root / "budget.json"
        trace_bytes = (
            None
            if events is None
            else (
                events
                if isinstance(events, str)
                else "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in events)
            )
        )
        if trace_bytes is not None:
            trace.write_text(trace_bytes)
        if budget is not None:
            budget_path.write_text(budget)
        try:
            result = accounting(root, budget_path)
            outcome = {
                "returned": result,
                "returned_json_bytes": json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            }
        except Exception as error:
            outcome = {"exception": type(error).__name__, "message": str(error)}
        output[name] = {
            "trace_jsonl_bytes": trace_bytes,
            "budget_json_bytes": budget,
            "outcome": outcome,
        }
    return output


def writer_contract(lab, temporary):
    import provider_contract_probe as helper
    import pytest
    from langgraph.store.memory import InMemoryStore

    import milai_lab.methods.local_state_attention.writers as writers
    import milai_lab.runners.writer_policy as owner
    from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel

    case_sources = {}

    class WriterRecorder(helper.Recorder):
        def pytest_runtest_setup(self, item):
            super().pytest_runtest_setup(item)
            import random
            import time

            import langgraph.checkpoint.base.id as checkpoint_id

            case_path = Path(item.module.__file__).resolve()
            assert case_path == lab / "tests/unit/test_writer_policy.py"
            case_sources[item.module.__name__] = {
                "file": str(case_path),
                "sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
            }
            rng = random.Random(0)  # noqa: S311 -- fixed SDK UUID fixture, no security use
            self.stack.enter_context(patch.object(time, "time", lambda: 1790640000.0))
            self.stack.enter_context(patch.object(time, "time_ns", lambda: 1790640000000000000))
            self.stack.enter_context(patch.object(random, "getrandbits", rng.getrandbits))
            self.stack.enter_context(patch.object(checkpoint_id, "_last_v6_timestamp", None))
            original_turn = item.module.run_writer_policy_turn

            def turn(
                policy,
                messages,
                raw_history,
                runtime,
                scope,
                world,
                journal,
                bank,
                toolset,
                controller,
                **kwargs,
            ):
                self.event(
                    "writer_turn.enter",
                    policy=policy,
                    messages=messages,
                    raw_history=raw_history,
                    scope=scope,
                    tool_names=[row.name for row in toolset.host_tools()],
                    kwargs=kwargs,
                )
                try:
                    returned = original_turn(
                        policy,
                        messages,
                        raw_history,
                        runtime,
                        scope,
                        world,
                        journal,
                        bank,
                        toolset,
                        controller,
                        **kwargs,
                    )
                except Exception as error:
                    self.event(
                        "writer_turn.error",
                        exception=type(error).__name__,
                        message=str(error),
                        states=bank.states(
                            writers.StateScope(scope.run_id, scope.arm_id, scope.user_id)
                        ),
                        pending=bank.pending(
                            writers.StateScope(scope.run_id, scope.arm_id, scope.user_id)
                        ),
                    )
                    raise
                self.event("writer_turn.return", returned=returned)
                return returned

            self.stack.enter_context(patch.object(item.module, "run_writer_policy_turn", turn))
            original_control = item.module.ControlReplies.chat

            def control(instance, messages, **kwargs):
                self.event("control.chat.enter", messages=messages, kwargs=kwargs)
                result = original_control(instance, messages, **kwargs)
                self.event("control.chat.return", returned=result)
                return result

            self.stack.enter_context(patch.object(item.module.ControlReplies, "chat", control))
            original_boundary = writers.run_writer_boundary

            def boundary(controller, toolset, context, allowed, **kwargs):
                self.event(
                    "writer_boundary.enter",
                    context=context,
                    allowed=[row.name for row in allowed],
                    kwargs=kwargs,
                )
                try:
                    result = original_boundary(controller, toolset, context, allowed, **kwargs)
                except Exception as error:
                    self.event(
                        "writer_boundary.error", exception=type(error).__name__, message=str(error)
                    )
                    raise
                self.event("writer_boundary.return", returned=result)
                return result

            self.stack.enter_context(patch.object(owner, "run_writer_boundary", boundary))
            self.stack.enter_context(patch.object(writers, "run_writer_boundary", boundary))
            for name in ("put", "delete"):
                original = getattr(InMemoryStore, name)

                def mutation(instance, *args, _original=original, _name=name, **kwargs):
                    self.event("store." + _name, args=args, kwargs=kwargs)
                    return _original(instance, *args, **kwargs)

                self.stack.enter_context(patch.object(InMemoryStore, name, mutation))
            original_case = item.module._turn

            def finished(*args, **kwargs):
                result = original_case(*args, **kwargs)
                self.event(
                    "writer_fixture.return",
                    returned=result[0],
                    control_payloads=result[1].payloads,
                    host_requests=result[2],
                )
                return result

            self.stack.enter_context(patch.object(item.module, "_turn", finished))

    recorder = WriterRecorder(LangMemRecipeChatModel, lab / "src", temporary)
    args = ["-q", "--disable-warnings", "--basetemp=" + temporary + "/pytest"]
    args.extend(str(lab / "tests/unit/test_writer_policy.py") + "::" + name for name in SELECTED)
    code = pytest.main(args, plugins=[recorder])
    return code, recorder.cases, case_sources
