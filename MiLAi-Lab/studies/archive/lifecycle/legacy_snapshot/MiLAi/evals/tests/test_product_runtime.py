from __future__ import annotations

import hashlib
import os
from pathlib import Path

from evals.harness import HistoryItem, TemporaryResourceSpec, WorkloadHistory
from evals.harness.product_runtime import (
    broker_policy,
    claim_projection,
    grouped_history,
    render_evaluation_environment,
    rewrite_database_url,
)


def _spec(tmp_path: Path) -> TemporaryResourceSpec:
    return TemporaryResourceSpec(
        lease_id="lease-1",
        database_name="milai_eval_lease_1",
        blob_root=tmp_path / "lease-1" / "blobs",
        temporary_root=tmp_path / "lease-1",
    )


def _source() -> dict[str, str]:
    return {
        name: f"postgresql://{role}:secret@127.0.0.1:25432/milai"
        for name, role in {
            "MILAI_DATABASE_URL": "milai_api",
            "MILAI_STEWARD_DATABASE_URL": "milai_steward",
            "MILAI_WORKER_DATABASE_URL": "milai_worker",
            "MILAI_MIGRATION_DATABASE_URL": "milai_owner",
            "MILAI_AUDIT_DATABASE_URL": "milai_audit",
        }.items()
    }


def test_evaluation_environment_rewrites_only_the_exact_temporary_resource(
    tmp_path: Path,
) -> None:
    source = {**_source(), "MILAI_AGENT_READER_TOKEN": "reader"}

    rendered = render_evaluation_environment(
        source,
        _spec(tmp_path),
        bind_port=28123,
        tenant_id="tenant",
        actor_id="actor",
    )

    assert rendered["MILAI_POSTGRES_DB"] == "milai_eval_lease_1"
    assert all(
        value.endswith("/milai_eval_lease_1")
        for name, value in rendered.items()
        if name.endswith("DATABASE_URL")
    )
    assert rendered["MILAI_BLOB_ROOT"] == str((tmp_path / "lease-1" / "blobs").resolve())
    assert rendered["MILAI_AGENT_READER_TOKEN"] == "reader"
    assert rendered["MILAI_DATA_MODE"] == "DEIDENTIFIED_ALLOWED"
    assert rendered["MILAI_BASE_URL"] == "http://127.0.0.1:28123"


def test_database_url_rewrite_discards_source_query_and_fragment() -> None:
    assert rewrite_database_url(
        "postgresql://role:secret@127.0.0.1:25432/source?sslmode=disable#x",
        "milai_eval_x",
    ) == "postgresql://role:secret@127.0.0.1:25432/milai_eval_x"


def test_grouped_history_preserves_session_and_turn_order() -> None:
    history = WorkloadHistory(
        "workload",
        "SYNTHETIC",
        (
            HistoryItem("1", "s-1", "user", "one", "2026-08-24T00:00:00+00:00"),
            HistoryItem("2", "s-2", "user", "two", "2026-08-25T00:00:00+00:00"),
            HistoryItem("3", "s-1", "assistant", "three"),
            HistoryItem("4", "s-3", "user", "four", "2026-08-26T00:00:00"),
        ),
    )

    assert grouped_history(history) == (
        ("s-1", "2026-08-24T00:00:00+00:00", "user: one\nassistant: three"),
        ("s-2", "2026-08-25T00:00:00+00:00", "user: two"),
        ("s-3", "2026-08-26T00:00:00+00:00", "user: four"),
    )


def test_broker_policy_binds_public_product_executable_and_scope(tmp_path: Path) -> None:
    executable = tmp_path / "milai-mcp"
    executable.write_bytes(b"installed executable")
    executable.chmod(0o700)
    socket_path = (tmp_path / "reader-lite.sock").resolve()

    policy = broker_policy(
        profile="reader-lite",
        socket_path=socket_path,
        mcp_executable=executable.resolve(),
        base_url="http://127.0.0.1:28123",
        scope={"project_ids": ["eval-workload"]},
    )

    assert policy["allowed_peer_uids"] == [os.geteuid()]
    assert policy["mcp_executable_sha256"] == hashlib.sha256(
        b"installed executable"
    ).hexdigest()
    assert policy["scope"] == {"project_ids": ["eval-workload"]}
    assert policy["consistency_floor"] == "CANONICAL_REQUIRED"
    assert policy["required_authority"] == "ACTION_SAFE"

    informational = broker_policy(
        profile="reader-lite",
        socket_path=(tmp_path / "reader-lite-info.sock").resolve(),
        mcp_executable=executable.resolve(),
        base_url="http://127.0.0.1:28123",
        scope={"project_ids": ["eval-workload"]},
        required_authority="INFORMATIONAL",
    )
    assert informational["profile"] == "reader-lite"
    assert informational["required_authority"] == "INFORMATIONAL"


def test_claim_projection_defaults_semantic_and_accepts_explicit_faithful_mapping() -> None:
    default = WorkloadHistory("workload", "SYNTHETIC", ())
    faithful = WorkloadHistory(
        "workload",
        "SYNTHETIC",
        (),
        metadata={
            "claim_subject_namespace": "source-case",
            "claim_subject_index_width": 3,
            "claim_predicate": "benchmark.memory.session",
            "claim_type": "BENCHMARK_MEMORY",
        },
    )

    assert claim_projection(default, fingerprint=default.fingerprint, index=2) == (
        "workload-00002",
        "memory.session",
        "SESSION_MEMORY",
    )
    assert claim_projection(faithful, fingerprint=faithful.fingerprint, index=2) == (
        "source-case-002",
        "benchmark.memory.session",
        "BENCHMARK_MEMORY",
    )


def test_claim_projection_accepts_exact_governed_fixture_keys() -> None:
    workload = WorkloadHistory(
        "workload",
        "SYNTHETIC",
        (),
        metadata={
            "claim_projections": [
                {
                    "subject_id": "orchid-release",
                    "predicate": "release.target",
                    "claim_type": "PROJECT_STATE",
                }
            ]
        },
    )

    assert claim_projection(workload, fingerprint=workload.fingerprint, index=0) == (
        "orchid-release",
        "release.target",
        "PROJECT_STATE",
    )
