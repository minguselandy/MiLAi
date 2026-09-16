"""Public-only typed Read/Write/Receipt contract; no private scorer or answer routing."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator, FormatChecker

from v0218_world import PUBLIC_RESOURCES, assert_public, digest

READ_ONLY = frozenset({"object_id", "scope", "version", "tenant", "project", "operation_id"})
VERSION_SCHEMA = {
    "type": "integer",
    "minimum": 0,
    "description": "WORLD version from a completed public observation; not object/Note version. "
    "Never silently rebase.",
}
TEXT_SCHEMA = {"type": "string", "minLength": 1, "pattern": r"\S"}
HASH_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}


class ContractError(ValueError):
    def __init__(self, code: str, *, path: list | None = None, rule: str = ""):
        super().__init__(code)
        self.code, self.path, self.rule = code, path or [], rule


def object_schema(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def variant(action: str, arguments: dict) -> dict:
    return object_schema({"action": {"const": action}, "arguments": arguments})


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("DUPLICATE_JSON_KEY", rule="unique property names")
        result[key] = value
    return result


@dataclass(frozen=True)
class ActionContract:
    """One authoritative public definition generates both schemas and validation."""

    read_schemas: dict
    enable_note: bool = False

    def __post_init__(self):
        copied = copy.deepcopy(self.read_schemas)
        assert_public(copied)
        if not copied:
            raise ContractError("EMPTY_OBJECT_CONTRACT")
        for key, schema in copied.items():
            Draft202012Validator.check_schema(schema)
            if (
                not isinstance(key, str)
                or schema.get("type") != "object"
                or schema.get("additionalProperties") is not False
                or schema.get("properties", {}).get("object_id") != {"const": key}
                or "object_id" not in schema.get("required", [])
            ):
                raise ContractError("PUBLIC_STORED_OBJECT_CONTRACT_REQUIRED")
        object.__setattr__(self, "read_schemas", copied)

    @classmethod
    def from_public(cls, public: dict, *, enable_note: bool = False) -> ActionContract:
        schemas = public["task"]["record_schemas"]
        if set(schemas) != set(public["objects"]):
            raise ContractError("OBJECT_UNIVERSE_MISMATCH")
        return cls(schemas, enable_note)

    @property
    def fingerprint(self) -> str:
        return digest({"read_schemas": self.read_schemas, "enable_note": self.enable_note})

    def write_schemas(self) -> dict:
        schemas = copy.deepcopy(self.read_schemas)
        for schema in schemas.values():
            schema["properties"] = {
                k: v for k, v in schema["properties"].items() if k not in READ_ONLY
            }
            schema["required"] = [k for k in schema["required"] if k not in READ_ONLY]
        return schemas

    def action_schema(self, *, finish_only: bool = False) -> dict:
        branches = [variant("finish", object_schema({"message": TEXT_SCHEMA}))]
        if not finish_only:
            branches.extend(
                [
                    variant(
                        "read", object_schema({"resource": {"enum": sorted(PUBLIC_RESOURCES)}})
                    ),
                    variant("operation_status", object_schema({"operation_id": TEXT_SCHEMA})),
                    variant(
                        "request_clarification",
                        object_schema(
                            {
                                "object_id": {"enum": sorted(self.read_schemas)},
                                "expected_version": VERSION_SCHEMA,
                                "data": object_schema({"question": TEXT_SCHEMA}),
                            }
                        ),
                    ),
                ]
            )
            branches.extend(
                variant(
                    "put_record",
                    object_schema(
                        {
                            "object_id": {"const": key},
                            "expected_version": VERSION_SCHEMA,
                            "data": schema,
                        }
                    ),
                )
                for key, schema in self.write_schemas().items()
            )
            if self.enable_note:
                branches.append(variant("save_note", object_schema({"note": TEXT_SCHEMA})))
        return {"$schema": "https://json-schema.org/draft/2020-12/schema", "anyOf": branches}

    def decode(self, raw: str, *, finish_only: bool = False) -> dict:
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
        except (ValueError, TypeError) as exc:
            if isinstance(exc, ContractError):
                raise
            raise ContractError(
                "INVALID_JSON", rule="one JSON object with named arguments"
            ) from None
        return self.validate(value, finish_only=finish_only)

    def validate(self, value: object, *, finish_only: bool = False) -> dict:
        try:
            json.dumps(value, allow_nan=False)
            assert_public(value)
        except (ValueError, TypeError):
            raise ContractError("NONPUBLIC_OR_NONFINITE", rule="public finite JSON only") from None
        if not isinstance(value, dict) or set(value) != {"action", "arguments"}:
            raise ContractError("ACTION_ENVELOPE_FIELDS", rule="action and arguments only")
        action, args = value["action"], value["arguments"]
        if not isinstance(action, str) or not isinstance(args, dict):
            raise ContractError("ACTION_ENVELOPE_TYPES")
        if action in {"put_record", "request_clarification"}:
            if type(args.get("expected_version")) is not int or args["expected_version"] < 0:
                raise ContractError(
                    "WORLD_VERSION_INTEGER_REQUIRED",
                    path=["arguments", "expected_version"],
                    rule="nonnegative integer, domain WORLD",
                )
            if (
                not isinstance(args.get("object_id"), str)
                or args["object_id"] not in self.read_schemas
            ):
                raise ContractError(
                    "OBJECT_SCOPE_DENIED",
                    path=["arguments", "object_id"],
                    rule="target must belong to this public object universe",
                )
            data = args.get("data")
            if isinstance(data, dict) and READ_ONLY.intersection(data):
                raise ContractError(
                    "READ_ONLY_FIELD",
                    path=["arguments", "data"],
                    rule="omit storage identity/version/host-owned fields; no automatic stripping",
                )
        branches = self.action_schema(finish_only=finish_only)["anyOf"]
        matched = [s for s in branches if s["properties"]["action"]["const"] == action]
        if action == "put_record":
            matched = [
                s
                for s in matched
                if s["properties"]["arguments"]["properties"]["object_id"]["const"]
                == args.get("object_id")
            ]
        if len(matched) != 1:
            raise ContractError("ACTION_NOT_AVAILABLE")
        errors = list(
            Draft202012Validator(matched[0], format_checker=FormatChecker()).iter_errors(value)
        )
        if errors:
            first = errors[0]
            # Never include validator.message or instance: those echo untrusted values.
            rule = str(first.validator)
            if first.validator in {
                "type",
                "required",
                "minLength",
                "maxLength",
                "minimum",
                "maximum",
                "enum",
                "format",
            }:
                rule += "=" + json.dumps(first.validator_value, ensure_ascii=False)
            raise ContractError("PUBLIC_FIELD_CONTRACT", path=list(first.absolute_path), rule=rule)
        return copy.deepcopy(value)

    def response_schema(self) -> dict:
        """Wire outcomes are separate from action schemas and private task correctness."""
        world = {"version_domain": {"const": "WORLD"}}
        operation = {**world, "operation_id": TEXT_SCHEMA}
        success = object_schema(
            {
                **operation,
                "status": {"const": "ACTION_EXECUTED_LOCAL_WORLD"},
                "action": {"enum": ["put_record", "request_clarification"]},
                "object_id": {"enum": sorted(self.read_schemas)},
                "version": VERSION_SCHEMA,
                "before_sha256": HASH_SCHEMA,
                "after_sha256": HASH_SCHEMA,
                "request_sha256": HASH_SCHEMA,
                "committed": {"const": True},
                "business_effect": {"const": True},
                "retry_requires": {"const": "NONE"},
            }
        )
        rejection = object_schema(
            {
                **world,
                "operation_id": {"type": ["string", "null"]},
                "status": {"const": "ACTION_REJECTED"},
                "committed": {"const": False},
                "business_effect": {"const": False},
                "code": {"type": "string", "pattern": "^[A-Z_]+$"},
                "path": {"type": "array", "items": {"type": ["string", "integer"]}},
                "rule": {"type": "string"},
                "retryable": {"type": "boolean"},
                "retry_requires": {
                    "enum": ["READ_AND_REVALIDATE", "CORRECT_REQUEST_NO_AUTO_RETRY"]
                },
            }
        )
        rejection["properties"].update(
            expected_version=VERSION_SCHEMA, current_version=VERSION_SCHEMA
        )
        rejection["allOf"] = [
            {
                "if": {"properties": {"code": {"const": "VERSION_CONFLICT"}}},
                "then": {
                    "required": ["expected_version", "current_version"],
                    "properties": {
                        "retry_requires": {"const": "READ_AND_REVALIDATE"},
                        "retryable": {"const": True},
                    },
                },
                "else": {
                    "not": {
                        "anyOf": [
                            {"required": ["expected_version"]},
                            {"required": ["current_version"]},
                        ]
                    }
                },
            }
        ]
        unknown = object_schema(
            {
                **operation,
                "status": {"const": "COMMIT_UNKNOWN"},
                "committed": {"type": "null"},
                "retry_requires": {"const": "QUERY_OR_EXACT_REPLAY_ONLY"},
                "stop_new_logical_writes": {"const": True},
            }
        )
        unknown["properties"].update(
            code={"const": "UNRESOLVED_PRIOR_OPERATION"}, dispatch_performed={"const": False}
        )
        unknown["dependentRequired"] = {
            "code": ["dispatch_performed"],
            "dispatch_performed": ["code"],
        }
        missing = object_schema(
            {
                **operation,
                "status": {"const": "NOT_OBSERVED"},
                "committed": {"type": "null"},
                "retry_requires": {"const": "QUERY_OR_EXACT_REPLAY_ONLY"},
            }
        )
        observations = []
        for resource in sorted(PUBLIC_RESOURCES):
            if resource == "records":
                content = {
                    "type": "object",
                    "properties": copy.deepcopy(self.read_schemas),
                    "additionalProperties": False,
                }
            elif resource == "pending":
                content = {
                    "type": "object",
                    "properties": {k: TEXT_SCHEMA for k in self.read_schemas},
                    "additionalProperties": False,
                }
            else:
                content = {"type": "array" if resource == "history" else "object"}
            observations.append(
                object_schema(
                    {
                        **world,
                        "status": {"const": "PUBLIC_OBSERVATION"},
                        "resource": {"const": resource},
                        "version": VERSION_SCHEMA,
                        "content": content,
                        "content_sha256": HASH_SCHEMA,
                        "committed": {"const": False},
                        "business_effect": {"const": False},
                    }
                )
            )
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "anyOf": [success, rejection, unknown, missing, *observations],
        }

    def validate_response(self, response: dict) -> dict:
        try:
            json.dumps(response, allow_nan=False)
            assert_public(response)
        except (ValueError, TypeError):
            raise ContractError("INVALID_PUBLIC_RESPONSE") from None
        if not Draft202012Validator(
            self.response_schema(), format_checker=FormatChecker()
        ).is_valid(response):
            raise ContractError("INVALID_PUBLIC_RESPONSE")
        if response.get("status") == "PUBLIC_OBSERVATION":
            if response["content_sha256"] != digest(response["content"]):
                raise ContractError("PUBLIC_OBSERVATION_HASH_MISMATCH")
        return copy.deepcopy(response)

    def documents(self) -> dict:
        return {
            "contract_version": "v0220-action-v1",
            "contract_sha256": self.fingerprint,
            "read_model": {
                "record_schemas": copy.deepcopy(self.read_schemas),
                "version_domain": "WORLD",
                "source": "completed public read",
            },
            "write_model": {
                "record_schemas": self.write_schemas(),
                "action_schema": self.action_schema(),
                "operation_id": "Host allocated per logical business action, not model supplied",
            },
            "receipt_model": {
                "schema": self.response_schema(),
                "business_success": "committed=true, operation_id, WORLD version, "
                "request/state digests; verify by public read",
                "rejection": "committed=false, code, safe field path/rule, retry_requires",
                "version_conflict": "READ_AND_REVALIDATE; never automatically bind current head",
                "unknown": "committed=null, stop new logical writes; "
                "query durable operation or replay exactly",
                "not_observed": "not proof of no commit; do not authorize a different request",
                "note_and_finish": "no business effect; task outcome evaluated independently",
            },
            "examples": [
                {"action": "read", "arguments": {"resource": "records"}},
                {
                    "action": "finish",
                    "arguments": {"message": "Describe actual effects and remaining work."},
                },
            ],
        }
