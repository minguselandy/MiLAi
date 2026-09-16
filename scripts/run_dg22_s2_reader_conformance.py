from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evals.dg14.provider import (
    MatchedVllmProvider,
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.dg22.reader_conformance import (
    conformance_matrix,
    diagnosis_matrix,
    failure_record,
    materialize_cell,
    safe_success_record,
    score_conformance,
    successor_ceiling_authorized,
)
from evals.paper.provider import EXPECTED_PROMPT_CONTRACT_SHA256, MODEL_ID

from scripts.run_dg16_q6 import _process_identity, _reader_models

_QUARANTINED = "dg14-a89d7624-2048-b52bfba32dc8d0ebb7324a45"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg22-s2-reader-conformance-20260829-001")
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    args = parser.parse_args()
    output = _ROOT / "var/dg22/s2" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "plan.json"
    plan = {
        "schema": "milai.dg22.s2-plan.v0.2",
        "run_id": args.run_id,
        "phase_order": ["S2A_TYPED_DIAGNOSIS_8", "S2B_CONFORMANCE_32"],
        "maximum_reader_calls": 40,
        "one_call_per_identity": True,
        "automatic_retries": 0,
        "response_salvage": 0,
        "current_output_ceiling": 256,
        "successor_output_ceiling_max": 512,
        "successor_evidence_gate": [
            "finish_reason=length",
            "completion_tokens=256",
            "truncated_json_prefix=true",
        ],
        "quarantined_logical_request_id": _QUARANTINED,
        "quarantined_identity_reissue_authorized": False,
        "model_id": MODEL_ID,
        "prompt_contract_sha256": EXPECTED_PROMPT_CONTRACT_SHA256,
        "formal_holdout_consumed": False,
    }
    _write(plan_path, plan)
    identity_path = output / "reader-runtime-identity.json"
    _write(
        identity_path,
        {
            "schema": "milai.dg22.s2-reader-runtime-identity.v0.1",
            "models": _reader_models(args.reader_url),
            "process": _process_identity(7860),
        },
    )

    diagnosis = _run_cells(
        args.reader_url,
        args.run_id,
        diagnosis_matrix(),
        output_ceiling=256,
        progress_path=output / "s2a-progress.json",
    )
    s2a_path = output / "s2a-typed-diagnosis.json"
    _write(s2a_path, {"schema": "milai.dg22.s2a-diagnosis.v0.2", "records": diagnosis})
    selected_ceiling = 512 if successor_ceiling_authorized(diagnosis) else 256
    contract = full_provider_contract(max_output_tokens=selected_ceiling)
    contract_path = output / "selected-reader-contract.json"
    _write(
        contract_path,
        {
            "schema": "milai.dg22.reader-conformance-contract.v0.2",
            "contract": contract,
            "contract_sha256": full_provider_contract_sha256(
                max_output_tokens=selected_ceiling
            ),
            "selected_output_ceiling": selected_ceiling,
            "successor_authorized_by_s2a_evidence": selected_ceiling == 512,
            "applies_to_all_s2b_and_matched_arms": True,
        },
    )
    conformance = _run_cells(
        args.reader_url,
        args.run_id,
        conformance_matrix(),
        output_ceiling=selected_ceiling,
        progress_path=output / "s2b-progress.json",
    )
    s2b_path = output / "s2b-conformance-matrix.json"
    _write(
        s2b_path, {"schema": "milai.dg22.s2b-conformance.v0.2", "records": conformance}
    )
    score = score_conformance(
        diagnosis,
        conformance,
        selected_ceiling=selected_ceiling,
        quarantined_logical_request_id=_QUARANTINED,
    )
    score["run_id"] = args.run_id
    score["reader_contract_sha256"] = full_provider_contract_sha256(
        max_output_tokens=selected_ceiling
    )
    score_path = output / "score.json"
    _write(score_path, score)
    receipt = {
        "schema": "milai.dg22.s2-reader-conformance-receipt.v0.2",
        "run_id": args.run_id,
        "status": score["status"],
        "hard_gate": score["hard_gate"],
        "metrics": score["metrics"],
        "plan": _identity(plan_path),
        "reader_runtime_identity": _identity(identity_path),
        "typed_diagnosis": _identity(s2a_path),
        "selected_reader_contract": _identity(contract_path),
        "conformance_matrix": _identity(s2b_path),
        "score": _identity(score_path),
        "quarantined_identity_reissue_count": 0,
        "formal_holdout_consumed": False,
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "metrics": receipt["metrics"],
                "receipt": str(receipt_path.relative_to(_ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 2


def _run_cells(
    reader_url: str,
    base_run_id: str,
    cells: list[dict[str, Any]],
    *,
    output_ceiling: int,
    progress_path: Path,
) -> list[dict[str, Any]]:
    provider = MatchedVllmProvider(reader_url, max_output_tokens=output_ceiling)
    records = []
    contract_digest = full_provider_contract_sha256(max_output_tokens=output_ceiling)
    for cell in cells:
        question, question_as_of, context = materialize_cell(cell)
        cell_run_id = f"{base_run_id}-{cell['cell_id']}"
        try:
            result = provider.answer(
                run_id=cell_run_id,
                case_id=cell["cell_id"],
                method_id=f"READER_CONFORMANCE_{cell['phase']}",
                question=question,
                question_as_of=question_as_of,
                memory_context=context,
                token_budget=cell["token_budget"],
            )
            record = safe_success_record(result)
        except Exception as exc:
            failure = failure_record(exc)
            safe = failure["safe_metadata"]
            record = {
                "status": "FAILED",
                "logical_request_id": _logical_identity(cell_run_id, cell),
                "reader_call_count": 1,
                "identity_drift": False,
                **failure,
                "finish_reason": safe.get("finish_reason"),
                "completion_tokens": safe.get("completion_tokens"),
                "truncated_json_prefix": safe.get("truncated_json_prefix", False),
            }
        record.update(
            {
                "cell": cell,
                "model_id": MODEL_ID,
                "prompt_contract_sha256": EXPECTED_PROMPT_CONTRACT_SHA256,
                "reader_contract_sha256": contract_digest,
                "response_schema_sha256": hashlib.sha256(
                    json.dumps(
                        full_provider_contract(max_output_tokens=output_ceiling)[
                            "answer_schema"
                        ],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "output_ceiling": output_ceiling,
                "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                "input_context_sha256": hashlib.sha256(context.encode()).hexdigest(),
                "raw_question_context_or_response_persisted": False,
            }
        )
        records.append(record)
        _write(
            progress_path,
            {
                "schema": "milai.dg22.s2-reader-progress.v0.1",
                "record_count": len(records),
                "records": records,
            },
        )
    return records


def _logical_identity(run_id: str, cell: dict[str, Any]) -> str:
    from evals.dg14.provider import logical_request_id

    return logical_request_id(
        run_id,
        cell["cell_id"],
        f"READER_CONFORMANCE_{cell['phase']}",
        cell["token_budget"],
    )


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(_ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
