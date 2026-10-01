"""Opt-in scoped generation reservations; a reservation is not a wire receipt."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

SCHEMA = "durable_shared_admission_v1"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _reject(reason: str) -> None:
    raise ValueError("GENERATION_ADMISSION_" + reason)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _persist(path: Path, state: dict[str, Any]) -> None:
    # Separate opt-in IO: do not change legacy artifact bytes/atomic-write behavior.
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class DurableGenerationAdmission:
    """One file/lock owns all callbacks; resume never substitutes a Host lower bound."""

    def __init__(self, path: Path, message: str, scope: dict[str, Any],
                 host_config: dict[str, Any], cap: int, phase: str,
                 checkpoint_calls: int) -> None:
        if phase not in {"start", "resume"}:
            _reject("EXPLICIT_PHASE_REQUIRED")
        if type(cap) is not int or cap <= 0:
            _reject("CAP_INVALID")
        if type(checkpoint_calls) is not int or checkpoint_calls < 0:
            _reject("CHECKPOINT_INVALID")
        if not isinstance(scope, dict) or set(scope) != {
            "owner", "bank", "session", "request_ref", "request_sha256", "config_sha256"
        }:
            _reject("SCOPE_INVALID")
        if any(type(scope[name]) is not str or not scope[name] for name in (
            "owner", "session", "request_ref", "request_sha256", "config_sha256"
        )) or type(message) is not str or not message:
            _reject("IDENTITY_INVALID")
        bank = scope["bank"]
        if (type(bank) is not list or not bank
                or any(type(row) is not str or not row for row in bank)):
            _reject("BANK_INVALID")
        if any(len(scope[name]) != 64 or any(char not in "0123456789abcdef"
                                           for char in scope[name])
               for name in ("request_sha256", "config_sha256")):
            _reject("HASH_INVALID")
        self.path, self.cap = path, cap
        self.identity = json.loads(json.dumps({**scope, "public_message_id": message}))
        self.configuration = json.loads(json.dumps({
            "owner": scope["owner"], "bank": bank, "config_sha256": scope["config_sha256"],
            "host": host_config, "cap": cap,
        }, allow_nan=False))
        self.key = _hash([scope["owner"], bank, scope["session"], message])
        with _locked(path):
            if not path.exists():
                if phase == "resume":
                    _reject("RESUMED_FILE_MISSING")
                state = {"schema": SCHEMA, "configuration": self.configuration, "messages": {}}
            else:
                state = self._load()
            row = state["messages"].get(self.key)
            if phase == "resume":
                if row is None:
                    _reject("RESUMED_MESSAGE_MISSING")
                self._match(row, checkpoint_calls)
            else:
                if row is not None:
                    _reject("MESSAGE_ALREADY_STARTED")
                if checkpoint_calls != 0:
                    _reject("START_HAS_CHECKPOINT_CALLS")
                row = {"identity": self.identity, "count": 0, "reservations": []}
                state["messages"][self.key] = row
                _persist(path, state)
            self.count = row["count"]

    def _load(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text())
        except (OSError, ValueError) as error:
            raise ValueError("GENERATION_ADMISSION_STATE_UNREADABLE") from error
        if (type(state) is not dict or set(state) != {"schema", "configuration", "messages"}
                or state["schema"] != SCHEMA or state["configuration"] != self.configuration
                or type(state["messages"]) is not dict):
            _reject("STATE_INCOMPATIBLE")
        for key, row in state["messages"].items():
            if (type(key) is not str or type(row) is not dict
                    or set(row) != {"identity", "count", "reservations"}
                    or type(row["identity"]) is not dict
                    or type(row["count"]) is not int or not 0 <= row["count"] <= self.cap
                    or type(row["reservations"]) is not list
                    or len(row["reservations"]) != row["count"]):
                _reject("COUNTER_INVALID")
            for ordinal, reservation in enumerate(row["reservations"], start=1):
                if (type(reservation) is not dict or set(reservation) != {"ordinal", "origin"}
                        or type(reservation["ordinal"]) is not int
                        or reservation["ordinal"] != ordinal
                        or (reservation["origin"] is not None
                            and (type(reservation["origin"]) is not str
                                 or not reservation["origin"]))):
                    _reject("RESERVATION_INVALID")
        return cast(dict[str, Any], state)

    def _match(self, row: dict[str, Any], checkpoint_calls: int) -> None:
        if row["identity"] != self.identity:
            _reject("MESSAGE_IDENTITY_CHANGED")
        if row["count"] < checkpoint_calls or row["count"] < getattr(self, "count", 0):
            _reject("COUNTER_BELOW_LOWER_BOUND")

    def reserve(self, host_config: dict[str, Any], cap: int,
                origin: str | None = None) -> int:
        if host_config != self.configuration["host"] or cap != self.cap:
            _reject("CONFIGURATION_CHANGED")
        if origin is not None and (type(origin) is not str or not origin):
            _reject("ORIGIN_INVALID")
        with _locked(self.path):
            if not self.path.exists():
                _reject("RESUMED_FILE_MISSING")
            state = self._load()
            row = state["messages"].get(self.key)
            if row is None:
                _reject("RESUMED_MESSAGE_MISSING")
            self._match(row, 0)
            if row["count"] >= self.cap:
                raise ValueError("PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED")
            count: int = row["count"] + 1
            row["reservations"].append({"ordinal": count, "origin": origin})
            row["count"] = count
            _persist(self.path, state)
            self.count = count
            return count
