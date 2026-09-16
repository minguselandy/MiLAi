"""R04 synthetic boundaries; original tests copied, old files unchanged."""

import hashlib
import json
import platform
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from v0222_admission_read_scope import AdmissionReadScope
from v0224_static_bundle import BundleLimits
from v0224_verified_digest_scope import BundleReadScope


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fixture(tmp_path, *, fresh=False, roles_override=None, receipt_change=None):
    leaf = tmp_path / "leaf.json"
    raw = b'{"value":[1,2]}'
    leaf.write_bytes(raw)
    root = tmp_path / "root.json"
    root_raw = encoded({"files": {str(leaf): sha(raw)}})
    root.write_bytes(root_raw)
    files = {str(leaf): sha(raw), str(root): sha(root_raw)}
    contents = {sha(raw): raw, sha(root_raw): root_raw}
    blobs, payload = {}, b""
    for digest in sorted(contents):
        data = contents[digest]
        blobs[digest] = {"offset": len(payload), "length": len(data)}
        payload += data
    roots = [{"path": str(root), "sha256": sha(root_raw), "purpose": "STATIC_TREE"}]
    header = {
        "format_revision": "V0224_STATIC_BUNDLE_V1",
        "roots": roots,
        "files": files,
        "blobs": blobs,
        "manifest_env": {"python": platform.python_version(), "packages": {}, "sources": {}},
    }
    header_raw = encoded(header)
    package = b"MILA-BUNDLE-V1\n" + len(header_raw).to_bytes(8, "big") + header_raw + payload
    bundle = tmp_path / "bundle.bin"
    bundle.write_bytes(package)
    verifier = tmp_path / "synthetic-verifier.txt"
    verifier.write_bytes(b"synthetic verifier stand-in, no execution authorization")
    roles = {str(verifier): {"sha256": sha(verifier.read_bytes()), "roles": ["VERIFIER"]}}
    if fresh:
        roles[str(leaf)] = {"sha256": sha(raw), "roles": ["SYNTHETIC_LIVE"]}
    if roles_override:
        roles_override(roles)
    receipt = {
        "status": "INDEPENDENT_STATIC_BUNDLE_APPROVED",
        "bundle_sha256": sha(package),
        "format_revision": header["format_revision"],
        "verifier_files": {str(verifier): sha(verifier.read_bytes())},
        "proof_roots": roots,
        "fresh_roles": roles,
        "environment": {"python": platform.python_version(), "packages": {}},
        "classification_digest": sha(encoded(roles)),
    }
    if receipt_change:
        receipt_change(receipt)
    receipt_path = tmp_path / "synthetic-receipt.json"
    receipt_path.write_bytes(encoded(receipt))
    kwargs = {
        "bundle_path": bundle,
        "bundle_sha256": sha(package),
        "receipt_path": receipt_path,
        "receipt_sha256": sha(receipt_path.read_bytes()),
        "limits": BundleLimits(
            max_header_bytes=100_000, max_payload_bytes=100_000, max_paths=100, max_blobs=100
        ),
    }
    return kwargs, leaf, raw, root, root_raw


def test_static_authority_intentionally_accepts_old_path_change(tmp_path):
    config, leaf, raw, root, root_raw = fixture(tmp_path)
    leaf.write_bytes(b"changed old static path")
    with BundleReadScope(**config) as scope:
        scope.verify_static_tree(root, sha(root_raw))
        assert scope.read_json(leaf, sha(raw)) == {"value": [1, 2]}
    assert scope.authority_stats["proof_uses"] == 1
    assert scope.stats["first_reads"] == scope.stats["closing_reads"] == 3
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        with AdmissionReadScope() as old:
            old.read_bytes(leaf, sha(raw))


def test_public_json_copy_and_virtual_physical_counts_are_separate(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    with BundleReadScope(**config) as scope:
        value = scope.read_json(leaf, sha(raw))
        value["value"].append(3)
        assert scope.read_json(leaf, sha(raw)) == {"value": [1, 2]}
        assert scope.authority_stats["member_reads"] == 1
        assert scope.stats["json_parses"] == 1
    assert scope.authority_stats["member_bytes"] == len(raw)
    with pytest.raises(ValueError, match="ALREADY_CLOSED"):
        scope.read_json(leaf, sha(raw))


def test_fresh_role_overrides_correct_bundle_member(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path, fresh=True)
    leaf.write_bytes(b"mutated live ledger stand-in")
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))


def test_promotion_reads_at_original_position_and_is_permanent(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    with BundleReadScope(**config) as scope:
        scope.read_bytes(leaf, sha(raw))
        before = scope.stats["first_reads"]
        with scope.physical_reads():
            assert scope.stats["first_reads"] == before
            scope.read_bytes(leaf, sha(raw))
        assert scope.stats["first_reads"] == before + 1
        scope.read_bytes(leaf, sha(raw))
        assert scope.authority_stats["promotions"] == 1
        assert leaf in scope._entries
    assert scope.stats["closing_reads"] == 4


def test_promotion_cannot_hide_physical_drift_or_caught_failure(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))
            leaf.write_bytes(b"drift")
            with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
                with scope.physical_reads():
                    scope.read_bytes(leaf, sha(raw))


def test_promotion_cannot_replace_virtual_expected_hash(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="CONFLICTING_EXPECTED_FILE_HASH"):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))
            leaf.write_bytes(b"new bytes")
            with scope.physical_reads():
                scope.read_bytes(leaf, sha(b"new bytes"))


@pytest.mark.parametrize("target", ["bundle_path", "receipt_path"])
def test_authority_close_drift_and_primary_preservation(tmp_path, target):
    config, leaf, raw, _, _ = fixture(tmp_path)
    primary = RuntimeError("original business primary")
    with pytest.raises(RuntimeError) as caught:
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))
            path = config[target]
            data = path.read_bytes()
            path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            raise primary
    assert caught.value is primary
    assert scope.close_failures
    assert any("closing" in note for note in primary.__notes__)


def test_each_scope_physically_rereads_authority(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    with BundleReadScope(**config) as one:
        one.read_bytes(leaf, sha(raw))
    config["bundle_path"].write_bytes(b"broken")
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        with BundleReadScope(**config) as two:
            two.read_bytes(leaf, sha(raw))


def test_unknown_tree_root_cannot_reuse_virtual_leaf(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    other = tmp_path / "other.json"
    other_raw = encoded({"files": {str(leaf): sha(raw)}})
    other.write_bytes(other_raw)
    leaf.write_bytes(b"physical drift")
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))
            scope.verify_static_tree(other, sha(other_raw))


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("status", "STATIC_BUNDLE_CANDIDATE_NOT_APPROVED", "INDEPENDENT_STATIC_APPROVAL"),
        ("bundle_sha256", "0" * 64, "BUNDLE_BINDING"),
        ("classification_digest", "0" * 64, "CLASSIFICATION_BINDING"),
        ("proof_roots", [], "PROOF_ROOTS"),
        ("verifier_files", {}, "VERIFIERS"),
    ],
)
def test_self_claims_do_not_replace_external_receipt_contract(tmp_path, field, value, error):
    config, leaf, raw, _, _ = fixture(tmp_path, receipt_change=lambda r: r.update({field: value}))
    with pytest.raises(ValueError, match=error):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))


def test_external_receipt_pin_not_taken_from_modified_receipt(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    config["receipt_path"].write_bytes(b"{}")
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))


def test_static_proof_cannot_close_without_all_declared_fresh_obligations(tmp_path):
    config, _, _, root, root_raw = fixture(tmp_path, fresh=True)
    with pytest.raises(ValueError, match="FRESH_ROLE_COVERAGE_INCOMPLETE"):
        with BundleReadScope(**config) as scope:
            scope.verify_static_tree(root, sha(root_raw))
    assert scope.stats["closing_reads"] == 3


def test_cross_thread_close_rejects_but_still_physically_closes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    config, leaf, raw, _, _ = fixture(tmp_path)
    scope = BundleReadScope(**config)
    scope.__enter__()
    scope.read_bytes(leaf, sha(raw))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(ValueError, match="BUNDLE_SCOPE_OWNER_DRIFT"):
            pool.submit(scope.close).result()
    assert scope.stats["closing_reads"] == 3
    assert scope.status == "CLOSED_FAILED"


def test_missing_fresh_coverage_does_not_mask_business_primary(tmp_path):
    config, _, _, root, root_raw = fixture(tmp_path, fresh=True)
    primary = RuntimeError("business first")
    with pytest.raises(RuntimeError) as caught:
        with BundleReadScope(**config) as scope:
            scope.verify_static_tree(root, sha(root_raw))
            raise primary
    assert caught.value is primary
    assert any("COVERAGE_INCOMPLETE" in note for note in primary.__notes__)


def test_promoted_member_must_survive_physical_close(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="CLOSING_CONTENT_OR_PATH_IDENTITY_MISMATCH"):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))
            with scope.physical_reads():
                scope.read_bytes(leaf, sha(raw))
            leaf.write_bytes(b"late drift")


def test_live_environment_checked_for_static_proof(tmp_path, monkeypatch):
    config, _, _, root, root_raw = fixture(tmp_path)
    monkeypatch.setattr(platform, "python_version", lambda: "0.0.synthetic-drift")
    with pytest.raises(ValueError, match="PYTHON_DRIFT"):
        with BundleReadScope(**config) as scope:
            scope.verify_static_tree(root, sha(root_raw))


def test_actual_verifier_source_is_fresh_even_with_approved_receipt(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    (tmp_path / "synthetic-verifier.txt").write_bytes(b"source drift")
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))


def test_bundle_alias_rejected_even_with_identical_bytes(tmp_path):
    config, leaf, raw, _, _ = fixture(tmp_path)
    path = config["bundle_path"]
    actual = path.with_name("real-bundle.bin")
    path.rename(actual)
    path.symlink_to(actual)
    with pytest.raises(ValueError, match="SYMLINK_PATH_NOT_SUPPORTED"):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))


def test_original_artifact_sql_error_precedes_physical_file_error(tmp_path):
    from v0222_presentation_batch_v2 import Batch

    class EmptyDatabase:
        def execute(self, _query):
            return []

    config, leaf, raw, _, _ = fixture(tmp_path)
    batch = object.__new__(Batch)
    batch.path = tmp_path / "current.sqlite"
    row = {"path": str(leaf), "sha256": sha(raw), "dependencies": "malformed SQL JSON"}
    leaf.write_bytes(b"also physical drift")
    with pytest.raises(json.JSONDecodeError):
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))
            with scope.physical_reads():
                Batch._read_artifact_row(batch, EmptyDatabase(), row, scope)
    assert leaf not in scope._promoted
    assert scope.stats["first_reads"] == 3


def test_original_class_and_parser_ast_only_one_hash_change():
    import ast

    import v0224_bundle_read_scope as old
    import v0224_static_bundle as parser
    import v0224_verified_digest_scope as new

    def functions(module):
        tree = ast.parse(Path(module.__file__).read_text())
        cls = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BundleReadScope"
        )
        return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}

    before, after = functions(old), functions(new)
    assert set(after) - set(before) == {"_parse_current_authority_bundle"}
    for name in before:
        if name == "_ensure_authority":
            statements = before[name].body[2].body
            at = next(
                i
                for i, n in enumerate(statements)
                if isinstance(n, ast.Assign)
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == "physical"
            )
            statements[at : at + 2] = ast.parse(
                "physical, index = self._parse_current_authority_bundle()"
            ).body
        assert ast.dump(before[name]) == ast.dump(after[name]), name
    tree = ast.parse(Path(parser.__file__).read_text())
    old_parse = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "parse_bundle"
    )
    business = after["_parse_current_authority_bundle"].body[-1].body
    start = next(
        i
        for i, n in enumerate(business)
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "_require"
    )
    copied = business[start:]
    assert [ast.dump(n) for n in copied[:-1]] == [ast.dump(n) for n in old_parse.body[1:-1]]
    expected = old_parse.body[-1].value
    expected.args[6] = ast.parse("verified_digest()", mode="eval").body
    assert ast.dump(copied[-1].value.elts[1]) == ast.dump(expected)


def test_exactly_one_duplicate_hash_removed_and_first_close_retained(tmp_path, monkeypatch):
    import v0224_bundle_read_scope as old

    config, leaf, raw, _, _ = fixture(tmp_path)
    package = config["bundle_path"].read_bytes()
    original_hash = hashlib.sha256
    calls = []

    def count(data=b"", *args, **kwargs):
        calls.append(bytes(data))
        return original_hash(data, *args, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", count)
    stats = []
    for cls, expected in ((old.BundleReadScope, 3), (BundleReadScope, 2)):
        calls.clear()
        with cls(**config) as scope:
            scope.read_bytes(leaf, sha(raw))
            import v0224_static_bundle as parser

            assert scope._index._source is scope._authority
            # Equality against public parser checked after restoring counted operation window.
            saved = list(calls)
            assert scope._index == parser.parse_bundle(scope._authority, config["limits"])
            calls[:] = saved
        assert calls.count(package) == expected
        stats.append(scope.stats)
        if cls is old.BundleReadScope:
            original_calls = list(calls)
        else:
            reduced = list(original_calls)
            removed = [i for i, data in enumerate(reduced) if data == package][1]
            del reduced[removed]
            assert calls == reduced
    assert stats[0] == stats[1]


@pytest.mark.parametrize("state", ["not_entered", "closed", "poisoned", "foreign", "subclass"])
def test_private_entry_rejects_invalid_scope_before_io(tmp_path, state):
    config, *_ = fixture(tmp_path)
    cls = (
        type("UnsupportedScope", (BundleReadScope,), {}) if state == "subclass" else BundleReadScope
    )
    scope = cls(**config)
    if state != "not_entered":
        scope.__enter__()
    if state == "closed":
        scope._closed = True
    if state == "poisoned":
        scope._poison(RuntimeError("prior"))
    if state == "foreign":
        scope._owner = (-1, -1)
    with pytest.raises(ValueError):
        scope._parse_current_authority_bundle()
    assert scope.stats["first_read_attempts"] == 0


@pytest.mark.parametrize("change", ["raw", "entry", "expected", "identity", "owner"])
def test_mid_parser_witness_replacement_rejected(tmp_path, monkeypatch, change):
    import v0224_static_bundle as parser

    config, leaf, raw, _, _ = fixture(tmp_path)
    original_environment = parser._environment
    scope = BundleReadScope(**config)

    def mutate(value, files):
        original_environment(value, files)
        entry = scope._entries[config["bundle_path"]]
        if change == "raw":
            entry.data = bytes(bytearray(entry.data))
        elif change == "entry":
            from v0222_admission_read_scope import _Entry

            scope._entries[config["bundle_path"]] = _Entry(
                entry.expected, entry.identity, entry.data
            )
        elif change == "expected":
            entry.expected = "0" * 64
        elif change == "identity":
            entry.identity = None
        else:
            scope._owner = (-1, -1)

    monkeypatch.setattr(parser, "_environment", mutate)
    with pytest.raises(ValueError, match=r"WITNESS|OWNER"):
        with scope:
            scope.read_bytes(leaf, sha(raw))
    assert scope.status == "CLOSED_FAILED"


@pytest.mark.parametrize("damage", ["magic", "header", "blob"])
def test_freshly_pinned_corrupt_package_still_runs_original_parser(tmp_path, damage):
    import v0224_static_bundle as parser

    config, leaf, raw, _, _ = fixture(tmp_path)
    package = config["bundle_path"].read_bytes()
    if damage == "magic":
        package = b"!" + package[1:]
    elif damage == "header":
        package = package[:22] + b"!" + package[23:]
    else:
        package = package[:-1] + bytes([package[-1] ^ 1])
    config["bundle_path"].write_bytes(package)
    config["bundle_sha256"] = sha(package)
    receipt = json.loads(config["receipt_path"].read_bytes())
    receipt["bundle_sha256"] = sha(package)
    config["receipt_path"].write_bytes(encoded(receipt))
    config["receipt_sha256"] = sha(config["receipt_path"].read_bytes())
    with pytest.raises(Exception) as previous:
        parser.parse_bundle(package, config["limits"])
    with pytest.raises(type(previous.value)) as current:
        with BundleReadScope(**config) as scope:
            scope.read_bytes(leaf, sha(raw))
    assert str(current.value) == str(previous.value)


def test_no_raw_digest_or_entry_arguments():
    import inspect

    assert list(inspect.signature(BundleReadScope._parse_current_authority_bundle).parameters) == [
        "self"
    ]
