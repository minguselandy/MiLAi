"""Separate CPU scopes with the complete original 16+80 reference materializer.

Neither importing nor deriving a plan grants live authority or creates a batch.
Actual preparation requires the fixed CPU contract and an already installed
socket guard. The original Session, World and reference audit are unchanged.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from prepare_v0221_http_v2 import CASES
from prepare_v0222_full import resolve_p4_spec
from prepare_v0222_presentation_v2 import materialize_references
from v0220_provider_hardened import ProviderStop
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_batch_v2 import PRESENTATION_ROOT
from v0222_presentation_lineage_v2 import read_inventory
from v0222_scoped_cpu_batch import OfflineBatch as Batch
from v0222_scoped_cpu_guard import require_cpu_network_guard
from v0222_scoped_cpu_worker import stop_batch


def episode_specs(scope: AdmissionReadScope) -> dict:
    """Derive only IDs/scopes and their initial hashes from pinned old bytes.

    Caller owns scope close and a separate full verify_lineage(scope). Reading
    the inventory here is not history verification or permission to execute.
    """
    inventory = read_inventory(scope)
    binding_path = PRESENTATION_ROOT / "execution-binding.json"
    binding = scope.read_json(binding_path, inventory["files"][str(binding_path)])
    manifest = scope.read_json(PRESENTATION_ROOT / "manifest.json", binding["manifest.json"])
    plan = {}
    for stage, count in (("P3", 16), ("P4", 24)):
        original = manifest["contract"][stage]
        if len(original) != count:
            raise ProviderStop("COMPLETE_ORIGINAL_16_PLUS_24_MATRIX_REQUIRED")
        plan[stage] = []
        for index, source in enumerate(original, 1):
            spec = copy.deepcopy(source)
            spec["id"] = f"cpu-{stage.lower()}-{index:02d}"
            spec["scope"] = f"v0222-cpu-20260912-{spec['id']}"
            if stage == "P4":
                path = CASES / spec["root"] / "public-initial.json"
                public = scope.read_json(path, manifest["inputs"][str(path)])
                spec, _ = resolve_p4_spec(spec, public)
            plan[stage].append(spec)
    return plan


def prepare(root: Path, binding: str) -> dict:
    require_cpu_network_guard()
    batch = None
    try:
        batch = Batch(root, binding)
        return materialize_references(batch)
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        raise


def main():
    require_cpu_network_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    args = parser.parse_args()
    result = prepare(args.root, args.binding_sha256)
    print({key: value for key, value in result.items() if key != "files"})
    return 0 if result["status"] == "REFERENCE_PREPARATION_PASS" else 1
