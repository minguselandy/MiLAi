from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import get_type_hints

from milai.api.app import create_app
from milai.api.retrieval_routes import _retrieval_operations_service, _service
from milai.application.chat import ChatService
from milai.application.context_preparation import PrepareContextService
from milai.application.memory_resolve import MemoryResolveService
from milai.application.memory_state import MemoryStateViewService
from milai.application.recollection import (
    MatchedReplayInvariantError,
    MatchedReplayPolicy,
    MatchedRetrievalReplay,
    RecollectionFacade,
    RetrievalExecution,
)
from milai.application.retrieval import (
    MatchedReplayInvariantError as LegacyMatchedReplayInvariantError,
)
from milai.application.retrieval import MatchedReplayPolicy as LegacyMatchedReplayPolicy
from milai.application.retrieval import MatchedRetrievalReplay as LegacyMatchedRetrievalReplay
from milai.application.retrieval import RetrievalExecution as LegacyRetrievalExecution
from milai.application.retrieval import RetrievalService
from milai.config.settings import load_settings, prepare_runtime_directories


class _Database:
    def ping(self) -> None:
        return None


def _settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    settings = load_settings(
        {
            "MILAI_DATABASE_URL": "postgresql://milai_api:secret@127.0.0.1:15432/milai",
            "MILAI_STEWARD_DATABASE_URL": (
                "postgresql://milai_steward:secret@127.0.0.1:15432/milai"
            ),
            "MILAI_BLOB_ROOT": str(tmp_path / "blobs"),
            "MILAI_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "MILAI_LOCAL_ACTOR_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "MILAI_API_TOKEN": "test-token-with-at-least-32-characters",
            "MILAI_CAUSAL_TOKEN_SECRET": "test-causal-secret-with-at-least-32-characters",
        }
    )
    prepare_runtime_directories(settings)
    return settings


def test_retrieval_module_keeps_execution_and_replay_import_compatibility() -> None:
    assert LegacyRetrievalExecution is RetrievalExecution
    assert LegacyMatchedRetrievalReplay is MatchedRetrievalReplay
    assert LegacyMatchedReplayPolicy is MatchedReplayPolicy
    assert LegacyMatchedReplayInvariantError is MatchedReplayInvariantError


def test_query_consumers_type_against_recollection_facade() -> None:
    assert get_type_hints(ChatService.__init__)["retrieval_service"] is RecollectionFacade
    assert get_type_hints(PrepareContextService.__init__)["retrieval"] is RecollectionFacade
    assert get_type_hints(MemoryResolveService.__init__)["retrieval"] is RecollectionFacade
    assert get_type_hints(MemoryStateViewService.__init__)["retrieval"] is RecollectionFacade
    assert get_type_hints(_service)["return"] is RecollectionFacade
    assert get_type_hints(_retrieval_operations_service)["return"] is RetrievalService


def test_first_recollection_seam_excludes_trace_and_status_operations() -> None:
    assert not hasattr(RecollectionFacade, "get_trace")
    assert not hasattr(RecollectionFacade, "system_status")


def test_recollection_import_does_not_load_concrete_retrieval() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import milai.application.recollection; "
                "assert 'milai.application.retrieval' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_flask_extension_remains_the_concrete_retrieval_service(tmp_path: Path) -> None:
    database = _Database()
    app = create_app(
        _settings(tmp_path),
        database=database,  # type: ignore[arg-type]
        steward_database=database,  # type: ignore[arg-type]
    )

    extension = app.extensions["milai.retrieval_service"]

    assert type(extension) is RetrievalService
    assert isinstance(extension, RecollectionFacade)
