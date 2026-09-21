from support.auth import ISSUER, RESOURCE, Fixture
from support.compact import NOTE_REF, compact_edge, tool_call
from support.http import edge, rpc
from support.postgres import _create_and_migrate_database, _free_port
from support.private_catalog import private_fixture
from support.profile import CLAIM_ID, EVIDENCE_ID, _as_client, _RoleClient
from support.working_state import CAPABILITIES, TOKEN


def test_mcp_support_facades_preserve_historical_helper_owners() -> None:
    assert Fixture.__module__ == "test_aigcit_auth"
    assert edge.__module__ == rpc.__module__ == "test_aigcit_http"
    assert _create_and_migrate_database.__module__ == "test_codex_full_postgres_e2e"
    assert _free_port.__module__ == "test_codex_full_postgres_e2e"
    assert _RoleClient.__module__ == _as_client.__module__ == "test_codex_full_profile"
    assert private_fixture.__module__ == "test_aigcit_full"
    assert compact_edge.__module__ == tool_call.__module__ == "test_compact_memory"
    assert isinstance(ISSUER, str) and isinstance(RESOURCE, str)
    assert isinstance(CLAIM_ID, str) and isinstance(EVIDENCE_ID, str)
    assert isinstance(CAPABILITIES, dict) and isinstance(TOKEN, str)
    assert isinstance(NOTE_REF, dict)
