"""Validate the label-free PE05 Memora all-method smoke and frozen inputs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.contracts import read_context_archive
from evals.paper.datasets.memora import load_inputs
from evals.paper.identity import sha256_file
from evals.paper.usage_ledger import UsageLedger

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "var/dg11/paper/runs/pe05-memora-smoke-20260824-001"
SMOKE_INPUTS = RUN / "inputs.json"
CONTROLLED_CONTEXTS = RUN / "controlled-contexts.json"
DG11_CONTEXTS = RUN / "dg11-contexts.json"
EXTERNAL_CONTEXTS = {
    "MEM0-OSS": RUN / "mem0-contexts-002.json",
    "HINDSIGHT-OSS": RUN / "hindsight-contexts-005.json",
    "GRAPHITI-OSS": RUN / "graphiti-contexts-003.json",
    "REME-OSS": RUN / "reme-contexts-002.json",
}
RAW_GENERATIONS = RUN / "answers-all/raw-generations.json"
USAGE_LEDGER = RUN / "answers-all/usage-ledger.jsonl"
ALL_METHOD_GENERATIONS = RUN / "answers-all-methods-001/raw-generations.json"
ALL_METHOD_LEDGER = RUN / "answers-all-methods-001/usage-ledger.jsonl"
METHOD_CONFIG = ROOT / "var/dg11/paper/method-configs/memora.json"
FORMAL_INPUTS = ROOT / "var/dg11/paper/freeze/memora-inputs.json"
DEFAULT_OUTPUT = RUN / "result-002.json"
CANDIDATE_MANIFEST = ROOT / "var/dg11/freeze/candidate/candidate-manifest.json"
CANDIDATE_INVENTORY = ROOT / "var/dg11/final/candidate/inventory.json"
EXPECTED = {
    "all_method_generations": (
        "e310d800cfb8d28819ed876e580ca94ba24a8c58d541810aab0a3a5ee5b3c12c"
    ),
    "all_method_ledger": (
        "4ff8614e403302fcfb858094f7b67eef5123eaecd5cb7391281b58644f218194"
    ),
    "candidate_inventory": (
        "b754b9cfed729192b02c9493c5cb3ff93a7961c72f440e5ddb358ef7785055bb"
    ),
    "candidate_manifest": (
        "9812af51eeafac55e9ab250d37d6d4fe8217b73428b4543af74bbb7ad00cef5d"
    ),
    "controlled_contexts": (
        "44685b31be6cff9e7fcbe16aae285bcff263f2b1e3f4e3e0741ea7e17b9d9550"
    ),
    "dg11_contexts": (
        "a0d70285e059915b3197becfd334ff63c2708639bb6a301d8c4bb33b15be4640"
    ),
    "formal_inputs": (
        "ee92ab7dc378a3759e624732232abcf3ab5ec5bda6f30fa330d59c4f5d63da80"
    ),
    "graphiti_contexts": (
        "e92c378e04d61ceda19b7a3b7f436b6a8ecb29e82e926cbfb449680185ee24fe"
    ),
    "hindsight_contexts": (
        "432aad985bb4b77b612c302c299fda379f11425de69e8688300b746b54455537"
    ),
    "mem0_contexts": (
        "28282ee4aa45ad5265f776c188c91b2fba3335af1136c1a89aa8ef174fa1b9a4"
    ),
    "method_config": (
        "0bda5a97d09a0302aeda9d104163efc1d733ddbb6e2fb7ced7fd661df85c387b"
    ),
    "raw_generations": (
        "f50e70f63e603af81b1dfa214899b3d16b286e9847374f0e8c68b0f49feddfed"
    ),
    "smoke_inputs": (
        "fcc9bc17f995d6ce4127686eb9fd615ab81f1764db41817d398c41096682cea9"
    ),
    "reme_contexts": (
        "091e6684a2ce0b03870ab435888f79989135d8e805843d77d7ce96246cb25cad"
    ),
    "usage_ledger": (
        "6405a365874dd33e4ef23e2bd931771e5eb3ac986bc97ced2bced7509c2307ad"
    ),
}
EXPECTED_CANDIDATE_ID = (
    "712577d17403951bdb6b7f6c7b6a2763b4b964427df33a857b02a316fbe74d51"
)
CORE_METHODS = ("CTRL-NONE", "LME-BM25-S", "DG11-FULL")
ALL_METHODS = (*CORE_METHODS, *EXTERNAL_CONTEXTS)


class PE05FinalizeError(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PE05FinalizeError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise PE05FinalizeError(f"expected JSON object: {path}")
    return value


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise PE05FinalizeError("PE05 smoke result is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _verify_hashes() -> dict[str, str]:
    paths = {
        "candidate_inventory": CANDIDATE_INVENTORY,
        "candidate_manifest": CANDIDATE_MANIFEST,
        "controlled_contexts": CONTROLLED_CONTEXTS,
        "dg11_contexts": DG11_CONTEXTS,
        "formal_inputs": FORMAL_INPUTS,
        "graphiti_contexts": EXTERNAL_CONTEXTS["GRAPHITI-OSS"],
        "hindsight_contexts": EXTERNAL_CONTEXTS["HINDSIGHT-OSS"],
        "mem0_contexts": EXTERNAL_CONTEXTS["MEM0-OSS"],
        "method_config": METHOD_CONFIG,
        "raw_generations": RAW_GENERATIONS,
        "reme_contexts": EXTERNAL_CONTEXTS["REME-OSS"],
        "smoke_inputs": SMOKE_INPUTS,
        "usage_ledger": USAGE_LEDGER,
        "all_method_generations": ALL_METHOD_GENERATIONS,
        "all_method_ledger": ALL_METHOD_LEDGER,
    }
    observed = {key: sha256_file(path) for key, path in paths.items()}
    if observed != EXPECTED:
        raise PE05FinalizeError("PE05 frozen artifact hash drifted")
    return observed


def _verify_formal_inputs() -> dict[str, Any]:
    cohorts, cases = load_inputs(FORMAL_INPUTS)
    sessions = sum(len(cohort.sessions) for cohort in cohorts)
    turns = sum(len(session.turns) for cohort in cohorts for session in cohort.sessions)
    if (
        len(cohorts) != 3
        or len(cases) != 60
        or sessions != 2743
        or turns != 42860
        or {case.task for case in cases} != {"Remembering", "Reasoning", "Recommending"}
    ):
        raise PE05FinalizeError("Memora formal input denominator drifted")
    return {
        "case_count": len(cases),
        "cohort_count": len(cohorts),
        "paper_labels_opened": False,
        "session_count": sessions,
        "turn_count": turns,
    }


def _verify_contexts() -> dict[str, Any]:
    controlled_envelope = _object(CONTROLLED_CONTEXTS)
    dg11_envelope = _object(DG11_CONTEXTS)
    controlled = read_context_archive(CONTROLLED_CONTEXTS)
    dg11 = read_context_archive(DG11_CONTEXTS)
    if (
        controlled_envelope.get("paper_labels_opened") is not False
        or controlled_envelope.get("labels_accessed") is not False
        or len(controlled) != 4
        or dg11_envelope.get("status") != "PASS"
        or dg11_envelope.get("failure_count") != 0
        or dg11_envelope.get("paper_labels_opened") is not False
        or dg11_envelope.get("labels_accessed") is not False
        or len(dg11) != 2
    ):
        raise PE05FinalizeError("PE05 context archive envelope drifted")
    combined = (*controlled, *dg11)
    expected = {
        (case, method)
        for case in ("synthetic-kayak", "synthetic-bicycle")
        for method in CORE_METHODS
    }
    if {(record.case_id, record.method_id) for record in combined} != expected:
        raise PE05FinalizeError("PE05 context denominator drifted")
    targets = {
        "synthetic-bicycle": "synthetic-session-bicycle",
        "synthetic-kayak": "synthetic-session-kayak",
    }
    for record in combined:
        if record.terminal_status != "SUCCEEDED" or record.declared_tokens > 512:
            raise PE05FinalizeError("PE05 context terminal drifted")
        if record.method_id == "CTRL-NONE":
            if record.context or record.source_ids or record.declared_tokens != 0:
                raise PE05FinalizeError("PE05 no-memory context drifted")
        elif not record.source_ids or record.source_ids[0] != targets[record.case_id]:
            raise PE05FinalizeError("PE05 target session was not ranked first")
    stats = dg11_envelope.get("cohort_stats")
    if (
        not isinstance(stats, list)
        or len(stats) != 1
        or stats[0].get("session_count") != 3
        or stats[0].get("question_count") != 2
        or stats[0].get("governed_claim_count") != 3
        or stats[0].get("api_query_embedding_calls") != 2
    ):
        raise PE05FinalizeError("PE05 cohort reuse accounting drifted")
    return {
        "cohort_index_builds": 1,
        "context_records": len(combined),
        "dg11_context_tokens_max": max(record.declared_tokens for record in dg11),
        "questions_reusing_index": 2,
        "target_rank_one": 4,
    }


def _verify_answers() -> dict[str, Any]:
    raw = _object(RAW_GENERATIONS)
    records = raw.get("raw_records")
    if (
        raw.get("schema") != "milai.dg11.paper-memora-generations.v1"
        or raw.get("status") != "PASS"
        or raw.get("case_count") != 2
        or raw.get("record_count") != 6
        or raw.get("expected_answer_calls") != 6
        or raw.get("methods") != list(CORE_METHODS)
        or raw.get("workers") != 2
        or raw.get("paper_labels_opened") is not False
        or not isinstance(records, list)
        or len(records) != 6
    ):
        raise PE05FinalizeError("PE05 answer envelope drifted")
    request_ids = {str(record.get("native_request_id")) for record in records}
    if len(request_ids) != 6 or any(
        not value.startswith("chatcmpl-") for value in request_ids
    ):
        raise PE05FinalizeError("PE05 native request identity drifted")
    for record in records:
        if not isinstance(record, dict):
            raise PE05FinalizeError("PE05 answer record is invalid")
        answer = str(record.get("answer"))
        method = record.get("method_id")
        case = record.get("case_id")
        if method == "CTRL-NONE" and answer != "UNKNOWN":
            raise PE05FinalizeError("PE05 no-memory answer drifted")
        expected_word = "kayak" if case == "synthetic-kayak" else "bicycle"
        if method != "CTRL-NONE" and expected_word not in answer.casefold():
            raise PE05FinalizeError("PE05 memory answer lost synthetic target")
        memory_tokens = record.get("memory_tokens")
        if (
            isinstance(memory_tokens, bool)
            or not isinstance(memory_tokens, int)
            or not 0 <= memory_tokens <= 512
        ):
            raise PE05FinalizeError("PE05 answer memory accounting drifted")
    verification = UsageLedger(USAGE_LEDGER).verify()
    if len(verification.events) != 18 or verification.root_sha256 != raw.get(
        "ledger_root_sha256"
    ):
        raise PE05FinalizeError("PE05 usage ledger drifted")
    return {
        "answer_calls": 6,
        "ledger_event_count": len(verification.events),
        "ledger_root_sha256": verification.root_sha256,
        "native_request_ids_unique": True,
        "workers": 2,
    }


def _verify_external_contexts() -> dict[str, Any]:
    targets = {
        "synthetic-bicycle": "synthetic-session-bicycle",
        "synthetic-kayak": "synthetic-session-kayak",
    }
    expected_workers = {
        "GRAPHITI-OSS": 2,
        "HINDSIGHT-OSS": 1,
        "MEM0-OSS": 1,
        "REME-OSS": 2,
    }
    token_maxima: dict[str, int] = {}
    for method, path in EXTERNAL_CONTEXTS.items():
        envelope = _object(path)
        records = read_context_archive(path)
        stats = envelope.get("cohort_stats")
        if (
            envelope.get("status") != "PASS"
            or envelope.get("failure_count") != 0
            or envelope.get("labels_accessed") is not False
            or envelope.get("paper_labels_opened") is not False
            or envelope.get("worker_count") != expected_workers[method]
            or len(records) != 2
            or not isinstance(stats, list)
            or len(stats) != 1
            or stats[0].get("session_count") != 3
            or stats[0].get("question_count") != 2
        ):
            raise PE05FinalizeError(f"PE05 {method} context envelope drifted")
        for record in records:
            if (
                record.method_id != method
                or record.terminal_status != "SUCCEEDED"
                or record.declared_tokens > 512
                or not record.source_ids
                or record.source_ids[0] != targets[record.case_id]
            ):
                raise PE05FinalizeError(
                    f"PE05 {method} target or token contract drifted"
                )
        token_maxima[method] = max(record.declared_tokens for record in records)
    mem0 = _object(EXTERNAL_CONTEXTS["MEM0-OSS"])
    graphiti = _object(EXTERNAL_CONTEXTS["GRAPHITI-OSS"])
    reme = _object(EXTERNAL_CONTEXTS["REME-OSS"])
    if (
        mem0.get("workspace_removed") is not True
        or (mem0.get("telemetry") or {}).get("disabled") is not True
        or (graphiti.get("telemetry") or {}).get("disabled") is not True
        or reme.get("workspace_removed") is not True
        or reme["cohort_stats"][0].get("server_shutdown")
        != "GRACEFUL_UVICORN_SIGTERM"
    ):
        raise PE05FinalizeError("PE05 external cleanup or telemetry gate drifted")
    return {
        "context_records": len(EXTERNAL_CONTEXTS) * 2,
        "methods": list(EXTERNAL_CONTEXTS),
        "target_rank_one": len(EXTERNAL_CONTEXTS) * 2,
        "token_maxima": token_maxima,
    }


def _verify_all_method_answers() -> dict[str, Any]:
    raw = _object(ALL_METHOD_GENERATIONS)
    records = raw.get("raw_records")
    if (
        raw.get("schema") != "milai.dg11.paper-memora-generations.v1"
        or raw.get("status") != "PASS"
        or raw.get("case_count") != 2
        or raw.get("record_count") != 14
        or raw.get("expected_answer_calls") != 14
        or raw.get("methods") != list(ALL_METHODS)
        or raw.get("workers") != 2
        or raw.get("paper_labels_opened") is not False
        or not isinstance(records, list)
        or len(records) != 14
    ):
        raise PE05FinalizeError("PE05 all-method answer envelope drifted")
    request_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise PE05FinalizeError("PE05 all-method answer record is invalid")
        request_id = str(record.get("native_request_id"))
        if not request_id.startswith("chatcmpl-"):
            raise PE05FinalizeError("PE05 all-method request identity drifted")
        request_ids.add(request_id)
        method = record.get("method_id")
        case = record.get("case_id")
        answer = str(record.get("answer"))
        expected_word = "kayak" if case == "synthetic-kayak" else "bicycle"
        if method == "CTRL-NONE":
            if answer != "UNKNOWN":
                raise PE05FinalizeError("PE05 all-method no-memory answer drifted")
        elif expected_word not in answer.casefold():
            raise PE05FinalizeError("PE05 all-method answer lost synthetic target")
        memory_tokens = record.get("memory_tokens")
        if (
            isinstance(memory_tokens, bool)
            or not isinstance(memory_tokens, int)
            or not 0 <= memory_tokens <= 512
        ):
            raise PE05FinalizeError("PE05 all-method memory accounting drifted")
    verification = UsageLedger(ALL_METHOD_LEDGER).verify()
    if (
        len(request_ids) != 14
        or len(verification.events) != 42
        or verification.root_sha256 != raw.get("ledger_root_sha256")
    ):
        raise PE05FinalizeError("PE05 all-method usage ledger drifted")
    return {
        "answer_calls": 14,
        "ledger_event_count": len(verification.events),
        "ledger_root_sha256": verification.root_sha256,
        "methods": list(ALL_METHODS),
        "native_request_ids_unique": True,
        "workers": 2,
    }


def _verify_method_config() -> dict[str, Any]:
    config = _object(METHOD_CONFIG)
    if (
        config.get("schema") != "milai.dg11.paper-memora-method-config.v1"
        or config.get("status") != "MEMORA_ALL_METHODS_READY_FOR_PAPER_FREEZE"
        or config.get("methods") != list(ALL_METHODS)
        or config.get("paper_labels_opened") is not False
    ):
        raise PE05FinalizeError("PE05 method configuration state drifted")
    bindings = config.get("source_bindings")
    external = config.get("external_native_methods")
    if not isinstance(bindings, dict) or not isinstance(external, dict):
        raise PE05FinalizeError("PE05 method source bindings are absent")
    if bindings.get("memora_runner_sha256") != sha256_file(
        ROOT / "evals/paper/runners/memora.py"
    ):
        raise PE05FinalizeError("PE05 common runner binding drifted")
    for method, artifact in EXTERNAL_CONTEXTS.items():
        entry = external.get(method)
        if not isinstance(entry, dict):
            raise PE05FinalizeError(f"PE05 {method} method entry is absent")
        runner = ROOT / str(entry.get("context_runner"))
        if (
            entry.get("status") != "MEMORA_ADAPTER_SMOKE_PASS"
            or entry.get("inclusion_decision") != "INCLUDE"
            or entry.get("context_runner_sha256") != sha256_file(runner)
            or entry.get("smoke_artifact") != str(artifact.relative_to(ROOT))
            or entry.get("smoke_artifact_sha256") != sha256_file(artifact)
        ):
            raise PE05FinalizeError(f"PE05 {method} method binding drifted")
    return {
        "all_method_count": len(ALL_METHODS),
        "external_native_method_count": len(EXTERNAL_CONTEXTS),
        "method_config_sha256": sha256_file(METHOD_CONFIG),
        "status": config["status"],
    }


def run(output: Path) -> dict[str, Any]:
    hashes = _verify_hashes()
    manifest = _object(CANDIDATE_MANIFEST)
    if manifest.get("candidate_id") != EXPECTED_CANDIDATE_ID:
        raise PE05FinalizeError("candidate identity drifted")
    result: dict[str, Any] = {
        "all_method_answer_smoke": _verify_all_method_answers(),
        "answer_smoke": _verify_answers(),
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "candidate_modified": False,
        "context_smoke": _verify_contexts(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_ai_reviews": 0,
        "external_native_context_smoke": _verify_external_contexts(),
        "formal_inputs": _verify_formal_inputs(),
        "hashes": hashes,
        "method_config": _verify_method_config(),
        "paper_labels_opened": False,
        "run_id": "pe05-memora-smoke-20260824-001",
        "schema": "milai.dg11.pe05-memora-all-method-smoke.v2",
        "status": "PASS",
        "work_package": "DG11-PE05",
    }
    _atomic_json_once(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(
        json.dumps(
            {
                "paper_labels_opened": result["paper_labels_opened"],
                "status": result["status"],
                "work_package": result["work_package"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
