"""P3 validate-only or P4 original Session, one cold process per frozen position."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from v0218_world import World
from v0220_evidence import read, save
from v0220_provider_hardened import ProviderStop
from v0220_session import PROFILES, Session
from v0222_batch import Batch
from v0222_full_provider import FullProvider, resolved_spec


def run(root: Path, binding: str, episode: str) -> dict:
    batch = Batch(root, binding)
    batch.claim(episode)
    spec = resolved_spec(batch, episode)
    directory = root / "episodes" / episode
    if spec["stage"] == "P3":
        row = next(r for r in batch.references("P3") if r["episode"] == episode)
        provider = FullProvider(directory / "provider", batch=batch, episode=episode)
        try:
            provider.verify()
            raw = provider.generate(episode, read(Path(row["canonical"])))
            result = {
                "status": "VALIDATE_ONLY_PASS",
                "raw": raw,
                "business_dispatches": 0,
                "notebook_writes": 0,
            }
        finally:
            provider.close()
    elif spec["stage"] == "P4":
        if PROFILES["INTENT_ORACLE"]["ORACLE"] != 4:
            raise ProviderStop("FOUR_ROUND_SESSION_CONTRACT_CHANGED")
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
            validate_binding=lambda: batch.authorize("P4"),
        )
        save(directory / "initial-world.json", world.snapshot())
        provider = FullProvider(directory / "provider", batch=batch, episode=episode, world=world)
        result = host.run(provider, deadline=provider.provider.deadline)
        save(directory / "final-world.json", world.snapshot())
        save(directory / "final-ledger.json", world.ledger())
        result["unresolved_operations"] = host.adapter.journal.unresolved()
    else:
        raise ProviderStop("WRONG_FULL_STAGE")
    result["pid"] = os.getpid()
    save(directory / "worker-result.json", result)
    return result


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
