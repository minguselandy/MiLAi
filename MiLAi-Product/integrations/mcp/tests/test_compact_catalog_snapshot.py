import json
from pathlib import Path

from compact_catalog_export import export


def test_release_snapshot_matches_current_protocol_metadata_and_scope_filters():
    path = Path(__file__).resolve().parents[3] / "contracts/mcp"
    expected = json.loads((path / "compact-memory-v1.release-0.1.15.tools.json").read_text())
    assert export() == expected
