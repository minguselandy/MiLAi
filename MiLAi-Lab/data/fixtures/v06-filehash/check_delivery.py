"""Frozen necessary CLI conditions, run only after a native task session exits."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

phase = sys.argv[1]
default = "sha512" if phase in {"R2", "R3"} else "sha256"
cli = Path("/workspace/filehash.py")
assert cli.is_file() and Path("/workspace/README.md").is_file()
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    binary = root / "二进制.bin"
    binary.write_bytes(b"\x00\xff\r\nFIRST\nLAST\x00")
    missing = root / "missing.txt"
    empty = root / "empty.txt"
    empty.write_bytes(b"")
    files = [binary.name, missing.name, empty.name, binary.name]
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    modes = [(default, [])] if phase == "G" else [
        (default, []), ("sha256", ["--algorithm", "sha256"]),
        ("sha512", ["--algorithm", "sha512"])]
    observations = []
    for algorithm, options in modes:
        result = subprocess.run([sys.executable, str(cli), *options, *files], cwd=root,
                                capture_output=True, timeout=5)
        assert result.returncode == 1
        assert binary.name.encode() in result.stdout
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        assert [row["path"] for row in rows] == files
        for index in (0, 2, 3):
            assert rows[index] == {"path": files[index], algorithm:
                hashlib.new(algorithm, before[files[index]]).hexdigest()}
        assert set(rows[1]) == {"path", "error"} and isinstance(rows[1]["error"], str)
        assert rows[1]["error"]
        success = subprocess.run([sys.executable, str(cli), *options, empty.name], cwd=root,
                                 capture_output=True, timeout=5)
        assert success.returncode == 0 and len(success.stdout.splitlines()) == 1
        assert {p.name: p.read_bytes() for p in root.iterdir()} == before
        observations.append({"algorithm": algorithm, "options": options, "checked": True})
    assert os.getcwd() == "/workspace"
print(json.dumps({"status": "PASS_NECESSARY_CLI_CONDITIONS", "phase": phase,
                  "modes": observations, "semantic_quality_outside_these_checks": "NOT_EVALUATED"}))
