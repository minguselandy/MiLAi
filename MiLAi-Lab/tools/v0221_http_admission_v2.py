"""Match historical CPU coverage modulo top-level anyOf branch permutation only.

World storage orders object maps; this changes ActionContract's top-level branch
order, not its branch contents. The actual canonical/wire request is NEVER reordered.
No nested array/operator/value transformation is admitted here.
"""

from __future__ import annotations

import copy
import uuid
from collections import Counter

from v0220_evidence import read, save
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import compile_contract, encoded, fingerprint
from v0221_http_provider import AuthorizedWireProvider, HTTPAdmission, http_identity


def same_branches(actual: dict, reference: dict) -> bool:
    if actual == reference:
        return True
    if (
        set(actual) != set(reference)
        or "anyOf" not in actual
        or not isinstance(actual["anyOf"], list)
        or not isinstance(reference["anyOf"], list)
    ):
        return False
    return {k: v for k, v in actual.items() if k != "anyOf"} == {
        k: v for k, v in reference.items() if k != "anyOf"
    } and Counter(encoded(b) for b in actual["anyOf"]) == Counter(
        encoded(b) for b in reference["anyOf"]
    )


class HTTPAdmissionV2(HTTPAdmission):
    def validate_historical_pair(self, original: dict, wire: dict) -> None:
        plan = compile_contract(original["response_format"]["json_schema"]["schema"])
        if wire != plan.prepare(original):
            raise ProviderStop("ACTUAL_WIRE_REQUEST_CHANGED")
        for row in read(self.historical.root / "inventory.json"):
            candidate = read(self.historical.root / "requests" / (row["id"] + "-canonical.json"))
            schema = candidate["response_format"]["json_schema"]["schema"]
            if not same_branches(plan.canonical, schema):
                continue
            normalized = copy.deepcopy(original)
            normalized["response_format"]["json_schema"]["schema"] = schema
            self.historical(normalized, compile_contract(schema).prepare(normalized))
            save(
                self.directory / ("branch-permutation-" + uuid.uuid4().hex + ".json"),
                {
                    "status": "EXACT_BRANCH_MULTISET_MATCH",
                    "reference_id": row["id"],
                    "actual_canonical_sha256": fingerprint(plan.canonical),
                    "historical_canonical_sha256": fingerprint(schema),
                    "actual_wire_request_sha256": fingerprint(wire),
                    "actual_request_mutated": False,
                    "proof_scope": (
                        "Top-level anyOf permutation only; branch multiplicities and all "
                        "nested schemas/values unchanged. Historical CPU coverage, "
                        "not fresh backend attestation."
                    ),
                },
            )
            return
        raise ProviderStop("UNVALIDATED_BRANCH_SET_OR_SCHEMA_CONTENT")

    def __call__(self, original: dict, wire: dict) -> None:
        self.validate_historical_pair(original, wire)
        current = http_identity(self.client, self.directory / ("http-identity-" + uuid.uuid4().hex))
        if current != self.batch.plan["http_identity"]:
            raise ProviderStop("LIVE_HTTP_IDENTITY_DRIFT")


class AuthorizedWireProviderV2(AuthorizedWireProvider):
    def __init__(
        self,
        root,
        *,
        batch,
        episode,
        transport=None,
        admission=None,
        intent_actions=None,
        world=None,
    ):
        super().__init__(
            root,
            batch=batch,
            episode=episode,
            transport=transport,
            admission=admission,
            intent_actions=intent_actions,
            world=world,
        )
        if admission is None:
            self.admission = HTTPAdmissionV2(batch, root, self.provider.client)
