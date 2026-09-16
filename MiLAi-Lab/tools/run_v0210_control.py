"""One explicitly authorized B1, six local generations, no tools or retries.

E0 freezes the case/templates/rubric. Three independent preparation outputs are
carried verbatim to three first deliveries after all actual delivery inputs fit.
An existing batch directory is never reset or resumed after an unknown outcome.
"""

from __future__ import annotations

import argparse
import json
import signal
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from check_v0210_control import (
    ENDPOINT,
    LAB,
    TOKENIZE_KEYS,
    load_case,
    validate_config,
    write,
)
from milai_lab.methods.state_control import (
    ARMS,
    MODEL,
    ControlStop,
    PreparedRequest,
    check_envelope,
    digest,
    prepare_request,
    presentation_audit,
)
from v02_deadline import Deadline, DeadlineExpired
from v02_local_provider import accounting, append_event, read_events


@contextmanager
def request_window(deadline: Deadline) -> Iterator[None]:
    """HTTPX bounds individual I/O waits; the existing alarm bounds total request time."""
    signal.setitimer(signal.ITIMER_REAL, min(60, deadline.check("generation_request_60s")))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, deadline.end - deadline.clock()))


def run(e0_root: Path, *, authorization: str,
        transport: httpx.BaseTransport | None = None) -> dict:
    if not authorization.strip():
        raise ControlStop("EXPLICIT_B1_AUTHORIZATION_REQUIRED")
    frozen = json.loads((e0_root / "result.json").read_text())
    if frozen["status"] != "READY_FOR_LOCAL_PILOT":
        raise ControlStop("E0_NOT_READY")
    for path, sha in frozen["implementation_pin"].items():
        if digest((LAB / path).read_bytes()) != sha:
            raise ControlStop("IMPLEMENTATION_CHANGED_SINCE_E0")
    config = json.loads((e0_root / "config.json").read_text())
    validate_config(config)
    if digest((e0_root / "config.json").read_bytes()) != frozen["frozen_config_sha256"]:
        raise ControlStop("FROZEN_CONFIG_CHANGED")
    case = load_case(config)
    if digest(case.common_text().encode()) != frozen["presentation"]["common_sha256"]:
        raise ControlStop("FROZEN_CASE_CHANGED")
    root = e0_root / "b1"
    root.mkdir(mode=0o700, exist_ok=False)
    ledger = root / "provider-ledger.jsonl"
    started = time.monotonic()
    records = {arm: {"prepare": "NOT_RUN", "deliver": "NOT_RUN"} for arm in ARMS}
    report = {"status": "STARTED", "arm_kind": "RESEARCH_PROTOTYPE",
              "authorization": authorization, "allocations": records,
              "oracle": "NOT_RUN", "semantic_negative_controls": "B2_NOT_RUN",
              "semantic_review": "PENDING_SEPARATE_REVIEW", "E2": "NOT_ENTERED",
              "E3": "NOT_ENTERED", "paid_requests": 0, "tools_called": 0}
    actual_requests: list[PreparedRequest] = []
    tokenization_events: list[dict] = []
    try:
        with Deadline(started, 600) as deadline, httpx.Client(
            base_url=ENDPOINT, trust_env=False, follow_redirects=False,
            timeout=60, transport=transport,
        ) as client:
            response = client.get("/v1/models", timeout=min(5, deadline.check("identity")))
            response.raise_for_status()
            models = response.json()["data"]
            if [model["id"] for model in models] != [MODEL]:
                raise ControlStop("MODEL_IDENTITY_DRIFT")
            context = models[0]["max_model_len"]

            def count(item: PreparedRequest) -> int:
                wire = json.loads(item.body)
                begun = time.monotonic()
                response = client.post(
                    "/tokenize", json={key: wire[key] for key in TOKENIZE_KEYS},
                    timeout=min(5, deadline.check("tokenize")),
                )
                response.raise_for_status()
                value = response.json()["count"]
                check_envelope(value, model_context=context)
                tokenization_events.append({"arm": item.arm, "phase": item.phase,
                                            "prompt_tokens": value,
                                            "seconds": time.monotonic() - begun})
                return value

            def dispatch(item: PreparedRequest, prompt_tokens: int) -> str:
                # Revalidate complete local material immediately before each transmission.
                if load_case(config) != case:
                    raise ControlStop("SOURCE_CHANGED_BEFORE_DISPATCH")
                state = accounting(read_events(ledger))
                if state["pending"] or state["violations"]:
                    raise ControlStop("UNRESOLVED_OR_BOUND_VIOLATION")
                upper = check_envelope(prompt_tokens, model_context=context)
                if state["requests"] >= 6 or state["raw_tokens"] + upper > 64000:
                    raise ControlStop("BATCH_LIMIT_BEFORE_DISPATCH")
                key = f"{item.arm}.{item.phase}"
                (root / f"{key}-request.json").write_bytes(item.body)
                deadline.check("before_reservation")
                append_event(ledger, {"event": "RESERVED", "request_id": key,
                                     "session": item.arm, "prompt_tokens": prompt_tokens,
                                     "output_cap": 1024, "raw_upper_bound": upper,
                                     "payload_sha256": digest(item.body), "time": time.time()})
                records[item.arm][item.phase] = "RESERVED"
                begun = time.monotonic()
                with request_window(deadline):
                    response = client.post(
                        "/v1/chat/completions", content=item.body,
                        headers={"Content-Type": "application/json"},
                        timeout=min(60, deadline.check("generation")),
                    )
                write(root / f"{key}-http.json", {"status_code": response.status_code,
                                                 "body": response.text})
                response.raise_for_status()
                value = response.json()
                usage = value.get("usage", {})
                prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
                if (type(prompt) is not int or type(completion) is not int
                        or prompt < 0 or completion < 0
                        or usage.get("total_tokens") != prompt + completion):
                    raise ControlStop("USAGE_UNKNOWN_RESERVATION_RETAINED")
                if prompt != prompt_tokens or completion > 1024:
                    append_event(ledger, {"event": "BOUND_VIOLATION", "request_id": key,
                                         "usage": usage})
                    raise ControlStop("USAGE_BOUND_MISMATCH")
                append_event(ledger, {"event": "SETTLED", "request_id": key,
                                     "input_tokens": prompt, "output_tokens": completion,
                                     "usage": usage, "seconds": time.monotonic() - begun})
                records[item.arm][item.phase] = "USAGE_SETTLED"
                actual_requests.append(item)
                deadline.check("response_settled")
                choice = value["choices"][0]
                content = choice["message"].get("content")
                if not isinstance(content, str):
                    raise ControlStop("MISSING_VISIBLE_OUTPUT_USAGE_RETAINED")
                # Empty, unchanged, malformed or truncated artifacts remain original outcomes.
                records[item.arm][item.phase] = choice["finish_reason"]
                (root / f"{key}-visible.txt").write_text(content, encoding="utf-8")
                return content

            prepare = {
                arm: prepare_request(case, arm, "prepare", scope=case.scope,
                                     eligible=lambda _: True, seed=config["seed"])
                for arm in ARMS
            }
            counts = {arm: count(item) for arm, item in prepare.items()}
            controls = {arm: dispatch(item, counts[arm]) for arm, item in prepare.items()}
            deliver = {
                arm: prepare_request(case, arm, "deliver", scope=case.scope,
                                     eligible=lambda _: True, control=controls[arm],
                                     seed=config["seed"])
                for arm in ARMS
            }
            # Never deliver only the shorter treatment when a complete control cannot fit.
            counts = {arm: count(item) for arm, item in deliver.items()}
            presentation_audit(case, tuple(prepare.values()) + tuple(deliver.values()))
            for arm, item in deliver.items():
                dispatch(item, counts[arm])
            report["presentation"] = presentation_audit(case, tuple(actual_requests))
            report["status"] = "B1_GENERATIONS_COMPLETE_REVIEW_PENDING"
    except (Exception, DeadlineExpired) as exc:
        report.update(status="STOPPED_BUDGET_OR_PROTOCOL_LIMIT", reason=str(exc),
                      error_type=type(exc).__name__)
        raise
    finally:
        report["accounting"] = accounting(read_events(ledger))
        report["tokenization"] = tokenization_events
        report["batch_seconds"] = time.monotonic() - started
        report["cost_unknown"] = ["gpu", "electricity", "review"]
        write(root / "result.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--e0-root", type=Path, required=True)
    parser.add_argument("--authorization", required=True,
                        help="Actual user authorization for this six-call/64000-token local B1")
    args = parser.parse_args()
    report = run(args.e0_root.resolve(), authorization=args.authorization)
    print(json.dumps({"status": report["status"], "accounting": report["accounting"]}))


if __name__ == "__main__":
    main()
