"""HTTP-only authorized transport; unchanged business acceptance via WireProvider.

Versioned hardened generate method changes only historical admission and central
event mirroring. Old ledgers/flags are untouched. No device/container probe.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx

from v02_local_provider import append_event, read_events
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import read, save
from v0220_provider_hardened import (
    Provider,
    ProviderStop,
    historical_usage,
    usage_state,
    valid_usage,
)
from v0220_wire_admission import WireSchemaAdmission
from v0220_wire_provider import WireProvider
from v0221_http_batch import Batch


def http_identity(client: httpx.Client, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    values = {}
    for name, route in (("models", "/v1/models"), ("version", "/version")):
        start = time.monotonic()
        response = client.get(route, timeout=5)
        save(
            directory / (name + ".json"),
            {
                "status_code": response.status_code,
                "body": response.text,
                "seconds": time.monotonic() - start,
            },
        )
        response.raise_for_status()
        values[name] = response.json()
    models = values["models"]["data"]
    if len(models) != 1 or models[0]["id"] != MODEL or models[0]["max_model_len"] != 65536:
        raise ProviderStop("HTTP_MODEL_OR_CONTEXT_DRIFT")
    return {
        "endpoint": ENDPOINT,
        "model": MODEL,
        "context": 65536,
        "version": values["version"]["version"],
    }


class HTTPAdmission:
    def __init__(self, batch: Batch, directory: Path, client: httpx.Client):
        self.batch, self.directory, self.client = batch, directory, client
        matrix = Path(batch.plan["wire_evidence"])
        historical_identity = read(matrix / "manifest.json")["contract"]["backend_identity"]
        # Historical CPU evidence only, not a fresh process/image attestation.
        self.historical = WireSchemaAdmission(
            matrix,
            hashes=batch.plan["wire_hashes"],
            identity=lambda: copy.deepcopy(historical_identity),
        )

    def __call__(self, original: dict, wire: dict) -> None:
        self.historical(original, wire)
        current = http_identity(self.client, self.directory / ("http-identity-" + uuid.uuid4().hex))
        if current != self.batch.plan["http_identity"]:
            raise ProviderStop("LIVE_HTTP_IDENTITY_DRIFT")


class BatchTransport(Provider):
    batch: Batch
    episode: str

    def verify(self) -> dict:
        self.batch.admit(self.episode)
        return super().verify()

    def generate(self, session: str, body: dict) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", session):
            raise ProviderStop("INVALID_SESSION_ID")
        self.batch.admit(self.episode)
        if session != self.episode:
            raise ProviderStop("WRONG_BATCH_EPISODE_SESSION")
        lineage = historical_usage(self.historical_ledgers)
        state = usage_state(read_events(self.ledger))
        if not state["new_generation_allowed"]:
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
            value = {"event": kind, "request_id": key, "unix": time.time(), **fields}
            self.batch.record(self.episode, value)
            append_event(self.ledger, value)

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


class AuthorizedWireProvider(WireProvider):
    def __init__(
        self,
        root: Path,
        *,
        batch: Batch,
        episode: str,
        transport: httpx.BaseTransport | None = None,
        admission=None,
        intent_actions=None,
        world=None,
    ):
        claim = batch.admit(episode)
        if root.resolve() != batch.root / "episodes" / episode / "provider":
            raise ProviderStop("PROVIDER_DIRECTORY_OUTSIDE_AUTHORIZED_EPISODE")
        self.root, self.pending_wire_hash, self.stopped = root, None, False
        self.batch = batch
        self.world, self.intent_actions = world, copy.deepcopy(intent_actions)
        self.intent_index, self.readback_seen = 0, False
        if claim["stage"] == "W3":
            spec = next(s for s in batch.plan["W3"] if s["id"] == episode)
            if (
                self.intent_actions != spec["actions"]
                or world is None
                or world.path.resolve() != batch.root / "worlds" / (episode + ".sqlite")
                or world.scope != spec["scope"]
            ):
                raise ProviderStop("FROZEN_INTENT_AND_WORLD_BINDING_REQUIRED")
        self.provider = BatchTransport(
            root,
            deadline=time.monotonic() + max(0, claim["deadline"] - time.time()),
            max_requests=claim["cap"],
            historical_ledgers=tuple(Path(s["path"]) for s in batch.auth["historical"]["sources"]),
            preflight=self._wire_preflight,
            transport=transport,
        )
        self.provider.batch, self.provider.episode = batch, episode
        self.admission = admission or HTTPAdmission(batch, root, self.provider.client)

    def generate(self, session: str, body: dict) -> str:
        check_path = self.root / ("intent-check-" + uuid.uuid4().hex + ".json")
        raw = None
        try:
            if self.intent_actions is not None:
                snapshot = self.world.snapshot()
                expected_records = {
                    a["arguments"]["object_id"]: {
                        "object_id": a["arguments"]["object_id"],
                        **a["arguments"]["data"],
                    }
                    for a in self.intent_actions[: self.intent_index]
                }
                if (
                    snapshot["records"] != expected_records
                    or snapshot["version"] != self.intent_index
                    or len(self.world.ledger()) != self.intent_index
                ):
                    raise ProviderStop("OBSERVED_EFFECT_DEVIATES_FROM_AUTHORIZED_INTENT")
            raw = super().generate(session, body)
            self.batch.admit(session)
            if self.intent_actions is not None:
                action = json.loads(raw)
                name = action["action"]
                if name == "put_record":
                    if (
                        self.intent_index >= len(self.intent_actions)
                        or action != self.intent_actions[self.intent_index]
                    ):
                        raise ProviderStop("INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH")
                    self.intent_index += 1
                    self.readback_seen = False
                elif name == "request_clarification":
                    raise ProviderStop("UNAUTHORIZED_ORACLE_BUSINESS_EFFECT")
                elif action == {"action": "read", "arguments": {"resource": "records"}}:
                    self.readback_seen = self.intent_index == len(self.intent_actions)
                elif name == "finish" and (
                    self.intent_index != len(self.intent_actions) or not self.readback_seen
                ):
                    raise ProviderStop("FINISH_BEFORE_INTENT_AND_PUBLIC_READBACK")
                save(
                    check_path,
                    {
                        "status": "INTENT_PROGRESS_PASS",
                        "released_to_executor": True,
                        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                    },
                )
            return raw
        except BaseException as exc:
            code = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
            if self.intent_actions is not None:
                save(
                    check_path,
                    {
                        "status": "NOT_RELEASED_TO_EXECUTOR",
                        "code": code,
                        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest() if raw else None,
                    },
                )
            self.batch.stop(code)
            raise
