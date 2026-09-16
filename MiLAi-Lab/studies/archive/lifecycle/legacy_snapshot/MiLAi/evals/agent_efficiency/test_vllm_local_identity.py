from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from evals.agent_efficiency import vllm_local_identity as identity


def test_strict_base_url_accepts_only_explicit_ipv4_loopback_origin() -> None:
    assert identity.strict_base_url("http://127.0.0.1:7860") == (
        "http://127.0.0.1:7860"
    )
    rejected = (
        "https://127.0.0.1:7860",
        "http://localhost:7860",
        "http://127.0.0.1",
        "http://127.0.0.1:7860/v1",
        "http://127.0.0.1:7860?next=http://example.test",
        "http://127.0.0.2:7860",
        "http://user@127.0.0.1:7860",
    )
    for value in rejected:
        with pytest.raises(identity.LocalVllmIdentityError):
            identity.strict_base_url(value)


def test_model_closure_is_content_bound_and_rejects_symlinks(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"model":"synthetic"}\n', encoding="utf-8")
    weights = model / "model.safetensors"
    weights.write_bytes(b"synthetic-weights")
    first = identity.model_closure(model)
    assert first["file_count"] == 2
    assert first["total_bytes"] == sum(path.stat().st_size for path in model.iterdir())
    assert first["entries_sha256"] == identity.sha256_bytes(
        identity.canonical_bytes(first["entries"])
    )

    weights.write_bytes(b"different-weights")
    second = identity.model_closure(model)
    assert second["entries_sha256"] != first["entries_sha256"]

    (model / "escape").symlink_to(tmp_path / "outside")
    with pytest.raises(identity.LocalVllmIdentityError, match="symlink"):
        identity.model_closure(model)


def test_atomic_report_is_private_and_parseable(tmp_path: Path) -> None:
    output = tmp_path / "identity.json"
    value = {"schema": "synthetic", "status": "LOCAL"}
    identity.atomic_write(output, value)
    assert json.loads(output.read_text(encoding="utf-8")) == value
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
