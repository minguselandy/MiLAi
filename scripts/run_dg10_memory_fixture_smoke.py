from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.agent_integration import e2e
from scripts import dg10_memory_fixture as fixture
from scripts import dg10_remediation as remediation
from scripts import dg10_runtime_fixture as runtime_fixture

DEFAULT_OUTPUT = ROOT / "docs/reports/DG-10-memory-fixture-ingest-ledgered-candidate.4-2026-08-22.json"
DEFAULT_CAPTURE_DIRECTORY = ROOT.parent / "evidence/dg10-remediation-memory-fixture"
DEFAULT_ENV_FILE = ROOT / "runtime/.env"


class WordCounter:
    def count(self, text: str) -> int:
        return len(text.split())


def _synthetic_sessions() -> tuple[fixture.CorpusSession, ...]:
    return (
        fixture.CorpusSession(
            session_id="planning-session",
            observed_at="2026-08-20T09:00:00+00:00",
            turns=(
                fixture.SessionTurn(
                    "user",
                    "The lighthouse migration deployment window was proposed for Tuesday morning.",
                ),
                fixture.SessionTurn(
                    "assistant",
                    "The Tuesday window is only a proposal and is not yet final.",
                ),
            ),
        ),
        fixture.CorpusSession(
            session_id="decision-session",
            observed_at="2026-08-21T09:00:00+00:00",
            turns=(
                fixture.SessionTurn(
                    "user",
                    "What is the latest approved deployment window for the lighthouse migration?",
                ),
                fixture.SessionTurn(
                    "assistant",
                    "Confirmed: Thursday afternoon is the latest approved deployment window.",
                ),
            ),
        ),
    )


def _latest_snapshots(objects: tuple[fixture.GovernedObject, ...]) -> list[dict[str, str]]:
    return [
        {
            "session_id": item.session_id,
            "evidence_id_sha256": hashlib.sha256(item.evidence_id.encode()).hexdigest(),
            "proposal_id_sha256": hashlib.sha256(item.proposal_id.encode()).hexdigest(),
            "decision_id_sha256": hashlib.sha256(item.decision_id.encode()).hexdigest(),
            "claim_id_sha256": hashlib.sha256(item.claim_id.encode()).hexdigest(),
            "claim_version_id_sha256": hashlib.sha256(item.claim_version_id.encode()).hexdigest(),
        }
        for item in objects
    ]


def run(*, output: Path, capture_directory: Path, env_file: Path) -> dict[str, Any]:
    e2e._load_environment_file(env_file.resolve())
    source = e2e.load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise fixture.FixtureError("Runtime database role URLs are absent")
    run_id = uuid4().hex
    case_id = run_id
    database_name = f"milai_smoke_{run_id[:20]}"
    database_urls = {
        "owner": e2e._database_url(owner_source, database_name),
        "api": e2e._database_url(source.database_dsn, database_name),
        "steward": e2e._database_url(source.steward_database_dsn, database_name),
        "worker": e2e._database_url(worker_source, database_name),
        "audit": e2e._database_url(audit_source, database_name),
    }
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in ("legacy", "causal", "reader", "submitter", "operator", "reviewer")
    }
    scope = {"project_ids": ["milai-agent-e2e"]}
    question = "What is the latest approved deployment window for the lighthouse migration?"
    created = False
    api_process: subprocess.Popen[bytes] | None = None
    worker_database: Any = None
    database_cleanup: dict[str, Any] = {"status": "NOT_CREATED"}
    blob_cleanup = False
    report: dict[str, Any] | None = None
    raw_sidecar: dict[str, Any] | None = None
    ledger: remediation.AttemptLedger | None = None
    ledger_path: Path | None = None
    try:
        capture_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        capture_directory.chmod(0o700)
        ledger_path = capture_directory / f"{run_id}.attempts.jsonl"
        ledger = remediation.AttemptLedger(ledger_path)
        e2e._create_database(owner_source, database_name)
        created = True
        with e2e._migration_url(database_urls["owner"]):
            command.upgrade(e2e._alembic_config(), "head")
        blob_root: Path | None = None
        with tempfile.TemporaryDirectory(prefix="milai-dg10-full-session-blobs-") as blob_dir:
            blob_root = Path(blob_dir)
            settings = e2e._smoke_settings(
                source,
                database_urls,
                blob_root,
                uuid4(),
                uuid4(),
                tokens,
                e2e._free_loopback_port(),
            )
            e2e.prepare_runtime_directories(settings)
            executable = Path(os.sys.executable).with_name("milai-api")
            api_process = subprocess.Popen(
                [str(executable)],
                cwd=ROOT / "runtime",
                env=e2e._api_environment(settings, database_urls, tokens),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            client = e2e._HttpClient(f"http://{settings.bind_host}:{settings.bind_port}")
            worker_database = e2e.Database(
                settings,
                dsn=database_urls["worker"],
                expected_role="milai_worker",
            )
            worker = e2e.FoundationWorker(
                settings,
                worker_database,
                repository=e2e.ProjectionRepository(worker_database),
                blob_store=e2e.LocalContentAddressedBlobStore(
                    settings.blob_root,
                    kek=settings.blob_kek,
                    key_reference=settings.blob_key_reference,
                    allow_plaintext_read=True,
                ),
                embedding=e2e.DeterministicHashEmbedding(),
                worker_id=f"dg10-fixture-{run_id[:12]}",
            )
            e2e._wait_api(client, api_process)
            gateway = runtime_fixture.RuntimeCanonicalGateway(
                client=client,
                worker=worker,
                base_url=f"http://{settings.bind_host}:{settings.bind_port}",
                tokens=tokens,
                run_id=case_id,
                expected_scope=scope,
                ledger=ledger,
            )
            sessions = _synthetic_sessions()
            receipt = fixture.ingest_full_session_corpus(
                gateway=gateway,
                case_id=case_id,
                sessions=sessions,
                scope=scope,
            )
            preflight = gateway.recall(
                case_id=case_id,
                query=question,
                scope=scope,
                limit=5,
            )
            if preflight.abstained:
                raise fixture.FixtureError(
                    "Runtime/MCP preflight abstained: "
                    + json.dumps(gateway.last_recall_diagnostic, sort_keys=True)
                )
            provider = fixture.GovernedMemoryProvider(
                gateway=gateway,
                receipt=receipt,
                token_counter=WordCounter(),
            )
            context = provider.retrieve(case_id=case_id, question=question)
            ranked_session_ids = [
                str(item.get("session_id"))
                for item in gateway.recall(
                    case_id=case_id,
                    query=question,
                    scope=scope,
                    limit=5,
                ).results
            ]
            metrics = fixture.retrieval_metrics(ranked_session_ids, ["decision-session"])
            if "Thursday afternoon" not in context.text:
                raise fixture.FixtureError("latest canonical session was not recalled")
            raw_sidecar = {
                "schema": "milai.dg10.memory-fixture-raw-sidecar.v1",
                "run_id": run_id,
                "question": question,
                "sessions": [session.render() for session in sessions],
                "governed_objects": [asdict(item) for item in receipt.governed_objects],
                "memory_context": context.text,
                "ranked_session_ids": ranked_session_ids,
            }
            report = {
                "schema": "milai.dg10.memory-fixture-ingest.v1",
                "candidate_id": remediation.CANDIDATE,
                "date": remediation.DATE,
                "run_id": run_id,
                "status": "REAL_RUNTIME_MCP_SYNTHETIC_AUTHOR_CANDIDATE_REVIEW_REQUIRED",
                "stage_id": "DG10-R4",
                "stage_state": "AUTHOR_CANDIDATE",
                "independent_acceptance": False,
                "data_boundary": "SYNTHETIC_ONLY",
                "model_requests": 0,
                "external_provider_requests": 0,
                "full_session_corpus": receipt.full_session_corpus,
                "governance_sequence": "EVIDENCE_PROPOSAL_DECISION_PER_SESSION",
                "corpus_session_count": receipt.corpus_session_count,
                "governed_objects": _latest_snapshots(receipt.governed_objects),
                "recall": {
                    "transport": "OFFICIAL_MCP_STDIO_TO_REAL_RUNTIME_API",
                    "query_equals_original_question": True,
                    "query_sha256": hashlib.sha256(question.encode()).hexdigest(),
                    "consistency": "CANONICAL_REQUIRED",
                    "canonical_gate": context.canonical_gate,
                    "artificial_marker": False,
                    "shared_naive_ranking": False,
                    "target_tokens": context.target_token_count,
                    "retrieval_metrics": metrics,
                },
                "cleanup": {"status": "PENDING_FINALLY"},
                "raw_sidecar": {"status": "PENDING_BIND"},
                "model_run_authorizes_benchmark": False,
            }
            e2e._stop_api(api_process)
            api_process = None
            worker_database.close()
            worker_database = None
        blob_cleanup = blob_root is not None and not blob_root.exists()
    finally:
        if api_process is not None:
            e2e._stop_api(api_process)
        if worker_database is not None:
            worker_database.close()
        if ledger is not None:
            ledger.close()
        if created:
            database_cleanup = e2e._drop_database(owner_source, database_name)
    if report is None or raw_sidecar is None:
        raise fixture.FixtureError("fixture run did not produce a report")
    if database_cleanup.get("status") != "PASS" or not blob_cleanup:
        raise fixture.FixtureError("isolated evaluation tenant cleanup failed")
    report["cleanup"] = {
        "runtime_database": database_cleanup,
        "canonical_rows_remaining": 0,
        "projection_rows_remaining": 0,
        "blob_bytes_remaining": 0,
        "status": "PASS_NO_EVALUATION_DATA_REMAINS",
    }
    if ledger_path is None:
        raise fixture.FixtureError("MCP attempt ledger was not created")
    ledger_summary = remediation.reconcile_attempt_ledger(ledger_path)
    if (
        ledger_summary["known_completed_mcp_calls"] != 3
        or ledger_summary["retained_successful_mcp_calls"] != 3
        or ledger_summary["unknown_early_diagnostics"] != 0
        or ledger_summary["complete"] is not True
    ):
        raise fixture.FixtureError("MCP attempt ledger reconciliation failed")
    report["attempt_ledger"] = {
        **ledger_summary,
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
    }
    raw = remediation.encoded_json(raw_sidecar)
    sidecar_path = capture_directory / f"{run_id}.raw.json"
    remediation.atomic_write_new(sidecar_path, raw)
    report["raw_sidecar"] = {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": remediation.sha256_bytes(raw),
        "size": len(raw),
    }
    report["finished_at"] = datetime.now(UTC).isoformat()
    remediation.atomic_write_new(output, remediation.encoded_json(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real Runtime/MCP DG-10 fixture smoke")
    parser.add_argument("--execute-real-runtime-mcp", action="store_true")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.execute_real_runtime_mcp:
        raise fixture.FixtureError("real Runtime/MCP execution flag is required")
    result = run(
        output=args.output.resolve(),
        capture_directory=args.capture_directory.resolve(),
        env_file=args.env_file.resolve(),
    )
    print(result["status"])


if __name__ == "__main__":
    main()
