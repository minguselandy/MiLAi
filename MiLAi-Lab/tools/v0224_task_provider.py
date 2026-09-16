"""D-stage public-schema provider with original HTTP accounting and no gold gate.

Canonical messages are preserved. D11 changes only its declared wire grammar.
Invalid visible actions reach the Host validator as rejections, never dispatch.
"""

import uuid

from v0220_evidence import save
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import WireContractError, fingerprint
from v0222_presentation_transport_v2 import Transport
from v0222_string_contract import compile_contract
from v0224_live_http import BoundedLiveHTTP


class TaskProvider:
    def __init__(self, root, *, batch, episode):
        self.root, self.batch, self.episode = root, batch, episode
        self.pending_wire_hash = None
        claim = batch.admit(episode)
        transport = BoundedLiveHTTP(
            identity_get=2, tokenize_post=claim["cap"], generation_post=claim["cap"]
        )
        try:
            self.provider = Transport(
                root,
                batch=batch,
                episode=episode,
                preflight=self._wire_preflight,
                transport=transport,
            )
        except BaseException as primary:
            try:
                transport.close()
            except BaseException as secondary:
                primary.add_note("SECONDARY_TRANSPORT_CLOSE_FAILURE: " + type(secondary).__name__)
            raise

    def _wire_preflight(self, body):
        if self.pending_wire_hash is None or fingerprint(body) != self.pending_wire_hash:
            raise ProviderStop("EXACT_PREPARED_PUBLIC_WIRE_REQUIRED")

    def verify(self):
        return self.provider.verify()

    def generate(self, session, body):
        if session != self.episode:
            raise ProviderStop("WRONG_TASK_SESSION")
        compiled = compile_contract(body["response_format"]["json_schema"]["schema"], "D11")
        wire = compiled.prepare(body)
        self.pending_wire_hash = fingerprint(wire)
        key = "public-contract-" + uuid.uuid4().hex
        save(
            self.root / (key + "-binding.json"),
            {
                "canonical_request": body,
                "canonical_request_sha256": fingerprint(body),
                "wire_request_sha256": self.pending_wire_hash,
                "contract": compiled.manifest(),
                "presentation": "ORIGINAL_NATURAL_MESSAGES_WITH_D11_NOTICE",
                "oracle_selection_or_business_truth_gate": False,
            },
        )
        try:
            raw = self.provider.generate(session, wire)
            valid = True
            try:
                compiled.validate_output(raw)
            except WireContractError:
                valid = False
            save(
                self.root / (key + "-output.json"),
                {
                    "raw_sha256": fingerprint(raw),
                    "public_schema_pass": valid,
                    "released_to_host_validator": True,
                    "business_dispatch_authorized": False,
                    "business_outcome": "NOT_EVALUATED",
                },
            )
            self.batch.admit(session)
            return raw
        finally:
            self.pending_wire_hash = None

    def close(self):
        self.provider.close()
