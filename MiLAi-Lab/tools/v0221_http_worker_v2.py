"""One cold client/episode; W2 validate-only or frozen Session W3. HTTP only."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from v0218_world import World
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_session import Session
from v0220_wire_contract import compile_contract
from v0221_http_admission_v2 import AuthorizedWireProviderV2 as AuthorizedWireProvider
from v0221_http_batch import Batch


def run(root: Path, binding: str, episode: str) -> dict:
    batch = Batch(root, binding)
    batch.claim(episode)
    spec = next(s for s in [*batch.plan["W2"], *batch.plan["W3"]] if s["id"] == episode)
    directory = root / "episodes" / episode
    if spec["stage"] == "W2":
        directory.mkdir(parents=True, exist_ok=False)
        reference = next(r for r in batch.references() if r["episode"] == episode)
        path = Path(reference["canonical"])
        if sha(path) != reference["hashes"]["canonical"]:
            raise ValueError("FROZEN_W2_REQUEST_DRIFT")
        body = read(path)
        provider = AuthorizedWireProvider(directory / "provider", batch=batch, episode=episode)
        try:
            provider.verify()
            raw = provider.generate(episode, body)
            value = compile_contract(
                body["response_format"]["json_schema"]["schema"]
            ).validate_output(raw)
            if spec["variant"] == "full" and value != spec["expected"]:
                raise ProviderStop("LEGAL_JSON_INTENT_FIDELITY_FAILURE")
            result = {
                "status": "VALIDATE_ONLY_PASS",
                "pid": os.getpid(),
                "business_dispatches": 0,
                "notebook_writes": 0,
                "raw": raw,
            }
        finally:
            provider.close()
    else:
        public = read(
            Path("/cra/memory/mx_memory/evidence/v0219/f2-wave1-v1/cases")
            / spec["root"]
            / "public-initial.json"
        )
        world = World.create(root / "worlds" / (episode + ".sqlite"), spec["scope"], public)
        host = Session(
            world,
            directory,
            episode_id=episode,
            profile="INTENT_ORACLE",
            arm="ORACLE",
            intent=spec["intent"],
            validate_binding=lambda: batch.authorize("W3"),
        )
        save(directory / "initial-world.json", world.snapshot())
        provider = AuthorizedWireProvider(
            directory / "provider",
            batch=batch,
            episode=episode,
            intent_actions=spec["actions"],
            world=world,
        )
        result = host.run(provider, deadline=provider.provider.deadline)
        save(directory / "final-world.json", world.snapshot())
        save(directory / "final-ledger.json", world.ledger())
        result.update(pid=os.getpid(), unresolved_operations=host.adapter.journal.unresolved())
    save(directory / "worker-result.json", {**result, "completed_unix": time.time()})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--episode", required=True)
    args = parser.parse_args()
    try:
        run(args.root, args.binding_sha256, args.episode)
    except Exception as exc:
        code = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        Batch(args.root, args.binding_sha256).stop(code)
        print(code, flush=True)
        raise SystemExit(1) from None
