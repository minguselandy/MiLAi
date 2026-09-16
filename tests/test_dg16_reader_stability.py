from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.dg14.benchmark import load_opened_dev
from evals.dg16.reader_stability import (
    artifact_forensics,
    find_record,
    prompt_sha256,
    reconstruct_context,
)
from scripts.run_dg16_reader_stability import (
    CASE_ID,
    LME_RECEIPT,
    Q6_RECEIPT,
    TOKEN_BUDGET,
)


def _receipt(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("reader-stability receipt must be a JSON object")
    return value


def test_bound_receipts_reconstruct_exact_prompts_and_isolate_evidence_ids() -> None:
    _partition, cases = load_opened_dev()
    case = next(item for item in cases if item.case_id == CASE_ID)
    q6_record = find_record(
        _receipt(Q6_RECEIPT), case_id=CASE_ID, token_budget=TOKEN_BUDGET
    )
    lme_record = find_record(
        _receipt(LME_RECEIPT), case_id=CASE_ID, token_budget=TOKEN_BUDGET
    )

    q6_context = reconstruct_context(q6_record, case.history_events)
    lme_context = reconstruct_context(lme_record, case.history_events)

    assert q6_context.sha256 == q6_record["context_sha256"]
    assert lme_context.sha256 == lme_record["context_sha256"]
    assert q6_context.sha256 != lme_context.sha256
    assert q6_context.stable_id_sha256 == lme_context.stable_id_sha256
    assert q6_context.ordered_source_refs == lme_context.ordered_source_refs
    assert (
        prompt_sha256(
            question=case.question,
            question_as_of=case.question_at,
            memory_context=q6_context.text,
        )
        == q6_record["provider"]["prompt_sha256"]
    )
    assert (
        prompt_sha256(
            question=case.question,
            question_as_of=case.question_at,
            memory_context=lme_context.text,
        )
        == lme_record["provider"]["prompt_sha256"]
    )

    observed = artifact_forensics(q6_record, lme_record, q6_context, lme_context)
    assert observed["same_selected_source_refs"] is True
    assert observed["same_all_source_refs"] is True
    assert observed["same_seed"] is True
    assert observed["opaque_evidence_id_only_context_drift"] is True
