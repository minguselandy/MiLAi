"""Run the synthetic DG-18 provider/wire conformance matrix without LME data."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg18/provider-conformance"


def run(
    *,
    run_id: str,
    output_root: Path,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    from milai.adapters.semantic_hint import LoopbackVllmSemanticProvider
    from milai.application.residual_refinding import (
        normalize_residual_cue_proposal,
        residual_cue_proposal_output_schema,
        validate_residual_search_hint,
    )
    from milai.application.semantic_hint import SemanticHintError
    from milai.domain.residual_refinding import ResidualCueProposal

    if not run_id:
        raise ValueError("provider conformance run ID is required")
    if output_root.exists():
        raise FileExistsError("provider conformance output exists; choose a fresh run ID")
    output_root.mkdir(parents=True)
    identity = _provider_runtime_identity(base_url, model)
    observation, state, plan = _synthetic_runtime_context()
    proposal_schema = residual_cue_proposal_output_schema()
    flat_action_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "SEARCH_LEXICAL",
                    "SEARCH_TEMPORAL",
                    "EXPAND_NEIGHBORS",
                    "NO_ACTION",
                ],
            }
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    unsupported_schema = {
        "type": "object",
        "properties": {
            "cues": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            }
        },
        "required": ["cues"],
        "additionalProperties": False,
    }
    specifications = (
        {
            "cell": "flat_action_enum",
            "schema_name": "dg18_flat_action_enum_v01",
            "schema": flat_action_schema,
            "instruction": "Return exactly one JSON object with action NO_ACTION.",
            "expected_action": "NO_ACTION",
            "runtime": False,
            "expected_failure": None,
        },
        {
            "cell": "flat_lexical_cue",
            "schema_name": "residual_cue_proposal_v01",
            "schema": proposal_schema,
            "instruction": (
                "Return exactly requirement_id TARGET_EVENT, action SEARCH_LEXICAL, "
                "and cues containing only rollout."
            ),
            "expected_action": "SEARCH_LEXICAL",
            "runtime": True,
            "expected_failure": None,
        },
        {
            "cell": "flat_temporal_cue",
            "schema_name": "residual_cue_proposal_v01",
            "schema": proposal_schema,
            "instruction": (
                "Return exactly requirement_id TARGET_EVENT, action SEARCH_TEMPORAL, "
                "and an empty cues array. Runtime supplies the time bounds."
            ),
            "expected_action": "SEARCH_TEMPORAL",
            "runtime": True,
            "expected_failure": None,
        },
        {
            "cell": "historical_unique_items_negative",
            "schema_name": "dg18_unique_items_negative_v01",
            "schema": unsupported_schema,
            "instruction": "Return exactly one JSON object with cues containing rollout.",
            "expected_action": None,
            "runtime": False,
            "expected_failure": "PROVIDER_SCHEMA_UNSUPPORTED",
        },
    )
    rows: list[dict[str, Any]] = []
    for transport in ("non-streaming", "streaming"):
        for index, specification in enumerate(specifications):
            provider = LoopbackVllmSemanticProvider(
                base_url=base_url,
                model=model,
                timeout_seconds=30,
                transport_mode=cast(Any, transport),
            )
            schema = cast(Mapping[str, Any], specification["schema"])
            schema_name = str(specification["schema_name"])
            row: dict[str, Any] = {
                "cell": specification["cell"],
                "transport_mode": transport,
                "ProviderCallAttempted": True,
                "ProviderSchemaAccepted": False,
                "ProviderSSEErrorObserved": False,
                "ProviderErrorClassificationCorrect": None,
                "JsonObjectParsed": False,
                "PydanticParsed": False,
                "RuntimeAccepted": False,
                "runtime_reason_code": None,
                "http_status": None,
                "stream_finish_state": None,
                "provider_version": identity["provider_version"],
                "model_identity": model,
                "schema_name": schema_name,
                "schema_digest": _digest(schema),
                "sse_top_level_error_type": None,
                "sse_top_level_error_code": None,
                "validation_error_field_path": None,
                "validation_error_type": None,
                "finish_reason": None,
                "completion_tokens": None,
                "latency_ms": None,
                "automatic_retry_count": 0,
                "completion_sha256": None,
                "expected_failure": specification["expected_failure"],
                "status": "FAIL",
            }
            try:
                completion = provider.complete_structured(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "This is a synthetic provider conformance probe. "
                                "Do not answer any user question or add fields."
                            ),
                        },
                        {"role": "user", "content": str(specification["instruction"])},
                    ],
                    schema_name=schema_name,
                    schema=schema,
                    max_completion_tokens=64,
                    seed=10_000 + index,
                )
                row.update(
                    {
                        "http_status": completion.http_status,
                        "stream_finish_state": completion.stream_finish_state,
                        "finish_reason": completion.finish_reason,
                        "completion_tokens": completion.completion_tokens,
                        "latency_ms": round(completion.total_ms, 6),
                        "completion_sha256": hashlib.sha256(
                            completion.content.encode()
                        ).hexdigest(),
                    }
                )
                if specification["expected_failure"] is not None:
                    row["validation_error_field_path"] = "$"
                    row["validation_error_type"] = "expected_provider_error_not_observed"
                elif specification["runtime"] is True:
                    proposal = ResidualCueProposal.model_validate_json(completion.content)
                    row["JsonObjectParsed"] = True
                    row["PydanticParsed"] = True
                    if proposal.action != specification["expected_action"]:
                        row["validation_error_field_path"] = "action"
                        row["validation_error_type"] = "unexpected_action"
                    else:
                        row["ProviderSchemaAccepted"] = True
                        hint = normalize_residual_cue_proposal(
                            proposal=proposal,
                            observation=observation,
                            plan=plan,
                        )
                        validation = validate_residual_search_hint(
                            hint=hint,
                            state=state,
                            plan=plan,
                        )
                        row["runtime_reason_code"] = validation.reason_code
                        row["RuntimeAccepted"] = validation.status == "ACCEPTED"
                        row["status"] = (
                            "PASS" if validation.status == "ACCEPTED" else "FAIL"
                        )
                else:
                    decoded = json.loads(completion.content)
                    if not isinstance(decoded, Mapping):
                        raise ValueError("flat action output is not an object")
                    row["JsonObjectParsed"] = True
                    if (
                        set(decoded) == {"action"}
                        and decoded.get("action") == specification["expected_action"]
                    ):
                        row["ProviderSchemaAccepted"] = True
                        row["status"] = "PASS"
                    else:
                        row["validation_error_field_path"] = "action"
                        row["validation_error_type"] = "unexpected_action_or_shape"
            except SemanticHintError as exc:
                row.update(
                    {
                        "http_status": exc.http_status,
                        "stream_finish_state": exc.stream_finish_state,
                        "ProviderSSEErrorObserved": (
                            exc.transport_mode == "streaming"
                            and (
                                exc.sse_error_type is not None
                                or exc.sse_error_code is not None
                            )
                        ),
                        "sse_top_level_error_type": exc.sse_error_type,
                        "sse_top_level_error_code": exc.sse_error_code,
                        "finish_reason": exc.finish_reason,
                        "completion_tokens": exc.completion_tokens,
                        "latency_ms": (
                            round(exc.latency_ms, 6)
                            if exc.latency_ms is not None
                            else None
                        ),
                        "validation_error_field_path": "$provider",
                        "validation_error_type": exc.code,
                    }
                )
                expected_failure = specification["expected_failure"] is not None
                correct = (
                    exc.code == "SEMANTIC_HINT_PROVIDER_SSE_ERROR"
                    if transport == "streaming"
                    else exc.http_status == 500
                )
                row["ProviderErrorClassificationCorrect"] = correct
                row["status"] = "PASS" if expected_failure and correct else "FAIL"
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                field_path, error_type = _validation_identity(exc)
                row["validation_error_field_path"] = field_path
                row["validation_error_type"] = error_type
            rows.append(row)

    flat_rows = [
        row for row in rows if row["cell"] != "historical_unique_items_negative"
    ]
    negative_rows = [
        row for row in rows if row["cell"] == "historical_unique_items_negative"
    ]
    matrix = {
        "schema": "milai.dg18.provider-conformance-matrix.v0.1",
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        "classification": "SYNTHETIC_PROVIDER_CONFORMANCE / NO_LME_DATA",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "provider_runtime_identity": identity,
        "application_schema_name": "residual_cue_proposal_v01",
        "application_schema_digest": _digest(proposal_schema),
        "application_schema_forbidden_keywords_absent": all(
            value not in json.dumps(proposal_schema, sort_keys=True)
            for value in ("uniqueItems", "oneOf", "anyOf")
        ),
        "automatic_retry_count": 0,
        "rows": rows,
        "summary": {
            "flat_cell_count": len(flat_rows),
            "flat_cell_pass_count": sum(row["status"] == "PASS" for row in flat_rows),
            "pydantic_parse_count": sum(row["PydanticParsed"] is True for row in rows),
            "runtime_accepted_count": sum(row["RuntimeAccepted"] is True for row in rows),
            "negative_cell_count": len(negative_rows),
            "negative_error_classification_pass_count": sum(
                row["ProviderErrorClassificationCorrect"] is True
                for row in negative_rows
            ),
        },
    }
    matrix_path = output_root / "matrix.json"
    _write_new(matrix_path, matrix)
    streaming_negative = next(
        row
        for row in negative_rows
        if row["transport_mode"] == "streaming"
    )
    sse_receipt = {
        "schema": "milai.dg18.typed-sse-error-receipt.v0.1",
        "status": (
            "PASS_TYPED_SSE_ERROR_CLASSIFICATION"
            if streaming_negative["status"] == "PASS"
            else "FAIL"
        ),
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "full_prompt_or_completion_persisted": False,
        "diagnostic": streaming_negative,
    }
    sse_path = output_root / "typed-sse-error-receipt.json"
    _write_new(sse_path, sse_receipt)
    receipt = {
        "schema": "milai.dg18.provider-conformance-receipt.v0.1",
        "status": (
            "PASS_PROVIDER_CONFORMANCE"
            if matrix["status"] == "PASS"
            else "FAIL_PROVIDER_CONFORMANCE"
        ),
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "lme_executed": False,
        "provider_restarted_or_reconfigured": False,
        "automatic_retry_count": 0,
        "provider_runtime_identity": identity,
        "summary": matrix["summary"],
        "artifacts": {
            "matrix": _identity(matrix_path),
            "typed_sse_error": _identity(sse_path),
        },
        "next_gate": (
            "SYNTHETIC_SHADOW_FIXTURE_ALLOWED_FULL_LME_STILL_DISABLED"
            if matrix["status"] == "PASS"
            else "PROVIDER_CONTRACT_REPAIR_REQUIRED"
        ),
    }
    receipt_path = output_root / "receipt.json"
    _write_new(receipt_path, receipt)
    return receipt


def _synthetic_runtime_context():  # type: ignore[no-untyped-def]
    from milai.application.acquisition_state import (
        advance_acquisition_state,
        build_acquisition_action,
        initialize_acquisition_state,
        reserve_residual_controller_call,
    )
    from milai.application.residual_refinding import build_acquisition_observation
    from milai.domain.acquisition import (
        AcquisitionBudget,
        AcquisitionEvidenceSourcePolicy,
        AcquisitionFusion,
        AcquisitionGlobalConstraints,
        AcquisitionPlan,
        AcquisitionProbe,
        AcquisitionResidualPolicy,
    )
    from milai.domain.semantic_query import (
        EvidenceRequirementV02,
        NormalizedTemporalConstraint,
    )

    reference = datetime(2026, 8, 28, tzinfo=UTC)
    temporal = NormalizedTemporalConstraint(
        reference_time=reference,
        start=reference - timedelta(days=30),
        end=reference,
        boundary="CLOSED_CLOSED",
        time_axis="SOURCE_OBSERVED_TIME",
    )
    requirement = EvidenceRequirementV02(
        slot_id="TARGET_EVENT",
        interpretation_kind="EVENT",
        entity_constraints=["release"],
        predicate_constraints=["rollout"],
        temporal_constraints=temporal,
    )
    plan = AcquisitionPlan(
        query_ir_digest="a" * 64,
        global_constraints=AcquisitionGlobalConstraints(
            principal_scope={"synthetic_probe": True},
            semantic_scope={},
            tenant_identity_digest="b" * 64,
            principal_identity_digest="c" * 64,
            authority_floor="INFORMATIONAL",
            valid_as_of=reference,
            system_as_of=reference,
            source_observed_range={
                "start": (reference - timedelta(days=30)).isoformat(),
                "end": reference.isoformat(),
            },
        ),
        probes=[
            AcquisitionProbe(
                probe_id="synthetic-target-event-fts",
                requirement_slot="TARGET_EVENT",
                channel="FTS_RAW",
                evidence_source_policy=AcquisitionEvidenceSourcePolicy(),
                lexical_terms=["release"],
                temporal_axis="SOURCE_OBSERVED_TIME",
                candidate_limit=8,
                expansion_policy="NONE",
            )
        ],
        fusion=AcquisitionFusion(
            policy_identity="synthetic-conformance",
            per_slot_quota={"TARGET_EVENT": 8},
            global_cap=8,
        ),
        residual_policy=AcquisitionResidualPolicy(
            allowed=True,
            max_model_calls=1,
            max_extra_passes=1,
        ),
        budget=AcquisitionBudget(
            latency_ms=5_000,
            candidate_count=8,
            hydrate_count=8,
            context_tokens=1_024,
        ),
    )
    initial = initialize_acquisition_state(plan, [requirement])
    deterministic = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=initial.missing_requirement_ids,
        probe_ids=[probe.probe_id for probe in plan.probes],
    )
    state = advance_acquisition_state(initial, deterministic).state
    observation = build_acquisition_observation(
        query="Find the target release event during the bounded synthetic window.",
        requirements=[requirement],
        candidates=[],
        state=state,
        plan=plan,
    )
    reserved = reserve_residual_controller_call(state, plan)
    if reserved.outcome != "APPLIED":
        raise RuntimeError("synthetic residual controller reservation failed")
    return observation, reserved.state, plan


def _provider_runtime_identity(base_url: str, model: str) -> dict[str, Any]:
    parsed = urlparse(base_url.rstrip("/"))
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port is None
    ):
        raise ValueError("provider conformance requires an explicit loopback endpoint")
    models, models_body = _get_json(parsed.hostname, parsed.port, "/v1/models")
    version, version_body = _get_json(parsed.hostname, parsed.port, "/version")
    model_rows = models.get("data") if isinstance(models, Mapping) else None
    if not isinstance(model_rows, list):
        raise TypeError("provider /v1/models identity is invalid")
    model_ids = sorted(
        str(item["id"])
        for item in model_rows
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    )
    if model not in model_ids:
        raise RuntimeError("configured model is absent from provider /v1/models")
    provider_version = version.get("version") if isinstance(version, Mapping) else None
    if not isinstance(provider_version, str) or not provider_version:
        raise RuntimeError("provider /version identity is invalid")
    listener = subprocess.run(
        ["ss", "-ltnp", f"sport = :{parsed.port}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    listener_output = listener.stdout.strip()
    if listener.returncode != 0 or "LISTEN" not in listener_output:
        raise RuntimeError("provider listener identity is not observable")
    return {
        "schema": "milai.dg18.provider-runtime-identity.v0.2",
        "verified": True,
        "base_url": base_url.rstrip("/"),
        "configured_model": model,
        "available_model_ids": model_ids,
        "provider_version": provider_version,
        "models_response_sha256": hashlib.sha256(models_body).hexdigest(),
        "version_response_sha256": hashlib.sha256(version_body).hexdigest(),
        "listener_observed": True,
        "listener_receipt_sha256": hashlib.sha256(listener_output.encode()).hexdigest(),
    }


def _get_json(host: str, port: int, path: str) -> tuple[Mapping[str, Any], bytes]:
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read(1_048_576)
        if response.status != 200:
            raise RuntimeError(f"provider identity {path} returned HTTP {response.status}")
        decoded = json.loads(body)
    finally:
        connection.close()
    if not isinstance(decoded, Mapping):
        raise TypeError(f"provider identity {path} is not a JSON object")
    return decoded, body


def _validation_identity(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, ValidationError):
        diagnostic = exc.errors(include_url=False, include_context=False)[0]
        path = ".".join(str(value) for value in diagnostic.get("loc", ())) or "$"
        return path, str(diagnostic.get("type", "unknown"))
    return "$", type(exc).__name__


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write_new(path: Path, value: object) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    with path.open("xb") as handle:
        handle.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        base_url=args.base_url,
        model=args.model,
    )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "run_id": args.run_id,
                "receipt": str(receipt_path),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "next_gate": receipt["next_gate"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if receipt["status"] == "PASS_PROVIDER_CONFORMANCE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
