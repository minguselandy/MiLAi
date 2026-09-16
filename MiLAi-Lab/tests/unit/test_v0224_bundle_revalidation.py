"""Independent semantic replay negatives using new complete synthetic closures."""

import hashlib
import json
import platform
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0224_bundle_revalidation as replay
import v0224_static_bundle as bundle
from v0220_evidence import dependencies

LIMITS = bundle.BundleLimits(2_000_000, 2_000_000, 200, 200)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bundle.canonical_json(value))
    return sha(path.read_bytes())


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    import v0222_scoped_cpu_guard as guard

    monkeypatch.setattr(guard, "require_cpu_network_guard", lambda: None)
    leaf = tmp_path / "leaf.json"
    leaf_sha = save(leaf, {"unused": [1, {"x": True}]})
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_bytes(b'{"event":"synthetic"}\n')
    extra = tmp_path / "verifier-only-fresh.txt"
    extra.write_bytes(b"must read even though no tree edge reaches this file")
    first = tmp_path / "a/manifest.json"
    first_sha = save(
        first,
        {
            "dependencies": {},
            "inputs": {str(leaf): leaf_sha},
            "python": platform.python_version(),
            "packages": {},
        },
    )
    second = tmp_path / "b/manifest.json"
    second_sha = save(
        second,
        {
            "dependencies": {},
            "inputs": {
                str(first): first_sha,
                str(leaf): leaf_sha,
                str(ledger): sha(ledger.read_bytes()),
            },
            "python": platform.python_version(),
            "packages": {},
        },
    )
    roles = {
        str(path): {"sha256": sha(path.read_bytes()), "roles": ["SYNTHETIC_LIVE"]}
        for path in (ledger, extra)
    }
    root = tmp_path / "sealed"
    bundle.seal_static_bundle(
        root,
        roots=[{"path": str(second), "sha256": second_sha, "purpose": "STATIC_TREE"}],
        fresh_roles=roles,
        limits=LIMITS,
    )
    return root, leaf, ledger, extra, first, second


def inputs(root):
    values = {}
    for key, name in (
        ("candidate", "candidate-receipt.json"),
        ("bundle", "static.bundle"),
        ("observation", "seal-observation.json"),
    ):
        path = root / name
        values[key + "_path"] = path
        values[key + "_sha256"] = sha(path.read_bytes())
    values["verifier_files"] = {
        str(p): sha(p.read_bytes()) for p in dependencies([Path(replay.__file__)])
    }
    values["limits"] = LIMITS
    return values


def repack(root, change):
    """Forge a syntactically valid candidate, never an approved runtime receipt."""
    raw = (root / "static.bundle").read_bytes()
    index = bundle.parse_bundle(raw, LIMITS)
    header_size = int.from_bytes(raw[len(bundle.MAGIC) : len(bundle.MAGIC) + 8], "big")
    header = json.loads(raw[len(bundle.MAGIC) + 8 : len(bundle.MAGIC) + 8 + header_size])
    members = {path: index.member_bytes(path, digest) for path, digest in index.files.items()}
    candidate = load(root / "candidate-receipt.json")
    observed = load(root / "seal-observation.json")
    change(header, members, candidate, observed)
    header["files"] = {path: sha(data) for path, data in members.items()}
    unique = {sha(data): data for data in members.values()}
    blobs, chunks, cursor = {}, [], 0
    for digest, data in sorted(unique.items()):
        blobs[digest] = {"offset": cursor, "length": len(data)}
        chunks.append(data)
        cursor += len(data)
    header["blobs"] = blobs
    encoded = bundle.canonical_json(header)
    package = bundle.MAGIC + len(encoded).to_bytes(8, "big") + encoded + b"".join(chunks)
    (root / "static.bundle").write_bytes(package)
    candidate["bundle_sha256"] = sha(package)
    candidate["proof_roots"] = header["roots"]
    candidate["environment"] = {key: header["manifest_env"][key] for key in ("python", "packages")}
    save(root / "candidate-receipt.json", candidate)
    save(root / "seal-observation.json", observed)


def test_complete_original_semantics_and_fresh_non_tree_roles(sealed, tmp_path):
    root, leaf, _, extra, _, _ = sealed
    leaf.unlink()  # R03 static authority does not use old-path bytes.
    result = replay.revalidate_candidate(tmp_path / "review", **inputs(root))
    assert result["status"] == "MECHANICAL_STATIC_REVALIDATION_COMPLETE_NOT_APPROVAL"
    assert result["runtime_authorized"] is False
    assert str(extra) in result["logical_files"]
    assert len(result["manifest_environment"]["sources"]) == 2
    assert result["replay_physical_stats"]["closing_reads"] > 0
    assert (
        result["replay_physical_stats"]["first_reads"]
        == result["replay_physical_stats"]["closing_reads"]
    )
    assert result["static_logical_paths"] == 3
    assert load(root / "candidate-receipt.json")["status"] == "STATIC_BUNDLE_CANDIDATE_NOT_APPROVED"
    assert not (tmp_path / "review/approved-receipt.json").exists()


@pytest.mark.parametrize("control", ["candidate", "bundle", "observation"])
def test_external_pin_drift_refuses(sealed, tmp_path, control):
    root = sealed[0]
    args = inputs(root)
    args[control + "_path"].write_bytes(b"changed")
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        replay.revalidate_candidate(tmp_path / "review", **args)
    assert (
        load(tmp_path / "review/revalidation-failure.json")["status"]
        == "MECHANICAL_REVALIDATION_FAILED"
    )


@pytest.mark.parametrize("mutation", ["missing", "wrong_digest"])
def test_external_source_pins_complete_and_current(sealed, tmp_path, mutation):
    args = inputs(sealed[0])
    if mutation == "missing":
        args["verifier_files"].pop(str(Path(replay.__file__)))
    else:
        args["verifier_files"][str(Path(replay.__file__))] = "0" * 64
    with pytest.raises(ValueError, match=r"SOURCE_PINS|INITIAL_CONTENT_HASH_MISMATCH"):
        replay.revalidate_candidate(tmp_path / "review", **args)


def test_approved_receipt_cannot_short_circuit_mechanical_replay(sealed, tmp_path):
    root = sealed[0]
    candidate = load(root / "candidate-receipt.json")
    candidate["status"] = "INDEPENDENT_STATIC_BUNDLE_APPROVED"
    save(root / "candidate-receipt.json", candidate)
    with pytest.raises(ValueError, match="NO_APPROVED_RECEIPT"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(root))


@pytest.mark.parametrize(
    "bad", [b'{"unused":{"x":1,"x":2}}', b'{"unused":NaN}', b'{"unused":"\xff"}', b'{"files":[]}']
)
def test_valid_blob_hash_is_not_a_semantic_certificate(sealed, tmp_path, bad):
    root, _, _, _, _, second = sealed

    def change(header, members, candidate, observed):
        members[str(second)] = bad
        header["roots"][0]["sha256"] = sha(bad)
        header["manifest_env"]["sources"].pop(str(second))
        observed["observed_files"][str(second)] = sha(bad)
        observed["manifest_environment_sources"].pop(str(second))

    repack(root, change)
    # The format/hash parser accepts; only independent original semantic replay rejects.
    bundle.parse_bundle((root / "static.bundle").read_bytes(), LIMITS)
    with pytest.raises((ValueError, UnicodeError)) as caught:
        replay.revalidate_candidate(tmp_path / "review", **inputs(root))
    assert "ORIGINAL_SEAL_VOLUME_DRIFT" not in str(caught.value)
    assert not (tmp_path / "review/mechanical-revalidation.json").exists()


def test_omitted_nested_manifest_environment_detected(sealed, tmp_path):
    root, _, _, _, first, _ = sealed

    def change(header, members, candidate, observed):
        header["manifest_env"]["sources"].pop(str(first))
        observed["manifest_environment_sources"].pop(str(first))

    repack(root, change)
    with pytest.raises(ValueError, match="COMPLETE_MANIFEST_ENVIRONMENT_REPLAY_DRIFT"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(root))


def test_unreferenced_member_cannot_be_claimed_as_visited(sealed, tmp_path):
    root = sealed[0]
    extra = str(tmp_path / "unreferenced.json")

    def change(header, members, candidate, observed):
        members[extra] = b"{}"
        observed["observed_files"][extra] = sha(b"{}")

    repack(root, change)
    with pytest.raises(ValueError, match="REPLAY_LOGICAL_CLOSURE_DRIFT"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(root))


def test_omitted_static_member_cannot_fall_back_to_disk(sealed, tmp_path):
    root, leaf, _, _, _, _ = sealed

    def change(header, members, candidate, observed):
        members.pop(str(leaf))
        observed["observed_files"].pop(str(leaf))

    repack(root, change)
    with pytest.raises(ValueError, match="REPLAY_LOGICAL_CLOSURE_DRIFT"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(root))


@pytest.mark.parametrize("member", [2, 3])
def test_all_fresh_roles_physically_read_even_if_not_reached_by_tree(sealed, tmp_path, member):
    sealed[member].write_bytes(b"changed fresh bytes")
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(sealed[0]))


def test_environment_verifier_executes_in_original_tree(sealed, tmp_path, monkeypatch):
    monkeypatch.setattr(platform, "python_version", lambda: "0.synthetic")
    with pytest.raises(ValueError, match="PYTHON_DRIFT"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(sealed[0]))


@pytest.mark.parametrize(
    "target", ["static.bundle", "candidate-receipt.json", "seal-observation.json"]
)
def test_control_closing_drift_blocks_report(sealed, tmp_path, monkeypatch, target):
    original = replay.verify_tree

    def tree(*args, **kwargs):
        result = original(*args, **kwargs)
        p = sealed[0] / target
        data = p.read_bytes()
        p.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        return result

    monkeypatch.setattr(replay, "verify_tree", tree)
    with pytest.raises(ValueError, match="CLOSING_CONTENT_OR_PATH_IDENTITY_MISMATCH"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(sealed[0]))
    assert not (tmp_path / "review/mechanical-revalidation.json").exists()


def test_synthetic_guard_refusal_before_output(sealed, tmp_path, monkeypatch):
    import v0222_scoped_cpu_guard as guard

    def refuse():
        raise RuntimeError("synthetic CPU guard absent")

    monkeypatch.setattr(guard, "require_cpu_network_guard", refuse)
    with pytest.raises(RuntimeError, match="CPU guard absent"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(sealed[0]))
    assert not (tmp_path / "review").exists()


@pytest.mark.parametrize("field", ["first_read_attempts", "closing_read_attempts"])
def test_complete_original_stats_not_just_selected_totals(sealed, tmp_path, field):
    path = sealed[0] / "seal-observation.json"
    observed = load(path)
    observed["original_scope_stats"][field] += 1
    save(path, observed)
    with pytest.raises(ValueError, match="EXACT_ORIGINAL_LOGICAL_STATS_REQUIRED"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(sealed[0]))


def test_fresh_role_closing_drift_blocks_semantic_receipt(sealed, tmp_path, monkeypatch):
    original = replay.verify_tree

    def tree(*args, **kwargs):
        result = original(*args, **kwargs)
        sealed[2].write_bytes(b"changed after original tree read")
        return result

    monkeypatch.setattr(replay, "verify_tree", tree)
    with pytest.raises(ValueError, match="CLOSING_CONTENT_OR_PATH_IDENTITY_MISMATCH"):
        replay.revalidate_candidate(tmp_path / "review", **inputs(sealed[0]))
    assert not (tmp_path / "review/mechanical-revalidation.json").exists()


def test_primary_survives_external_control_closing_failure(sealed, tmp_path, monkeypatch):
    original = replay.verify_tree
    primary = RuntimeError("original semantic primary")

    def tree(*args, **kwargs):
        original(*args, **kwargs)
        (sealed[0] / "static.bundle").write_bytes(b"closing drift")
        raise primary

    monkeypatch.setattr(replay, "verify_tree", tree)
    with pytest.raises(RuntimeError) as caught:
        replay.revalidate_candidate(tmp_path / "review", **inputs(sealed[0]))
    assert caught.value is primary
    assert any("closing" in note for note in primary.__notes__)
    failure = load(tmp_path / "review/revalidation-failure.json")
    assert failure["reason"] == "original semantic primary"


def test_original_deepcopy_recursion_refusal_is_replayed(sealed, tmp_path):
    root, _, _, _, _, second = sealed
    bad = b'{"unused":' + b"[" * 600 + b"0" + b"]" * 600 + b"}"

    def change(header, members, candidate, observed):
        members[str(second)] = bad
        header["roots"][0]["sha256"] = sha(bad)
        header["manifest_env"]["sources"].pop(str(second))
        observed["observed_files"][str(second)] = sha(bad)
        observed["manifest_environment_sources"].pop(str(second))

    repack(root, change)
    bundle.parse_bundle((root / "static.bundle").read_bytes(), LIMITS)
    with pytest.raises(RecursionError):
        replay.revalidate_candidate(tmp_path / "review", **inputs(root))
    failure = load(tmp_path / "review/revalidation-failure.json")
    assert failure["exception_type"] == "RecursionError"
