"""Public Working State round trip of an actually generated native experience bank.

Reuse the existing owned Product lifecycle and checkpoint implementation. These
two child processes make no model calls and never replay benchmark actions.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from contextlib import closing
from pathlib import Path

from milai_lab.methods.reasoning_bank import BankConfig, ExperienceBank
from run_workspace_public_checkpoint import LAB, SDK, TracedClient, run
from workspace_checkpoint import WorkingStateCheckpoint, atomic_json, canonical


def child(root: Path, phase: str, bank_file: Path):
    from milai_client import MilaiClient

    assert Path(importlib.util.find_spec("milai_client").origin).resolve() == (
        SDK / "src/milai_client/__init__.py"
    )
    binding = {
        "principal_binding_digest": hashlib.sha256(root.name.encode()).hexdigest(),
        "project_id": "reasoningbank-native-lifecycle",
        "scope_type": "TASK",
        "scope_ref": root.name,
    }
    with closing(
        MilaiClient(
            base_url=os.environ["MILAI_BASE_URL"],
            token=os.environ["MILAI_API_TOKEN"],
            max_retries=0,
        )
    ) as sdk:
        client = TracedClient(sdk, root / "sdk-events.jsonl")
        port = WorkingStateCheckpoint(
            client, binding=binding, journal=root / "checkpoint-journal.json"
        )
        if phase == "save":
            artifact = json.loads(bank_file.read_text())
            bank = ExperienceBank.restore(
                artifact, scope=artifact["scope"], contract=artifact["contract"]
            )
            assert bank.records and bank.cards
            config = BankConfig(**bank.contract["config"])
            vector = bank.records[-1]["embedding"]
            receipt = port.save(artifact, operation_id="save-generated-native-bank")
            atomic_json(
                root / "saved.json",
                {
                    "pid": os.getpid(),
                    "version": receipt["version"],
                    "artifact_sha256": hashlib.sha256(canonical(artifact)).hexdigest(),
                    "source_artifact": str(bank_file),
                    "scope": bank.scope,
                    "contract": bank.contract,
                    "query_vector": vector,
                    "expected_retrieval": bank.select(vector, config),
                    "cards": len(bank.cards),
                    "records": len(bank.records),
                    "sources": len(bank.sources),
                    "historical_cards": len(bank.historical_cards),
                    "model_http_calls": 0,
                },
            )
            return
        saved = json.loads((root / "saved.json").read_text())
        assert saved["pid"] != os.getpid()
        artifact = port.load()  # No local bank-file fallback in this process.
        assert hashlib.sha256(canonical(artifact)).hexdigest() == saved["artifact_sha256"]
        bank = ExperienceBank.restore(artifact, scope=saved["scope"], contract=saved["contract"])
        handles = bank.select(saved["query_vector"], BankConfig(**bank.contract["config"]))
        assert handles == saved["expected_retrieval"]
        assert all(
            ref in bank.sources for handle in handles for ref in bank.cards[handle].source_refs
        )
        atomic_json(root / "restored-bank.json", artifact)
        atomic_json(
            root / "resumed.json",
            {
                "pid": os.getpid(),
                "different_process": True,
                "transport": "PUBLIC_SDK_HTTP",
                "all_bank_bytes_preserved": True,
                "retrieval_preserved": True,
                "source_references_readable": True,
                "retrieved_handles": handles,
                "cards": len(bank.cards),
                "records": len(bank.records),
                "model_http_calls": 0,
                "local_checkpoint_fallback": False,
                "benchmark_actions_replayed": 0,
            },
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument(
        "--lock", type=Path, default=LAB / "data/locks/workspace-rwc-repair-product.lock.json"
    )
    parser.add_argument("--phase", choices=["save", "resume"])
    parser.add_argument("--method", default="RESEARCH_EXPERIENCE_BANK")
    args = parser.parse_args()
    if args.phase:
        child(args.root, args.phase, args.bank)
    else:
        run(
            args.root,
            args.lock,
            method="RESEARCH_EXPERIENCE_BANK",
            child_script=Path(__file__),
            child_phases=("save", "resume"),
            child_interpreter=LAB / ".venv/bin/python",
            child_arguments=("--bank", str(args.bank)),
        )


if __name__ == "__main__":
    main()
