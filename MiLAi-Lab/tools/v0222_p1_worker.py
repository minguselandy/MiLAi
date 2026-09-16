"""One cold P1 HTTP client; intentionally no Session, World or dispatcher."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from v02_local_provider import read_events
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_batch import Batch
from v0222_diagnostic import observe, request
from v0222_transport import Transport


def run(root: Path, binding: str, episode: str) -> dict:
    batch = Batch(root, binding)
    batch.claim(episode)
    spec = next(s for s in batch.plan["P1"] if s["id"] == episode)
    row = next(r for r in batch.references("P1") if r["episode"] == episode)
    for kind in ("canonical", "wire", "output"):
        if sha(Path(row[kind])) != row["hashes"][kind]:
            raise ProviderStop("FROZEN_REFERENCE_DRIFT")
    canonical, body = request(spec["fixture"], spec["condition"])
    if fingerprint(canonical) != fingerprint(read(Path(row["canonical"]))) or fingerprint(
        body
    ) != fingerprint(read(Path(row["wire"]))):
        raise ProviderStop("FROZEN_CONTRAST_DRIFT")
    expected_wire_hash = fingerprint(body)

    def verify_wire(wire):
        if fingerprint(wire) != expected_wire_hash:
            raise ProviderStop("UNFROZEN_DIAGNOSTIC_REQUEST")

    directory = root / "episodes" / episode
    provider = Transport(
        directory / "provider", batch=batch, episode=episode, preflight=verify_wire
    )
    try:
        provider.verify()
        raw = provider.generate(episode, body)
        observation = observe(raw, spec["fixture"])
        events = read_events(provider.ledger)
        key = next(e["request_id"] for e in events if e["event"] == "RESERVED")
        result = {
            **observation,
            "id": episode,
            "request_id": key,
            "http_usage_audit": "PASS",
            "pid": os.getpid(),
        }
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
