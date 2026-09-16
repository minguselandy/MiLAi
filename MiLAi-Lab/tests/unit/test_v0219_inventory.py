"""Neutral-parser and path-boundary canaries before any new task metadata access."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0219_inventory import digest, metadata, safe_path


def test_metadata_only_neutral_fields_no_task_execution(tmp_path):
    marker = tmp_path / "must-not-exist"
    raw = (
        f"open({str(marker)!r}, 'w').write('executed')\n"
        "METADATA = {'id':'PRIVATE_GOLD_CANARY', 'category':'PRIVATE_GOLD_CANARY', "
        "'environments':['filesystem','email'], 'timeout_seconds':600, 'mm_level':'L4', "
        "'gold':'PRIVATE_GOLD_CANARY'}\nTASK='PRIVATE_GOLD_CANARY'\n"
    ).encode()
    assert metadata(raw) == {
        "parse_status": "STATIC_AST_ONLY",
        "environments": ["filesystem", "email"],
        "timeout_seconds": 600,
        "mm_level": "L4",
    }
    assert not marker.exists() and "CANARY" not in json.dumps(metadata(raw))


@pytest.mark.parametrize(
    "raw",
    [
        b"METADATA={'environments': ['GOLD_CANARY']}",
        b"METADATA={'mm_level':'GOLD_CANARY'}",
        b"METADATA={'timeout_seconds':True}",
        b"METADATA={'environments': dangerous_call('GOLD_CANARY')}",
        b"METADATA=GOLD_CANARY",
        b"METADATA={'x': 'GOLD_CANARY'",
        b"\xffGOLD_CANARY",
    ],
)
def test_nonliteral_invalid_metadata_never_echoes_source(raw):
    assert "CANARY" not in json.dumps(metadata(raw))
    assert metadata(raw)["parse_status"] != "STATIC_AST_ONLY"


def test_canonical_hash_is_order_independent_but_type_sensitive():
    assert digest({"b": 2, "a": 1}) == digest({"a": 1, "b": 2})
    assert digest(["a:b", "c"]) != digest(["a", "b:c"])
    assert digest([1]) != digest(["1"])


@pytest.mark.parametrize("relative", ["../secret", "/etc/passwd", "a/../../secret"])
def test_catalog_path_escape_rejected(tmp_path, relative):
    with pytest.raises(ValueError):
        safe_path(tmp_path, relative)


def test_symlink_rejected(tmp_path):
    (tmp_path / "alias").symlink_to("/etc/passwd")
    with pytest.raises(ValueError):
        safe_path(tmp_path, "alias")
    assert safe_path(tmp_path, "valid/asset") == tmp_path / "valid/asset"
