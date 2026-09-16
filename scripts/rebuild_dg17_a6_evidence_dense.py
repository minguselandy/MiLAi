#!/usr/bin/env python3
"""Rebuild the optional DG-17 Raw Evidence 128d dense projection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from milai.config import load_settings
from milai.operations.evidence_dense_rebuild import rebuild_evidence_dense
from milai.operations.local_runtime import load_runtime_environment
from milai.persistence import Database, SessionContext
from milai.persistence.projection_repository import ProjectionRepository
from milai.workers.main import _embedding_provider

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / "runtime/.env")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-batches", type=int)
    args = parser.parse_args()
    load_runtime_environment(args.env_file)
    settings = load_settings()
    worker_dsn = os.environ.get("MILAI_WORKER_DATABASE_URL")
    if not worker_dsn:
        raise RuntimeError("MILAI_WORKER_DATABASE_URL is required")
    database = Database(settings, dsn=worker_dsn, expected_role="milai_worker")
    try:
        report = rebuild_evidence_dense(
            ProjectionRepository(database),
            SessionContext(settings.tenant_id, settings.local_actor_id),
            _embedding_provider(settings),
            batch_size=args.batch_size,
            max_batches=args.max_batches,
        )
    finally:
        database.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
