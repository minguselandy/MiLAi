"""SimpleMem source provenance uses Git metadata, without reading bodies for digests."""

import shutil
import subprocess
from pathlib import Path

from milai_lab.integrations.memory import simplemem


def test_identity_records_actual_changed_source_without_digest_or_revision_gate(
    tmp_path, monkeypatch,
):
    root = tmp_path / "native"
    package = root / "simplemem"
    package.mkdir(parents=True)
    tracked = package / "core.py"
    tracked.write_text("value = 'original'\n")
    git = shutil.which("git") or "/usr/bin/git"
    for arguments in (["init", "-q", "-b", "test", str(root)],
                      ["-C", str(root), "add", "simplemem"],
                      ["-C", str(root), "-c", "user.name=Test", "-c",
                       "user.email=test@example.invalid", "commit", "-qm", "initial"]):
        subprocess.run([git, *arguments], check=True)  # noqa: S603 - fixed temporary test repo
    tracked.write_text("value = 'actual changed source'\n")
    (package / "extension.py").write_text("extension = True\n")
    monkeypatch.setattr(simplemem.importlib.metadata, "version", lambda name: "test-installed")

    def forbidden(*args, **kwargs):
        raise AssertionError("Source identity must not read bodies for SHA verification")

    monkeypatch.setattr(simplemem.hashlib, "sha256", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    identity = simplemem.dependency_identity({
        "source_root": str(root), "source_commit": "historical-declaration"})
    assert identity["declared_source_commit"] == "historical-declaration"
    assert identity["source_commit"] != identity["declared_source_commit"]
    assert identity["source_modules"] == ["simplemem/core.py", "simplemem/extension.py"]
    assert identity["source_changes"] == [" M simplemem/core.py", "?? simplemem/extension.py"]
    assert "source_sha256" not in identity
    assert identity["dependencies"]["lancedb"] == "test-installed"
