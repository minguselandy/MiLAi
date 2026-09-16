"""Prospective, single-writer Provider diagnostics; not wired into frozen V2.

No retries, schema lowering, cumulative token cap, inferred zero usage, or implicit
historical debt waiver. Full-schema preflight and lineage are mandatory inputs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx

from v02_local_provider import accounting, append_event, read_events
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import save


class ProviderStop(RuntimeError):
    """Stable public classification; provider content stays in external evidence."""


def valid_usage(usage: object) -> bool:
    return (
        isinstance(usage, dict)
        and all(
            type(usage.get(k)) is int and usage[k] >= 0
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        )
        and usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    )


def usage_state(events: list[dict]) -> dict:
    requests: dict[str, dict] = {}
    violations = []
    for event in events:
        kind, key = event["event"], event["request_id"]
        if kind == "RESERVED":
            if (
                key in requests
                or not isinstance(key, str)
                or any(
                    type(event.get(k)) is not int or event[k] < 0
                    for k in ("prompt_tokens", "output_cap", "raw_upper_bound")
                )
                or event["raw_upper_bound"] != event["prompt_tokens"] + event["output_cap"]
            ):
                raise ProviderStop("CORRUPT_USAGE_LEDGER")
            requests[key] = {"state": "RESERVED", "reservation": event, "usage": None}
            continue
        if key not in requests:
            raise ProviderStop("CORRUPT_USAGE_LEDGER")
        row = requests[key]
        expected = {
            "DISPATCH_STARTED": {"RESERVED"},
            "RESPONSE_RECEIVED": {"DISPATCH_STARTED"},
            "USAGE_UNKNOWN": {"RESERVED", "DISPATCH_STARTED", "RESPONSE_RECEIVED"},
            "USAGE_KNOWN": {"RESPONSE_RECEIVED"},
            "BOUND_VIOLATION": {"USAGE_KNOWN"},
        }
        if kind not in expected or row["state"] not in expected[kind]:
            raise ProviderStop("CORRUPT_USAGE_LEDGER")
        if kind == "BOUND_VIOLATION":
            violations.append(event)
        else:
            row["state"] = kind
        if kind == "USAGE_KNOWN":
            if not valid_usage(event["usage"]):
                raise ProviderStop("CORRUPT_USAGE_LEDGER")
            row["usage"] = event["usage"]
    known = sum(r["usage"]["total_tokens"] for r in requests.values() if r["usage"])
    pending = [{"request_id": k, **v} for k, v in requests.items() if v["usage"] is None]
    return {
        "requests": len(requests),
        "known_raw_tokens": known,
        "actual_total_raw_tokens": None if pending else known,
        "unresolved_reservations": pending,
        "reserved_raw_upper_bound": sum(r["reservation"]["raw_upper_bound"] for r in pending),
        "reservation_is_actual_usage": False,
        "violations": violations,
        "new_generation_allowed": not pending and not violations,
    }


def historical_usage(paths: tuple[Path, ...]) -> dict:
    """Read historical ledgers without adding SETTLED or editing any old artifact."""
    if not paths or len(set(p.resolve() for p in paths)) != len(paths):
        raise ProviderStop("EXPLICIT_UNIQUE_HISTORICAL_LINEAGE_REQUIRED")
    sources, pending, violations = [], [], []
    known = requests = 0
    for path in paths:
        if not path.is_file():
            raise ProviderStop("HISTORICAL_LEDGER_MISSING")
        events = read_events(path)
        reserved, seen = set(), set()
        for event in events:
            kind, key = event.get("event"), event.get("request_id")
            if kind == "RESERVED":
                if (
                    key in seen
                    or not isinstance(key, str)
                    or any(
                        type(event.get(k)) is not int or event[k] < 0
                        for k in ("prompt_tokens", "output_cap", "raw_upper_bound")
                    )
                    or event["raw_upper_bound"] != event["prompt_tokens"] + event["output_cap"]
                ):
                    raise ProviderStop("CORRUPT_HISTORICAL_LEDGER")
                reserved.add(key)
                seen.add(key)
            elif kind == "SETTLED":
                if key not in reserved or any(
                    type(event.get(k)) is not int or event[k] < 0
                    for k in ("input_tokens", "output_tokens")
                ):
                    raise ProviderStop("CORRUPT_HISTORICAL_LEDGER")
                reserved.remove(key)
            elif kind != "BOUND_VIOLATION" or key not in reserved:
                raise ProviderStop("CORRUPT_HISTORICAL_LEDGER")
        state = accounting(events)
        known += state["raw_tokens"]
        requests += state["requests"]
        pending.extend({"ledger": str(path.resolve()), **row} for row in state["pending"])
        violations.extend(state["violations"])
        sources.append(
            {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    return {
        "sources": sources,
        "requests": requests,
        "known_raw_tokens": known,
        "actual_total_raw_tokens": None if pending else known,
        "unresolved_reservations": pending,
        "reserved_raw_upper_bound": sum(r["raw_upper_bound"] for r in pending),
        "reservation_is_actual_usage": False,
        "violations": violations,
        "new_generation_allowed": not pending and not violations,
        "settlement_policy": "Only authentic per-request usage evidence; never CPU inference",
    }


class Provider:
    def __init__(
        self,
        root: Path,
        *,
        deadline: float,
        max_requests: int,
        historical_ledgers: tuple[Path, ...],
        preflight: Callable[[dict], None],
        transport: httpx.BaseTransport | None = None,
    ):
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError("POSITIVE_REQUEST_BOUND_REQUIRED")
        # Exclusive directory prevents accidental restart/second writer to a live ledger.
        root.mkdir(parents=True, exist_ok=False)
        self.root, self.deadline, self.max_requests = root, deadline, max_requests
        self.historical_ledgers, self.preflight = historical_ledgers, preflight
        self.ledger = root / "provider-ledger-v2.jsonl"
        self.client = httpx.Client(
            base_url=ENDPOINT,
            timeout=60,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )
        self.context = None

    def timeout(self, cap: float) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderStop("WALL_CLOCK_LIMIT")
        return min(remaining, cap)

    def verify(self) -> dict:
        response = self.client.get("/v1/models", timeout=self.timeout(5))
        response.raise_for_status()
        models = response.json()["data"]
        if len(models) != 1 or models[0]["id"] != MODEL or models[0]["max_model_len"] != 65536:
            raise ProviderStop("MODEL_OR_CONTEXT_CHANGED")
        self.context = 65536
        save(self.root / "model.json", models[0])
        return models[0]

    def generate(self, session: str, body: dict) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", session):
            raise ProviderStop("INVALID_SESSION_ID")
        lineage = historical_usage(self.historical_ledgers)
        state = usage_state(read_events(self.ledger))
        if not lineage["new_generation_allowed"] or not state["new_generation_allowed"]:
            raise ProviderStop("UNSETTLED_USAGE_NO_RETRY")
        if state["requests"] >= self.max_requests:
            raise ProviderStop("GENERATION_COUNT_LIMIT")
        if self.context is None:
            raise ProviderStop("MODEL_NOT_VERIFIED")
        if (
            body.get("model") != MODEL
            or body.get("max_tokens") != 4096
            or body.get("stream") is not False
        ):
            raise ProviderStop("SEALED_MODEL_PARAMETERS_CHANGED")
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
        # Preflight cannot mutate the payload; checks must cover the exact full schema.
        self.preflight(copy.deepcopy(body))
        counted = self.client.post(
            "/tokenize", json={k: body[k] for k in TOKENIZE_KEYS}, timeout=self.timeout(5)
        )
        counted.raise_for_status()
        count = counted.json()["count"]
        if type(count) is not int or count < 0 or count + 4096 > self.context:
            raise ProviderStop("INVALID_TOKEN_COUNT_OR_CONTEXT_LIMIT")
        key = f"{session}-{uuid.uuid4().hex}"
        with (self.root / f"{key}-request.json").open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        save(self.root / f"{key}-tokenize.json", {"count": count})
        save(self.root / f"{key}-lineage.json", lineage)

        def event(kind: str, **fields) -> None:
            append_event(
                self.ledger, {"event": kind, "request_id": key, "unix": time.time(), **fields}
            )

        event(
            "RESERVED",
            session=session,
            prompt_tokens=count,
            output_cap=4096,
            raw_upper_bound=count + 4096,
            cumulative_raw_cap=None,
            payload_sha256=hashlib.sha256(raw).hexdigest(),
        )
        started, known = time.monotonic(), False
        classification = "CLIENT_INTERRUPTED_OR_EVIDENCE_FAILURE"
        try:
            timeout = self.timeout(60)
            event("DISPATCH_STARTED")
            response = self.client.post(
                "/v1/chat/completions",
                content=raw,
                headers={"Content-Type": "application/json", "X-Request-Id": key},
                timeout=timeout,
            )
            save(
                self.root / f"{key}-http.json",
                {
                    "client_request_id": key,
                    "status_code": response.status_code,
                    "headers": {
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() in {"x-request-id", "request-id", "date", "content-type"}
                    },
                    "body": response.text,
                    "seconds": time.monotonic() - started,
                    "request_wire_sha256": hashlib.sha256(raw).hexdigest(),
                },
            )
            event("RESPONSE_RECEIVED", status_code=response.status_code)
            if response.status_code != 200:
                classification = f"HTTP_{response.status_code}_USAGE_UNKNOWN"
                raise ProviderStop(classification)
            classification = "MALFORMED_RESPONSE_USAGE_UNKNOWN"
            value = response.json()
            usage = value.get("usage") if isinstance(value, dict) else None
            if not valid_usage(usage):
                classification = "INVALID_OR_MISSING_USAGE"
                raise ProviderStop(classification)
            event("USAGE_KNOWN", usage=usage, seconds=time.monotonic() - started)
            known = True
            if usage["prompt_tokens"] != count or usage["completion_tokens"] > 4096:
                event("BOUND_VIOLATION", usage=usage)
                raise ProviderStop("USAGE_BOUND_MISMATCH_ACTUAL_RECORDED")
            classification = "VISIBLE_OUTPUT_INVALID_USAGE_KNOWN"
            content = value["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ProviderStop(classification)
            save(self.root / f"{key}-visible.json", {"content": content})
            return content
        except BaseException as exc:
            if isinstance(exc, httpx.TimeoutException):
                classification = "TRANSPORT_TIMEOUT_USAGE_UNKNOWN"
            elif isinstance(exc, httpx.TransportError):
                classification = "TRANSPORT_ERROR_USAGE_UNKNOWN"
            if not known:
                event(
                    "USAGE_UNKNOWN",
                    classification=classification,
                    exception_type=type(exc).__name__,
                    seconds=time.monotonic() - started,
                )
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, ProviderStop):
                raise
            raise ProviderStop(classification) from None

    def close(self) -> None:
        self.client.close()
