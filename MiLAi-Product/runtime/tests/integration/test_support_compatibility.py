import pytest
from support.evidence import evidence_app
from support.projection import worker_runtime
from support.working_state import _binding

pytestmark = pytest.mark.integration


def test_runtime_support_facades_preserve_integration_fixture_owners() -> None:
    assert evidence_app.__module__ == "test_evidence_api"
    assert worker_runtime.__module__ == "test_projection_worker"
    assert _binding.__module__ == "test_host_cognitive_state"
