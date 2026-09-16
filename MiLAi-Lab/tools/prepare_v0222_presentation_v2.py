"""New-scope plan derivation and complete offline reference preparation.

Reuse the frozen 16+80 materializer and original Session/World/auditor. This
entry neither creates an authorization nor launches a model stage. The caller
must separately freeze a new instance and obtain its complete scope review.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from prepare_v0221_http_v2 import CASES
from prepare_v0222_full import resolve_p4_spec
from prepare_v0222_presentation import materialize_references as original_materialize
from v0220_provider_hardened import ProviderStop
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_batch_v2 import PRESENTATION_ROOT
from v0222_presentation_finish_v2 import Batch
from v0222_presentation_lineage_v2 import read_inventory
from v0222_presentation_worker_v2 import stop_batch


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
            spec["id"] = f"scoped-{stage.lower()}-{index:02d}"
            spec["scope"] = f"v0222-scoped-20260912-{spec['id']}"
            if stage == "P4":
                path = CASES / spec["root"] / "public-initial.json"
                public = scope.read_json(path, manifest["inputs"][str(path)])
                spec, _ = resolve_p4_spec(spec, public)
            plan[stage].append(spec)
    return plan


class _PreparationView:
    """Explicit facade, not a replacement of any frozen module's globals.

    Old materialization guards call authorize many times. Here each guard also
    freshly checks the current journal/stop, in a scope that ends before the
    original reference Session runs. Secondary stop failure cannot replace the
    materializer's original failure.
    """

    def __init__(self, batch):
        self.batch = batch
        self.stop_errors = []

    @property
    def root(self):
        return self.batch.root

    @property
    def plan(self):
        return copy.deepcopy(self.batch.plan)

    def authorize(self, stage):
        if stage != "PREP":
            raise ProviderStop("REFERENCE_PREPARATION_CANNOT_AUTHORIZE_MODEL_STAGE")
        with self.batch._operation("PREP"):
            pass

    def spec(self, episode):
        return self.batch.spec(episode)

    def freeze_artifact(self, name, path, status=None):
        return self.batch.freeze_artifact(name, path, status)

    def stop(self, reason):
        try:
            self.batch.stop(reason)
        except BaseException as secondary:
            self.stop_errors.append(type(secondary).__name__)


def materialize_references(batch) -> dict:
    view = _PreparationView(batch)
    try:
        return original_materialize(view)
    except BaseException as exc:
        # Includes failures before the old materializer's try (initial guard
        # and fresh directory creation), without masking the original cause.
        view.stop(str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__)
        for name in view.stop_errors:
            exc.add_note("SECONDARY_PREPARATION_STOP_FAILURE: " + name)
        raise


def prepare(root: Path, binding: str) -> dict:
    batch = None
    try:
        batch = Batch(root, binding)
        return materialize_references(batch)
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    args = parser.parse_args()
    result = prepare(args.root, args.binding_sha256)
    print({key: value for key, value in result.items() if key != "files"})
    return 0 if result["status"] == "REFERENCE_PREPARATION_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
