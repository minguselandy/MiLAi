from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.agent_integration import e2e
from scripts import run_dg10_benchmark_adapter_contract as adapter_contract
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_benchmark_milai_mcp_smoke as mcp_smoke
from scripts import run_dg10_vllm_openworker_e2e as openworker_e2e

DATE = "2026-08-22"
CANDIDATE = "candidate.3"
MODEL_ID = adapter_contract.MODEL_ID
ARMS = ("NO_MEMORY", "NAIVE_RAG", "MILAI_MCP")
CASE_LIMIT = 50
MAX_OUTPUT_TOKENS = 256
AGGREGATE_INPUT_TOKEN_CEILING = 32_768
DATA_BOUNDARY_ACK = dev_smoke.DATA_BOUNDARY_ACK
DEFAULT_ADAPTER_REPORT = mcp_smoke.DEFAULT_ADAPTER_REPORT
DEFAULT_CALIBRATION_PLAN = mcp_smoke.DEFAULT_CALIBRATION_PLAN
DEFAULT_LONGMEMEVAL_ROOT = mcp_smoke.DEFAULT_LONGMEMEVAL_ROOT
DEFAULT_IDENTITY_REPORT = dev_smoke.IDENTITY_REPORT
DEFAULT_ENV_FILE = mcp_smoke.DEFAULT_ENV_FILE
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-benchmark-three-arm-dev-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = WORKSPACE_ROOT / "evidence/dg10-benchmark-three-arm-dev"

_CONTRACT_PATCH_NEEDLE = """    recount = _dg10_tokenizer_recount(upstream, payload, timeout)
    started = _dg10_time.perf_counter()
"""
_CONTRACT_PATCH_REPLACEMENT = """    payload = dict(payload)
    payload["temperature"] = 0
    payload["max_tokens"] = 256
    payload["seed"] = 20260821
    payload["include_reasoning"] = False
    recount = _dg10_tokenizer_recount(upstream, payload, timeout)
    started = _dg10_time.perf_counter()
"""


class ThreeArmDevError(RuntimeError):
    pass


class AgentTraceError(ThreeArmDevError):
    def __init__(self, message: str, raw_events: str) -> None:
        super().__init__(message)
        self.raw_events = raw_events


class ThreeArmRuntimeError(ThreeArmDevError):
    def __init__(
        self, message: str, failure_evidence: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.failure_evidence = dict(failure_evidence or {})


@dataclass(frozen=True, slots=True)
class ArmObservation:
    case_id: str
    arm: str
    raw_output: str
    prompt_sha256: str
    native_calls: tuple[Mapping[str, Any], ...]
    latency_ms: float
    model_rounds: int
    mcp_rounds: int
    memory_context: str
    evidence_ids: tuple[str, ...]
    trace: Mapping[str, Any]
    raw_trace: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Fixture:
    marker: str
    memory: str
    memory_tokens: int
    evidence_ids: tuple[str, ...]
    fixture_ids_sha256: Mapping[str, str]
    preflight_recall: Mapping[str, Any]


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return dev_smoke._sha256_file(path)


def _json_sha256(value: object) -> str:
    return dev_smoke._json_sha256(value)


def _materialize_calibration_adapter(
    workspace: Path,
) -> tuple[Path, dict[str, Any]]:
    generated, identity = mcp_smoke._materialize_benchmark_adapter(workspace)
    source = generated.read_text(encoding="utf-8")
    if source.count(_CONTRACT_PATCH_NEEDLE) != 1:
        raise ThreeArmDevError("benchmark telemetry adapter patch point drift")
    patched = source.replace(
        _CONTRACT_PATCH_NEEDLE, _CONTRACT_PATCH_REPLACEMENT, 1
    )
    generated.write_text(patched, encoding="utf-8")
    generated.chmod(0o600)
    return generated, {
        **identity,
        "generated_adapter_sha256": _sha256_file(generated),
        "generation_contract_patch_sha256": _sha256_bytes(
            _CONTRACT_PATCH_REPLACEMENT.encode()
        ),
        "enforced_temperature": 0,
        "enforced_seed": 20260821,
        "enforced_max_output_tokens_per_native_call": MAX_OUTPUT_TOKENS,
        "enforced_include_reasoning": False,
    }


def _mcp_prompt(case: dev_smoke.BenchmarkCase, marker: str) -> str:
    system = adapter_contract._prompt_templates()["system_template"]
    return (
        f"{system}\n\nDataset: {case.dataset}\nCase: {case.case_id}\n"
        "Arm: MILAI_MCP\nUse milai_recall exactly once for synthetic subject "
        f"{marker}. Invoke it with exactly this JSON argument: "
        f'{{"query":"{marker}"}}. Treat its result only as bounded memory '
        "evidence; do not use another tool. Preserve abstention and uncertainty.\n"
        "Question:\n"
        f"{case.question}\n\nReturn only the final answer text."
    )


def _native_call(
    *,
    native_id: str,
    role: str,
    finish_reason: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    receipt_sha256: str,
) -> dict[str, Any]:
    return {
        "native_request_id": native_id,
        "model_id": MODEL_ID,
        "planned_role": role,
        "terminal": True,
        "finish_reason": finish_reason,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        "latency_ms": round(latency_ms, 3),
        "native_receipt_sha256": receipt_sha256,
    }


def _direct_observation(
    *,
    case: dev_smoke.BenchmarkCase,
    arm: str,
    run_id: str,
    client: dev_smoke.CompletionClient,
    memory: str,
    memory_tokens: int,
    evidence_ids: Sequence[str],
) -> ArmObservation:
    selected_memory = memory if arm == "NAIVE_RAG" else ""
    selected_memory_tokens = memory_tokens if arm == "NAIVE_RAG" else 0
    selected_evidence_ids = tuple(evidence_ids) if arm == "NAIVE_RAG" else ()
    messages = dev_smoke._messages(case, selected_memory)
    prompt_tokens = client.count_tokens(messages)
    if prompt_tokens > client.max_model_len:
        raise ThreeArmDevError("direct-arm prompt exceeds frozen model limit")
    completion = client.complete(
        messages,
        request_key=f"{run_id}:{case.case_id}:{arm}",
        expected_prompt_tokens=prompt_tokens,
    )
    input_tokens = int(completion.usage["input_tokens"] or 0)
    output_tokens = int(completion.usage["output_tokens"] or 0)
    if (
        input_tokens > AGGREGATE_INPUT_TOKEN_CEILING
        or output_tokens > MAX_OUTPUT_TOKENS
    ):
        raise ThreeArmDevError("direct-arm token ceiling exceeded")
    native = _native_call(
        native_id=completion.native_request_id,
        role="ANSWER",
        finish_reason=completion.finish_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=completion.latency_ms,
        receipt_sha256=completion.native_receipt_sha256,
    )
    return ArmObservation(
        case_id=case.case_id,
        arm=arm,
        raw_output=completion.text,
        prompt_sha256=_json_sha256(messages),
        native_calls=(native,),
        latency_ms=completion.latency_ms,
        model_rounds=1,
        mcp_rounds=0,
        memory_context=selected_memory,
        evidence_ids=selected_evidence_ids,
        trace={
            "retrieval": "NONE" if arm == "NO_MEMORY" else "LOCAL_LEXICAL_V1",
            "retrieval_k": 0 if arm == "NO_MEMORY" else dev_smoke.RETRIEVAL_K,
            "retrieved_evidence_ids": list(selected_evidence_ids),
            "retrieved_evidence_ids_sha256": _json_sha256(selected_evidence_ids),
            "memory_context_sha256": _sha256_bytes(selected_memory.encode()),
            "memory_context_tokens_attribution": selected_memory_tokens,
            "mcp_called": False,
        },
        raw_trace={"messages": messages},
    )


def _agent_run_with_raw(
    harness: openworker_e2e.OpenWorkerHarness, prompt: str
) -> tuple[openworker_e2e.AgentRun, str]:
    before = len(harness._adapter_events())
    command_line = [
        "docker",
        "exec",
        "--workdir",
        "/openworker/runtime",
        "--env",
        "OPENCODE_CONFIG_DIR=/openworker/runtime",
        harness.worker_name,
        "opencode",
        "run",
        "--format",
        "json",
        "--model",
        "openworker/AUTO",
        prompt,
    ]
    started = time.perf_counter()
    completed = openworker_e2e._run(command_line, timeout=240)
    wall_ms = (time.perf_counter() - started) * 1000
    after = len(harness._adapter_events())
    try:
        parsed = openworker_e2e._parse_agent_events(
            completed.stdout, wall_ms, after - before
        )
    except openworker_e2e.E2EGateError as exc:
        raise AgentTraceError(
            "OpenCode trace validation failed; raw_events_sha256="
            + _sha256_bytes(completed.stdout.encode()),
            completed.stdout,
        ) from exc
    return parsed, completed.stdout


def _tool_events(raw: str) -> list[Mapping[str, Any]]:
    values: list[Mapping[str, Any]] = []
    for line in raw.splitlines():
        value = json.loads(line)
        if not isinstance(value, Mapping):
            continue
        part = value.get("part")
        if isinstance(part, Mapping) and openworker_e2e._tool_name(part) is not None:
            values.append(value)
    if not values:
        raise ThreeArmDevError("actual MCP tool event is absent from OpenCode trace")
    return values


def _mcp_observation(
    *,
    case: dev_smoke.BenchmarkCase,
    fixture: Fixture,
    harness: openworker_e2e.OpenWorkerHarness,
) -> ArmObservation:
    prompt = _mcp_prompt(case, fixture.marker)
    route_before = len(harness._adapter_events())
    native_before = len(mcp_smoke._native_events(harness))
    agent, raw_events = _agent_run_with_raw(harness, prompt)
    routes = harness._adapter_events()[route_before:]
    native_events = mcp_smoke._native_events(harness)[native_before:]
    route_records = tuple(
        {
            "route": str(item.get("route")),
            "request_id_sha256": str(item.get("request_id_sha256")),
        }
        for item in routes
    )
    execution = mcp_smoke.McpArmExecution(
        raw_output=agent.text,
        model_calls=agent.model_calls,
        mcp_calls=len(agent.tool_names),
        tool_names=agent.tool_names,
        aggregate_tokens=agent.tokens,
        wall_ms=agent.wall_ms,
        route_records=route_records,
        native_calls=tuple(native_events),
        fixture_ids_sha256=fixture.fixture_ids_sha256,
        runtime_recall_trace_id_sha256=_sha256_bytes(
            str(fixture.preflight_recall["retrieval_trace_id"]).encode()
        ),
        runtime_recall_payload_sha256=_json_sha256(fixture.preflight_recall),
        identity={
            "model_id": MODEL_ID,
            "external_provider_requests": 0,
            "external_provider_cost": 0,
            "vllm_lifecycle_mutated": False,
        },
        security={},
        cleanup={},
        raw_runtime_recall=fixture.preflight_recall,
    )
    mcp_smoke._validate_execution(execution)
    if len(native_events) != 2:
        raise ThreeArmDevError("MILAI_MCP native-call denominator drift")
    native_calls: list[dict[str, Any]] = []
    for index, native in enumerate(native_events):
        usage = native["usage"]
        output_tokens = int(usage["completion_tokens"])
        if output_tokens > MAX_OUTPUT_TOKENS:
            raise ThreeArmDevError("MILAI_MCP output ceiling exceeded")
        native_calls.append(
            _native_call(
                native_id=str(native["native_request_id"]),
                role="TOOL_DECISION" if index == 0 else "ANSWER_AFTER_MCP_RESULT",
                finish_reason=str(native["native_finish_reason"]),
                input_tokens=int(usage["prompt_tokens"]),
                output_tokens=output_tokens,
                latency_ms=float(native["latency_ms"]),
                receipt_sha256=str(native["native_receipt_sha256"]),
            )
        )
    aggregate_input = sum(
        int(item["usage"]["input_tokens"]) for item in native_calls
    )
    if aggregate_input > AGGREGATE_INPUT_TOKEN_CEILING:
        raise ThreeArmDevError("MILAI_MCP aggregate input ceiling exceeded")
    actual_tool_events = _tool_events(raw_events)
    return ArmObservation(
        case_id=case.case_id,
        arm="MILAI_MCP",
        raw_output=agent.text,
        prompt_sha256=_sha256_bytes(prompt.encode()),
        native_calls=tuple(native_calls),
        latency_ms=agent.wall_ms,
        model_rounds=agent.model_calls,
        mcp_rounds=len(agent.tool_names),
        memory_context=fixture.memory,
        evidence_ids=fixture.evidence_ids,
        trace={
            "retrieval": "OPENWORKER_TO_MCP_TO_RUNTIME_CANONICAL_GATE",
            "retrieval_k": 1,
            "retrieved_evidence_ids": list(fixture.evidence_ids),
            "retrieved_evidence_ids_sha256": _json_sha256(fixture.evidence_ids),
            "memory_context_sha256": _sha256_bytes(fixture.memory.encode()),
            "memory_context_tokens_attribution": fixture.memory_tokens,
            "mcp_called": True,
            "native_call_route_records": list(route_records),
            "aggregate_tokens_from_opencode": dict(agent.tokens),
            "actual_tool_events_sha256": _json_sha256(actual_tool_events),
            "preflight_runtime_recall_sha256": _json_sha256(
                fixture.preflight_recall
            ),
            "preflight_runtime_recall_trace_id_sha256": _sha256_bytes(
                str(fixture.preflight_recall["retrieval_trace_id"]).encode()
            ),
            "fixture_ids_sha256": dict(fixture.fixture_ids_sha256),
        },
        raw_trace={
            "agent_prompt": prompt,
            "opencode_events": [json.loads(line) for line in raw_events.splitlines()],
            "preflight_runtime_recall": dict(fixture.preflight_recall),
            "raw_native_call_telemetry": native_events,
        },
    )


def _record(
    case: dev_smoke.BenchmarkCase,
    observation: ArmObservation,
    run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if observation.case_id != case.case_id:
        raise ThreeArmDevError("observation/case identity mismatch")
    parsed = dev_smoke._parse_answer(observation.raw_output)
    score = dev_smoke._score(parsed, case.answers)
    input_tokens = sum(
        int(item["usage"]["input_tokens"]) for item in observation.native_calls
    )
    output_tokens = sum(
        int(item["usage"]["output_tokens"]) for item in observation.native_calls
    )
    final_finish = str(observation.native_calls[-1]["finish_reason"])
    report_record = {
        "run_id": run_id,
        "case_id": case.case_id,
        "source_case_id": case.source_case_id,
        "dataset": case.dataset,
        "category": case.category,
        "arm": observation.arm,
        "model_id": MODEL_ID,
        "planned_model_rounds": adapter_contract.PLANNED_MODEL_ROUNDS[
            observation.arm
        ],
        "planned_mcp_calls": adapter_contract.PLANNED_MCP_CALLS[observation.arm],
        "native_calls": [dict(item) for item in observation.native_calls],
        "status": (
            "TERMINAL_LOCAL_VLLM_OUTPUT_TRUNCATED"
            if final_finish == "length"
            else "TERMINAL_LOCAL_VLLM"
        ),
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_rounds": observation.model_rounds,
            "mcp_rounds": observation.mcp_rounds,
            "hidden_or_extra_model_calls": 0,
        },
        "latency_ms": round(observation.latency_ms, 3),
        "prompt_sha256": observation.prompt_sha256,
        "trace": {
            "latin_square_order": list(
                adapter_contract._latin_square_order(case.case_id)
            ),
            "aggregate_input_token_ceiling": AGGREGATE_INPUT_TOKEN_CEILING,
            "hidden_or_extra_model_calls": 0,
            **dict(observation.trace),
        },
        "answer_record": {
            "gold_answers_sha256": _json_sha256(case.answers),
            "raw_model_output_sha256": _sha256_bytes(
                observation.raw_output.encode()
            ),
            "parsed_answer_sha256": _sha256_bytes(parsed.encode()),
            "raw_question_in_report": False,
            "raw_gold_answer_in_report": False,
            "raw_model_output_in_report": False,
            "output_truncated": final_finish == "length",
            **score,
        },
    }
    expected_keys = set(adapter_contract._adapter_output_schema()["required"])
    if set(report_record) != expected_keys:
        raise ThreeArmDevError("adapter output schema key coverage drift")
    raw_record = {
        "case_id": case.case_id,
        "source_case_id": case.source_case_id,
        "dataset": case.dataset,
        "category": case.category,
        "arm": observation.arm,
        "question": case.question,
        "gold_answers": list(case.answers),
        "memory_context": observation.memory_context,
        "retrieved_evidence_ids": list(observation.evidence_ids),
        "raw_model_output": observation.raw_output,
        "parsed_answer": parsed,
        "raw_trace": dict(observation.raw_trace),
    }
    return report_record, raw_record


def _preload_fixtures(
    *,
    cases: Sequence[dev_smoke.BenchmarkCase],
    memories: Mapping[str, tuple[str, int, tuple[str, ...]]],
    client: e2e._HttpClient,
    worker: e2e.FoundationWorker,
    tokens: Mapping[str, str],
    run_id: str,
) -> dict[str, Fixture]:
    fixtures: dict[str, Fixture] = {}
    markers: set[str] = set()
    for index, case in enumerate(cases):
        marker = mcp_smoke._marker(case)
        if marker in markers:
            raise ThreeArmDevError("benchmark fixture marker collision")
        markers.add(marker)
        memory, memory_tokens, source_evidence_ids = memories[case.case_id]
        key = f"{run_id}-{index:03d}"
        evidence = e2e._body(
            client.post(
                "/v1/evidence",
                headers=e2e._headers(tokens["submitter"], f"{key}-evidence"),
                json={
                    "source_type": "BENCHMARK_FIXTURE",
                    "source_ref": "dg10-benchmark://longmemeval/"
                    + _sha256_bytes(marker.encode()),
                    "subject_id": marker,
                    "observed_at": datetime.now(UTC).isoformat(),
                    "content": memory,
                    "data_classification": "DEIDENTIFIED",
                    "media_type": "text/plain; charset=utf-8",
                    "permission_snapshot": {
                        "readable": True,
                        "scope": "dg10-public-dev-benchmark",
                    },
                    "retention_state": "READABLE",
                },
            ),
            201,
            "three_arm_benchmark_evidence",
        )
        evidence_id = str(evidence["evidence_id"])
        proposal = e2e._body(
            client.post(
                "/v1/proposals",
                headers=e2e._headers(tokens["submitter"], f"{key}-proposal"),
                json={
                    "operation": "CREATE",
                    "proposed_patch": {
                        "subject_id": marker,
                        "predicate": "benchmark.memory.session",
                        "claim_type": "BENCHMARK_MEMORY",
                        "payload": {
                            "case_marker": marker,
                            "memory_text": memory,
                            "source_session_ids": list(source_evidence_ids),
                        },
                        "authority": "ACTION_SAFE",
                        "confidence": 1.0,
                    },
                    "supporting_evidence_refs": [evidence_id],
                    "scope_predicate": {"project_ids": ["milai"]},
                    "requested_authority": "ACTION_SAFE",
                    "derivation_policy_id": "dg10-public-dev-fixture-v1",
                    "derivation_snapshot": {
                        "fixture": "public-deidentified-dev",
                        "selection": "question-only-lexical-top-1-512-token-fit",
                        "memory_sha256": _sha256_bytes(memory.encode()),
                    },
                },
            ),
            201,
            "three_arm_benchmark_proposal",
        )
        reviewed = e2e._review(
            client,
            tokens["reviewer"],
            str(proposal["proposal_id"]),
            f"{key}-review",
            "PUBLIC_DEIDENTIFIED_DEV_FIXTURE_ADAPTER",
        )
        if worker.run_once() <= 0:
            raise ThreeArmDevError("benchmark fixture projection did not run")
        recall = e2e._body(
            client.post(
                "/v1/memory/query",
                headers=e2e._headers(tokens["reader"]),
                json={
                    "route": "L1",
                    "query": marker,
                    "requested_scope": {"project_ids": ["milai"]},
                    "required_authority": "ACTION_SAFE",
                    "consistency": "CANONICAL_REQUIRED",
                    "limit": 3,
                },
            ),
            200,
            "three_arm_benchmark_recall_preflight",
        )
        results = recall.get("results")
        if (
            recall.get("abstained") is not False
            or not isinstance(results, list)
            or len(results) != 1
            or not isinstance(results[0], Mapping)
            or results[0].get("payload", {}).get("case_marker") != marker
        ):
            raise ThreeArmDevError("benchmark fixture preflight recall failed")
        fixtures[case.case_id] = Fixture(
            marker=marker,
            memory=memory,
            memory_tokens=memory_tokens,
            evidence_ids=source_evidence_ids,
            fixture_ids_sha256={
                "evidence_id": _sha256_bytes(evidence_id.encode()),
                "proposal_id": _sha256_bytes(str(proposal["proposal_id"]).encode()),
                "claim_id": _sha256_bytes(str(reviewed["claim_id"]).encode()),
                "claim_version_id": _sha256_bytes(
                    str(reviewed["claim_version_id"]).encode()
                ),
            },
            preflight_recall=recall,
        )
    return fixtures


def _quality_delta(aggregates: Mapping[str, Any]) -> dict[str, Any]:
    prefix = "LONGMEMEVAL_CLEANED_500/"
    values = {arm: aggregates[prefix + arm] for arm in ARMS}
    strongest = max(
        ("NO_MEMORY", "NAIVE_RAG"),
        key=lambda arm: (
            float(values[arm]["normalized_f1_mean"]),
            float(values[arm]["exact_match_mean"]),
        ),
    )
    return {
        "strongest_fixed_baseline": strongest,
        "milai_minus_strongest_baseline": {
            "exact_match_mean": round(
                float(values["MILAI_MCP"]["exact_match_mean"])
                - float(values[strongest]["exact_match_mean"]),
                6,
            ),
            "normalized_f1_mean": round(
                float(values["MILAI_MCP"]["normalized_f1_mean"])
                - float(values[strongest]["normalized_f1_mean"]),
                6,
            ),
        },
        "release_interpretation": "DEV_CALIBRATION_INPUT_ONLY_NOT_TEST_RESULT",
    }


def _run_real(
    *,
    cases: Sequence[dev_smoke.BenchmarkCase],
    direct_client: dev_smoke.CompletionClient,
    env_file: Path,
    run_id: str,
    failure_capture_directory: Path,
) -> tuple[list[ArmObservation], dict[str, Any]]:
    e2e._load_environment_file(env_file.resolve())
    source = e2e.load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise ThreeArmDevError("runtime database role URLs are absent")

    memories: dict[str, tuple[str, int, tuple[str, ...]]] = {}
    for case in cases:
        raw_memory, evidence_ids = dev_smoke._retrieve(case, k=1)
        memory, memory_tokens = dev_smoke._fit_memory(
            direct_client, case, raw_memory
        )
        memories[case.case_id] = (memory, memory_tokens, tuple(evidence_ids))

    infrastructure_run_id = uuid4().hex
    database_name = f"milai_smoke_{infrastructure_run_id[:20]}"
    database_urls = {
        "owner": e2e._database_url(owner_source, database_name),
        "api": e2e._database_url(source.database_dsn, database_name),
        "steward": e2e._database_url(source.steward_database_dsn, database_name),
        "worker": e2e._database_url(worker_source, database_name),
        "audit": e2e._database_url(audit_source, database_name),
    }
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in ("legacy", "causal", "reader", "submitter", "operator", "reviewer")
    }
    observations: list[ArmObservation] = []
    native_ids: set[str] = set()
    created = False
    model_cleanup: dict[str, Any] = {"status": "NOT_STARTED"}
    database_cleanup: dict[str, Any] = {"status": "NOT_CREATED"}
    identity: dict[str, Any] = {}
    security: dict[str, Any] = {}
    failure: Exception | None = None
    active_case_id = "NOT_STARTED"
    active_arm = "NOT_STARTED"
    try:
        e2e._create_database(owner_source, database_name)
        created = True
        with e2e._migration_url(database_urls["owner"]):
            command.upgrade(e2e._alembic_config(), "head")
        with tempfile.TemporaryDirectory(
            prefix="milai-dg10-three-arm-openworker-"
        ) as temporary, tempfile.TemporaryDirectory(
            prefix="milai-dg10-three-arm-blobs-"
        ) as blob_directory:
            workspace = Path(temporary)
            workspace.chmod(0o700)
            settings = e2e._smoke_settings(
                source,
                database_urls,
                Path(blob_directory),
                uuid4(),
                uuid4(),
                tokens,
                e2e._free_loopback_port(),
            ).model_copy(update={"data_mode": "DEIDENTIFIED_ALLOWED"})
            e2e.prepare_runtime_directories(settings)
            environment = e2e._api_environment(settings, database_urls, tokens)
            environment["MILAI_DATA_MODE"] = "DEIDENTIFIED_ALLOWED"
            api_process: subprocess.Popen[bytes] | None = None
            worker_database: Any = None
            harness: openworker_e2e.OpenWorkerHarness | None = None
            try:
                executable = Path(sys.executable).with_name("milai-api")
                api_process = subprocess.Popen(
                    [str(executable)],
                    cwd=ROOT / "runtime",
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                base_url = f"http://{settings.bind_host}:{settings.bind_port}"
                api_client = e2e._HttpClient(base_url)
                worker_database = e2e.Database(
                    settings,
                    dsn=database_urls["worker"],
                    expected_role="milai_worker",
                )
                worker = e2e.FoundationWorker(
                    settings,
                    worker_database,
                    repository=e2e.ProjectionRepository(worker_database),
                    blob_store=e2e.LocalContentAddressedBlobStore(
                        settings.blob_root,
                        kek=settings.blob_kek,
                        key_reference=settings.blob_key_reference,
                        allow_plaintext_read=True,
                    ),
                    embedding=e2e.DeterministicHashEmbedding(),
                    worker_id=f"dg10-three-arm-{infrastructure_run_id[:12]}",
                )
                e2e._wait_api(api_client, api_process)
                fixtures = _preload_fixtures(
                    cases=cases,
                    memories=memories,
                    client=api_client,
                    worker=worker,
                    tokens=tokens,
                    run_id=run_id,
                )
                harness = openworker_e2e.OpenWorkerHarness(
                    workspace, infrastructure_run_id
                )
                adapter_path, adapter_identity = _materialize_calibration_adapter(
                    workspace
                )
                frozen_adapter = openworker_e2e.ADAPTER
                openworker_e2e.ADAPTER = adapter_path
                try:
                    harness.start_model_plane()
                finally:
                    openworker_e2e.ADAPTER = frozen_adapter
                broker = mcp_smoke._start_benchmark_broker_and_worker(
                    harness, base_url, tokens["reader"]
                )
                security = mcp_smoke._nonmodel_security_scan(harness, base_url)
                identity = {
                    **dict(direct_client.identity_evidence),
                    "worker_image_id": openworker_e2e.WORKER_IMAGE_ID,
                    "gateway_image_id": openworker_e2e.GATEWAY_IMAGE_ID,
                    "postgres_image_id": openworker_e2e.POSTGRES_IMAGE_ID,
                    "broker_policy_sha256": broker["policy_sha256"],
                    "catalog_protocol": broker["catalog_protocol"],
                    "catalog_tools": broker["catalog_tools"],
                    "rendered_config_sha256": broker["rendered_config_sha256"],
                    "benchmark_adapter": adapter_identity,
                }
                for case_index, case in enumerate(cases, start=1):
                    active_case_id = case.case_id
                    memory, memory_tokens, evidence_ids = memories[case.case_id]
                    for arm_index, arm in enumerate(
                        adapter_contract._latin_square_order(case.case_id), start=1
                    ):
                        active_arm = arm
                        if arm == "MILAI_MCP":
                            observation = _mcp_observation(
                                case=case,
                                fixture=fixtures[case.case_id],
                                harness=harness,
                            )
                        else:
                            observation = _direct_observation(
                                case=case,
                                arm=arm,
                                run_id=run_id,
                                client=direct_client,
                                memory=memory,
                                memory_tokens=memory_tokens,
                                evidence_ids=evidence_ids,
                            )
                        for native in observation.native_calls:
                            native_id = str(native["native_request_id"])
                            if native_id in native_ids:
                                raise ThreeArmDevError(
                                    "duplicate native request ID across calibration"
                                )
                            native_ids.add(native_id)
                        observations.append(observation)
                        print(
                            json.dumps(
                                {
                                    "event": "DG10_THREE_ARM_PROGRESS",
                                    "case": case_index,
                                    "case_total": len(cases),
                                    "arm_position": arm_index,
                                    "arm": arm,
                                    "records": len(observations),
                                    "native_requests": len(native_ids),
                                },
                                sort_keys=True,
                            ),
                            flush=True,
                        )
                openworker_e2e.vllm_local_ab._live_check(harness.binding)
                current_restart = json.loads(
                    openworker_e2e._run(
                        [
                            "docker",
                            "container",
                            "inspect",
                            str(harness.binding["container"]["id"]),
                        ]
                    ).stdout
                )[0]["RestartCount"]
                if current_restart != harness.initial_vllm_restart_count:
                    raise ThreeArmDevError("vLLM lifecycle drift during calibration")
            except Exception as exc:
                failure = exc
            finally:
                if harness is not None:
                    model_cleanup = harness.close()
                if api_process is not None:
                    e2e._stop_api(api_process)
                if worker_database is not None:
                    worker_database.close()
    finally:
        if created:
            database_cleanup = e2e._drop_database(owner_source, database_name)
    cleanup = {
        "model_and_worker_plane": model_cleanup,
        "runtime_database": database_cleanup,
    }
    if failure is not None:
        failure_evidence: dict[str, Any] = {}
        if isinstance(failure, AgentTraceError):
            raw_failure = dev_smoke._encoded_json(
                {
                    "schema": "milai.dg10.benchmark-three-arm-agent-failure-raw.v1",
                    "run_id": run_id,
                    "created_at": datetime.now(UTC).isoformat(),
                    "data_classification": "PUBLIC_BENCHMARK_DEV_RAW_AGENT_TRACE",
                    "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
                    "active_case_id": active_case_id,
                    "active_arm": active_arm,
                    "opencode_events": [
                        json.loads(line) for line in failure.raw_events.splitlines()
                    ],
                }
            )
            failure_path = failure_capture_directory / f"{run_id}.failure.raw.json"
            dev_smoke._write_new(failure_path, raw_failure)
            failure_evidence = {
                "status": "WRITTEN_HASH_BOUND",
                "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
                "sha256": _sha256_bytes(raw_failure),
                "size": len(raw_failure),
                "mode": "0600",
                "active_case_id_sha256": _sha256_bytes(active_case_id.encode()),
                "active_arm": active_arm,
            }
        raise ThreeArmRuntimeError(
            "three-arm shared calibration runtime failed; "
            f"completed_records={len(observations)}; "
            f"cause={type(failure).__name__}:{failure}",
            failure_evidence,
        ) from failure
    if (
        model_cleanup.get("broker_log_secret_scan") != "PASS"
        or database_cleanup.get("status") != "PASS"
    ):
        raise ThreeArmDevError("three-arm runtime cleanup or secret scan failed")
    expected_native = len(cases) * 4
    if len(observations) != len(cases) * 3 or len(native_ids) != expected_native:
        raise ThreeArmDevError("three-arm record or native-request denominator failed")
    return observations, {
        "identity": identity,
        "security": security,
        "cleanup": cleanup,
        "unique_native_request_ids": len(native_ids),
    }


def run_three_arm_dev(
    *,
    adapter_report_path: Path,
    calibration_plan_path: Path,
    longmemeval_root: Path,
    direct_client: dev_smoke.CompletionClient,
    env_file: Path,
    failure_capture_directory: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    adapter, calibration = dev_smoke._load_contracts(
        adapter_report_path.resolve(), calibration_plan_path.resolve()
    )
    if adapter.get("candidate") != "candidate.4":
        raise ThreeArmDevError("frozen adapter contract candidate drift")
    cases, dataset_evidence = dev_smoke._load_longmemeval_cases(
        longmemeval_root.resolve(), calibration, CASE_LIMIT
    )
    run_id = f"dg10-three-arm-dev-{DATE}-{uuid4().hex[:12]}"
    observations, runtime = _run_real(
        cases=cases,
        direct_client=direct_client,
        env_file=env_file,
        run_id=run_id,
        failure_capture_directory=failure_capture_directory,
    )
    case_by_id = {case.case_id: case for case in cases}
    records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    for observation in observations:
        record, raw_record = _record(
            case_by_id[observation.case_id], observation, run_id
        )
        records.append(record)
        raw_records.append(raw_record)
    expected_order = [
        (case.case_id, arm)
        for case in cases
        for arm in adapter_contract._latin_square_order(case.case_id)
    ]
    actual_order = [(record["case_id"], record["arm"]) for record in records]
    if actual_order != expected_order:
        raise ThreeArmDevError("executed order differs from frozen Latin-square schedule")
    aggregates = dev_smoke._aggregates(records)
    ended = datetime.now(UTC)
    report = {
        "schema": "milai.dg10.benchmark-three-arm-dev.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": "THREE_ARM_LONGMEMEVAL_DEV_CALIBRATION_COMPLETE",
        "quality_outcome": "DEV_CALIBRATION_INPUT_ONLY",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "data_boundary": "PUBLIC_DEV_LABELS_OPENED_RAW_CONTENT_REPO_EXTERNAL_HASHED_ONLY",
        "calibration_dev_labels_opened": True,
        "test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": len(cases) * 4,
        "local_tokenizer_requests": direct_client.tokenizer_requests + len(cases) * 2,
        "logical_arm_records": len(records),
        "unique_native_request_ids": runtime["unique_native_request_ids"],
        "hidden_or_extra_model_calls": 0,
        "model_id": MODEL_ID,
        "identity": runtime["identity"],
        "inputs": {
            "adapter_report_sha256": _sha256_file(adapter_report_path.resolve()),
            "adapter_contract_canonical_sha256": _json_sha256(adapter),
            "calibration_plan_sha256": _sha256_file(
                calibration_plan_path.resolve()
            ),
            "dataset": dataset_evidence,
        },
        "execution": {
            "selected_dev_case_count": len(cases),
            "selected_dev_case_ids": [case.case_id for case in cases],
            "selected_dev_case_ids_sha256": _json_sha256(
                [case.case_id for case in cases]
            ),
            "arms_executed": list(ARMS),
            "logical_records": len(records),
            "native_model_requests_per_case": 4,
            "native_model_requests": len(cases) * 4,
            "mcp_calls": len(cases),
            "records_per_case": 3,
            "actual_execution_order_sha256": _json_sha256(actual_order),
            "expected_execution_order_sha256": _json_sha256(expected_order),
            "latin_square_dev_schedule_sha256": calibration["schedule"][
                "dev_case_arm_schedule_sha256"
            ],
            "generation_contract_sha256": adapter[
                "generation_contract_sha256"
            ],
            "prompt_templates_sha256": adapter["prompt_templates_sha256"],
            "retrieval_k": 1,
            "memory_context_tokens_max": dev_smoke.MAX_MEMORY_CONTEXT_TOKENS,
            "aggregate_input_token_ceiling_per_case_arm": AGGREGATE_INPUT_TOKEN_CEILING,
            "output_token_ceiling_per_native_call": MAX_OUTPUT_TOKENS,
            "shared_fresh_runtime": True,
            "model_execution_interleaved_by_frozen_schedule": True,
        },
        "records": records,
        "aggregates": aggregates,
        "quality_delta": _quality_delta(aggregates),
        "security": runtime["security"],
        "cleanup": runtime["cleanup"],
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "BMG-02": "DEV_THREE_ARM_CALIBRATION_COMPLETE_TEST_NOT_RUN",
            "BMG-05": "NO_GO_THRESHOLDS_NOT_YET_HASH_FROZEN",
            "three_arm_denominator": "PASS_50_CASES_150_LOGICAL_200_NATIVE",
            "frozen_latin_square_execution": "PASS",
            "same_vllm_identity": "PASS",
            "hidden_or_extra_model_calls": "PASS_ZERO",
            "test_boundary": "PASS_CLOSED",
        },
        "known_limits": [
            "This is the frozen 50-case LongMemEval dev/calibration split, not test.",
            "EM/F1 is the frozen local deterministic scorer, not the official external-judge leaderboard protocol.",
            "Fixture selection is question-only lexical top-1 and shared by NAIVE_RAG and MILAI_MCP.",
            "Tier 2 blinded human audit and Tier 3 same-vLLM judge characterization are separate and not included here.",
            "BMG-02 and BMG-05 remain unaccepted until a pre-test quality contract decision and any authorized test run.",
        ],
    }
    sidecar = {
        "schema": "milai.dg10.benchmark-three-arm-dev-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "PUBLIC_BENCHMARK_DEV_RAW_PROMPT_MEMORY_LABEL_RUNTIME_TRACE_AND_MODEL_OUTPUT",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "records": raw_records,
    }
    return report, sidecar


def _partial_report(
    *,
    error: Exception,
    adapter_report: Path,
    calibration_plan: Path,
) -> dict[str, Any]:
    return {
        "schema": "milai.dg10.benchmark-three-arm-dev.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": "FAIL_PARTIAL_THREE_ARM_DEV_NOT_CALIBRATION",
        "quality_outcome": "NOT_EVALUABLE",
        "calibration_dev_labels_opened": True,
        "test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "failure": {
            "type": type(error).__name__,
            "reason_sha256": _sha256_bytes(str(error).encode()),
            "repo_external_raw_trace": (
                error.failure_evidence
                if isinstance(error, ThreeArmRuntimeError)
                else {"status": "NOT_AVAILABLE"}
            ),
        },
        "inputs": {
            "adapter_report_sha256": _sha256_file(adapter_report.resolve()),
            "calibration_plan_sha256": _sha256_file(calibration_plan.resolve()),
        },
        "repo_external_sidecar": {"status": "NOT_WRITTEN_FOR_PARTIAL_FAILURE"},
        "gate_results": {
            "BMG-02": "NO_GO_PARTIAL_FAILURE",
            "BMG-05": "NO_GO_THRESHOLDS_NOT_FROZEN",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run frozen 50-case LongMemEval three-arm dev calibration"
    )
    parser.add_argument("--execute-local-vllm", action="store_true")
    parser.add_argument("--execute-fresh-runtime-openworker-mcp", action="store_true")
    parser.add_argument("--data-boundary-ack")
    parser.add_argument("--adapter-report", type=Path, default=DEFAULT_ADAPTER_REPORT)
    parser.add_argument(
        "--calibration-plan", type=Path, default=DEFAULT_CALIBRATION_PLAN
    )
    parser.add_argument(
        "--longmemeval-root", type=Path, default=DEFAULT_LONGMEMEVAL_ROOT
    )
    parser.add_argument("--identity-report", type=Path, default=DEFAULT_IDENTITY_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if (
        not args.execute_local_vllm
        or not args.execute_fresh_runtime_openworker_mcp
        or args.data_boundary_ack != DATA_BOUNDARY_ACK
    ):
        raise ThreeArmDevError(
            "real calibration requires both execution flags and exact data-boundary ack"
        )
    capture_directory = dev_smoke._validate_capture_directory(
        args.capture_directory
    )
    direct_client = dev_smoke.LocalVllmClient(
        args.base_url, args.identity_report, args.timeout
    )
    try:
        report, sidecar = run_three_arm_dev(
            adapter_report_path=args.adapter_report,
            calibration_plan_path=args.calibration_plan,
            longmemeval_root=args.longmemeval_root,
            direct_client=direct_client,
            env_file=args.env_file,
            failure_capture_directory=capture_directory,
        )
    except Exception as exc:
        partial = _partial_report(
            error=exc,
            adapter_report=args.adapter_report,
            calibration_plan=args.calibration_plan,
        )
        dev_smoke._write_new(args.output.resolve(), dev_smoke._encoded_json(partial))
        raise
    sidecar_raw = dev_smoke._encoded_json(sidecar)
    sidecar_path = capture_directory / f"{report['run_id']}.raw.json"
    dev_smoke._write_new(sidecar_path, sidecar_raw)
    report["repo_external_sidecar"] = {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": _sha256_bytes(sidecar_raw),
        "size": len(sidecar_raw),
        "mode": "0600",
    }
    report_raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), report_raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": _sha256_bytes(report_raw),
                "sidecar": str(sidecar_path),
                "sidecar_sha256": _sha256_bytes(sidecar_raw),
                "status": report["status"],
                "logical_arm_records": report["logical_arm_records"],
                "local_vllm_requests": report["local_vllm_requests"],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
