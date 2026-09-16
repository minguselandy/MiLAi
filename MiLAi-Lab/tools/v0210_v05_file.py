"""Strong local notes control: Git history, exclusive CAS lock and operation receipts."""

# ruff: noqa: S603, S607 -- fixed Git executable and synthetic host-owned argv

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from pathlib import Path


class GitNotes:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        if not (root / ".git").exists():
            self.git("init", "--quiet")
            self.git("config", "user.name", "Synthetic recovery host")
            self.git("config", "user.email", "synthetic@localhost")
            self.git("config", "core.fsync", "committed")

    def git(self, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True,
                                text=True)
        return result.stdout.strip()

    def get(self) -> dict:
        if not (self.root / "note.json").exists():
            return {"status": "ABSENT", "version": 0, "payload": {}}
        return json.loads(self.git("show", "HEAD:note.json"))

    def update(self, operation_id: str, expected_version: int, payload: dict) -> dict:
        with (self.root / "writer.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = self.get()
            if current["version"]:
                for commit in self.git("rev-list", "HEAD").splitlines():
                    past = json.loads(self.git("show", f"{commit}:note.json"))
                    if past["operation_id"] == operation_id:
                        if (past["expected_version"] != expected_version
                                or past["payload"] != payload):
                            return {"status": "OPERATION_INPUT_CONFLICT"}
                        return {**past, "replayed": True}
            if current["version"] != expected_version:
                return {"status": "STALE_VERSION", "version": current["version"]}
            value = {"status": "ACTIVE", "version": expected_version + 1,
                     "operation_id": operation_id, "expected_version": expected_version,
                     "payload": payload}
            with (self.root / "note.json").open("w") as output:
                json.dump(value, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            self.git("add", "note.json")
            self.git("commit", "--quiet", "-m", operation_id)
            return {**value, "replayed": False}
