"""Type declarations for the existing benchmark execution dictionaries and arguments."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NotRequired, Protocol, TypedDict


class BenchmarkJob(TypedDict):
    """Common job ID with the metadata produced by MERIT and MemSyco."""

    job_id: str
    selection_path: NotRequired[str]
    selection_sha256: NotRequired[str]
    domain: NotRequired[str]
    arc_sha256: NotRequired[str]
    public_messages: NotRequired[int]
    track: NotRequired[str]
    owner: NotRequired[str]
    history_id: NotRequired[str]
    history_sha256: NotRequired[str]
    build_history_id: NotRequired[str]


class BenchmarkAttempt(TypedDict):
    status: str
    output: NotRequired[str | None]
    error_type: NotRequired[str | None]


class BenchmarkManifest(TypedDict):
    identity: dict[str, Any]
    jobs: list[BenchmarkJob]
    attempts: dict[str, BenchmarkAttempt]
    status: str
    history_attempts: NotRequired[dict[str, Any]]


class BenchmarkPreparationReceipt(TypedDict):
    status: str
    jobs: list[BenchmarkJob]
    manifest_path: str
    identity_sha256: str


class BenchmarkSourceIdentity(TypedDict):
    source_sha256: dict[str, str]
    dependency_lock_sha256: str
    native_transport_requirements_sha256: str | None
    dependencies: dict[str, str | None]
    python: str
    environment_packages: dict[str, str]
    git_sha: str


class BenchmarkPrepareArguments(Protocol):
    runtime_root: Path
    output: Path


class BenchmarkStartArguments(Protocol):
    runtime_root: Path
    prepared: Path
    job: str


class BenchmarkFinishArguments(Protocol):
    runtime_root: Path
    job: str
