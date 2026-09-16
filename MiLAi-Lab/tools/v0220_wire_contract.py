"""Explicit generator grammar plus unchanged authoritative validation, revision 1.

Only uniqueItems is deferred to pre-dispatch validation. This is NOT an equivalent
decoder grammar: it admits a superset. The acceptance contract remains the original
schema. No value repair, target filtering, remote references or negative rewrites.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator, FormatChecker

from v0220_action_contract import ContractError, unique_object
from v0220_provider_hardened import ProviderStop

REVISION = "UNIQUE_ITEMS_RUNTIME_V1"
MAPS = {"properties", "patternProperties"}
LISTS = {"anyOf", "allOf", "prefixItems"}
SINGLES = {"items", "additionalProperties", "propertyNames"}
LITERALS = {
    "$schema",
    "title",
    "description",
    "$comment",
    "default",
    "examples",
    "readOnly",
    "writeOnly",
    "deprecated",
    "type",
    "const",
    "enum",
    "required",
    "minProperties",
    "maxProperties",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minItems",
    "maxItems",
}


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def fingerprint(value: object) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def pointer(parts: list) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


class WireContractError(ProviderStop):
    def __init__(self, code: str, *, issues: list[dict] | None = None):
        super().__init__(code)
        self.issues = issues or []


@dataclass(frozen=True)
class WireContract:
    # Immutable serializations prevent a caller mutating the public schema after admission.
    canonical_json: str
    wire_json: str
    deferred_json: str

    @property
    def canonical(self) -> dict:
        return json.loads(self.canonical_json)

    @property
    def wire(self) -> dict:
        return json.loads(self.wire_json)

    def manifest(self) -> dict:
        return {
            "revision": REVISION,
            "canonical_sha256": fingerprint(self.canonical),
            "wire_sha256": fingerprint(self.wire),
            "deferred_checks": json.loads(self.deferred_json),
            "decoder_is_superset_not_equivalent": True,
            "full_validation_required_before_dispatch": True,
            "automatic_value_repair": False,
        }

    def prepare(self, body: dict) -> dict:
        if body["response_format"]["json_schema"]["schema"] != self.canonical:
            raise WireContractError("CANONICAL_REQUEST_DRIFT")
        wire = copy.deepcopy(body)
        wire["response_format"]["json_schema"]["schema"] = self.wire
        notice = (
            "Transport compatibility contract (not business facts or action authorization): "
            "the decoder cannot enforce uniqueItems. Array items must still be unique where "
            "the unchanged public schema requires it. Every response is validated against "
            "the full schema before any action; duplicates are rejected, never deduplicated. "
            "All original sources, goals, identity and version rules remain in force. "
            "Authoritative public response schema:\n" + self.canonical_json
        )
        if wire["messages"] and wire["messages"][0]["role"] == "system":
            content = wire["messages"][0].get("content")
            if not isinstance(content, str):
                raise WireContractError("TEXT_SYSTEM_CONTRACT_REQUIRED")
            wire["messages"][0]["content"] = content + "\n\n" + notice
        else:
            wire["messages"].insert(0, {"role": "system", "content": notice})
        return wire

    def validate_output(self, raw: str) -> dict:
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            encoded(value)  # Reject NaN, Infinity, overflowed JSON numbers.
        except (ValueError, TypeError, RecursionError) as exc:
            code = exc.code if isinstance(exc, ContractError) else "INVALID_FINITE_JSON"
            raise WireContractError(code) from None
        errors = list(
            Draft202012Validator(self.canonical, format_checker=FormatChecker()).iter_errors(value)
        )
        if errors:
            # Field/schema paths only: error.message and instance may echo sensitive content.
            pending, issues = list(errors), []
            while pending and len(issues) < 16:
                error = pending.pop(0)
                if error.context:
                    pending[0:0] = list(error.context)
                else:
                    issues.append(
                        {
                            "path": pointer(list(error.absolute_path)),
                            "schema_path": pointer(list(error.absolute_schema_path)),
                            "rule": str(error.validator),
                        }
                    )
            raise WireContractError("OUTPUT_PUBLIC_CONTRACT_REJECTED", issues=issues)
        return value


def compile_contract(schema: dict) -> WireContract:
    """Conservative positive-schema subset; unknown operators fail before any HTTP.

    Do not recursively delete arbitrary keys. Names/literals called uniqueItems
    remain intact. not/oneOf/if/$ref/contains/unevaluated* need separate proofs and
    are deliberately unsupported, even if a backend would silently accept them.
    """
    canonical = encoded(schema)
    if (
        not isinstance(schema, dict)
        or schema.get("$schema", Draft202012Validator.META_SCHEMA["$id"])
        != (Draft202012Validator.META_SCHEMA["$id"])
    ):
        raise WireContractError("UNSUPPORTED_SCHEMA_DIALECT")
    Draft202012Validator.check_schema(schema)
    deferred = []

    def visit(node: object, path: list) -> object:
        if isinstance(node, bool):
            return node
        if not isinstance(node, dict):
            raise WireContractError("SCHEMA_NODE_REQUIRED")
        unknown = set(node) - MAPS - LISTS - SINGLES - LITERALS - {"uniqueItems"}
        if unknown:
            raise WireContractError(
                "UNREVIEWED_SCHEMA_OPERATOR",
                issues=[{"path": pointer(path), "keyword": k} for k in sorted(unknown)],
            )
        result = {}
        for key, value in node.items():
            if key == "uniqueItems":
                deferred.append(
                    {
                        "path": pointer([*path, key]),
                        "value": value,
                        "enforced_by": "full_schema_before_dispatch",
                    }
                )
            elif key in MAPS:
                result[key] = {
                    name: visit(child, [*path, key, name]) for name, child in value.items()
                }
            elif key in LISTS:
                result[key] = [visit(child, [*path, key, i]) for i, child in enumerate(value)]
            elif key in SINGLES:
                result[key] = visit(value, [*path, key])
            else:
                result[key] = copy.deepcopy(value)
        return result

    wire = visit(schema, [])
    Draft202012Validator.check_schema(wire)
    return WireContract(canonical, encoded(wire), encoded(deferred))
