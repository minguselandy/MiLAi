"""Pre-freeze resource and native-method gate for BEAM 128K."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from evals.paper.contracts import read_context_archive
from evals.paper.datasets.extended import (
    ExtendedCase,
    ExtendedSession,
    load_beam_inputs,
)
from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[2]
FORMAL_INPUTS = ROOT / "var/dg11/paper/freeze/beam-128k-inputs.json"
SMOKE_INPUTS = ROOT / "var/dg11/paper/runs/pe07-beam-smoke-20260824-001/inputs.json"
DG11_SMOKE = ROOT / "var/dg11/paper/runs/pe07-beam-smoke-20260824-001/dg11-contexts.json"
DEFAULT_OUTPUT = (
    ROOT / "var/dg11/paper/runs/pe07-beam-smoke-20260824-001/resource-estimate-002.json"
)
LIGHT_SOURCE = Path(
    "/cra/memory/mx_memory/benchmarks/BEAM/src/answer_probing_questions/light.py"
)
NATIVE_SOURCE = Path(
    "/cra/memory/mx_memory/benchmarks/BEAM/"
    "src/answer_probing_questions/long_term_memory_methods.py"
)
MAX_GENERATIVE_PROVIDER_CALLS_PER_METHOD = 3_000
MAX_DG11_EMBEDDING_CALLS = 1_000_000


class PE07ResourceError(RuntimeError):
    pass


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise PE07ResourceError("PE07 resource estimate is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _histories(cases: tuple[ExtendedCase, ...]) -> tuple[tuple[ExtendedSession, ...], ...]:
    unique: dict[tuple[str, ...], tuple[ExtendedSession, ...]] = {}
    for case in cases:
        key = tuple(session.session_id for session in case.sessions)
        existing = unique.setdefault(key, case.sessions)
        if existing != case.sessions:
            raise PE07ResourceError("BEAM shared history content drifted")
    return tuple(unique.values())


def _stats(cases: tuple[ExtendedCase, ...]) -> dict[str, int]:
    histories = _histories(cases)
    sessions = [session for history in histories for session in history]
    turns = [turn for session in sessions for turn in session.turns]
    return {
        "case_count": len(cases),
        "history_count": len(histories),
        "official_light_pair_count": sum(
            math.ceil(len(session.turns) / 2) for session in sessions
        ),
        "session_count": len(sessions),
        "source_payload_bytes": sum(len(turn.content.encode()) for turn in turns),
        "turn_count": len(turns),
    }


def run(output: Path) -> dict[str, Any]:
    formal_partition, formal_cases = load_beam_inputs(FORMAL_INPUTS)
    smoke_partition, smoke_cases = load_beam_inputs(SMOKE_INPUTS)
    formal = _stats(formal_cases)
    smoke = _stats(smoke_cases)
    envelope = json.loads(DG11_SMOKE.read_text(encoding="utf-8"))
    records = read_context_archive(DG11_SMOKE)
    if (
        formal_partition != "BEAM-128K-FULL"
        or formal["case_count"] != 400
        or formal["history_count"] != 20
        or "SMOKE" not in smoke_partition
        or not isinstance(envelope, dict)
        or envelope.get("status") != "PASS"
        or envelope.get("paper_labels_opened") is not False
        or envelope.get("labels_accessed") is not False
        or len(records) != smoke["case_count"]
    ):
        raise PE07ResourceError("PE07 input or DG11 smoke gate failed")
    smoke_embeddings = sum(
        int(stat.get("total_embedding_calls", 0))
        for stat in envelope.get("cohort_stats", [])
        if isinstance(stat, dict)
    )
    if smoke_embeddings <= 0:
        raise PE07ResourceError("PE07 DG11 embedding accounting is absent")
    scale = max(
        formal["turn_count"] / smoke["turn_count"],
        formal["source_payload_bytes"] / smoke["source_payload_bytes"],
    )
    estimated_dg11_embeddings = math.ceil(smoke_embeddings * scale * 2)
    light_minimum = formal["official_light_pair_count"] * 2 + formal["case_count"]
    gates = {
        "dg11_embedding_call_ceiling": (
            estimated_dg11_embeddings <= MAX_DG11_EMBEDDING_CALLS
        ),
        "light_provider_call_ceiling": (
            light_minimum <= MAX_GENERATIVE_PROVIDER_CALLS_PER_METHOD
        ),
    }
    result: dict[str, Any] = {
        "candidate_resource_estimate": {
            "estimated_embedding_calls_with_2x_safety_factor": estimated_dg11_embeddings,
            "isolated_runtime_database_count": formal["history_count"],
            "question_count": formal["case_count"],
            "shared_history_reuse": "ONE_DATABASE_PER_HISTORY_FOR_TWENTY_QUESTIONS",
            "smoke_embedding_calls": smoke_embeddings,
            "synthetic_to_formal_scale_factor": round(scale, 6),
        },
        "development_ai_reviews": 0,
        "gate_results": gates,
        "formal": formal,
        "formal_input_sha256": sha256_file(FORMAL_INPUTS),
        "maximum_concurrent_requests": 2,
        "native_methods": {
            "LIGHT": {
                "decision": "EXCLUDE_PRE_FREEZE_RESOURCE_CEILING",
                "minimum_generative_calls": light_minimum,
                "minimum_excludes": [
                    "iterative_scratchpad_summarization",
                    "per_question_semantic_scratchpad_filtering",
                ],
                "official_internal_workers": 25,
                "paper_worker_ceiling": 2,
                "reason": "MINIMUM_PROVIDER_CALLS_EXCEED_FIXED_METHOD_CEILING",
            },
            "OFFICIAL_DENSE_RAG": {
                "answer_calls": formal["case_count"],
                "decision": "INCLUDE_IF_ADAPTER_SMOKE_PASSES",
                "generative_memory_build_calls": 0,
            },
            "OFFICIAL_LONG_CONTEXT": {
                "decision": "NATIVE_EXACT_EXCLUDED_LOCAL_CONTEXT_LIMIT",
                "local_model_context_tokens": 65_536,
                "published_scale_label": "128K",
                "truncated_characterization_method": "CTRL-TRUNC-FULL",
            },
        },
        "paper_labels_opened": False,
        "provider_call_ceiling_per_method": MAX_GENERATIVE_PROVIDER_CALLS_PER_METHOD,
        "dg11_embedding_call_ceiling": MAX_DG11_EMBEDDING_CALLS,
        "schema": "milai.dg11.pe07-resource-estimate.v1",
        "smoke": smoke,
        "smoke_dg11_sha256": sha256_file(DG11_SMOKE),
        "smoke_input_sha256": sha256_file(SMOKE_INPUTS),
        "status": (
            "PASS_WITH_LIGHT_EXCLUDED"
            if gates["dg11_embedding_call_ceiling"]
            and not gates["light_provider_call_ceiling"]
            else "RESOURCE_GATE_FAIL"
        ),
        "source_bindings": {
            "light_sha256": sha256_file(LIGHT_SOURCE),
            "native_memory_methods_sha256": sha256_file(NATIVE_SOURCE),
        },
        "work_package": "DG11-PE07",
    }
    _atomic_json_once(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(json.dumps({"status": result["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
