"""Offline artifact controls: interrupted evidence cannot silently become success."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "v13_5_evaluate", Path(__file__).resolve().parents[2] / "tools/v13_5_evaluate.py"
)
assert SPEC is not None and SPEC.loader is not None
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))


def budget(
    requests: int, known: int, charged: int | None = None, unknown: int = 0
) -> dict[str, Any]:
    return {
        "generation_requests": requests,
        "generation": {
            "known_tokens": known,
            "charged_tokens": known if charged is None else charged,
            "unknown_usage": unknown,
        },
        "embedding": {"known_tokens": 0, "charged_tokens": 0, "unknown_usage": 0},
    }


def setup_run(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "run"
    case = {
        "case_id": "sample",
        "owner": "owner-a",
        "workflow": "reservation",
        "initial_world": {},
        "messages": [{"session_id": "s1", "message_id": "m1", "content": "Remember the source."}],
    }
    fixture = {"cases": [case]}
    config = {"profile": "functional_v1"}
    save(
        root / "input-freeze.json",
        {
            "fixture": fixture,
            "config": config,
            "fixture_sha256": EVAL.canonical_hash(fixture),
            "config_sha256": EVAL.canonical_hash(config),
        },
    )
    bank = root / "banks" / EVAL.canonical_hash(["sample", "owner-a"])[:24]
    bank.mkdir(parents=True)
    return root, bank, EVAL.canonical_hash(["s1", "m1"])


def attempt(
    bank: Path, identity: str, number: int = 0, *, status: str = "COMPLETED", owner: str = "owner-a"
) -> dict[str, Any]:
    source = {
        "event_id": "source-1",
        "owner": owner,
        "session": "s1",
        "role": "user",
        "content": "Remember the source.",
        "content_sha256": EVAL.text_hash("Remember the source."),
    }
    row = {
        "owner": "owner-a",
        "bank": "sample",
        "session": "s1",
        "message_id": "m1",
        "content": "Remember the source.",
        "workflow": "reservation",
        "attempt": number,
        "process_id": 100 + number,
        "status": status,
        "snapshot_before_close": True,
        "sources": [source],
        "records": [],
        "final_answer": "Saved.",
        "budget_before": budget(number, number * 10),
        "budget_after": budget(number + 1, (number + 1) * 10),
        "messages": [],
    }
    receipt = {
        "id": "response-" + str(number),
        "choices": [{"message": {"content": json.dumps({"answer": "Saved."})}}],
    }
    trace = {
        "event": "vllm_response",
        "http_status": 200,
        "path": "chat/completions",
        "usage": {"total_tokens": 10},
        "receipt": receipt,
        "response_text": json.dumps(receipt),
    }
    save(bank / f"{identity}-attempt-{number}.json", row)
    save(bank / f"{identity}-result.json", row)
    (bank / f"{identity}-trace-{number}.jsonl").write_text(json.dumps(trace) + "\n")
    return row


def test_mechanical_success_never_assigns_semantic_pass(tmp_path: Path) -> None:
    root, bank, identity = setup_run(tmp_path)
    attempt(bank, identity)
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = EVAL.evaluate(root, cohort="L2")
    assert result["case_packs"][0]["acceptance_evidence_complete"] is True
    assert result["case_packs"][0]["semantic_verdict"] == "UNREVIEWED"
    assert result["grading_template"]["cases"][0]["utility"] is None
    assert result["attempt_ledger_delta_sum"]["generation.known_tokens"] == 10
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("fault", ["none", "provider_text", "missing_http", "delivery_hash",
                                  "missing_delivery", "checkpoint_text", "metadata", "policy"])
def test_retained_agent_answer_requires_original_http_and_delivery(
    tmp_path: Path, fault: str,
) -> None:
    root, bank, identity = setup_run(tmp_path)
    row = attempt(bank, identity)
    metadata = dict(status="agent_response_retained", attempts=0, tools_available=False,
                    execution_candidate_delivered=True, protocol="agent_response_v1",
                    model_generation=False)
    row.update(finalization=metadata, messages=[dict(type="ai", content="Saved.")])
    freeze = json.loads((root / "input-freeze.json").read_text())
    freeze["config"]["finalization"] = "receipt_or_agent_response_v1"
    freeze["config_sha256"] = EVAL.canonical_hash(freeze["config"])
    trace = bank / f"{identity}-trace-0.jsonl"
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    delivery = dict(event="functional_agent_finalization", **metadata,
                    final_text_sha256=EVAL.text_hash("Saved."))
    events.append(delivery)
    if fault == "provider_text":
        receipt = {"choices": [{"message": {"content": "Different actual response."}}]}
        events[0].update(receipt=receipt, response_text=json.dumps(receipt))
    elif fault == "missing_http":
        events = [delivery]
    elif fault == "delivery_hash":
        delivery["final_text_sha256"] = "wrong"
    elif fault == "missing_delivery":
        events.pop()
    elif fault == "checkpoint_text":
        row["messages"][-1]["content"] = "Different checkpoint."
    elif fault == "metadata":
        row["finalization"] = {**metadata, "attempts": 1}
    elif fault == "policy":
        freeze["config"]["finalization"] = "agent_final_v1"
        freeze["config_sha256"] = EVAL.canonical_hash(freeze["config"])
    save(root / "input-freeze.json", freeze)
    save(bank / f"{identity}-attempt-0.json", row)
    save(bank / f"{identity}-result.json", row)
    trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    result = EVAL.evaluate(root, cohort="L2")
    pack = result["case_packs"][0]
    checks = pack["messages"][0]["attempts"][0]["checks"]
    linkage = next(c for c in checks if c["name"] == "final_actual_http_link")
    assert (linkage["status"] == "PASS") is (fault == "none")
    assert pack["acceptance_evidence_complete"] is (fault == "none")
    assert pack["semantic_verdict"] == "UNREVIEWED"


def test_resumed_failure_is_retained_and_latest_not_double_charged(tmp_path: Path) -> None:
    root, bank, identity = setup_run(tmp_path)
    attempt(bank, identity, 0, status="FAILED")
    attempt(bank, identity, 1)
    result = EVAL.evaluate(root, cohort="L2")
    assert result["attempt_terminal_counts"] == {"FAILED": 1, "COMPLETED": 1}
    assert result["denominators"]["retained_attempts"] == 2
    assert result["attempt_ledger_delta_sum"]["generation.known_tokens"] == 20
    assert result["case_packs"][0]["messages"][0]["attempts"][0]["execution_status"] == "FAILED"


def test_missing_terminal_with_trace_is_unknown_not_not_run_or_zero_cost(tmp_path: Path) -> None:
    root, bank, identity = setup_run(tmp_path)
    (bank / f"{identity}-trace-0.jsonl").write_text(
        json.dumps({"event": "vllm_error", "path": "chat/completions", "usage": "unknown"})
        + "\n{interrupted"
    )
    result = EVAL.evaluate(root, cohort="L2")
    assert result["message_execution_counts"] == {"UNKNOWN": 1}
    assert result["attempt_ledger_delta_sum"]["generation.charged_tokens"] is None
    orphan = result["case_packs"][0]["messages"][0]["orphan_traces"][0]
    assert orphan["broken_lines"] == [2]
    assert orphan["usage"]["generation"]["unknown_usage_events"] == 1


def test_cross_owner_source_is_a_proven_mechanical_failure(tmp_path: Path) -> None:
    root, bank, identity = setup_run(tmp_path)
    attempt(bank, identity, owner="other-owner")
    result = EVAL.evaluate(root, cohort="L2")
    pack = result["case_packs"][0]
    assert pack["earliest_mechanically_proven_breakpoint"]["name"] == "source_owner_binding"
    assert pack["acceptance_evidence_complete"] is False
    assert pack["semantic_verdict"] == "UNREVIEWED"


def test_patched_latest_and_forged_http_receipt_are_detected(tmp_path: Path) -> None:
    root, bank, identity = setup_run(tmp_path)
    row = attempt(bank, identity)
    save(bank / f"{identity}-result.json", row | {"final_answer": "patched"})
    trace_path = bank / f"{identity}-trace-0.jsonl"
    trace = json.loads(trace_path.read_text())
    trace["receipt"]["id"] = "forged"
    trace_path.write_text(json.dumps(trace) + "\n")
    result = EVAL.evaluate(root, cohort="L2")
    pack = result["case_packs"][0]
    assert any(c["status"] == "FAIL" for c in pack["mechanical_checks"])
    assert pack["messages"][0]["attempts"][0]["actual_http_linkage"]["status"] == "FAIL"


def test_original_e0_contract_change_cannot_keep_old_gate(tmp_path: Path) -> None:
    root, _, _ = setup_run(tmp_path)
    original = tmp_path / "original.json"
    save(original, {"cases": []})
    result = EVAL.evaluate(root, cohort="L1", original_fixture=original)
    assert result["input_checks"][-1]["status"] == "FAIL"
    assert result["L1_gate"]["status"] == "NOT_EVALUATED"


def test_manual_normal22_does_not_waive_critical_blocker() -> None:
    packs = [
        {
            "case_id": str(i),
            "execution_status": "COMPLETED",
            "mechanical_failure_count": 0,
            "acceptance_evidence_complete": True,
        }
        for i in range(24)
    ]
    rows = [
        EVAL.review_slot(p["case_id"])
        | {
            "semantic_verdict": "PASS",
            "reviewer": "same-family development reviewer",
            "evidence_refs": ["actual-artifact#/observation"],
            "critical_blockers": dict.fromkeys(EVAL.CRITICAL_BLOCKERS, False),
        }
        for p in packs
    ]
    rows[0]["critical_blockers"]["false_save_claim"] = True
    gate = EVAL.l1_gate(packs, [], {"cases": rows})
    assert gate["manual_pass_count"] == 24
    assert gate["status"] == "NOT_PASSED"
    rows[0]["critical_blockers"]["false_save_claim"] = None
    assert EVAL.l1_gate(packs, [], {"cases": rows})["status"] == "NOT_EVALUATED"


def test_unknown_usage_and_quotes_are_not_zero_or_semantic_truth() -> None:
    usage = EVAL.trace_usage([{"event": "vllm_error", "path": "chat/completions"}])
    assert usage["generation"]["unknown_usage_events"] == 1
    source = {"event_id": "s", "content": "a\r\nΩ"}
    checked = EVAL.quote_checks(
        {"source_ref": "s", "quote": "\r\n", "start": 1, "end": 3}, [source]
    )
    assert checked["status"] == "PASS" and checked["semantic_support"] == "UNREVIEWED"
    assert (
        EVAL.quote_checks({"source_ref": "s", "quote": "\n", "start": 1, "end": 3}, [source])[
            "status"
        ]
        == "FAIL"
    )
    assert EVAL.quote_checks({}, [source])["status"] == "UNKNOWN"


def test_output_is_new_directory_only(tmp_path: Path) -> None:
    root, _, _ = setup_run(tmp_path)
    result = EVAL.evaluate(root, cohort="L2")
    output = tmp_path / "review"
    EVAL.write_report(output, result)
    with pytest.raises(FileExistsError):
        EVAL.write_report(output, result)
    assert (output / "case-packs.jsonl").is_file()


def test_unreached_injection_stays_unverified_even_with_completed_answer(tmp_path: Path) -> None:
    root, bank, identity = setup_run(tmp_path)
    attempt(bank, identity)
    freeze = json.loads((root / "input-freeze.json").read_text())
    controls = {
        "cases": [
            {
                "case_id": "sample",
                "one_shot_fault": {
                    "message_index": 0,
                    "boundary": "after_native_before_journal_complete",
                    "target_operation": "reserve_and_label",
                },
            }
        ]
    }
    freeze.update(
        evaluator_controls=controls, evaluator_controls_sha256=EVAL.canonical_hash(controls)
    )
    save(root / "input-freeze.json", freeze)
    result = EVAL.evaluate(root, cohort="L2")
    pack = result["case_packs"][0]
    assert pack["declared_fault_execution"]["observed_applied"] is False
    condition = next(c for c in pack["mechanical_checks"] if c["name"] == "declared_fault_applied")
    assert condition["status"] == "UNKNOWN"
    assert condition["detail"]["condition_status"] == "NOT_RUN_CONDITION_NOT_REACHED"


def test_prepared_material_needs_actual_provider_input_and_is_deduplicated(tmp_path: Path) -> None:
    root, bank, identity = setup_run(tmp_path)
    attempt(bank, identity)
    trace_path = bank / f"{identity}-trace-0.jsonl"
    response = json.loads(trace_path.read_text())
    material = {"content": "source body", "omitted": []}
    prepared = {"event": "functional_material_delivery", "material": material}
    trace_path.write_text("\n".join(json.dumps(x) for x in [prepared, prepared, response]) + "\n")
    result = EVAL.evaluate(root, cohort="L2")
    deliveries = result["case_packs"][0]["messages"][0]["attempts"][0]["material_deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["delivery_verification"] == "PREPARED_ONLY_UNVERIFIED_HTTP_INPUT"
    response["request"] = {"messages": [{"role": "system", "content": json.dumps(material)}]}
    trace_path.write_text("\n".join(json.dumps(x) for x in [prepared, response]) + "\n")
    result = EVAL.evaluate(root, cohort="L2")
    delivered = result["case_packs"][0]["messages"][0]["attempts"][0]["material_deliveries"][0]
    assert delivered["delivery_verification"] == "EXACT_RECORDED_HTTP_INPUT"


def test_started_input_without_receipt_is_unknown_cost(tmp_path: Path) -> None:
    root, bank, identity = setup_run(tmp_path)
    save(
        bank / f"{identity}-input.json",
        {
            "owner": "owner-a",
            "session": "s1",
            "message_id": "m1",
            "content": "Remember the source.",
            "workflow": "reservation",
        },
    )
    result = EVAL.evaluate(root, cohort="L2")
    assert result["message_execution_counts"] == {"UNKNOWN": 1}
    assert result["attempt_ledger_delta_sum"]["generation.known_tokens"] is None


def test_normal22_preserves_unknown_nonpasses_without_inventing_normal24_threshold() -> None:
    packs = [
        {
            "case_id": str(i),
            "execution_status": "COMPLETED",
            "mechanical_failure_count": 0,
            "acceptance_evidence_complete": True,
        }
        for i in range(24)
    ]
    rows = [
        EVAL.review_slot(p["case_id"])
        | {
            "semantic_verdict": "PASS" if i < 22 else "UNKNOWN",
            "reviewer": "Root",
            "evidence_refs": ["actual-artifact#/observation"],
            "critical_blockers": dict.fromkeys(EVAL.CRITICAL_BLOCKERS, False),
        }
        for i, p in enumerate(packs)
    ]
    gate = EVAL.l1_gate(packs, [], {"cases": rows})
    assert gate["status"] == "PASSED_SCOPED"
    assert gate["manual_pass_count"] == 22
    assert gate["semantic_unknown_cases"] == ["22", "23"]
    assert gate["denominator"] == 24


@pytest.mark.parametrize('fault', ['none', 'text', 'role', 'session', 'source_id', 'hash',
                                  'render_hash', 'missing_render', 'missing_source', 'policy'])
@pytest.mark.parametrize('hidden', [False, True])
@pytest.mark.parametrize('policy', ['receipt_business_response_v2', 'receipt_or_agent_response_v1'])
def test_program_final_requires_actual_bound_public_capture(
    fault: str, hidden: bool, policy: str,
) -> None:
    import hashlib
    metadata = {'status': 'response_rendered', 'attempts': 0, 'tools_available': False,
                'execution_candidate_delivered': False, 'protocol': 'receipt_business_response_v1',
                'model_generation': False}
    identity = [['functional', 'run', 'bank', 'alice'], 's', 'm:final', 'assistant']
    ref = 'src-' + hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    text = 'Only listed receipt effects are confirmed.'
    source = dict(event_id=ref, owner='alice', session='s', role='assistant',
                  origin='public_assistant_message', content=text,
                  content_sha256=EVAL.text_hash(text))
    row = dict(bank='bank', owner='alice', session='s', message_id='m', final_answer=text,
               finalization=metadata, sources=[source], messages=[dict(type='ai', content=text)])
    event = dict(event='functional_receipt_finalization', **metadata,
                 final_text_sha256=EVAL.text_hash(text))
    freeze = dict(run_id='run', config=dict(finalization=policy))
    events = [event]
    if fault in {'text', 'role', 'session', 'source_id', 'hash'}:
        key = dict(text='content', role='role', session='session', source_id='event_id',
                   hash='content_sha256')[fault]
        source[key] = 'wrong'
    elif fault == 'render_hash':
        event['final_text_sha256'] = 'wrong'
    elif fault == 'missing_render':
        events = []
    elif fault == 'missing_source':
        row['sources'] = []
    elif fault == 'policy':
        freeze['config']['finalization'] = 'agent_final_v1'
    hidden_source = None
    if hidden:
        hidden_source = source if fault != 'missing_source' else None
        row['sources'] = []
        row['final_capture'] = dict(ok=True, source_ref=ref, visibility='revoked')
    result = EVAL.program_final_linkage(row, events, freeze, hidden_source)
    expected = 'PASS' if fault == 'none' else 'UNKNOWN' if fault == 'policy' else 'FAIL'
    assert result['status'] == expected
    assert 'semantic_verdict' not in result


@pytest.mark.parametrize('fault', ['none', 'missing_event', 'missing_receipt', 'receipt_hash',
                                  'event_changed', 'visible_capture', 'uncheckpointed_wal'])
def test_hidden_program_capture_requires_actual_event_and_durable_confirmation(
    tmp_path: Path, fault: str,
) -> None:
    import sqlite3
    ref = 'src-actual'
    event = {'event_id': ref, 'owner': 'alice', 'session': 's', 'role': 'assistant',
             'origin': 'public_assistant_message', 'content': 'Selected visibility revoked.',
             'content_sha256': EVAL.text_hash('Selected visibility revoked.')}
    digest = EVAL.text_hash(json.dumps(event, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')))
    capture = {'source_ref': ref, 'event_sha256': digest}
    row = {'final_capture': {'ok': True, 'source_ref': ref, 'visibility': 'revoked'}}
    if fault == 'receipt_hash':
        capture['event_sha256'] = 'wrong'
    if fault == 'event_changed':
        event['content'] = 'Different output.'
    if fault == 'visible_capture':
        row['final_capture'].pop('visibility')
    database = tmp_path / 'memory.sqlite'
    with sqlite3.connect(database) as store:
        store.execute('create table store (key text, value text)')
        if fault != 'missing_event':
            store.execute('insert into store values (?, ?)', (ref, json.dumps(event)))
        if fault != 'missing_receipt':
            store.execute('insert into store values (?, ?)',
                          ('capture:' + ref, json.dumps(capture)))
    if fault == 'uncheckpointed_wal':
        (tmp_path / 'memory.sqlite-wal').write_bytes(b'not an immutable snapshot')
    original = database.read_bytes()
    reader = EVAL.ArtifactReader()
    actual = EVAL.hidden_program_capture(reader, tmp_path, row)
    assert (actual == event) if fault == 'none' else actual is None
    assert database.read_bytes() == original
    assert not (tmp_path / 'memory.sqlite-shm').exists()
