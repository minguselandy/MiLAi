"""One cold residual-boundary HTTP observation, without a business executor."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from v02_local_provider import read_events
from v0220_evidence import save
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_boundary_audit import validate_reference
from v0222_boundary_batch import Batch
from v0222_boundary_contract import observe
from v0222_boundary_transport import Transport


def run(root: Path, binding: str, episode: str) -> dict:
    batch = Batch(root, binding)
    batch.claim(episode)
    spec = next(s for s in batch.plan["episodes"] if s["id"] == episode)
    reference = next(r for r in batch.references() if r["episode"] == episode)
    canonical, wire, _ = validate_reference(batch, reference, spec)
    expected_hash = fingerprint(wire)

    def validate_actual(body):
        if fingerprint(body) != expected_hash:
            raise ProviderStop("BOUNDARY_ACTUAL_WIRE_NOT_FROZEN_REFERENCE")

    directory = root / "episodes" / episode
    provider = Transport(
        directory / "provider", batch=batch, episode=episode, preflight=validate_actual
    )
    try:
        provider.verify()
        raw = provider.generate(episode, wire)
        result = observe(
            spec["expected"], canonical["response_format"]["json_schema"]["schema"], raw
        )
        key = next(
            e["request_id"] for e in read_events(provider.ledger) if e["event"] == "RESERVED"
        )
        result.update(
            id=episode,
            root=spec["root"],
            cold=spec["cold"],
            condition=spec["condition"],
            request_id=key,
            http_usage_audit="PASS",
            business_dispatches=0,
            pid=os.getpid(),
        )
        save(directory / "observation.json", result)
        return result
    finally:
        provider.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--episode", required=True)
    args = parser.parse_args()
    try:
        print(run(args.root, args.binding_sha256, args.episode))
    except Exception as exc:
        code = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        Batch(args.root, args.binding_sha256).stop(code)
        print(code, flush=True)
        raise SystemExit(1) from None
