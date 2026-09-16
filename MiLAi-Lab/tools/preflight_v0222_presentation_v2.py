"""Scoped, bounded HTTP-only capacity checks for all original references.

Only the explicit CLI/function call can send HTTP; importing does not. This
entry uses the existing vLLM service, never model libraries or device APIs.
Reference reconstruction and raw receipt acceptance remain the frozen originals.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx

from preflight_v0222_presentation import PREFLIGHT_SECONDS, RECEIPT_COUNTS, REFERENCE_COUNTS
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded
from v0222_http import bounded_request, strict_http_json
from v0222_presentation_audit import validate_reference
from v0222_presentation_finish_v2 import Batch
from v0222_presentation_gates_v2 import SCOPE_PREREQUISITES, AuditView
from v0222_presentation_http_v2 import identity, owned_timeout
from v0222_presentation_worker_v2 import stop_batch


def admit_preflight(batch, stage: str, deadline: float) -> dict:
    """One fresh scope/SQL admission; never require our not-yet-created gate.

    A preflight is not a worker claim or a model-stage launch. It needs the
    complete preparation/review closure on every HTTP boundary, and P4 also
    needs the new P3 gate. Returning happens only after scope close/SQL unlock.
    """
    if stage not in PREFLIGHT_SECONDS:
        raise ProviderStop("PRESENTATION_PREFLIGHT_STAGE_REQUIRED")
    with batch._operation(stage) as (db, scope, _state):
        if db.execute("SELECT 1 FROM launches WHERE stage=?", (stage,)).fetchone():
            raise ProviderStop("PREFLIGHT_CANNOT_REOPEN_LAUNCHED_STAGE")
        if db.execute("SELECT 1 FROM episodes WHERE status='RUNNING'").fetchone():
            raise ProviderStop("PREFLIGHT_REQUIRES_NO_ACTIVE_WORKER")
        artifacts = batch._capture_artifacts(db, scope, SCOPE_PREREQUISITES)
        review = batch._artifact(db, "scope_review", scope)
        if (
            review.get("status") != "G_AUTH_SCOPE_REVIEW_PASS"
            or artifacts["engineering_checks"]["value"].get("status") != "ENGINEERING_CHECKS_PASS"
        ):
            raise ProviderStop("REVIEW_AND_ENGINEERING_REQUIRED_BEFORE_HTTP")
        batch._scope_review(
            review,
            AuditView(
                batch.root,
                batch.plan,
                {},
                binding_sha=batch.binding_sha,
                artifacts=artifacts,
                control_pins=batch._scope_control_pins(scope),
            ),
        )
        if stage == "P4":
            gate = batch._artifact(db, "P3_gate", scope)
            passed = db.execute(
                "SELECT COUNT(*) FROM episodes WHERE stage='P3' AND status='PASS'"
            ).fetchone()[0]
            if gate.get("status") != "G_P3_PASS" or passed != 16:
                raise ProviderStop("P4_REQUIRES_NEW_COMPLETE_P3_16_PASS")
    # Preserve the original preflight's full five-second room requirement,
    # including authorization expiry, after all CPU/file work has completed.
    remaining = min(deadline - time.monotonic(), batch.auth["expires_unix"] - time.time())
    if remaining < 5:
        raise ProviderStop("PRESENTATION_PREFLIGHT_DEADLINE")
    return {"deadline": min(batch.auth["expires_unix"], time.time() + remaining)}


def preflight(root: Path, binding: str, stage: str, *, transport=None) -> dict:
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--stage", choices=("P3", "P4"), required=True)
    args = parser.parse_args()
    value = preflight(args.root, args.binding_sha256, args.stage)
    return 0 if value["status"] == "G_PREFLIGHT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
