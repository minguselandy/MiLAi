"""V1 zero-model subprocess fixture executor. Never used as a natural/model Host."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from v0218_world import World, digest
from v0220_action_adapter import ActionAdapter
from v0220_action_contract import ActionContract, ContractError
from v0220_evidence import read, save, sha, validate


def run(config_path: Path, expected_sha256: str) -> dict:
    if sha(config_path) != expected_sha256:
        raise ValueError("CONFIG_DRIFT")
    config = read(config_path)
    validate(Path(config["batch"]), manifest_sha256=config["manifest_sha256"])
    public = read(Path(config["public"]))
    world = World(Path(config["world"]), config["scope"])
    adapter = ActionAdapter(world, ActionContract.from_public(public))
    before = digest(world.snapshot())
    mode = config["mode"]
    if mode in {"crash_before_effect", "crash_after_effect"}:
        original = world.act

        def crash(**kwargs):
            if mode == "crash_after_effect":
                original(**kwargs)
            os._exit(71)  # Deliberate fixture process loss; no finally/client response.

        world.act = crash
        adapter.execute(config["action"], operation_id=config["operation_id"])
        raise AssertionError("CRASH_NOT_EXERCISED")
    if mode == "execute":
        response = adapter.execute(config["action"], operation_id=config["operation_id"])
    elif mode == "decode_execute":
        try:
            action = adapter.contract.decode(config["raw"])
        except ContractError as exc:
            response = adapter.rejected(exc.code, operation_id=None, path=exc.path, rule=exc.rule)
        else:
            response = adapter.execute(action, operation_id=config["operation_id"])
    elif mode == "read":
        response = adapter.read(config["resource"])
    elif mode == "query":
        response = adapter.operation_status(config["operation_id"])
    elif mode == "acknowledge":
        response = adapter.acknowledge_committed_operation(config["operation_id"])
    else:
        raise ValueError("FIXTURE_MODE_NOT_ALLOWED")
    result = {
        "pid": os.getpid(),
        "mode": mode,
        "response": response,
        "before_sha256": before,
        "after_sha256": digest(world.snapshot()),
        "world_version": world.snapshot()["version"],
        "ledger_rows": len(world.ledger()),
        "unresolved": adapter.journal.unresolved(),
        "model_requests": 0,
    }
    save(Path(config["output"]), result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args()
    run(args.config, args.config_sha256)
