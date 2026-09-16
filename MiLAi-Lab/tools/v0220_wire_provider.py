"""Opt-in dual-contract Provider. Frozen Host/Provider/World are not modified.

The transport records and settles usage before authoritative output validation.
A rejected response is a measured failure, never an automatic retry or repaired
action. The old unresolved-usage guard remains mandatory and cannot be waived here.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx

from v0220_evidence import save
from v0220_provider_hardened import Provider, ProviderStop
from v0220_wire_contract import compile_contract, fingerprint


class WireProvider:
    def __init__(
        self,
        root: Path,
        *,
        deadline: float,
        max_requests: int,
        historical_ledgers: tuple[Path, ...],
        admission: Callable[[dict, dict], None],
        transport: httpx.BaseTransport | None = None,
    ):
        self.root, self.admission = root, admission
        self.pending_wire_hash = None
        self.stopped = False
        self.provider = Provider(
            root,
            deadline=deadline,
            max_requests=max_requests,
            historical_ledgers=historical_ledgers,
            preflight=self._wire_preflight,
            transport=transport,
        )

    def _wire_preflight(self, wire: dict) -> None:
        if self.pending_wire_hash is None or fingerprint(wire) != self.pending_wire_hash:
            raise ProviderStop("WIRE_REQUEST_NOT_PREPARED_OR_DRIFTED")

    def verify(self) -> dict:
        if self.stopped:
            raise ProviderStop("WIRE_PROVIDER_STOPPED_NO_RETRY")
        return self.provider.verify()

    def generate(self, session: str, body: dict) -> str:
        if self.stopped:
            raise ProviderStop("WIRE_PROVIDER_STOPPED_NO_RETRY")
        key = "contract-" + uuid.uuid4().hex
        try:
            plan = compile_contract(body["response_format"]["json_schema"]["schema"])
            wire = plan.prepare(body)
            # Admission sees the unchanged request and prepared request, not a narrowed task.
            self.admission(copy.deepcopy(body), copy.deepcopy(wire))
            self.pending_wire_hash = fingerprint(wire)
            save(
                self.root / (key + "-binding.json"),
                {
                    **plan.manifest(),
                    "original_request": body,
                    "original_request_sha256": fingerprint(body),
                    "wire_request_sha256": self.pending_wire_hash,
                    "new_instruction_utf8_bytes": len(wire["messages"][0]["content"].encode())
                    - (
                        len(body["messages"][0]["content"].encode())
                        if body["messages"] and body["messages"][0]["role"] == "system"
                        else 0
                    ),
                },
            )
            raw = self.provider.generate(session, wire)
            # Hardened Provider has already saved the exact output/HTTP/usage. No business
            # caller sees an invalid output; Session and ActionAdapter revalidate as well.
            plan.validate_output(raw)
            save(
                self.root / (key + "-validation.json"),
                {
                    "status": "PUBLIC_CONTRACT_PASS",
                    "released_to_host": True,
                    "business_effect": False,
                    "output_sha256": fingerprint(raw),
                },
            )
            return raw
        except BaseException as exc:
            self.stopped = True
            save(
                self.root / (key + "-failure.json"),
                {
                    "status": "STOPPED_NO_RETRY",
                    "released_to_host": False,
                    "business_effect": False,
                    "exception_type": type(exc).__name__,
                    "code": str(exc) if isinstance(exc, ProviderStop) else "LOCAL_CONTRACT_FAILURE",
                    "issues": getattr(exc, "issues", []),
                    "usage": "consult unchanged transport ledger; validation failure is not free",
                },
            )
            raise
        finally:
            self.pending_wire_hash = None

    def close(self) -> None:
        self.provider.close()
