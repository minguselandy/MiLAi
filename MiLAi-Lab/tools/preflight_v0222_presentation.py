"""Bounded HTTP-only full-reference capacity checks; never model generation."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded
from v0222_http import bounded_request, strict_http_json
from v0222_presentation_audit import validate_reference
from v0222_presentation_batch import Batch
from v0222_presentation_http import identity as boundary_identity
from v0222_presentation_worker import stop_batch

# Includes repeated immutable-lineage/reference validation, not just network time.
# These are preflight-only windows, not changes to the 1800/7200 model phases.
PREFLIGHT_SECONDS = {"P3": 1200, "P4": 2400}
REFERENCE_COUNTS = {"P3": 16, "P4": 80}
RECEIPT_COUNTS = {"P3": 104, "P4": 488}


def preflight(root: Path, binding: str, stage: str, *, transport=None) -> dict:
    try:
        batch = Batch(root, binding)
    except BaseException as exc:
        stop_batch(root, binding, None, exc)
        raise
    directory = batch.root / (stage + "-preflight")
    started = time.monotonic()
    rows, calls = [], []

    def fail(exc):
        reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        batch.stop(reason)
        return reason

    def persist(path, value):
        try:
            save(path, value)
        except BaseException as exc:
            fail(exc)
            raise

    try:
        if stage not in PREFLIGHT_SECONDS:
            raise ProviderStop("PRESENTATION_PREFLIGHT_STAGE_REQUIRED")
        deadline = started + PREFLIGHT_SECONDS[stage]

        def admit_http():
            batch.authorize(stage)
            with batch.transaction() as db:
                batch.check_journal(db)
            # Identity helper has a fixed five-second wall bound. Do not start
            # any HTTP call without room for its whole bound after CPU checks.
            if time.monotonic() + 5 > deadline:
                raise ProviderStop("PRESENTATION_PREFLIGHT_DEADLINE")

        admit_http()
        for name, status in (
            ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
            ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
        ):
            if batch.artifact(name).get("status") != status:
                raise ProviderStop("REVIEW_AND_ENGINEERING_REQUIRED_BEFORE_HTTP")
        references = batch.references(stage)
        positions = [
            (spec["id"], turn)
            for spec in batch.plan[stage]
            for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3)
        ]
        if (
            len(references) != REFERENCE_COUNTS[stage]
            or [(ref["episode"], ref["turn"]) for ref in references] != positions
        ):
            raise ProviderStop("COMPLETE_ORDERED_STAGE_REFERENCES_REQUIRED")
        # Exclusive directory prevents retry/resume and preserves previous evidence.
        directory.mkdir(exist_ok=False)
    except BaseException as exc:
        fail(exc)
        raise

    reason = None
    try:
        with httpx.Client(
            base_url=ENDPOINT,
            transport=transport,
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            identity = boundary_identity(
                client, directory / "identity-start", admit=admit_http, on_failure=fail
            )
            if identity != batch.plan["http_identity"]:
                raise ProviderStop("HTTP_IDENTITY_DRIFT")
            for ref in references:
                _, _, wire, raw = validate_reference(batch, ref, batch.spec(ref["episode"]))
                counts = {}
                for kind, body in (
                    ("input", {key: wire[key] for key in TOKENIZE_KEYS}),
                    ("output", {"model": MODEL, "prompt": raw, "add_special_tokens": False}),
                ):
                    stem = directory / f"{ref['episode']}-{ref['turn']:02d}-{kind}"
                    attempt = {
                        "episode": ref["episode"],
                        "turn": ref["turn"],
                        "kind": kind,
                        "method": "POST",
                        "route": "/tokenize",
                    }
                    persist(stem.with_suffix(".request.json"), body)
                    persist(stem.with_suffix(".attempt.json"), attempt)
                    # Fresh admission after all preparation/persistence and before
                    # network timing; RESERVED model requests are never created.
                    admit_http()
                    calls.append(attempt)
                    http_started = time.monotonic()
                    try:
                        response = bounded_request(
                            client,
                            "POST",
                            "/tokenize",
                            content=encoded(body).encode(),
                            headers={"Content-Type": "application/json"},
                            timeout=5,
                        )
                    except Exception as exc:
                        fail(exc)
                        persist(
                            stem.with_suffix(".error.json"),
                            {
                                "exception_type": type(exc).__name__,
                                "seconds": time.monotonic() - http_started,
                            },
                        )
                        raise
                    persist(
                        stem.with_suffix(".http.json"),
                        {
                            "status_code": response.status_code,
                            "body": response.text,
                            "seconds": time.monotonic() - http_started,
                        },
                    )
                    if response.status_code != 200:
                        raise ProviderStop("TOKENIZE_REQUIRES_HTTP_200")
                    count = strict_http_json(response.text)["count"]
                    if type(count) is not int or count < 0:
                        raise ProviderStop("INVALID_TOKENIZE_COUNT")
                    counts[kind] = count
                if counts["input"] + 4096 > 65536 or counts["output"] + 1 > 4096:
                    raise ProviderStop("COMPLETE_INPUT_OR_OUTPUT_CAPACITY_NOT_MET")
                rows.append(
                    {
                        "episode": ref["episode"],
                        "turn": ref["turn"],
                        "counts": counts,
                        "reference_hashes": ref["hashes"],
                    }
                )
                print(f"capacity {stage} {len(rows)}/{len(references)} {counts}", flush=True)
            if (
                boundary_identity(
                    client, directory / "identity-final", admit=admit_http, on_failure=fail
                )
                != identity
            ):
                raise ProviderStop("HTTP_IDENTITY_DRIFT")
            admit_http()
    except Exception as exc:
        reason = fail(exc)
    except BaseException as exc:
        fail(exc)
        raise

    try:
        files = {str(path): sha(path) for path in sorted(directory.rglob("*.json"))}
        if reason is None and len(files) != RECEIPT_COUNTS[stage]:
            raise ProviderStop("EXACT_COMPLETE_PREFLIGHT_RECEIPTS_REQUIRED")
        result = {
            "status": "G_PREFLIGHT_PASS" if reason is None else "NOT_MET",
            "stage": stage,
            "selected_condition": "B1",
            "selected_decoder": "D11",
            "rows": rows,
            "tokenize_calls": calls,
            "reason": reason,
            "model_requests": 0,
            "direct_device_calls": 0,
            "preflight_window_seconds": PREFLIGHT_SECONDS[stage],
            "files": files,
        }
        persist(directory / "result.json", result)
        if reason is None:
            admit_http()
            batch.freeze_artifact(
                stage + "_preflight", directory / "result.json", "G_PREFLIGHT_PASS"
            )
            # Independent freeze repeats reference validation outside its SQL lock.
            # A late overrun permanently stops admission even if the artifact exists.
            admit_http()
        return result
    except BaseException as exc:
        fail(exc)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--stage", choices=("P3", "P4"), required=True)
    args = parser.parse_args()
    value = preflight(args.root, args.binding_sha256, args.stage)
    raise SystemExit(0 if value["status"] == "G_PREFLIGHT_PASS" else 1)
