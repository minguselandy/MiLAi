"""HTTP-only transport with raw-first accounting and exact 28-ledger carry.

Diagnostic content classification is performed outside this transport. Transport,
identity, accounting and evidence failures always stop the entire new batch.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import httpx

from v02_local_provider import append_event, read_events
from v0213_provider import MODEL, TOKENIZE_KEYS
from v0220_evidence import save
from v0220_provider_hardened import Provider, ProviderStop, usage_state, valid_usage
from v0220_wire_contract import encoded
from v0222_boundary_batch import historical_usage_boundary
from v0222_boundary_http import boundary_identity
from v0222_http import bounded_request, strict_http_json


class Transport(Provider):
    def __init__(self, root: Path, *, batch, episode: str, preflight, transport=None):
        claim = batch.admit(episode)
        if root.resolve() != batch.root / "episodes" / episode / "provider":
            raise ProviderStop("PROVIDER_DIRECTORY_OUTSIDE_AUTHORIZED_EPISODE")
        self.batch, self.episode = batch, episode
        super().__init__(
            root,
            deadline=time.monotonic() + max(0, claim["deadline"] - time.time()),
            max_requests=claim["cap"],
            historical_ledgers=tuple(Path(r["path"]) for r in batch.auth["historical"]["sources"]),
            preflight=preflight,
            transport=transport,
        )

    def verify(self) -> dict:
        self.context = None
        try:
            self.batch.admit(self.episode)
            directory = self.root / ("identity-" + uuid.uuid4().hex)
            current = boundary_identity(
                self.client, directory, lambda: self.batch.http_admit(self.episode)
            )
            if current != self.batch.plan["http_identity"]:
                raise ProviderStop("LIVE_HTTP_IDENTITY_DRIFT")
            self.context = current["context"]
            return current
        except BaseException as exc:
            code = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
            self.batch.stop(code)
            raise

    def generate(self, session: str, body: dict) -> str:
        try:
            return self._generate(session, body)
        except BaseException as exc:
            code = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
            self.batch.stop(code)
            raise

    def _generate(self, session: str, body: dict) -> str:
        self.batch.admit(self.episode)
        if session != self.episode:
            raise ProviderStop("WRONG_BATCH_EPISODE_SESSION")
        lineage = historical_usage_boundary(self.historical_ledgers)
        if lineage != self.batch.auth["historical"]:
            raise ProviderStop("HISTORICAL_LINEAGE_DRIFT")
        state = usage_state(read_events(self.ledger))
        if not state["new_generation_allowed"] or state["requests"] >= self.max_requests:
            raise ProviderStop("UNSETTLED_OR_EXHAUSTED_EPISODE")
        if self.context is None:
            raise ProviderStop("MODEL_NOT_VERIFIED")
        if (
            body.get("model") != MODEL
            or body.get("max_tokens") != 4096
            or body.get("stream") is not False
        ):
            raise ProviderStop("SEALED_MODEL_PARAMETERS_CHANGED")
        self.preflight(copy.deepcopy(body))
        raw = encoded(body).encode()
        key = f"{session}-{uuid.uuid4().hex}"
        count_body = {k: body[k] for k in TOKENIZE_KEYS}
        save(self.root / (key + "-tokenize-request.json"), count_body)
        start = time.monotonic()
        try:
            self.batch.http_admit(self.episode)
            counted = bounded_request(
                self.client, "POST", "/tokenize", json=count_body, timeout=self.timeout(5)
            )
        except Exception as exc:
            save(
                self.root / (key + "-tokenize-error.json"),
                {
                    "exception_type": type(exc).__name__,
                    "seconds": time.monotonic() - start,
                },
            )
            raise
        save(
            self.root / (key + "-tokenize-http.json"),
            {
                "status_code": counted.status_code,
                "body": counted.text,
                "seconds": time.monotonic() - start,
            },
        )
        counted.raise_for_status()
        if counted.status_code != 200:
            raise ProviderStop("TOKENIZE_REQUIRES_HTTP_200")
        count = strict_http_json(counted.text)["count"]
        if type(count) is not int or count < 0 or count + 4096 > self.context:
            raise ProviderStop("INVALID_TOKEN_COUNT_OR_CONTEXT_LIMIT")
        with (self.root / (key + "-request.json")).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        save(self.root / (key + "-tokenize.json"), {"count": count})
        save(self.root / (key + "-lineage.json"), lineage)

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
            event("DISPATCH_STARTED")
            self.batch.http_admit(self.episode, inflight=True)
            response = bounded_request(
                self.client,
                "POST",
                "/v1/chat/completions",
                content=raw,
                headers={"Content-Type": "application/json", "X-Request-Id": key},
                timeout=self.timeout(60),
            )
            save(
                self.root / (key + "-http.json"),
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
            value = strict_http_json(response.text)
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
            if (
                not isinstance(content, str)
                or not isinstance(value.get("id"), str)
                or not value["id"]
            ):
                raise ProviderStop(classification)
            # Escaping preserves even malformed Unicode content without replacing characters.
            with (self.root / (key + "-visible.json")).open("x", encoding="utf-8") as stream:
                json.dump({"content": content}, stream, ensure_ascii=True, allow_nan=False)
            self.batch.admit(self.episode)
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
            if isinstance(exc, (KeyboardInterrupt, SystemExit, ProviderStop)):
                raise
            raise ProviderStop(classification) from None
