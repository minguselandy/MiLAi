"""Fresh-process V2 actor: public World plus explicitly authorized current Oracle intent."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from v02_local_provider import accounting, read_events
from v0213_provider import Provider
from v0218_world import World, digest
from v0220_evidence import save, validate
from v0220_session import Session


def run(root: Path, manifest_sha: str, episode_id: str) -> dict:
    started = time.monotonic()
    manifest = validate(root, manifest_sha256=manifest_sha)
    contract = manifest["contract"]
    if contract["stage"] != "V2_INTENT_ORACLE" or contract["candidate"] != 1:
        raise ValueError("V2_CANDIDATE_NOT_AUTHORIZED")
    matches = [s for s in contract["episodes"] if s["id"] == episode_id]
    if len(matches) != 1:
        raise ValueError("EPISODE_NOT_AUTHORIZED")
    spec = matches[0]
    world = World(root / "worlds" / f"{episode_id}.sqlite", spec["scope"])
    if digest(world.snapshot()) != spec["initial_state_sha256"] or world.ledger():
        raise ValueError("FRESH_FROZEN_WORLD_REQUIRED")
    deadline = started + 300
    directory = root / "episodes" / episode_id
    host = Session(
        world,
        directory,
        episode_id=episode_id,
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent=spec["intent"],
        validate_binding=lambda: validate(root, manifest_sha256=manifest_sha),
    )
    save(directory / "initial-world.json", world.snapshot())
    result = host.run(Provider(directory, deadline=deadline, max_requests=4), deadline=deadline)
    save(directory / "final-world.json", World(world.path, world.scope).snapshot())
    save(directory / "final-ledger.json", world.ledger())
    result.update(
        pid=os.getpid(),
        seconds=time.monotonic() - started,
        cost=accounting(read_events(directory / "provider-ledger.jsonl")),
        unresolved_operations=host.adapter.journal.unresolved(),
    )
    save(directory / "worker-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--episode", required=True)
    args = parser.parse_args()
    try:
        run(args.root, args.manifest_sha256, args.episode)
    except Exception as exc:
        print(type(exc).__name__)
        raise SystemExit(1) from None
