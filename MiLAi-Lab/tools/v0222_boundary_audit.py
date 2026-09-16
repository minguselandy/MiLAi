"""Read-only evidence reconstruction for the finite residual-boundary diagnostic."""

from __future__ import annotations

from pathlib import Path

from v02_local_provider import read_events
from v0213_provider import MODEL, TOKENIZE_KEYS
from v0220_evidence import read, sha
from v0220_provider_hardened import ProviderStop, usage_state, valid_usage
from v0220_wire_contract import fingerprint
from v0222_boundary_contract import audit_transform, observe, transform
from v0222_http import strict_http_json
from v0222_string_contract import compile_contract


def validate_reference(batch, reference: dict, spec: dict) -> tuple[dict, dict, str]:
    """Bind every reference to the original full source and the sole transformation."""
    for key in ("root", "cold", "condition", "source_episode"):
        if reference.get(key) != spec[key]:
            raise ProviderStop("BOUNDARY_REFERENCE_POSITION_DRIFT")
    if reference.get("episode") != spec["id"] or reference.get("stage") != "R1":
        raise ProviderStop("BOUNDARY_REFERENCE_EPISODE_DRIFT")
    source = Path(reference["source_canonical"])
    expected_source = (
        Path(batch.plan["parent_root"])
        / "full-reference/P3"
        / spec["source_episode"]
        / "request-01.canonical.json"
    )
    if (
        source.resolve() != expected_source.resolve()
        or sha(source) != reference["source_canonical_sha256"]
    ):
        raise ProviderStop("ORIGINAL_FULL_SOURCE_REFERENCE_DRIFT")
    values = {}
    for kind in ("canonical", "wire", "output", "diff"):
        path = Path(reference[kind]).resolve()
        if not path.is_relative_to(batch.root) or sha(path) != reference["hashes"][kind]:
            raise ProviderStop("BOUNDARY_REFERENCE_FILE_DRIFT")
        values[kind] = strict_http_json(path.read_text(encoding="utf-8"))
    original = strict_http_json(source.read_text(encoding="utf-8"))
    original_intent = strict_http_json(original["messages"][-1]["content"])["authorized_intent"]
    if fingerprint(original_intent["authorized_action"]) != fingerprint(spec["expected"]):
        raise ProviderStop("ORIGINAL_AUTHORIZED_TARGET_AND_COMPLETE_VALUES_REQUIRED")
    canonical, wire = values["canonical"], values["wire"]
    if fingerprint(transform(original, spec["condition"])) != fingerprint(canonical):
        raise ProviderStop("BOUNDARY_CANONICAL_TRANSFORMATION_DRIFT")
    if fingerprint(audit_transform(original, canonical, spec["condition"])) != fingerprint(
        values["diff"]
    ):
        raise ProviderStop("BOUNDARY_REVERSIBLE_DIFF_DRIFT")
    compiled = compile_contract(canonical["response_format"]["json_schema"]["schema"], "D11")
    raw = values["output"]["raw"]
    if (
        fingerprint(compiled.prepare(canonical)) != fingerprint(wire)
        or sha(Path(reference["wire"])) != fingerprint(wire)
        or fingerprint(reference["schema_pair"]) != fingerprint(compiled.manifest())
        or fingerprint(compiled.validate_output(raw)) != fingerprint(spec["expected"])
    ):
        raise ProviderStop("UNCHANGED_D11_FULL_CONTRACT_OR_REFERENCE_INTENT_REQUIRED")
    return canonical, wire, raw


def audit_episode(batch, episode: str) -> dict:
    """Known-usage content failures are observations; trace failures are fatal."""
    spec = next(s for s in batch.plan["episodes"] if s["id"] == episode)
    matches = [r for r in batch.references() if r["episode"] == episode]
    if len(matches) != 1:
        raise ProviderStop("ONE_BOUNDARY_REFERENCE_PER_POSITION_REQUIRED")
    canonical, wire, _ = validate_reference(batch, matches[0], spec)
    directory = batch.root / "episodes" / episode
    provider = directory / "provider"
    worker = read(directory / "observation.json")
    events = read_events(provider / "provider-ledger-v2.jsonl")
    cost = usage_state(events)
    reserved = [e for e in events if e["event"] == "RESERVED"]
    settled = [e for e in events if e["event"] == "USAGE_KNOWN"]
    if len(reserved) != 1 or len(settled) != 1 or not cost["new_generation_allowed"]:
        raise ProviderStop("ONE_SETTLED_BOUNDARY_OBSERVATION_REQUIRED")
    reservation, known = reserved[0], settled[0]
    key = reservation["request_id"]
    request = provider / (key + "-request.json")
    http = read(provider / (key + "-http.json"))
    envelope = strict_http_json(http["body"])
    tokenize_http = read(provider / (key + "-tokenize-http.json"))
    counted = strict_http_json(tokenize_http["body"])
    raw = envelope["choices"][0]["message"]["content"]
    if (
        reservation["session"] != episode
        or known["request_id"] != key
        or http["status_code"] != 200
        or http["client_request_id"] != key
        or sha(request) != reservation["payload_sha256"]
        or http["request_wire_sha256"] != sha(request)
        or sha(request) != fingerprint(wire)
        or fingerprint(strict_http_json(request.read_text())) != fingerprint(wire)
        or tokenize_http["status_code"] != 200
        or type(counted["count"]) is not int
        or counted["count"] < 0
        or counted["count"] + 4096 > 65536
        or fingerprint(read(provider / (key + "-tokenize-request.json")))
        != fingerprint({k: wire[k] for k in TOKENIZE_KEYS})
        or fingerprint(read(provider / (key + "-tokenize.json")))
        != fingerprint({"count": counted["count"]})
        or counted["count"] != reservation["prompt_tokens"]
        or not valid_usage(envelope["usage"])
        or fingerprint(envelope["usage"]) != fingerprint(known["usage"])
        or envelope["usage"]["prompt_tokens"] != counted["count"]
        or envelope["usage"]["completion_tokens"] > 4096
        or not isinstance(envelope.get("id"), str)
        or not envelope["id"]
        or not isinstance(raw, str)
        or read(provider / (key + "-visible.json"))["content"] != raw
    ):
        raise ProviderStop("BOUNDARY_ACTUAL_REQUEST_HTTP_TOKENIZE_USAGE_AUDIT_FAILED")
    observation = observe(
        spec["expected"], canonical["response_format"]["json_schema"]["schema"], raw
    )
    expected = {
        **observation,
        "id": episode,
        "root": spec["root"],
        "cold": spec["cold"],
        "condition": spec["condition"],
        "request_id": key,
        "http_usage_audit": "PASS",
        "business_dispatches": 0,
    }
    if (
        any(fingerprint(worker.get(k)) != fingerprint(v) for k, v in expected.items())
        or type(worker.get("pid")) is not int
        or (batch.root / "worlds").exists()
        or list(directory.glob("turn-*.json"))
        or list(directory.glob("note-*.json"))
    ):
        raise ProviderStop("BOUNDARY_OBSERVATION_NOT_DERIVED_FROM_RAW_OR_NOT_VALIDATE_ONLY")
    return {
        **expected,
        "status": "OBSERVED",
        "pid": worker["pid"],
        "cost": cost,
        "files": {
            str(p): sha(p)
            for p in sorted(directory.rglob("*"))
            if p.is_file()
            and p.suffix in {".json", ".jsonl"}
            and p.name != "independent-observation.json"
        },
    }


def validate_preflight(batch, result: dict) -> None:
    """A PASS label cannot substitute for all actual input/output HTTP receipts."""
    specs, references = batch.plan["episodes"], batch.references()
    expected_calls = [
        {"episode": spec["id"], "kind": kind, "method": "POST", "route": "/tokenize"}
        for spec in specs
        for kind in ("input", "output")
    ]
    if (
        result.get("status") != "G_PREFLIGHT_PASS"
        or result.get("model_requests") != 0
        or len(specs) != 16
        or len(references) != 16
        or len(result.get("rows", [])) != 16
        or fingerprint(result.get("tokenize_calls")) != fingerprint(expected_calls)
        or result.get("reason") is not None
    ):
        raise ProviderStop("COMPLETE_16_REFERENCE_PREFLIGHT_EVIDENCE_REQUIRED")
    directory = batch.root / "preflight"
    expected_files = set()

    def receipt(path: Path):
        expected_files.add(str(path))
        if result.get("files", {}).get(str(path)) != sha(path):
            raise ProviderStop("PREFLIGHT_RAW_RECEIPT_NOT_BOUND")
        return strict_http_json(path.read_text(encoding="utf-8"))

    for side in ("identity-start", "identity-final"):
        actual = {}
        for name, route in (("models", "/v1/models"), ("version", "/version")):
            attempt = receipt(directory / side / (name + "-attempt.json"))
            http = receipt(directory / side / (name + ".json"))
            if attempt != {"method": "GET", "route": route} or http["status_code"] != 200:
                raise ProviderStop("STRICT_HTTP_IDENTITY_RECEIPTS_REQUIRED")
            actual[name] = strict_http_json(http["body"])
        models = actual["models"]["data"]
        if (
            len(models) != 1
            or models[0]["id"] != MODEL
            or type(models[0]["max_model_len"]) is not int
            or models[0]["max_model_len"] != 65536
            or actual["version"]["version"] != batch.plan["http_identity"]["version"]
        ):
            raise ProviderStop("PREFLIGHT_IDENTITY_DRIFT")
    for spec, reference, row in zip(specs, references, result["rows"], strict=True):
        _, wire, raw = validate_reference(batch, reference, spec)
        counts = {}
        for kind, wanted in (
            ("input", {k: wire[k] for k in TOKENIZE_KEYS}),
            ("output", {"model": MODEL, "prompt": raw, "add_special_tokens": False}),
        ):
            stem = directory / (spec["id"] + "-" + kind)
            body = receipt(stem.with_suffix(".request.json"))
            attempt = receipt(stem.with_suffix(".attempt.json"))
            http = receipt(stem.with_suffix(".http.json"))
            expected_attempt = {
                "episode": spec["id"],
                "kind": kind,
                "method": "POST",
                "route": "/tokenize",
            }
            if (
                fingerprint(body) != fingerprint(wanted)
                or fingerprint(attempt) != fingerprint(expected_attempt)
                or http["status_code"] != 200
            ):
                raise ProviderStop("ACTUAL_PREFLIGHT_REQUEST_OR_HTTP_STATUS_DRIFT")
            count = strict_http_json(http["body"])["count"]
            if type(count) is not int or count < 0:
                raise ProviderStop("PREFLIGHT_STRICT_INTEGER_COUNT_REQUIRED")
            counts[kind] = count
        if (
            counts["input"] + 4096 > 65536
            or counts["output"] + 1 > 4096
            or fingerprint(row)
            != fingerprint(
                {"episode": spec["id"], "counts": counts, "reference_hashes": reference["hashes"]}
            )
        ):
            raise ProviderStop("PREFLIGHT_COMPLETE_CAPACITY_OR_ROW_DRIFT")
    if set(result["files"]) != expected_files:
        raise ProviderStop("EXACT_COMPLETE_PREFLIGHT_RECEIPT_SET_REQUIRED")
