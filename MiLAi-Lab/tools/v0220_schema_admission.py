"""Exact full-schema CPU gate for prospective diagnostics, not a live-generation PASS."""

from __future__ import annotations

from pathlib import Path

from v0220_evidence import read, sha, validate
from v0220_provider_hardened import ProviderStop


class FullSchemaPreflight:
    def __init__(self, root: Path, *, hashes: dict[str, str]):
        required = {"manifest.json", "result.json", "inventory.json", "probes.json"}
        if set(hashes) != required:
            raise ProviderStop("COMPLETE_PREFLIGHT_HASH_BINDING_REQUIRED")
        self.root, self.hashes = root, dict(hashes)

    def __call__(self, body: dict) -> None:
        if any(sha(self.root / name) != value for name, value in self.hashes.items()):
            raise ProviderStop("PREFLIGHT_EVIDENCE_DRIFT")
        manifest = validate(self.root)
        result, inventory = read(self.root / "result.json"), read(self.root / "inventory.json")
        roots = manifest["contract"]["roots"]
        if (
            len(roots) != 4
            or len(set(roots)) != 4
            or manifest["contract"].get("no_schema_lowering_or_target_filtering") is not True
            or result.get("unchanged_public_contract") is not True
        ):
            raise ProviderStop("FULL_FOUR_ROOT_CONTRACT_REQUIRED")
        expected = {r + suffix for r in roots for suffix in ("-full", "-finish")}
        rows = result["rows"]
        if len(rows) != 8 or {r["id"] for r in rows} != expected:
            raise ProviderStop("INCOMPLETE_FULL_SCHEMA_MATRIX")
        if any(r["status"] != "PASS_CPU_ONLY" for r in rows):
            raise ProviderStop("FULL_SCHEMA_PROVIDER_INCOMPATIBLE_NO_DISPATCH")
        if len(inventory) != 8 or {r["id"] for r in inventory} != expected:
            raise ProviderStop("INCOMPLETE_FULL_SCHEMA_INVENTORY")
        schemas = []
        for row in inventory:
            request = self.root / "requests" / (row["id"] + ".json")
            if sha(request) != row["request_sha256"]:
                raise ProviderStop("PREFLIGHT_REQUEST_DRIFT")
            schemas.append(read(request)["response_format"]["json_schema"]["schema"])
        if body["response_format"]["json_schema"]["schema"] not in schemas:
            raise ProviderStop("UNVALIDATED_SCHEMA_NO_DISPATCH")
