"""Guarded CPU-only replay of the complete original preflight workflow.

Counts and identity come from the fixed local Mock script, never vLLM. Passing
this replay is not real tokenizer capacity or live admission. The full reference,
receipt, fresh-admission and failure logic is retained from live V2; use the
dedicated guarded bootstrap. No caller-selected transport or endpoint exists.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx

from preflight_v0222_presentation import PREFLIGHT_SECONDS, RECEIPT_COUNTS, REFERENCE_COUNTS
from preflight_v0222_presentation_v2 import admit_preflight
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded
from v0222_http import bounded_request, strict_http_json
from v0222_presentation_audit import validate_reference
from v0222_presentation_http_v2 import identity, owned_timeout
from v0222_scoped_cpu_batch import OfflineBatch as Batch
from v0222_scoped_cpu_guard import require_cpu_network_guard
from v0222_scoped_cpu_mock import make_mock_transport
from v0222_scoped_cpu_worker import stop_batch


def preflight(root: Path, binding: str, stage: str) -> dict:
    require_cpu_network_guard()
    batch = None

    def fail(exc):
        stop_batch(root, binding, batch, exc)
        return str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__

    def persist(path, value):
        try:
            save(path, value)
        except BaseException as exc:
            fail(exc)
            raise

    try:
        if stage not in PREFLIGHT_SECONDS:
            raise ProviderStop("PRESENTATION_PREFLIGHT_STAGE_REQUIRED")
        batch = Batch(root, binding)
        transport = make_mock_transport(batch)
        directory = batch.root / (stage + "-preflight")
        deadline = time.monotonic() + PREFLIGHT_SECONDS[stage]

        def admit_http():
            return admit_preflight(batch, stage, deadline)

        admit_http()
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
        directory.mkdir(exist_ok=False)
    except BaseException as exc:
        fail(exc)
        raise

    rows, calls, reason = [], [], None
    try:
        with httpx.Client(
            base_url=ENDPOINT,
            transport=transport,
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            initial_identity = identity(
                client, directory / "identity-start", admit=admit_http, on_failure=fail
            )
            if initial_identity != batch.plan["http_identity"]:
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
                    content = encoded(body).encode()
                    persist(stem.with_suffix(".request.json"), body)
                    persist(stem.with_suffix(".attempt.json"), attempt)
                    claim = admit_http()
                    timeout = owned_timeout(claim, 5)
                    calls.append(attempt)
                    http_started = time.monotonic()
                    try:
                        response = bounded_request(
                            client,
                            "POST",
                            "/tokenize",
                            content=content,
                            headers={"Content-Type": "application/json"},
                            timeout=timeout,
                        )
                    except BaseException as exc:
                        fail(exc)
                        try:
                            persist(
                                stem.with_suffix(".error.json"),
                                {
                                    "exception_type": type(exc).__name__,
                                    "seconds": time.monotonic() - http_started,
                                },
                            )
                        except BaseException as secondary:
                            exc.add_note(
                                "SECONDARY_HTTP_REPORT_FAILURE: " + type(secondary).__name__
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
                identity(client, directory / "identity-final", admit=admit_http, on_failure=fail)
                != initial_identity
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
            admit_http()
        return result
    except BaseException as exc:
        fail(exc)
        raise


def main():
    require_cpu_network_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--stage", choices=("P3", "P4"), required=True)
    args = parser.parse_args()
    value = preflight(args.root, args.binding_sha256, args.stage)
    return 0 if value["status"] == "G_PREFLIGHT_PASS" else 1
