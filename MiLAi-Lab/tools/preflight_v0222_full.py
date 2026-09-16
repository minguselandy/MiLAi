"""HTTP-only full actual-wire capacity checks; never generate or launch episodes."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx

from prepare_v0222_full import selected
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded
from v0222_batch import Batch
from v0222_http import bounded_request, http_identity, strict_http_json
from v0222_string_contract import compile_contract


def validate_reference(row: dict, condition: str) -> tuple[dict, str]:
    for kind in ("canonical", "wire", "output"):
        if sha(Path(row[kind])) != row["hashes"][kind]:
            raise ProviderStop("FROZEN_REFERENCE_DRIFT")
    canonical, wire = read(Path(row["canonical"])), read(Path(row["wire"]))
    contract = compile_contract(
        canonical["response_format"]["json_schema"]["schema"],
        selected_condition=condition,
    )
    if contract.prepare(canonical) != wire or contract.manifest() != row["schema_pair"]:
        raise ProviderStop("FULL_WIRE_CANDIDATE_DRIFT")
    raw = read(Path(row["output"]))["raw"]
    contract.validate_output(raw)
    return wire, raw


def preflight(root: Path, binding: str, stage: str, *, transport=None) -> dict:
    if stage not in {"P3", "P4"}:
        raise ProviderStop("FULL_PREFLIGHT_STAGE_REQUIRED")
    batch = Batch(root, binding)
    batch.authorize(stage)
    condition = batch.artifact("P1_final_selection")["selected_condition"]
    selected(batch, condition)
    if batch.artifact("P2_gate")["status"] != "G_P2_PASS":
        raise ProviderStop("P2_FULL_REGRESSION_GATE_REQUIRED")
    if batch.artifact("P_full_preparation")["status"] != "REFERENCE_PREPARATION_PASS":
        raise ProviderStop("COMPLETE_FULL_REFERENCES_REQUIRED")
    snapshot = batch.snapshot()
    if snapshot["stop"]:
        raise ProviderStop("BATCH_ALREADY_STOPPED")
    references = batch.references(stage)
    expected = 16 if stage == "P3" else 80
    if len(references) != expected:
        raise ProviderStop("COMPLETE_STAGE_REFERENCE_MATRIX_REQUIRED")
    specs = batch.plan[stage] if stage == "P3" else batch.artifact("P4_resolved_specs")["specs"]
    expected_positions = [
        (spec["id"], turn)
        for spec in specs
        for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3)
    ]
    if [(r["episode"], r["turn"]) for r in references] != expected_positions:
        raise ProviderStop("FULL_REFERENCE_POSITION_OR_ORDER_DRIFT")
    directory = root / (stage + "-preflight")
    directory.mkdir(exist_ok=False)
    rows, calls, reason = [], [], None
    deadline = time.monotonic() + 600
    try:
        with httpx.Client(
            base_url=ENDPOINT,
            transport=transport,
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            identity = http_identity(client, directory / "identity-start")
            if identity != batch.plan["http_identity"]:
                raise ProviderStop("HTTP_IDENTITY_DRIFT")
            for row in references:
                batch.authorize(stage)
                if row["stage"] != stage or row["selected_condition"] != condition:
                    raise ProviderStop("REFERENCE_STAGE_OR_CANDIDATE_DRIFT")
                wire, raw = validate_reference(row, condition)
                counts = {}
                for kind, body in (
                    ("input", {k: wire[k] for k in TOKENIZE_KEYS}),
                    ("output", {"model": MODEL, "prompt": raw, "add_special_tokens": False}),
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProviderStop("PREFLIGHT_DEADLINE")
                    stem = directory / f"{row['episode']}-{row['turn']:02d}-{kind}"
                    save(stem.with_suffix(".request.json"), body)
                    attempt = {
                        "episode": row["episode"],
                        "turn": row["turn"],
                        "kind": kind,
                        "method": "POST",
                        "route": "/tokenize",
                        "attempted": True,
                    }
                    save(stem.with_suffix(".attempt.json"), attempt)
                    calls.append(attempt)
                    started = time.monotonic()
                    try:
                        response = bounded_request(
                            client,
                            "POST",
                            "/tokenize",
                            content=encoded(body).encode(),
                            headers={"Content-Type": "application/json"},
                            timeout=min(5, remaining),
                        )
                    except Exception as exc:
                        attempt["exception_type"] = type(exc).__name__
                        save(
                            stem.with_suffix(".error.json"),
                            {
                                **attempt,
                                "seconds": time.monotonic() - started,
                            },
                        )
                        raise
                    attempt["status_code"] = response.status_code
                    save(
                        stem.with_suffix(".http.json"),
                        {
                            "status_code": response.status_code,
                            "body": response.text,
                            "seconds": time.monotonic() - started,
                        },
                    )
                    response.raise_for_status()
                    count = strict_http_json(response.text)["count"]
                    if type(count) is not int or count < 0:
                        raise ProviderStop("INVALID_TOKENIZE_COUNT")
                    counts[kind] = count
                if counts["input"] + 4096 > 65536 or counts["output"] + 1 > 4096:
                    raise ProviderStop("CAPACITY_NOT_ADMITTED")
                rows.append(
                    {
                        "episode": row["episode"],
                        "turn": row["turn"],
                        "counts": counts,
                        "reference_hashes": row["hashes"],
                    }
                )
                print(
                    f"capacity {stage} {len(rows)}/{expected} {row['episode']} {counts}", flush=True
                )
            batch.authorize(stage)
            if (
                time.monotonic() >= deadline
                or http_identity(client, directory / "identity-final") != identity
            ):
                raise ProviderStop("HTTP_IDENTITY_DRIFT_OR_PREFLIGHT_DEADLINE")
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        batch.stop(reason)
    result = {
        "status": "G_PREFLIGHT_PASS" if reason is None and len(rows) == expected else "NOT_MET",
        "stage": stage,
        "selected_condition": condition,
        "rows": rows,
        "tokenize_calls": calls,
        "reason": reason,
        "model_requests": 0,
        "direct_device_calls": 0,
        "files": {str(p): sha(p) for p in sorted(directory.rglob("*.json"))},
    }
    save(directory / "result.json", result)
    if result["status"] == "G_PREFLIGHT_PASS":
        try:
            batch.freeze_artifact(
                stage + "_preflight", directory / "result.json", "G_PREFLIGHT_PASS"
            )
        except Exception as exc:
            batch.stop(type(exc).__name__)
            save(
                directory / "admission-error.json",
                {"status": "NOT_ADMITTED", "exception_type": type(exc).__name__},
            )
            raise
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--stage", choices=("P3", "P4"), required=True)
    args = parser.parse_args()
    preflight(args.root, args.binding_sha256, args.stage)
