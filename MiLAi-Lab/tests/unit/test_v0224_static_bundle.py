"""Synthetic-only format/sealing tests; no receipt is independently approved."""

import hashlib
import json
import platform
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0224_static_bundle as bundle
from v0222_admission_read_scope import AdmissionReadScope

LIMITS = bundle.BundleLimits(1_000_000, 2_000_000, 100, 100)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(header, payload):
    raw = bundle.canonical_json(header)
    return bundle.MAGIC + len(raw).to_bytes(8, "big") + raw + payload


def fixture_bundle():
    payload = b"{}"
    digest = sha(payload)
    header = {
        "format_revision": bundle.FORMAT_REVISION,
        "roots": [{"path": "/synthetic/a.json", "sha256": digest, "purpose": "STATIC_TREE"}],
        "files": {"/synthetic/a.json": digest, "/synthetic/b.json": digest},
        "blobs": {digest: {"offset": 0, "length": len(payload)}},
        "manifest_env": {"python": platform.python_version(), "packages": {}, "sources": {}},
    }
    return header, payload


def test_deduplicated_immutable_index_and_exact_buffer():
    header, payload = fixture_bundle()
    raw = encode(header, payload)
    index = bundle.parse_bundle(raw, LIMITS)
    assert len(index.files) == 2 and len(index.blobs) == 1
    assert index.format_revision == bundle.FORMAT_REVISION
    assert index.member_bytes("/synthetic/b.json", sha(payload)) == payload
    for target in (index.files, index.blobs[sha(payload)], index.roots[0], index.manifest_env):
        with pytest.raises(TypeError):
            target["mutation"] = 1
    with pytest.raises(bundle.StaticBundleError, match="INDEX_SOURCE"):
        bundle.entry_bytes(bytes(bytearray(raw)), index, "/synthetic/a.json", sha(payload))
    with pytest.raises(bundle.StaticBundleError, match="STATIC_MEMBER"):
        index.member_bytes("/synthetic/missing", sha(payload))


@pytest.mark.parametrize(
    "mutation",
    [
        "padding",
        "truncate",
        "digest",
        "offset",
        "bool_length",
        "unknown",
        "relative",
        "parent",
        "duplicate_root",
        "purpose",
        "root_pin",
        "extra_package",
    ],
)
def test_malformed_bundle_is_rejected(mutation):
    header, payload = fixture_bundle()
    digest = sha(payload)
    if mutation == "padding":
        payload += b"x"
    elif mutation == "truncate":
        payload = payload[:-1]
    elif mutation == "digest":
        payload = b"[]"
    elif mutation == "offset":
        header["blobs"][digest]["offset"] = 1
    elif mutation == "bool_length":
        header["blobs"][digest]["length"] = True
    elif mutation == "unknown":
        header["extra"] = 1
    elif mutation in ("relative", "parent"):
        header["files"][("relative" if mutation == "relative" else "/synthetic/../x")] = digest
    elif mutation == "duplicate_root":
        header["roots"].append(header["roots"][0])
    elif mutation == "purpose":
        header["roots"][0]["purpose"] = "ANY_PASS"
    elif mutation == "root_pin":
        header["roots"][0]["sha256"] = "0" * 64
    elif mutation == "extra_package":
        header["manifest_env"]["packages"]["unproved"] = "1"
    with pytest.raises(bundle.StaticBundleError):
        bundle.parse_bundle(encode(header, payload), LIMITS)


@pytest.mark.parametrize("header", [b'{"a":1,"a":2}', b'{"x":NaN}', b"\xff"])
def test_strict_header(header):
    with pytest.raises((ValueError, UnicodeError)):
        bundle.parse_bundle(bundle.MAGIC + len(header).to_bytes(8, "big") + header, LIMITS)


def test_header_canonical_and_limits():
    header, payload = fixture_bundle()
    pretty = json.dumps(header).encode()
    with pytest.raises(bundle.StaticBundleError, match="CANONICAL"):
        bundle.parse_bundle(
            bundle.MAGIC + len(pretty).to_bytes(8, "big") + pretty + payload, LIMITS
        )
    raw = encode(header, payload)
    for limits in (
        bundle.BundleLimits(1, 10, 10, 10),
        bundle.BundleLimits(10000, 1, 10, 10),
        bundle.BundleLimits(10000, 10, 1, 10),
    ):
        with pytest.raises(bundle.StaticBundleError, match="LIMIT"):
            bundle.parse_bundle(raw, limits)
    with pytest.raises(bundle.StaticBundleError):
        bundle.BundleLimits(True, 1, 1, 1)


@pytest.fixture
def sealing(monkeypatch, tmp_path):
    import v0222_scoped_cpu_guard as guard

    monkeypatch.setattr(guard, "_installed", True)
    leaf1, leaf2, live = (tmp_path / name for name in ("leaf1.json", "leaf2.json", "ledger.jsonl"))
    leaf1.write_bytes(b'{"unused":[1,2]}')
    leaf2.write_bytes(leaf1.read_bytes())
    live.write_bytes(b'{"event":"synthetic"}\n')
    root = tmp_path / "root.json"
    root.write_bytes(
        bundle.canonical_json(
            {"files": {str(p): sha(p.read_bytes()) for p in (leaf1, leaf2, live)}}
        )
    )
    roots = [{"path": str(root), "sha256": sha(root.read_bytes()), "purpose": "STATIC_TREE"}]
    roles = {str(live): {"sha256": sha(live.read_bytes()), "roles": ["HISTORICAL_LEDGER"]}}
    return tmp_path / "sealed", roots, roles, leaf1


def test_sealer_original_validation_close_dedup_and_unapproved(sealing):
    output, roots, roles, leaf = sealing
    result = bundle.seal_static_bundle(output, roots=roots, fresh_roles=roles, limits=LIMITS)
    assert result["status"] == "STATIC_BUNDLE_CANDIDATE_NOT_APPROVED"
    assert json.loads((output / "candidate-receipt.json").read_bytes()) == result
    index = bundle.parse_bundle((output / "static.bundle").read_bytes(), LIMITS)
    assert str(leaf) in index.files and set(roles).isdisjoint(index.files)
    assert len(index.files) == 3 and len(index.blobs) == 2
    assert result["verifier_files"]
    assert all(
        "SEAL_VERIFIER" in result["fresh_roles"][p]["roles"] for p in result["verifier_files"]
    )
    stats = json.loads((output / "seal-observation.json").read_bytes())["original_scope_stats"]
    assert stats["first_reads"] == stats["closing_reads"] > 3
    assert stats["first_bytes"] == stats["closing_bytes"] > 0
    with pytest.raises(bundle.StaticBundleError, match="FRESH_CANONICAL"):
        bundle.seal_static_bundle(output, roots=roots, fresh_roles=roles, limits=LIMITS)


def test_all_nested_manifest_environment_sources(sealing):
    output, roots, roles, leaf = sealing
    manifest = leaf.parent / "manifest.json"
    manifest.write_bytes(
        bundle.canonical_json(
            {
                "dependencies": {},
                "inputs": {str(leaf): sha(leaf.read_bytes())},
                "python": platform.python_version(),
                "packages": {},
            }
        )
    )
    roots.append(
        {"path": str(manifest), "sha256": sha(manifest.read_bytes()), "purpose": "STATIC_TREE"}
    )
    bundle.seal_static_bundle(output, roots=roots, fresh_roles=roles, limits=LIMITS)
    index = bundle.parse_bundle((output / "static.bundle").read_bytes(), LIMITS)
    assert index.manifest_env["sources"][str(manifest)]["sha256"] == roots[-1]["sha256"]


@pytest.mark.parametrize("invalid", [b'{"x":1,"x":2}', b'{"unused":NaN}', b"\xff"])
def test_invalid_unused_json_rejected_with_original_failure(sealing, invalid):
    output, roots, roles, leaf = sealing
    leaf.write_bytes(invalid)
    roots = [{"path": str(leaf), "sha256": sha(invalid), "purpose": "STATIC_TREE"}]
    with pytest.raises((ValueError, UnicodeError)) as error:
        bundle.seal_static_bundle(output, roots=roots, fresh_roles=roles, limits=LIMITS)
    failure = json.loads((output / "seal-failure.json").read_bytes())
    assert failure["exception_type"] == type(error.value).__name__
    assert failure["reason"] == str(error.value)
    assert not (output / "candidate-receipt.json").exists()


def test_closing_drift_rejects_candidate(sealing, monkeypatch):
    output, roots, roles, leaf = sealing
    original = AdmissionReadScope._close

    def drift(self, body_error=None):
        leaf.write_bytes(b"changed")
        return original(self, body_error)

    monkeypatch.setattr(AdmissionReadScope, "_close", drift)
    with pytest.raises(ValueError):
        bundle.seal_static_bundle(output, roots=roots, fresh_roles=roles, limits=LIMITS)
    assert (output / "seal-failure.json").exists()
    assert not (output / "candidate-receipt.json").exists()


def test_bound_refusal_and_guard_are_not_approval(sealing, monkeypatch):
    output, roots, roles, leaf = sealing
    with pytest.raises(bundle.StaticBundleError, match="PAYLOAD_LIMIT"):
        bundle.seal_static_bundle(
            output, roots=roots, fresh_roles=roles, limits=bundle.BundleLimits(1000000, 1, 100, 100)
        )
    assert not (output / "static.bundle").exists()
    import v0222_scoped_cpu_guard as guard

    monkeypatch.setattr(guard, "_installed", False)
    with pytest.raises(Exception, match="GUARD"):
        bundle.seal_static_bundle(
            leaf.parent / "no_guard", roots=roots, fresh_roles=roles, limits=LIMITS
        )
    assert not (leaf.parent / "no_guard").exists()


def test_direct_missing_edge_precedes_invalid_unused_json(sealing):
    output, roots, roles, leaf = sealing
    leaf.write_bytes(b'{"duplicate":1,"duplicate":2}')
    missing = leaf.parent / "missing.json"
    root = Path(roots[0]["path"])
    root.write_bytes(
        json.dumps({"files": {str(missing): "0" * 64, str(leaf): sha(leaf.read_bytes())}}).encode()
    )
    roots[0]["sha256"] = sha(root.read_bytes())
    with pytest.raises(FileNotFoundError):
        bundle.seal_static_bundle(output, roots=roots, fresh_roles=roles, limits=LIMITS)
    assert not (output / "candidate-receipt.json").exists()


def test_mandatory_fresh_pin_conflict_rejects(sealing):
    output, roots, roles, _leaf = sealing
    roles[next(iter(roles))]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        bundle.seal_static_bundle(output, roots=roots, fresh_roles=roles, limits=LIMITS)
    assert not (output / "candidate-receipt.json").exists()


def test_environment_union_requires_complete_consistent_sources():
    header, payload = fixture_bundle()
    environment = header["manifest_env"]
    environment["sources"] = {
        "/synthetic/a.json": {
            "sha256": sha(payload),
            "python": platform.python_version(),
            "packages": {"synthetic": "1"},
        },
        "/synthetic/b.json": {
            "sha256": sha(payload),
            "python": platform.python_version(),
            "packages": {"synthetic": "2"},
        },
    }
    environment["packages"] = {"synthetic": "1"}
    with pytest.raises(bundle.StaticBundleError, match="CONFLICTING_PACKAGE"):
        bundle.parse_bundle(encode(header, payload), LIMITS)
    environment["sources"]["/synthetic/b.json"]["packages"] = {"synthetic": "1"}
    parsed = bundle.parse_bundle(encode(header, payload), LIMITS)
    assert len(parsed.manifest_env["sources"]) == 2
