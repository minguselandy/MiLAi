"""Four preregistered B2 first answers using matched controlled records, no new G."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import httpx

from check_v0210_control import ENDPOINT, LAB, load_case, tokenize, write
from milai_lab.methods.state_control import (
    Case,
    ControlStop,
    canonical,
    digest,
    prepare_request,
    presentation_audit,
)
from run_v0210_control import request_window
from v02_deadline import Deadline, DeadlineExpired
from v02_local_provider import accounting, append_event, read_events


def run(root: Path, *, authorization: str,
        transport: httpx.BaseTransport | None = None) -> dict:
    if not authorization.strip():
        raise ControlStop("EXPLICIT_B2_ALLOCATION_REQUIRED")
    config_path = LAB / "configs/v0210-negative-controls.json"
    config = json.loads(config_path.read_text())
    source_config = json.loads((LAB / config["source_config"]).read_text())
    sources = load_case(source_config)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    (root / "evaluation").mkdir()
    (root / "evaluation/rubric.json").write_bytes(
        (LAB / "data/manifests/v0210-negative-controls-rubric.json").read_bytes()
    )
    write(root / "config.json", config)
    paths = [config_path, Path(__file__).resolve(), LAB / "tools/run_v0210_control.py",
             LAB / "tools/check_v0210_control.py", LAB / "tools/v02_local_provider.py",
             LAB / "tools/v02_deadline.py", LAB / "src/milai_lab/methods/state_control.py",
             LAB / "data/manifests/v0210-negative-controls-rubric.json"]
    write(root / "implementation-pin.json", {
        str(path.relative_to(LAB)): digest(path.read_bytes()) for path in paths
    })
    started = time.monotonic()
    ledger = root / "provider-ledger.jsonl"
    events: list[dict] = []
    report = {"status": "STARTED", "authorization": authorization,
              "arm_kind": "RESEARCH_PROTOTYPE", "new_G": False, "oracle": "NOT_RUN",
              "allocations": dict.fromkeys(config["order"], "NOT_RUN"),
              "presentation": {}, "tools_called": 0, "paid_generations": 0}
    try:
        requests = {}
        for item in config["cases"]:
            case = Case(item["scope"], item["task"], tuple(item["history"]),
                        tuple(item["observations"]),
                        tuple(replace(m, scope=item["scope"]) for m in sources.materials))
            pair = []
            for arm in config["arms"]:
                control = item["ordinary_note"] if arm == "C0" else canonical(item["old_record"])
                prepared = prepare_request(case, arm, "deliver", scope=case.scope,
                                           eligible=lambda _: True, control=control,
                                           seed=config["seed"])
                key = f"{item['id']}.{arm}"
                requests[key] = prepared
                pair.append(prepared)
                (root / f"{key}-request.json").write_bytes(prepared.body)
            report["presentation"][item["id"]] = presentation_audit(case, tuple(pair))
        if (list(requests) != config["order"] or len(requests) != 4
                or config["batch_request_limit"] != 4
                or config["batch_raw_token_limit"] != 32000
                or config["batch_timeout_seconds"] != 300
                or config["request_timeout_seconds"] != 60):
            raise ControlStop("B2_PROTOCOL_MISMATCH")
        with Deadline(started, 300) as deadline, httpx.Client(
            base_url=ENDPOINT, trust_env=False, follow_redirects=False, timeout=60,
            transport=transport,
        ) as client:
            # Freeze all four complete actual inputs before any generation.
            preflight = tokenize(requests, events=events, transport=transport)
            report["preflight"] = preflight
            counts = preflight["prompt_tokens"]
            total_reservation = sum(counts.values()) + 4 * 1024
            if total_reservation > 32000:
                raise ControlStop("COMPLETE_BATCH_OVER_LIMIT")
            report["complete_batch_upper_bound"] = total_reservation
            for key, prepared in requests.items():
                if load_case(source_config) != sources:
                    raise ControlStop("SOURCE_CHANGED_BEFORE_DISPATCH")
                deadline.check("before_reservation")
                append_event(ledger, {"event": "RESERVED", "request_id": key, "session": key,
                                     "prompt_tokens": counts[key], "output_cap": 1024,
                                     "raw_upper_bound": counts[key] + 1024,
                                     "payload_sha256": digest(prepared.body), "time": time.time()})
                report["allocations"][key] = "RESERVED"
                begun = time.monotonic()
                with request_window(deadline):
                    response = client.post("/v1/chat/completions", content=prepared.body,
                                           headers={"Content-Type": "application/json"},
                                           timeout=min(60, deadline.check("generation")))
                write(root / f"{key}-http.json", {"status_code": response.status_code,
                                                 "body": response.text})
                response.raise_for_status()
                value = response.json()
                usage = value.get("usage", {})
                prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
                if (type(prompt) is not int or type(output) is not int or min(prompt, output) < 0
                        or usage.get("total_tokens") != prompt + output):
                    raise ControlStop("USAGE_UNKNOWN_RESERVATION_RETAINED")
                if prompt != counts[key] or output > 1024:
                    append_event(ledger, {"event": "BOUND_VIOLATION", "request_id": key,
                                         "usage": usage})
                    raise ControlStop("USAGE_BOUND_MISMATCH")
                append_event(ledger, {"event": "SETTLED", "request_id": key,
                                     "input_tokens": prompt, "output_tokens": output,
                                     "usage": usage, "seconds": time.monotonic() - begun})
                report["allocations"][key] = "USAGE_SETTLED"
                deadline.check("response_settled")
                choice = value["choices"][0]
                content = choice["message"].get("content")
                if not isinstance(content, str):
                    raise ControlStop("MISSING_VISIBLE_OUTPUT")
                (root / f"{key}-visible.txt").write_text(content, encoding="utf-8")
                report["allocations"][key] = choice["finish_reason"]
            report["status"] = "B2_GENERATIONS_COMPLETE_REVIEW_PENDING"
    except (Exception, DeadlineExpired) as exc:
        report.update(status="STOPPED_BUDGET_OR_PROTOCOL_LIMIT", reason=str(exc))
        raise
    finally:
        report["accounting"] = accounting(read_events(ledger))
        report["http_preflight_events"] = events
        report["batch_seconds"] = time.monotonic() - started
        report["cost_unknown"] = ["gpu", "electricity", "review"]
        write(root / "result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--authorization", required=True)
    args = parser.parse_args()
    result = run(args.root.resolve(), authorization=args.authorization)
    print(json.dumps({"status": result["status"], "accounting": result["accounting"]}))
