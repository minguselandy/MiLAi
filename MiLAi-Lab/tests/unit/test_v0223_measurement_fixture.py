"""Reject pre-seal isolation and post-observation integrity drift offline."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0223_measurement_fixture import (
    _check_sealed_pins,
    _public_inputs,
    _require_fresh_root,
)
from v0222_admission_read_scope import AdmissionReadScope


def test_public_source_pin_is_read_through_historical_manifest(tmp_path):
    source = tmp_path / "public-initial.json"
    source.write_text('{"public": true}')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"inputs": {str(source): digest}}))
    binding = tmp_path / "execution-binding.json"
    binding.write_text(
        json.dumps({"manifest.json": hashlib.sha256(manifest.read_bytes()).hexdigest()})
    )
    # A wrapper inventory legitimately lists controls rather than their leaves.
    outer_inputs = {str(binding): hashlib.sha256(binding.read_bytes()).hexdigest()}
    assert str(source) not in outer_inputs
    with AdmissionReadScope() as scope:
        pins = _public_inputs(scope, tmp_path, outer_inputs[str(binding)])
        assert scope.read_json(source, pins[str(source)]) == {"public": True}
    assert scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"


def test_symlink_parent_rejected_before_any_seal_write(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="CANONICAL"):
        _require_fresh_root(alias / "k1-u1")
    assert not (outside / "k1-u1").exists()


def test_stopped_or_partial_fixture_cannot_be_reused(tmp_path):
    root = tmp_path / "k1-u1"
    _require_fresh_root(root)
    root.mkdir()
    with pytest.raises(ValueError, match="NO_RETRY"):
        _require_fresh_root(root)


@pytest.mark.parametrize("field", ["inputs", "dependencies"])
def test_changed_bytes_between_scope_close_and_seal_cannot_get_new_pins(field):
    inputs, sources = {"/input": "old"}, {"/source": "old"}
    sealed = {"inputs": dict(inputs), "dependencies": dict(sources)}
    _check_sealed_pins(sealed, inputs, sources)
    name = next(iter(sealed[field]))
    sealed[field][name] = "new"
    with pytest.raises(ValueError, match="CHANGED_AFTER_SCOPE_CLOSE"):
        _check_sealed_pins(sealed, inputs, sources)
