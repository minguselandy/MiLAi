"""Owned release-pinned Product Note seed/cold read/isolation, with zero model requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from check_v0210_control import verify_baseline
from milai_lab.product_adapter.manifest import (
    ProductLock,
    PublicInterfacePin,
    digest_paths,
    load_product_lock,
    verify_product_lock,
)
from run_v0212_horizon import product
from v0210_v05_product import observer
from v0218_memory import content_digest, read_note, save_note

LAB = Path(__file__).resolve().parents[1]


def save(path: Path, value: dict):
    path.write_text(json.dumps(value, indent=2))


def freeze_delivery(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    source = LAB.parent / "MiLAi-Product"
    historical = json.loads((LAB / "configs/v0210-control-e1.json").read_text())
    receipt = verify_baseline(historical)
    shutil.copyfile(
        source / "integrations/mcp/dist/delivery/v0209-final/milai-mcp-delivery-0.1.15.tar.gz",
        root / "delivery.tar.gz",
    )
    contracts = root / "public-contracts"
    contracts.mkdir()
    shutil.copyfile(
        source / "contracts/mcp/compact-memory-v1.release-0.1.15.tools.json",
        contracts / "compact-memory-v1.release-0.1.15.tools.json",
    )
    lock = ProductLock(
        schema_version=1,
        product_name="MiLAi-Product-immutable-delivery",
        product_version="Runtime0.1.4-MCP0.1.15-Client0.1.3",
        repository=".",
        git_commit=None,
        tree_paths=("delivery.tar.gz", "public-contracts"),
        tree_sha256=digest_paths(root, ("delivery.tar.gz", "public-contracts")),
        public_interfaces=(
            PublicInterfacePin(
                "compact-memory-v1-release-0.1.15",
                "public-contracts",
                digest_paths(root, ("public-contracts",)),
            ),
        ),
    )
    save(root / "product.lock.json", lock.to_dict())
    verified = verify_product_lock(lock, root).to_dict()
    assert verified["valid"]
    save(
        root / "verification.json",
        {
            "artifact_verification": verified,
            "historical_delivery_identity": receipt,
            "source_worktree_verification": "GLOBAL_LOCK_DRIFT_PRESERVED_NOT_USED_AS_RUNTIME",
            "execution_link": "Product launcher re-verifies installed .py bytes "
                "against every delivered wheel",
        },
    )
    return verified


def worker(root: Path, owned: Path, operation: str):
    directory = root / operation
    directory.mkdir()
    scope = "v0218-persistence-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    effective = scope if operation != "cross-scope" else scope + "-other"
    calls = []
    with observer(
        owned, directory / "mcp", task=effective, principal=effective, project=effective
    ) as public:

        def call(name, arguments):
            response = public(name, arguments)
            calls.append({"tool": name, "arguments": arguments, "response": response})
            return response

        if operation == "seed":
            expected = json.loads((root / "pinned-delivery/public-contracts/"
                "compact-memory-v1.release-0.1.15.tools.json").read_text())["catalogs"][
                    "compact-memory-v1"]["tools"]
            actual = call(None, {})["tools"]["tools"]
            assert {item["name"]: item["inputSchema"] for item in actual} == {
                item["name"]: item["inputSchema"] for item in expected}
            text = "T2 synthetic transport fixture, not Agent-authored. " + "版本核验\n" * 2200
            committed = save_note(call, text, scope + "-seed")
            save(directory / "committed.json", committed)
            result = {
                "status": "HARNESS_SEED_COMMITTED",
                "content_digest": content_digest(text),
                "version": committed["version"],
                "memory_id": committed["memory_id"],
            }
        else:
            committed = json.loads((root / "seed/committed.json").read_text())
            if operation == "cold-read":
                result = read_note(call, committed)
                assert len(result["pages"]) >= 2
                result.pop("content")
                result.pop("pages")
            else:
                result = call(
                    "milai_memory_read",
                    {
                        "target": {
                            "kind": "NOTE",
                            "id": committed["memory_id"],
                            "version": committed["version"],
                        }
                    },
                )
                assert result.get("mcp_error")
                result = {"status": "CROSS_SCOPE_PUBLIC_READ_DENIED"}
    result.update(pid=os.getpid(), model_requests=0, agent_memory_writes=0)
    save(directory / "result.json", result)
    save(directory / "public-calls.json", {"calls": calls})


def run(root: Path, installed: Path):
    root.mkdir(parents=True, exist_ok=False)
    global_check = verify_product_lock(
        load_product_lock(LAB / "product.lock.json"), LAB.parent / "MiLAi-Product"
    ).to_dict()
    save(root / "global-pin-diagnostic.json", global_check)
    pin = freeze_delivery(root / "pinned-delivery")
    rows = []
    try:
        with product(root / "product", installed) as owned:
            for operation in ("seed", "cold-read", "cross-scope"):
                subprocess.run(  # noqa: S603 -- own reviewed zero-model child, exact arguments
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--root",
                        str(root),
                        "--owned",
                        str(owned),
                        "--worker",
                        operation,
                    ],
                    check=True,
                    timeout=90,
                    cwd=LAB,
                )
                row = json.loads((root / operation / "result.json").read_text())
                row["child_process_exited_before_next"] = True
                rows.append(row)
        result = {
            "status": "T2_PUBLIC_NOTE_COLD_TRANSPORT_VERIFIED_NO_AGENT_PRESENTATION",
            "rows": rows,
            "run_specific_product_lock": pin,
            "model_requests": 0,
            "harness_note_writes": 1,
            "agent_note_writes": 0,
            "actual_model_presentation": 0,
            "carrier": "PUBLIC_NOTE_CRUD_NOT_WORKING_STATE",
            "cleanup": json.loads((root / "product/cleanup.json").read_text()),
        }
    except Exception as exc:
        result = {
            "status": "T2_INCOMPLETE_PRESERVED",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "rows": rows,
            "model_requests": 0,
        }
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--installed", type=Path)
    parser.add_argument("--owned", type=Path)
    parser.add_argument("--worker", choices=["seed", "cold-read", "cross-scope"])
    args = parser.parse_args()
    if args.worker:
        worker(args.root, args.owned, args.worker)
    else:
        print(json.dumps(run(args.root, args.installed)))
