"""Non-model checks executed inside the actual readable container."""

# Fixed fixtures and reviewed historical reads; network disabled, no credentials mounted.
# ruff: noqa: S603, S607

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shlex
import subprocess
from pathlib import Path


def main() -> None:
    assert "MILAI_CODEX_LAUNCHER_TOKEN" not in os.environ
    assert not (Path(os.environ["CODEX_HOME"]) / "auth.json").exists()
    versions = {}
    for program in ("python", "python3", "jq", "rg"):
        r = subprocess.run([program, "--version"], capture_output=True, timeout=10, check=True)
        versions[program] = (r.stdout + r.stderr).decode().strip().splitlines()[0]
    fixture = {"text": "  中文🙂\r\n\t\n", "empty": "", "null": None, "list": []}
    Path("fixture.json").write_text(json.dumps(fixture, ensure_ascii=False))
    for program in ("python", "python3"):
        r = subprocess.run([program, "-c", "import json;print(json.dumps(json.load("
                            "open('fixture.json')),ensure_ascii=False))"],
                           capture_output=True, timeout=10, check=True)
        assert json.loads(r.stdout) == fixture
    r = subprocess.run(["jq", ".", "fixture.json"], capture_output=True, timeout=10, check=True)
    assert json.loads(r.stdout) == fixture
    loader = importlib.machinery.SourceFileLoader("reader", "/usr/local/bin/milai-read")
    spec = importlib.util.spec_from_loader(loader.name, loader)
    reader = importlib.util.module_from_spec(spec)
    loader.exec_module(reader)
    pages = []
    for filename in ("fixture.json", "sources/history.json"):
        original = Path(filename).read_bytes()
        recovered, offset, sha, count, maximum = b"", 0, None, 0, 0
        while True:
            value = reader.read_page(Path.cwd(), filename, offset, 4096, sha)
            size = len(reader.encode(value))
            assert size <= 4096
            maximum = max(size, maximum)
            recovered += value["text"].encode()
            count += 1
            if value["next"] is None:
                break
            offset, sha = value["next"]["offset"], value["next"]["sha256"]
        assert recovered == original
        pages.append({"file": filename, "bytes": len(original), "pages": count,
                      "max_response_bytes": maximum,
                      "sha256": hashlib.sha256(original).hexdigest()})
    for path in ("fixture.json", "missing", "../home/auth.json", "/etc/passwd"):
        r = subprocess.run(["milai-read", path, "--max-bytes", "512"],
                           capture_output=True, timeout=10)
        data = json.loads(r.stdout)
        assert len(r.stdout) <= 512
        assert (r.returncode == 0) == (path == "fixture.json")
        assert (data["status"] != "ERROR") == (path == "fixture.json")
    denied = False
    try:
        Path("sources/write-probe").write_text("must fail")
    except OSError:
        denied = True
    assert denied
    commands = []
    for job in json.loads(Path("jobs.json").read_text()):
        # These historical read-only commands were reviewed before this replay.
        r = subprocess.run(shlex.split(job["command"]), capture_output=True, timeout=20)
        Path(job["id"] + ".stdout").write_bytes(r.stdout)
        Path(job["id"] + ".stderr").write_bytes(r.stderr)
        commands.append({"id": job["id"], "old_exit_code": job["exit_code"],
            "new_exit_code": r.returncode, "stdout_bytes": len(r.stdout),
            "stdout_sha256": hashlib.sha256(r.stdout).hexdigest(),
            "stderr_bytes": len(r.stderr)})
    print(json.dumps({"status": "PASS" if all(c["new_exit_code"] == 0 for c in commands)
                      else "REPLAY_HAS_ERRORS", "versions": versions, "pages": pages,
                      "source_write_denied": denied, "commands": commands,
                      "provider_calls": 0, "model_executions": 0}))


if __name__ == "__main__":
    main()
