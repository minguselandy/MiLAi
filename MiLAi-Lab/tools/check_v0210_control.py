"""Freeze P1/E0 full-material requests; only loopback discovery/tokenization.

This entry point has no generation transport. Host material is separate from
the evaluator rubric. Actual model controls require re-tokenization before E1 delivery.
"""

from __future__ import annotations

import argparse
import json
import tarfile
import time
from pathlib import Path

import httpx

from milai_lab.methods.state_control import (
    ARMS,
    MODEL,
    Case,
    ControlStop,
    Material,
    PreparedRequest,
    check_envelope,
    digest,
    prepare_request,
    presentation_audit,
)

ENDPOINT = "http://127.0.0.1:7860"
TOKENIZE_KEYS = (
    "model", "messages", "chat_template_kwargs", "add_generation_prompt", "add_special_tokens",
)
LAB = Path(__file__).resolve().parents[1]


def validate_config(config: dict) -> None:
    fixed = {
        "arm_kind": "RESEARCH_PROTOTYPE", "goal_version": "0.4",
        "order": [f"{arm}.{phase}" for phase in ("prepare", "deliver") for arm in ARMS],
        "max_input_tokens": 8192, "max_output_tokens": 1024, "batch_request_limit": 6,
        "batch_raw_token_limit": 64000, "batch_timeout_seconds": 600,
        "request_timeout_seconds": 60, "compatibility_probes": 0, "oracle": "NOT_RUN",
        "context_projection_enabled": False, "model_transport_enabled": False,
        "new_local_model_requests_authorized": 0, "new_paid_model_requests_authorized": 0,
        "new_raw_tokens_authorized": 0,
        "tool_state": "MODEL_TOOLS_DISABLED_SERVER_CATALOG_UNCHANGED",
        "product_access": "NOT_USED_IN_E1",
    }
    for key, expected in fixed.items():
        if config.get(key) != expected or type(config.get(key)) is not type(expected):
            raise ControlStop("FROZEN_PROTOCOL_MISMATCH:" + key)


def verify_baseline(config: dict) -> dict:
    product = LAB.parent / "MiLAi-Product"
    archive = product / (
        "integrations/mcp/dist/delivery/v0209-final/milai-mcp-delivery-0.1.15.tar.gz"
    )
    baseline = config["product_baseline"]
    archive_hash = digest(archive.read_bytes())
    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.extractfile(
            "milai-mcp-delivery-0.1.15/packages/milai_mcp-0.1.15-py3-none-any.whl"
        )
        if member is None:
            raise ControlStop("MCP_WHEEL_MISSING")
        wheel_hash = digest(member.read())
    if (archive_hash != baseline["delivery_sha256"]
            or wheel_hash != baseline["mcp_wheel_sha256"]):
        raise ControlStop("PRODUCT_BASELINE_DRIFT")
    catalog_path = product / "contracts/mcp/compact-memory-v1.release-0.1.15.tools.json"
    catalog = json.loads(catalog_path.read_bytes())
    compact = catalog["catalogs"]["compact-memory-v1"]
    if len(compact["tools"]) != 8:
        raise ControlStop("COMPACT_CATALOG_DRIFT")
    return {"delivery_sha256": archive_hash, "mcp_wheel_sha256": wheel_hash,
            "catalog_snapshot_sha256": digest(catalog_path.read_bytes()),
            "registered_tools": len(compact["tools"]),
            "verification": "LOCAL_ARTIFACT_BYTES_ONLY_NO_PRODUCT_SERVICE_ACCESS"}


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_case(config: dict) -> Case:
    raw = (LAB / config["source_package"]).read_bytes()
    if digest(raw) != config["source_package_sha256"]:
        raise ControlStop("SOURCE_PACKAGE_DRIFT")
    materials = []
    for item in json.loads(raw)["files"]:
        if digest(item["content"].encode("utf-8")) != item["sha256"]:
            raise ControlStop("SOURCE_CONTENT_DRIFT")
        materials.append(Material(item["path"], item["sha256"], config["scope"], item["content"]))
    return Case(config["scope"], config["task"], tuple(config["base_history"]),
                tuple(config["observations"]), tuple(materials))


def tokenize(
    requests: dict[str, PreparedRequest], *, events: list[dict],
    transport: httpx.BaseTransport | None = None,
) -> dict:
    with httpx.Client(base_url=ENDPOINT, timeout=5, trust_env=False,
                      follow_redirects=False, transport=transport) as client:
        def call(method: str, path: str, payload: dict | None = None) -> dict:
            event = {"method": method, "path": path, "status": "ATTEMPT"}
            events.append(event)
            started = time.monotonic()
            try:
                response = client.request(method, path, json=payload)
                event["http_status"] = response.status_code
                response.raise_for_status()
                result = response.json()
                event["status"] = "RETURNED"
                return result
            finally:
                event["seconds"] = time.monotonic() - started

        models = call("GET", "/v1/models")
        if [item["id"] for item in models["data"]] != [MODEL]:
            raise ControlStop("MODEL_IDENTITY_DRIFT")
        context = models["data"][0].get("max_model_len")
        if type(context) is not int or context <= 0:
            raise ControlStop("MODEL_CONTEXT_UNKNOWN")
        version = call("GET", "/version")
        counts = {}
        for name, prepared in requests.items():
            body = json.loads(prepared.body)
            value = call("POST", "/tokenize", {key: body[key] for key in TOKENIZE_KEYS})
            count = value["count"]
            check_envelope(count, model_context=context)
            counts[name] = count
        return {"model": MODEL, "server_version": version, "model_context": context,
                "prompt_tokens": counts, "generation_usage": 0,
                "actual_controls_require_fresh_tokenization": True}


def run(root: Path, config_path: Path, *, loopback: bool,
        transport: httpx.BaseTransport | None = None) -> dict:
    # A single new directory preserves failures and the exact frozen input.
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = time.monotonic()
    events: list[dict] = []
    report: dict = {"status": "STARTED", "stage": "E0", "arm_kind": "RESEARCH_PROTOTYPE",
                    "actual_model_generations": 0, "http_events": events,
                    "H1": "NOT_TESTED", "E2": "NOT_ENTERED", "E3": "NOT_ENTERED"}
    try:
        config = json.loads(config_path.read_text())
        validate_config(config)
        case = load_case(config)
        host_root, review_root = root / "host", root / "evaluation"
        host_root.mkdir()
        review_root.mkdir()
        write(host_root / "case.json", json.loads(case.common_text()))
        write(root / "config.json", config)
        report["frozen_config_sha256"] = digest((root / "config.json").read_bytes())
        rubric_path = LAB / "data/manifests/v0210-control-e1-rubric.json"
        (review_root / "rubric.json").write_bytes(rubric_path.read_bytes())
        requests = {}
        # Distinct fixed substitutes validate data flow only, never autonomous focus quality.
        controls = {"C0": "FIXED_REVIEW_DOUBLE: reread materials.",
                    "C1": "FIXED_OUTLINE_DOUBLE: judgment, evidence, unresolved.",
                    "C2": "current_question: FIXED_STATE_DOUBLE\nunresolved: unknown\n"
                          "next_action: compare sources"}
        for phase in ("prepare", "deliver"):
            for arm in ARMS:
                name = f"{arm}.{phase}"
                item = prepare_request(case, arm, phase, scope=case.scope,
                                       eligible=lambda _: True, control=controls[arm],
                                       seed=config["seed"])
                requests[name] = item
                (host_root / f"{name}.json").write_bytes(item.body)
        report["presentation"] = presentation_audit(case, tuple(requests.values()))
        report["request_sha256"] = {name: digest(item.body) for name, item in requests.items()}
        report["control_origin"] = "FIXED_TEST_DOUBLES_NOT_MODEL_OUTPUT"
        report["eligibility"] = "FROZEN_LOCAL_SYNTHETIC_DOMAIN_NOT_LIVE_PRODUCT_PERMISSION"
        # All six allocations fit even at their full registered input/output maxima.
        reservation = 6 * (8192 + 1024)
        if reservation > config["batch_raw_token_limit"]:
            raise ControlStop("UNEQUAL_OR_INSUFFICIENT_BATCH_ENVELOPE")
        report["batch_reservation_upper_bound"] = reservation
        report["registered_allocations"] = config["order"]
        report["oracle"] = config["oracle"]
        report["product_baseline"] = config["product_baseline"]
        report["product_artifact_verification"] = verify_baseline(config)
        report["product_access"] = "NONE"
        pin_paths = [Path(__file__).resolve(), config_path, rubric_path,
                     LAB / "tools/run_v0210_control.py",
                     LAB / "tools/v02_deadline.py", LAB / "tools/v02_local_provider.py",
                     LAB / "src/milai_lab/methods/state_control.py",
                     LAB / "tests/unit/test_state_control.py",
                     LAB / "tests/unit/test_v0210_control_runner.py"]
        report["implementation_pin"] = {
            str(path.relative_to(LAB)): digest(path.read_bytes()) for path in pin_paths
        }
        if loopback:
            report["tokenizer"] = tokenize(requests, events=events, transport=transport)
        report["status"] = "READY_FOR_LOCAL_PILOT" if loopback else "P1_MECHANICAL_PREPARED"
        report["generation_authorized"] = False
        report["semantic_negative_controls"] = "B2_NOT_RUN"
        report["cost"] = {"generation_raw_tokens": 0, "paid_requests": 0,
                          "gpu_cost": "UNKNOWN", "review_cost": "SEPARATE_SUBAGENT_REVIEW",
                          "storage_bytes": sum(p.stat().st_size for p in root.rglob("*")
                                               if p.is_file())}
    except Exception as exc:
        report.update(status="STOPPED", error_type=type(exc).__name__, reason=str(exc))
        raise
    finally:
        report["preparation_seconds"] = time.monotonic() - started
        write(root / "result.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=LAB / "configs/v0210-control-e1.json")
    parser.add_argument("--tokenize-loopback", action="store_true")
    args = parser.parse_args()
    report = run(args.root.resolve(), args.config.resolve(), loopback=args.tokenize_loopback)
    print(json.dumps({"status": report["status"], "actual_model_generations": 0,
                      "result": str(args.root / "result.json")}))


if __name__ == "__main__":
    main()
