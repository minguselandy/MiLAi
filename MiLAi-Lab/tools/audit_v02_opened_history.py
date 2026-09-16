# ruff: noqa: RUF001 -- Preserve the existing Host's Chinese input delimiters.
"""Fixed-order opened-history source and input audit; tokenizer only, no generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx

from run_v02_local_vllm import ACTION_SCHEMA, SYSTEM
from v02_lme_sources import history_events
from v02_local_provider import ENDPOINT, MODEL, write_json

LAB = Path(__file__).resolve().parents[1]


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main(root: Path) -> None:
    selection_path = LAB / "studies/active/MILA_V02_LME_INCREMENTAL_SELECTION.json"
    selection = json.loads(selection_path.read_text())
    case_id = selection["D"][0]
    source_path = LAB / "artifacts/v02-lme-incremental/data-20260905b/sources" / (case_id + ".json")
    source = json.loads(source_path.read_text())
    target = root / "opened-history-audit"
    target.mkdir(exist_ok=False)
    workspace = target / "workspace"
    workspace.mkdir()
    # Freeze the first already-opened D case before any tokenizer outcome. No held-out body is read.
    write_json(
        target / "selection.json",
        {
            "case_id": case_id,
            "selection_sha256": digest(selection_path.read_bytes()),
            "source_sha256": digest(source_path.read_bytes()),
            "rule": "First existing opened D history in frozen list; no outcome selection",
        },
    )
    files = {}
    turn_bytes = 0
    for session in source["sessions"]:
        path = workspace / f"session-{session['session_ordinal']:03d}.json"
        write_json(path, session)
        files[path.name] = {"sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}
        turn_bytes += sum(len(turn["content"].encode()) for turn in session["turns"])
    left = history_events(source, "opened-a")
    right = history_events(source, "opened-b")
    invariant = (
        "event_type",
        "subject_id",
        "content",
        "observed_at",
        "turn_ordinal",
        "round_ordinal",
    )
    if len(left) != len(right) or any(
        any(a[key] != b[key] for key in invariant) for a, b in zip(left, right, strict=True)
    ):
        raise ValueError("SOURCE_REBINDING_SEMANTIC_DRIFT")
    catalog = json.loads(
        (
            LAB / "artifacts/v02-local-vllm-simulation/local-sim-20260906b" / "G/catalog.json"
        ).read_text()
    )
    names = [
        {"name": t["name"], "description": t["description"][:160]}
        for t in catalog["tools"]["tools"]
    ]
    task = (
        "Review the available conversation histories for future collaboration. "
        "Create handoff.md only for reusable continuity, with source entry points; "
        "retain the original histories. No future question is supplied."
    )
    bootstrap = {
        "status": "ABSENT",
        "payload": {},
        "files": {name: value["sha256"] for name, value in files.items()},
    }
    messages = [
        {
            "role": "system",
            "content": SYSTEM
            + "\n公开 MiLA 工具（可查完整合同）："
            + json.dumps(names, ensure_ascii=False),
        },
        {
            "role": "user",
            "content": task
            + "\n恢复内容及文件入口：\n"
            + json.dumps(bootstrap, ensure_ascii=False),
        },
    ]
    chat = {
        "model": MODEL,
        "messages": messages,
        "chat_template_kwargs": {"enable_thinking": False},
        "add_generation_prompt": True,
        "add_special_tokens": False,
    }
    write_json(target / "candidate-first-input.json", {**chat, "response_schema": ACTION_SCHEMA})
    # This diagnostic full-history counterfactual is never sent to a generation endpoint.
    full = {
        **chat,
        "messages": [
            *messages,
            {"role": "user", "content": json.dumps(source["sessions"], ensure_ascii=False)},
        ],
    }
    counts = {}
    with httpx.Client(
        base_url=ENDPOINT, trust_env=False, follow_redirects=False, timeout=30
    ) as client:
        response = client.get("/v1/models")
        response.raise_for_status()
        models = response.json()["data"]
        if len(models) != 1 or models[0]["id"] != MODEL:
            raise ValueError("TOKENIZER_MODEL_IDENTITY_DRIFT")
        for label, body in (("candidate_first_request", chat), ("all_history_diagnostic", full)):
            response = client.post("/tokenize", json=body)
            response.raise_for_status()
            value = response.json()
            count = value["count"]
            if type(count) is not int or count <= 0:
                raise ValueError("INVALID_TOKEN_COUNT")
            counts[label] = {
                "input_tokens": count,
                "body_sha256": digest(json.dumps(body, ensure_ascii=False).encode()),
                "response_sha256": digest(response.content),
            }
    write_json(
        target / "result.json",
        {
            "status": "NON_MODEL_SOURCE_AND_INPUT_AUDIT_COMPLETE",
            "case_id": case_id,
            "new_model_requests": 0,
            "new_model_tokens": 0,
            "tokenize_requests": 2,
            "files": files,
            "sessions": len(source["sessions"]),
            "events": len(left),
            "original_turn_content_bytes": turn_bytes,
            "tokenizer_counts": counts,
            "source_mapping": {
                "status": "LOCAL_MAPPING_EQUIVALENCE_ONLY",
                "preserved": invariant,
                "public_full_history_import": "NOT_RUN",
                "time_contract": "Existing event mapper adds turn ordinal to session time; "
                "original session time remains in retained source files",
            },
            "future_question_in_G": False,
            "gold_in_workspace": False,
            "twenty_thousand_session_budget_proven": False,
            "limitations": [
                "Candidate input audit, not an actual submitted model request",
                "Remaining reads and repeated history must be budgeted cumulatively",
                "Imported source eligibility and cross-project remapping remain unproved",
            ],
        },
    )
    print(
        json.dumps(
            {
                "case_id": case_id,
                "sessions": len(source["sessions"]),
                "events": len(left),
                "counts": counts,
                "model_requests": 0,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    main(parser.parse_args().root)
