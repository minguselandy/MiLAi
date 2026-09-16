"""Cold V1 scripted-provider fixture only; never an experimental model entry point."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from v0218_world import World
from v0220_evidence import read, save, sha, validate
from v0220_session import Session


class ScriptedProvider:
    def __init__(self, directory: Path, outputs: list[str]):
        self.directory, self.outputs = directory, iter(outputs)
        self.requests = 0

    def verify(self):
        return {"kind": "SCRIPTED_ZERO_MODEL_FIXTURE_NOT_MODEL_IDENTITY_VERIFICATION"}

    def generate(self, episode: str, body: dict) -> str:
        self.requests += 1
        output = next(self.outputs)
        save(
            self.directory / f"scripted-provider-{self.requests:02d}.json",
            {"body": body, "raw": output, "kind": "SCRIPTED_NOT_HTTP_NOT_MODEL"},
        )
        return output

    def close(self):
        pass


def run(path: Path, expected: str) -> dict:
    def binding():
        if sha(path) != expected:
            raise ValueError("CONFIG_DRIFT")
        validate(Path(config["batch"]), manifest_sha256=config["manifest_sha256"])

    if sha(path) != expected:
        raise ValueError("CONFIG_DRIFT")
    config = read(path)
    binding()
    if config["stage"] != "V1_SCRIPTED_HOST_FIXTURE":
        raise ValueError("NO_REAL_PROVIDER_AUTHORITY")
    world = World(Path(config["world"]), config["scope"])
    directory = Path(config["output"])
    host = Session(
        world,
        directory,
        episode_id=config["episode_id"],
        profile=config["profile"],
        arm=config["arm"],
        intent=config["intent"],
        validate_binding=binding,
    )
    provider = ScriptedProvider(directory, config["outputs"])
    result = host.run(provider, deadline=time.monotonic() + 30)
    # Harness-only independent post-session durable read; never a tool/checker answer.
    snapshot = World(world.path, world.scope).snapshot()
    save(directory / "actual-world.json", snapshot)
    save(directory / "actual-ledger.json", world.ledger())
    result.update(
        pid=os.getpid(),
        scripted_generations=provider.requests,
        experimental_model_requests=0,
        judge_requests=0,
        usage="N/A_SCRIPTED_PROVIDER_NO_MODEL",
        actual_record_count=len(snapshot["records"]),
        actual_world_version=snapshot["version"],
        ledger_rows=len(world.ledger()),
    )
    save(directory / "fixture-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args()
    try:
        run(args.config, args.config_sha256)
    except Exception as exc:
        print(type(exc).__name__)  # No raw config, private values or exception body.
        raise SystemExit(1) from None
