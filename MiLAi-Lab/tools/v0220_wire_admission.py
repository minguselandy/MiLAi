"""Sealed four-root CPU admission for the explicit dual-contract transport.

This admits a compatibility diagnostic only, not a live-generation or V2 PASS.
Backend identity and request options are checked again; historical usage is an
independent mandatory guard in the underlying hardened Provider.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from v0220_evidence import read, sha, validate
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import REVISION, compile_contract, fingerprint

IDENTITY_SCRIPT = r"""
import hashlib, importlib.metadata, json
files = [
    'vllm/v1/structured_output/backend_xgrammar.py',
    'vllm/v1/structured_output/backend_guidance.py',
    'vllm/sampling_params.py', 'vllm/v1/engine/input_processor.py',
    'vllm/v1/engine/async_llm.py', 'vllm/config/structured_outputs.py',
    'vllm/entrypoints/openai/chat_completion/protocol.py',
    'vllm/entrypoints/serve/utils/error_response.py',
]
dist = importlib.metadata.distribution('vllm')
print(json.dumps({
    'versions': {k: importlib.metadata.version(k) for k in ('vllm','xgrammar','llguidance')},
    'sources': {k: hashlib.sha256(dist.locate_file(k).read_bytes()).hexdigest() for k in files},
    'profile': 'CPU_DEFAULT_AUTO_PARAMETER_VALIDATION_NOT_GPU_OR_LIVE_CONFIG_PASS',
}))
"""


def backend_identity(container: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{12,64}", container):
        raise ValueError("PINNED_CONTAINER_ID_REQUIRED")
    # No environment, credentials or arbitrary service command line is collected.
    info = subprocess.run(  # noqa: S603 - validated container, read-only selected fields
        [
            "/usr/bin/docker",
            "inspect",
            "--format",
            "{{.Id}} {{.Image}} {{.State.Pid}} {{.State.StartedAt}} {{.State.Running}}",
            container,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout.strip()
    if not info.endswith(" true"):
        raise ProviderStop("PINNED_BACKEND_NOT_RUNNING")
    metadata = subprocess.run(  # noqa: S603 - fixed CPU metadata script, no engine or request
        ["/usr/bin/docker", "exec", container, "python3", "-c", IDENTITY_SCRIPT],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    return {"container": info, "libraries": json.loads(metadata.stdout)}


def request_profile(body: dict) -> str:
    copied = copy.deepcopy(body)
    copied.pop("messages")
    copied["response_format"]["json_schema"]["schema"] = "SCHEMA_BOUND_SEPARATELY"
    return fingerprint(copied)


class WireSchemaAdmission:
    def __init__(
        self,
        root: Path,
        *,
        hashes: dict[str, str],
        identity: Callable[[], dict],
    ):
        if set(hashes) != {"manifest.json", "result.json", "inventory.json", "probes.json"}:
            raise ProviderStop("COMPLETE_WIRE_PREFLIGHT_HASH_BINDING_REQUIRED")
        self.root, self.hashes, self.identity = root, dict(hashes), identity

    def __call__(self, original: dict, wire: dict) -> None:
        if any(sha(self.root / k) != v for k, v in self.hashes.items()):
            raise ProviderStop("WIRE_PREFLIGHT_EVIDENCE_DRIFT")
        manifest = validate(self.root)
        contract = manifest["contract"]
        roots = contract["roots"]
        if (
            len(roots) != 4
            or len(set(roots)) != 4
            or contract["revision"] != REVISION
            or contract.get("public_contract_unchanged") is not True
        ):
            raise ProviderStop("FULL_FOUR_ROOT_WIRE_CONTRACT_REQUIRED")
        result, inventory = read(self.root / "result.json"), read(self.root / "inventory.json")
        if (
            result.get("all_wire_cpu_pass") is not True
            or result.get("all_local_semantic_checks_pass") is not True
            or result.get("model_requests") != 0
        ):
            raise ProviderStop("FULL_WIRE_MATRIX_NOT_ADMITTED")
        expected = {key + suffix for key in roots for suffix in ("-full", "-finish")}
        if len(inventory) != 8 or {r["id"] for r in inventory} != expected:
            raise ProviderStop("INCOMPLETE_WIRE_MATRIX")
        probes = read(self.root / "probes.json")
        expected_probes = {key + suffix for key in expected for suffix in ("-canonical", "-wire")}
        if len(probes) != 16 or {r["id"] for r in probes} != expected_probes:
            raise ProviderStop("INCOMPLETE_WIRE_CPU_EVIDENCE")
        for row in probes:
            if row["counts"]["engine_submissions"] != 0:
                raise ProviderStop("CPU_BOUNDARY_NOT_PROVEN")
            if row["id"].endswith("-wire") and (
                row["counts"]["input_validation_entered"] != 1
                or row["counts"]["post_validation_reached"] != 1
                or row["observed"]["cause_message"]
                != "CPU_PROBE_STOP_AFTER_PARAMETER_VALIDATION_NO_ENGINE"
            ):
                raise ProviderStop("WIRE_CPU_RESULT_NOT_PASS")
        if self.identity() != contract["backend_identity"]:
            raise ProviderStop("BACKEND_CHANGED_REVALIDATE_BEFORE_HTTP")
        plan = compile_contract(original["response_format"]["json_schema"]["schema"])
        if wire != plan.prepare(original):
            raise ProviderStop("UNREVIEWED_WIRE_OR_PROMPT_CHANGE")
        admitted = False
        for row in inventory:
            canonical = read(self.root / "requests" / (row["id"] + "-canonical.json"))
            prepared = read(self.root / "requests" / (row["id"] + "-wire.json"))
            if (
                fingerprint(canonical) != row["canonical_request_sha256"]
                or fingerprint(prepared) != row["wire_request_sha256"]
            ):
                raise ProviderStop("WIRE_PREFLIGHT_REQUEST_DRIFT")
            compiled = compile_contract(canonical["response_format"]["json_schema"]["schema"])
            if prepared != compiled.prepare(canonical) or row["contract"] != compiled.manifest():
                raise ProviderStop("PREFLIGHT_COMPILER_BINDING_DRIFT")
            if (
                canonical["response_format"]["json_schema"]["schema"] == plan.canonical
                and prepared["response_format"]["json_schema"]["schema"] == plan.wire
                and request_profile(original) == request_profile(canonical)
            ):
                admitted = True
        if not admitted:
            raise ProviderStop("UNVALIDATED_CANONICAL_WIRE_PAIR_OR_OPTIONS")
