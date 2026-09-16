"""One cold P3 validation or original P4 Session for the frozen B1 candidate."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from v0218_world import World
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_session import PROFILES, Session
from v0222_presentation_batch import ROOT, Batch
from v0222_presentation_provider import FullProvider

CASES = Path("/cra/memory/mx_memory/evidence/v0219/f2-wave1-v1/cases")


def stop_batch(root: Path, binding: str, batch, exc: BaseException) -> None:
    """Preserve the first stop even if normal construction can no longer authorize."""
    reason = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
    if batch is None:
        # Do not construct/re-authorize, create a DB, or touch a different root.
        if root.resolve() != ROOT or sha(root / "execution-binding.json") != binding:
            return
        batch = Batch.__new__(Batch)
        batch.root, batch.path, batch.binding_sha = (
            root.resolve(),
            root.resolve() / "batch.sqlite",
            binding,
        )
    batch.stop(reason)  # mode=rw + the journal's exact binding check still apply.


def run(root: Path, binding: str, episode: str) -> dict:
    batch, provider = None, None
    try:
        batch = Batch(root, binding)
        batch.claim(episode)
        spec = batch.spec(episode)
        directory = root / "episodes" / episode
        if spec["stage"] == "P3":
            row = next(r for r in batch.references("P3") if r["episode"] == episode)
            provider = FullProvider(directory / "provider", batch=batch, episode=episode)
            provider.verify()
            raw = provider.generate(episode, read(Path(row["canonical"])))
            result = {
                "status": "VALIDATE_ONLY_PASS",
                "raw": raw,
                "business_dispatches": 0,
                "notebook_writes": 0,
            }
        elif spec["stage"] == "P4":
            if PROFILES["INTENT_ORACLE"]["ORACLE"] != 4:
                raise ProviderStop("FOUR_ROUND_SESSION_CONTRACT_CHANGED")
            public = read(CASES / spec["root"] / "public-initial.json")
            world = World.create(root / "worlds" / (episode + ".sqlite"), spec["scope"], public)
            host = Session(
                world,
                directory,
                episode_id=episode,
                profile="INTENT_ORACLE",
                arm="ORACLE",
                intent=spec["intent"],
                validate_binding=lambda: batch.admit(episode),
            )
            save(directory / "initial-world.json", world.snapshot())
            provider = FullProvider(
                directory / "provider", batch=batch, episode=episode, world=world
            )
            result = host.run(provider, deadline=provider.provider.deadline)
            if (
                result.get("status") != "SESSION_FINISHED_NOT_TASK_VERDICT"
                or result.get("close_exception_type")
                or host.adapter.journal.unresolved()
            ):
                raise ProviderStop("PRESENTATION_SESSION_NOT_CLEANLY_FINISHED")
            save(directory / "final-world.json", world.snapshot())
            save(directory / "final-ledger.json", world.ledger())
            result["unresolved_operations"] = []
        else:
            raise ProviderStop("WRONG_PRESENTATION_FULL_STAGE")
        # Close before success persistence; a close failure is never a PASS.
        provider.close()
        batch.admit(episode)
        result["pid"] = os.getpid()
        save(directory / "worker-result.json", result)
        return result
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        raise
    finally:
        if provider is not None:
            try:
                provider.close()
            except BaseException as exc:
                stop_batch(root, binding, batch, exc)
                raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--episode", required=True)
    args = parser.parse_args()
    run(args.root, args.binding_sha256, args.episode)
