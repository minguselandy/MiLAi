"""Offline, body-aware V0214 evidence and cost summary; never grants D6 admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from itertools import pairwise
from pathlib import Path

from jsonschema import Draft202012Validator

from v02_local_provider import accounting, read_events


def read(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def body_texts(value) -> list[str]:
    """Extract returned material, not query echoes, IDs, schemas, instructions or hit metadata."""
    if isinstance(value, list):
        return [text for item in value for text in body_texts(item)]
    if not isinstance(value, dict) or value.get("mcp_error") or value.get("payload_withheld"):
        return []
    texts = []
    for key, item in value.items():
        if key in ("query", "arguments", "source_refs", "suggested_next_step",
                   "mcp_usage_contract", "warnings", "search_scope"):
            continue
        if key in ("text", "content", "body", "excerpt", "snippet", "payload"):
            if isinstance(item, str):
                texts.append(item)
            elif key == "payload" and isinstance(item, dict):
                texts.extend(str(v) for v in item.values() if isinstance(v, (str, int, float)))
                texts.extend(body_texts(item))
            else:
                texts.extend(body_texts(item))
        elif isinstance(item, (dict, list)):
            texts.extend(body_texts(item))
    return texts


def page_texts(pages: list[dict]) -> list[str]:
    """Join only byte-contiguous ranges of the same version/source/binding."""
    groups = {}
    for page in pages:
        if not page.get("text") or page.get("coverage") in ("WITHHELD", "UNAVAILABLE", "UNKNOWN"):
            continue
        key = (page.get("source_id", page.get("path")), page.get("version",
               page.get("source_sha256")), json.dumps(page.get("binding"), sort_keys=True))
        groups.setdefault(key, []).append(page)
    texts = []
    for ranges in groups.values():
        current, end = "", None
        for page in sorted(ranges, key=lambda p: p.get("cursor", p.get("offset", 0))):
            text, start = page["text"], page.get("cursor", page.get("offset", 0))
            if start == end:
                current += text
            else:
                if current:
                    texts.append(current)
                current = text
            end = start + len(text.encode())
        if current:
            texts.append(current)
    return texts


def prompt_material(body: dict) -> dict[str, list[str]]:
    pages, product, current, tail = [], [], [], []
    for message in body.get("messages", []):
        if message.get("role") != "user" or not isinstance(message.get("content"), str):
            continue
        try:
            value = json.loads(message["content"])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        pages.extend(value.get("source_pages", []))
        if isinstance(value.get("source_view"), dict):
            tail.append(value["source_view"])
        product.extend(body_texts(value.get("current_note_results", [])))
        product.extend(body_texts(value.get("current_state", {})))
        current.append(str(value.get("question", "")))
        current.append(json.dumps(value.get("current_inputs", {}), ensure_ascii=False))
    return {"source_pages": page_texts(pages), "a0_tail": page_texts(tail),
            "product_material": product, "current_input": current}


def matches(value: str, texts: list[str], *, parameter: bool = False) -> bool:
    if not value:
        return False
    pattern = r"(?<![\w.-])" + re.escape(value) + r"(?![\w.-])"
    return any(bool(re.search(pattern, text)) if parameter else value in text for text in texts)


def support_rows(contract: dict) -> list[dict]:
    return [{"id": str(index), "text": value if isinstance(value, str) else value["text"]}
            for index, value in enumerate(contract.get("required_support", []))]


def parameter_rows(contract: dict) -> list[dict]:
    expected = contract.get("expected_intent", [])
    calls = expected.get("calls", []) if isinstance(expected, dict) else expected
    if calls is None:
        return []  # Clarification contracts deliberately have no parameter-scoring target.
    rows = []

    def descend(value, field):
        if isinstance(value, dict):
            for key, item in value.items():
                descend(item, field + "." + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                descend(item, field + f"[{index}]")
        elif value is not None:
            rows.append({"id": field, "text": value if isinstance(value, str)
                         else json.dumps(value), "value": value})
    for index, call in enumerate(calls):
        descend(call.get("arguments", {}), f"calls[{index}].arguments")
    return rows


def intent_parts(actual, contract: dict) -> dict:
    expected = contract.get("expected_intent", [])
    expected = expected.get("calls", []) if isinstance(expected, dict) else expected
    actual = actual if isinstance(actual, list) else []
    def canonical(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return {"first_call_exact_match": canonical(actual[0]) == canonical(expected[0])
            if actual and expected else None,
            "complete_plan_exact_match": canonical(actual) == canonical(expected)
            if expected else None, "call_count": len(actual),
            "duplicate_call_count": len(actual) - len({canonical(call) for call in actual}),
            "scope": "OFFLINE_EXACT_DIAGNOSTIC_DOES_NOT_REPLACE_RUNNER_OUTCOME"}


def transmission(directory: Path, event: dict) -> tuple[str, dict | None]:
    response = read(directory / f"{event['request_id']}-http.json")
    if response is None:
        return "UNKNOWN_AFTER_RESERVATION", None
    if not 200 <= response.get("status_code", 0) < 300:
        return "HTTP_REJECTED_NOT_MODEL_PRESENTED", None
    try:
        payload = json.loads(response["body"]) if isinstance(response["body"], str) \
            else response["body"]
    except (KeyError, json.JSONDecodeError):
        return "HTTP_RESPONSE_MODEL_ACCEPTANCE_UNKNOWN", None
    return ("MODEL_RESPONSE_OBSERVED" if payload.get("choices") else
            "HTTP_RESPONSE_MODEL_ACCEPTANCE_UNKNOWN"), payload


def response_diagnostic(response: dict | None, request: dict) -> dict:
    """Inspect public visible output only, supporting both old actions and new envelopes."""
    if not response or not response.get("choices"):
        return {"status": "NO_VISIBLE_MODEL_RESPONSE", "schema_errors": []}
    content = response["choices"][0].get("message", {}).get("content")
    try:
        envelope = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError:
        envelope = None
    if not isinstance(envelope, dict):
        return {"status": "VISIBLE_OUTPUT_NOT_JSON_OBJECT",
                "schema_errors": ["Visible content is not a JSON object"]}
    schema = request.get("response_format", {}).get("json_schema", {}).get("schema")
    errors = [error.message for error in Draft202012Validator(schema).iter_errors(envelope)] \
        if schema else []
    assessment = envelope.get("assessment")
    action = envelope.get("delivery", envelope)
    result = {"status": "NESTED_ASSESSMENT_DELIVERY" if assessment is not None
              else "LEGACY_ACTION", "schema_errors": errors,
              "schema_present": schema is not None}
    if not isinstance(assessment, dict) or not isinstance(action, dict):
        return result
    keys = list(envelope)
    expected = {"tools": ("NEEDS_SOURCE",), "business": ("READY",),
                "abstain": ("NEEDS_CLARIFICATION", "BLOCKED")}.get(action.get("action"), ())
    calls = action.get("calls", [])
    declared = assessment.get("requested_business_operations")
    result.update(public_assessment=assessment, delivery_action=action.get("action"),
        assessment_precedes_delivery=(keys.index("assessment") < keys.index("delivery")
                                     if "delivery" in keys else False),
        readiness_action_consistent=assessment.get("readiness") in expected,
        declared_operation_count_matches_calls=(type(declared) is int and
            isinstance(calls, list) and declared == len(calls))
            if action.get("action") == "business" else None,
        semantic_readiness_verified=False,
        count_scope="SELF_REPORTED_COUNT_NOT_INDEPENDENT_USER_REQUEST_OR_DUPLICATION_PROOF")
    return result


def overlap(rows: list[dict], start="started_monotonic", end="ended_monotonic") -> list[dict]:
    pairs = []
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            if left.get("key") == right.get("key") or left.get(start) is None \
                    or right.get(start) is None or left.get(end) is None or right.get(end) is None:
                continue
            seconds = min(left[end], right[end]) - max(left[start], right[start])
            if seconds > 0:
                pairs.append({"left": [left.get(k) for k in ("key", "arm", "phase")],
                              "right": [right.get(k) for k in ("key", "arm", "phase")],
                              "seconds": seconds})
    return pairs


def summarize_phase(root: Path, row: dict, manifest: dict) -> dict:
    key, arm, phase = row["key"], row["arm"], row["phase"]
    directory = root / "runs" / key / arm / f"phase-{phase}"
    online = root / "cases" / key / "online"
    if (online / f"phase-{phase}").exists():
        online /= f"phase-{phase}"
    evaluation = root / "cases" / key / "evaluation"
    contract_path = evaluation / f"contract-{phase}.json"
    if not contract_path.exists():
        contract_path = evaluation / "contract.json"
    contract = read(contract_path, {})
    source_paths = sorted([*online.glob("source-*.txt"), *online.glob("session_*.jsonl")])
    available = [path.read_text() for path in source_paths]
    violations = []
    for path in [contract_path, *source_paths]:
        expected = manifest.get("files", {}).get(str(path.relative_to(root)))
        if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            violations.append("SEALED_ARTIFACT_CHANGED:" + str(path.relative_to(root)))
    acquisitions = read(directory / "acquisition-calls.json", [])
    acquired_pages = page_texts([event.get("page", event) for event in acquisitions])
    public = read_events(directory / "public-calls.jsonl")
    relevant_public = [event for event in public if event.get("purpose") !=
                       "ZERO_GENERATION_CROSS_REPLAY" and event.get("tool") not in
                       ("milai_memory_save", "milai_memory_delete", "milai_working_state_update")]
    product_acquired = [text for event in relevant_public
                        for text in body_texts(event.get("result"))]
    events = read_events(directory / "provider-ledger.jsonl")
    cost = accounting(events)
    if row.get("accounting") != cost:
        violations.append("PHASE_ACCOUNTING_MISMATCH")
    settled = {e["request_id"]: e for e in events if e["event"] == "SETTLED"}
    timeline = read_events(directory / "timeline.jsonl")
    requests, presented, assembled_unknown, tails, current = [], [], [], [], []
    for event in events:
        if event["event"] != "RESERVED":
            continue
        rid = event["request_id"]
        request_path = directory / f"{rid}-request.json"
        if not request_path.exists():
            violations.append("RESERVED_PAYLOAD_MISSING:" + rid)
            continue
        if hashlib.sha256(request_path.read_bytes()).hexdigest() != event["payload_sha256"]:
            violations.append("PAYLOAD_HASH_MISMATCH:" + rid)
        request = read(request_path)
        material = prompt_material(request)
        state, response = transmission(directory, event)
        diagnostic = response_diagnostic(response, request)
        if diagnostic["schema_errors"]:
            violations.append("VISIBLE_OUTPUT_SCHEMA_MISMATCH:" + rid)
        memory_texts = material["source_pages"] + material["a0_tail"] + material["product_material"]
        tails.extend(material["a0_tail"])
        if state == "MODEL_RESPONSE_OBSERVED":
            presented.extend(memory_texts)
            current.extend(material["current_input"])
        elif state == "UNKNOWN_AFTER_RESERVATION":
            assembled_unknown.extend(memory_texts)
        if rid in settled:
            usage = response.get("usage") if response else None
            if usage != settled[rid].get("usage"):
                violations.append("HTTP_LEDGER_USAGE_MISMATCH:" + rid)
            tokenized = read(directory / f"{rid}-tokenize.json", {})
            if tokenized.get("count") != settled[rid]["input_tokens"]:
                violations.append("EXACT_TOKEN_COUNT_MISMATCH:" + rid)
        timed = next((e for e in timeline if e.get("request_id") == rid
                      and e.get("event") in ("MODEL_SETTLED", "MODEL_DISPATCHED")), {})
        requests.append({"request_id": rid, "transmission": state,
            "visible_protocol": diagnostic,
            "started_monotonic": timed.get("started_monotonic"),
            "ended_monotonic": timed.get("ended_monotonic"),
            "memory_material": memory_texts, "channels": {k: len(v) for k, v in material.items()}})
    acquired = acquired_pages + product_acquired + tails

    def coverage(specs, parameter=False):
        return [{**spec, "available_bound_source": matches(spec["text"], available,
                    parameter=parameter),
                 "available_public_material_observed": matches(spec["text"], product_acquired,
                    parameter=parameter), "acquired": matches(spec["text"], acquired,
                    parameter=parameter), "presented": matches(spec["text"], presented,
                    parameter=parameter), "assembled_unknown_transmission": matches(spec["text"],
                    assembled_unknown, parameter=parameter),
                 "current_input_presented": matches(spec["text"], current, parameter=parameter)}
                for spec in specs]
    facts = coverage(support_rows(contract))
    parameters = coverage(parameter_rows(contract), True)
    if contract.get("no_memory_needed"):
        support_contract = "NOT_APPLICABLE_NO_MEMORY_NEEDED"
    elif contract.get("expected_readiness") == "NEEDS_CLARIFICATION":
        support_contract = "CLARIFICATION_NOT_SUFFICIENT_SUPPORT_TARGET"
    elif any(not fact["available_bound_source"] and not fact[
            "available_public_material_observed"] and not fact["current_input_presented"]
            for fact in facts):
        if parameters and all(parameter["available_bound_source"] or parameter[
                "available_public_material_observed"] or parameter["current_input_presented"]
                for parameter in parameters):
            support_contract = "LITERAL_FACT_CONTRACT_GAP_SEMANTIC_SUFFICIENCY_UNKNOWN"
        else:
            support_contract = "DECLARED_FACT_NOT_OBSERVED_AVAILABLE"
    else:
        support_contract = "DECLARED_LITERAL_FACTS_AVAILABLE"
    first_times = [event["ended_monotonic"] for event in relevant_public
                   if event.get("ended_monotonic") is not None and any(matches(f["text"],
                       body_texts(event.get("result"))) for f in facts)]
    by_id = {item["page"]["request_id"]: item["page"] for item in acquisitions if "page" in item}
    for event in timeline:
        if event.get("event") == "SOURCE_ACQUIRED" and event.get("ended_monotonic") is not None:
            texts = page_texts([by_id[rid] for rid in event.get("request_ids", []) if rid in by_id])
            if any(matches(f["text"], texts) for f in facts):
                first_times.append(event["ended_monotonic"])
    first_prompt = [item["started_monotonic"] for item in requests
                    if item["transmission"] == "MODEL_RESPONSE_OBSERVED"
                    and item["started_monotonic"] is not None
                    and any(matches(f["text"], item["memory_material"]) for f in facts)]
    cross = read(directory / "query-cross-replay.json", {})
    cross_rows = [{"origin": item.get("origin"), "query": item.get("query"),
        "effective_lexical_query": item.get("lexical", {}).get("query"),
        "lexical_candidate_spans": len(item.get("lexical", {}).get("spans", [])),
        "product_returned_material_strings": len(body_texts(item.get("original_product_backend"))),
        "presented_to_model": False} for item in cross.get("rows", [])]
    for item in requests:
        del item["memory_material"]
    started = row.get("started_monotonic")
    return {"key": key, "arm": arm, "phase": phase, "status": row.get("status"),
        "outcome": row.get("outcome"), "category": contract.get("category"),
        "expected_readiness": contract.get("expected_readiness"),
        "no_memory_needed": contract.get("no_memory_needed"), "support": facts,
        "support_contract_assessment": support_contract,
        "parameter_literal_coverage": parameters,
        "intent_parts": intent_parts(row.get("intent"), contract),
        "support_semantics": ("Exact evaluator string coverage, not entailment or causal memory "
                              "benefit; parameter literals do not prove relation/applicability."),
        "acquisition": {"calls": len(acquisitions), "received_bytes": sum(
            e.get("acquired_bytes", 0) for e in acquisitions), "queue_seconds": sum(
            e.get("queue_seconds", 0) for e in acquisitions), "first_useful_seconds":
            min(first_times) - started if first_times and started is not None else None,
            "first_presented_dispatch_upper_bound_seconds": min(first_prompt) - started
            if first_prompt and started is not None else None},
        "requests": requests, "accounting": cost, "violations": violations,
        "delivery_checks": read_events(directory / "delivery-checks.jsonl"),
        "delivery_budget_reported": row.get("delivery_budget"),
        "public_calls": len(public) + int((directory / "catalog.json").exists()),
        "public_calls_in_unified_ledger": len(public),
        "catalog_calls_in_separate_receipt": int((directory / "catalog.json").exists()),
        "cross_replay_public_calls": sum(e.get("purpose") == "ZERO_GENERATION_CROSS_REPLAY"
                                         for e in public),
        "public_request_json_bytes": sum(e.get("request_json_bytes", 0) for e in public),
        "public_response_json_bytes": sum(e.get("response_json_bytes", 0) for e in public),
        "save": row.get("save", "UNKNOWN"), "memory_mutations": row.get("memory_mutations"),
        "cold": read(directory / "cold-resume.json", {}), "pid": row.get("pid"),
        "started_monotonic": started, "ended_monotonic": row.get("ended_monotonic"),
        "seconds": row.get("seconds"), "host_cpu_seconds": row.get("host_cpu_seconds"),
        "cross_replay": cross_rows,
        "external_business_actions": row.get("business_actions_executed")}


def summarize(root: Path, *, allow_confirmation_after_result=False) -> dict:
    if not (root / "result.json").exists():
        raise ValueError("TERMINAL_ROOT_RESULT_REQUIRED_BEFORE_EVALUATOR_READ")
    manifest, result = read(root / "manifest.json"), read(root / "result.json")
    config = manifest.get("config", {})
    confirmation = (config.get("confirmation_opening", False) or any(word in root.name.lower()
                    for word in ("confirmation", "holdout", "d6-")) or any(
                    not row["key"].startswith("dev-") for row in result.get("results", [])))
    if confirmation and not allow_confirmation_after_result:
        raise PermissionError("EXPLICIT_CONFIRMATION_AFTER_RESULT_FLAG_REQUIRED")
    for row in result.get("results", []):
        if any(Path(row[field]).name != row[field] or row[field] in (".", "..")
               for field in ("key", "arm")):
            raise ValueError("RESULT_PATH_OUTSIDE_RUN")
    phases = [summarize_phase(root, row, manifest) for row in result.get("results", [])]
    actual = {field: sum(row["accounting"][field] for row in phases)
              for field in ("requests", "raw_tokens")}
    violations = [item for row in phases for item in row["violations"]]
    for field in actual:
        if actual[field] != result.get(field):
            violations.append("ROOT_" + field.upper() + "_MISMATCH")
    cold_pairs, budgets = [], []
    for key, arm in sorted({(r["key"], r["arm"]) for r in phases}):
        ordered = sorted([r for r in phases if r["key"] == key and r["arm"] == arm],
                         key=lambda r: r["phase"])
        for previous, resumed in pairwise(ordered):
            cold_pairs.append({"key": key, "arm": arm, "previous_pid": previous["pid"],
                "resumed_pid": resumed["pid"], "distinct_pid": previous["pid"] != resumed["pid"],
                "same_binding": previous["cold"].get("binding") == resumed["cold"].get("binding"),
                "inherited_messages": resumed["cold"].get("inherited_messages"),
                "previous_interval_ended": previous["ended_monotonic"] <= resumed[
                    "started_monotonic"]
                if previous["ended_monotonic"] and resumed["started_monotonic"] else None})
        ledger = read_events(root / "runs" / key / arm / "budget-ledger.jsonl")
        pending = {}
        for event in ledger:
            if event["event"] == "RESERVE":
                pending[event["request_id"]] = event["upper"]
            elif event["event"] == "SETTLE":
                pending.pop(event["request_id"], None)
        budgets.append({"key": key, "arm": arm, "unknown_reservations": pending,
                        "frozen_contracts": [e["contract"] for e in ledger
                                             if e["event"] == "CONTRACT"]})
    counts = {arm: dict(Counter(row["outcome"] for row in phases if row["arm"] == arm))
              for arm in sorted({r["arm"] for r in phases})}
    model_intervals = [{**request, "key": row["key"], "arm": row["arm"], "phase": row["phase"]}
                       for row in phases for request in row["requests"]]
    parameters = {arm: {"correct": values.get("CORRECT", 0),
                       "incorrect": values.get("INCORRECT", 0),
                       "denominator": values.get("CORRECT", 0) + values.get("INCORRECT", 0),
                       "excluded_outcomes": {k: n for k, n in values.items()
                                             if k not in ("CORRECT", "INCORRECT")}}
                  for arm, values in counts.items()}
    coverage_counts = {}
    for arm in counts:
        facts = [fact for row in phases if row["arm"] == arm and not row["no_memory_needed"]
                 and row["support_contract_assessment"] in ("DECLARED_LITERAL_FACTS_AVAILABLE",
                                                           "DECLARED_FACT_NOT_OBSERVED_AVAILABLE")
                 for fact in row["support"]]
        coverage_counts[arm] = {"fact_phase_denominator": len(facts),
            "contract_gap_phases": sum(row["arm"] == arm and row["support_contract_assessment"] ==
                "LITERAL_FACT_CONTRACT_GAP_SEMANTIC_SUFFICIENCY_UNKNOWN" for row in phases),
            **{field: sum(fact[field] for fact in facts) for field in
               ("available_bound_source", "available_public_material_observed", "acquired",
                "presented", "assembled_unknown_transmission")}}
    return {"status": "SUMMARY_RECONCILED" if not violations else "SUMMARY_HAS_EVIDENCE_GAPS",
        "root": str(root), "result_sha256": hashlib.sha256((root / "result.json").read_bytes()).
        hexdigest(), "confirmation_evaluator_read_authorized": bool(confirmation),
        "phase_count": len(phases), "task_clusters": len({row["key"] for row in phases}),
        "actual": actual, "outcomes_by_arm": counts, "phases": phases, "violations": violations,
        "parameter_accuracy_denominators": parameters,
        "memory_required_fact_coverage_by_arm": coverage_counts,
        "public_calls_total": sum(row["public_calls"] for row in phases),
        "host_cpu_seconds_observed": sum(row["host_cpu_seconds"] or 0 for row in phases),
        "host_cpu_missing_phase_count": sum(row["host_cpu_seconds"] is None for row in phases),
        "save_phase_counts": dict(Counter("NO_CHANGE" if row["save"] == "NO_CHANGE"
            else "SAVE_RECEIPT" if isinstance(row["save"], dict) else "UNKNOWN" for row in phases)),
        "unknown_provider_requests": sum(len(r["accounting"]["pending"]) for r in phases),
        "budget_allocations": budgets, "cold_pairs": cold_pairs,
        "cross_task_host_overlaps": overlap(phases), "cross_task_model_dispatch_overlaps":
        overlap(model_intervals), "cleanup": result.get("cleanup"),
        "decision": "NO_D6_ADMISSION_DECISION_OFFLINE_EVIDENCE_ONLY",
        "limits": ["Outcome labels retained from runner, not silently rescored or relabeled",
            "No gold/support inference is returned to any online Host",
            "String support coverage is diagnostic, not proof of semantic grounding",
            "Parameter denominator includes only CORRECT/INCORRECT intents; "
            "clarification, format and budget stops are separate",
            "Unknown transmission is not counted as confirmed model presentation",
            "PID/interval evidence is not an independent OS exit receipt or cold model load",
            "No CPU/GPU/disk/network cost is inferred to be zero from an absent counter"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-confirmation-after-result", action="store_true")
    args = parser.parse_args()
    result = summarize(args.root.resolve(),
                       allow_confirmation_after_result=args.allow_confirmation_after_result)
    target = args.output or args.root / "summary.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    keys = ("status", "phase_count", "task_clusters", "actual", "outcomes_by_arm",
            "unknown_provider_requests", "violations")
    print(json.dumps({key: result[key] for key in keys}, ensure_ascii=False))


if __name__ == "__main__":
    main()
