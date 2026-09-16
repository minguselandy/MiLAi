"""Protocol-v3 gates for unchanged frozen DG10/DG11 and dense producers."""

from __future__ import annotations

from typing import Any

from .freeze import (
    ANSWER_TOKENIZER_SHA256,
    require_formal_holdout_authorized,
    require_paper_v3_ready,
    sha256_file,
)


def _require_answer_tokenizer(kwargs: dict[str, Any]) -> None:
    if sha256_file(kwargs["tokenizer_path"]) != ANSWER_TOKENIZER_SHA256:
        raise ValueError("answer tokenizer drifted from the v3 freeze")


def run_dense(**kwargs: Any) -> dict[str, Any]:
    from evals.paper.runners import contriever_contexts as producer

    freeze_manifest = kwargs["freeze_manifest"]
    require_paper_v3_ready(freeze_manifest)
    require_formal_holdout_authorized(
        input_path=kwargs["input_path"],
        manifest_path=freeze_manifest,
        authorization_path=kwargs.pop("execution_authorization", None),
    )
    _require_answer_tokenizer(kwargs)
    kwargs["allow_unfrozen_smoke"] = False
    original = producer.require_paper_evaluation_ready
    producer.require_paper_evaluation_ready = lambda _path: None
    try:
        return producer.run(**kwargs)
    finally:
        producer.require_paper_evaluation_ready = original


def run_legacy_milai(**kwargs: Any) -> dict[str, Any]:
    from evals.paper.runners import milai_contexts as producer

    if kwargs.get("method_id") not in {"DG10-FROZEN", "DG11-FULL"}:
        raise ValueError("legacy MiLAi wrapper only accepts DG10-FROZEN or DG11-FULL")
    freeze_manifest = kwargs["freeze_manifest"]
    require_paper_v3_ready(freeze_manifest)
    require_formal_holdout_authorized(
        input_path=kwargs["input_path"],
        manifest_path=freeze_manifest,
        authorization_path=kwargs.pop("execution_authorization", None),
    )
    _require_answer_tokenizer(kwargs)
    kwargs["allow_unfrozen_smoke"] = False
    kwargs["max_case_attempts"] = 1
    kwargs["workers"] = 1
    original = producer.require_paper_evaluation_ready
    producer.require_paper_evaluation_ready = lambda _path: None
    try:
        return producer.run(**kwargs)
    finally:
        producer.require_paper_evaluation_ready = original
