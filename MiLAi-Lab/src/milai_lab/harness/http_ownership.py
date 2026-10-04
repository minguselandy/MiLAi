"""Cooperating local Linux ledger lease and shared synchronous request ownership.

No provider import, backend/distributed CAS, noncooperating-writer guarantee, or
inclusive generation admission is supplied by this infrastructure contract.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from threading import Lock, get_ident
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

PROFILE = "serialized_ledger_owner_v1"
CONFIG_FIELDS = frozenset(
    {
        "base_url",
        "model",
        "temperature",
        "max_tokens",
        "timeout",
        "tool_mode",
        "max_calls",
        "response_format",
        "enable_thinking",
    }
)


class HttpOwnershipError(RuntimeError):
    """An explicit infrastructure rejection; no implicit retry or refund."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalized_url(value: Any) -> str:
    if type(value) is not str or not value:
        raise HttpOwnershipError("HTTP_OWNER_URL_INVALID")
    u = urlsplit(value)
    if (
        u.scheme not in {"http", "https"}
        or not u.hostname
        or u.username is not None
        or u.password is not None
        or u.query
        or u.fragment
    ):
        raise HttpOwnershipError("HTTP_OWNER_URL_INVALID")
    port = u.port
    host = u.hostname.lower()
    if ":" in host:
        host = "[" + host + "]"
    if port is not None and port != (80 if u.scheme == "http" else 443):
        host += ":" + str(port)
    return urlunsplit((u.scheme, host, u.path.rstrip("/"), "", ""))


def normalized_config(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != CONFIG_FIELDS:
        raise HttpOwnershipError("HTTP_OWNER_COMPLETE_CLIENT_CONFIG_REQUIRED")
    if (
        type(value["model"]) is not str
        or not value["model"]
        or value["tool_mode"] not in {"native", "json_action"}
        or type(value["max_tokens"]) is not int
        or value["max_tokens"] < 0
        or type(value["max_calls"]) is not int
        or value["max_calls"] < 0
        or type(value["temperature"]) not in {int, float}
        or not math.isfinite(value["temperature"])
        or type(value["timeout"]) not in {int, float}
        or value["timeout"] <= 0
        or not math.isfinite(value["timeout"])
        or (value["enable_thinking"] is not None and type(value["enable_thinking"]) is not bool)
        or (value["response_format"] is not None and type(value["response_format"]) is not dict)
    ):
        raise HttpOwnershipError("HTTP_OWNER_CLIENT_CONFIG_INVALID")
    result = json.loads(canonical(value))
    result["base_url"] = normalized_url(result["base_url"])
    return cast(dict[str, Any], result)


def normalized_domain(value: Any) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value) != {"deployment_id", "clients"}
        or type(value["deployment_id"]) is not str
        or not value["deployment_id"]
        or type(value["clients"]) is not list
        or not value["clients"]
    ):
        raise HttpOwnershipError("HTTP_OWNER_EXPLICIT_DOMAIN_REQUIRED")
    clients = [normalized_config(c) for c in value["clients"]]
    ordered = sorted(clients, key=canonical)
    if len({canonical(c) for c in ordered}) != len(ordered):
        raise HttpOwnershipError("HTTP_OWNER_DUPLICATE_CLIENT_CONFIG")
    return {"deployment_id": value["deployment_id"], "clients": ordered}


def settings_profile(settings: dict[str, Any]) -> str:
    value = settings.get("http_ownership_profile", "legacy")
    if type(value) is not str or value not in {"legacy", PROFILE}:
        raise HttpOwnershipError("HTTP_OWNER_PROFILE_INVALID")
    if value != "legacy":
        normalized_domain(settings.get("http_ownership_domain"))
        if type(settings.get("budget_path")) is not str or not settings["budget_path"]:
            raise HttpOwnershipError("HTTP_OWNER_LEDGER_PATH_REQUIRED")
    return value


def freeze_fields(
    settings: dict[str, Any], *, client_configs: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    if settings_profile(settings) == "legacy":
        return {}
    domain = normalized_domain(settings["http_ownership_domain"])
    if client_configs is not None:
        allowed = {canonical(c) for c in domain["clients"]}
        if any(canonical(normalized_config(c)) not in allowed for c in client_configs):
            raise HttpOwnershipError("HTTP_OWNER_CLIENT_NOT_ALLOWED")
    return {
        "http_ownership_profile": PROFILE,
        "http_ownership_domain": domain,
        "http_ownership_binding": {
            "canonical_ledger": str(Path(settings["budget_path"]).resolve()),
            "domain_sha256": sha(canonical(domain)),
        },
    }


def check_frozen(frozen: dict[str, Any]) -> None:
    expected = freeze_fields(frozen["config"])
    for key in ("http_ownership_profile", "http_ownership_domain", "http_ownership_binding"):
        if canonical(frozen.get(key)) != canonical(expected.get(key)):
            raise HttpOwnershipError("HTTP_OWNER_FROZEN_CHANGED")


def validate_state(value: Any) -> dict[str, Any]:
    if type(value) is not dict or type(value.get("limits")) is not dict:
        raise HttpOwnershipError("HTTP_OWNER_LEDGER_MALFORMED")
    limits = value["limits"]
    if set(limits) != {
        "questions",
        "arms",
        "generation_requests",
        "generation_tokens",
        "embedding_tokens",
    }:
        raise HttpOwnershipError("HTTP_OWNER_LEDGER_MALFORMED")
    for key, item in limits.items():
        if item is None and key not in {"questions", "arms"}:
            continue
        if type(item) is not int or item < 0:
            raise HttpOwnershipError("HTTP_OWNER_LEDGER_MALFORMED")
    if type(value.get("generation_requests")) is not int or value["generation_requests"] < 0:
        raise HttpOwnershipError("HTTP_OWNER_LEDGER_MALFORMED")
    for kind in ("generation", "embedding"):
        counters = value.get(kind)
        if type(counters) is not dict:
            raise HttpOwnershipError("HTTP_OWNER_LEDGER_MALFORMED")
        for key in ("charged_tokens", "known_tokens", "unknown_usage"):
            if type(counters.get(key)) is not int or counters[key] < 0:
                raise HttpOwnershipError("HTTP_OWNER_LEDGER_MALFORMED")
        if counters["known_tokens"] > counters["charged_tokens"]:
            raise HttpOwnershipError("HTTP_OWNER_LEDGER_MALFORMED")
    if value["generation"]["unknown_usage"] > value["generation_requests"]:
        raise HttpOwnershipError("HTTP_OWNER_LEDGER_MALFORMED")
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise HttpOwnershipError("HTTP_OWNER_LEDGER_DUPLICATE_KEY")
        result[key] = value
    return result


class OwnedReservation(tuple[str, int]):
    """Ephemeral exact-object completion capability; persisted schema is unchanged."""

    def __new__(cls, kind: str, estimate: int) -> OwnedReservation:
        return tuple.__new__(cls, (kind, estimate))


class HttpOwnership:
    def __init__(self, ledger: Path, domain: Any) -> None:
        self.pid = os.getpid()
        self._pid = self.pid
        self.path = ledger.resolve()
        self.domain = normalized_domain(domain)
        self._domain_bytes = canonical(self.domain)
        self.lease_path = self.path.with_name(self.path.name + ".http-owner.lock")
        self._fd: int | None = None
        self.closed = False
        self.faulted = False
        self.budget: Any = None
        self.mutex = Lock()
        self._metadata = Lock()
        self._active_thread: int | None = None
        self._active_client: Any = None
        self._waiting = 0
        self._clients: dict[int, tuple[Any, bytes, bool]] = {}
        self._fd = os.open(
            self.lease_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
        )
        try:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise HttpOwnershipError("HTTP_OWNER_BUSY") from error
            stamp = os.fstat(self._fd)
            self._stamp = (stamp.st_dev, stamp.st_ino)
            self._lease_bytes = canonical(
                {"pid": self.pid, "canonical_ledger": str(self.path), "domain": self.domain}
            )
            os.ftruncate(self._fd, 0)
            os.write(self._fd, self._lease_bytes)
            os.fsync(self._fd)
            raw = self._read_disk()
            self._ledger_sha = sha(raw)
            self.initial_state = self._parse(raw)
        except BaseException:
            os.close(self._fd)
            self._fd = None
            self.closed = True
            raise

    @staticmethod
    def _parse(raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(
                raw,
                object_pairs_hook=_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
        except (ValueError, UnicodeError) as error:
            raise HttpOwnershipError("HTTP_OWNER_LEDGER_MALFORMED") from error
        return validate_state(value)

    def _read_disk(self) -> bytes:
        if not self.path.is_file():
            raise HttpOwnershipError("HTTP_OWNER_LEDGER_MISSING")
        return self.path.read_bytes()

    def _pid_guard(self) -> None:
        if self.pid != self._pid or os.getpid() != self._pid:
            if os.getpid() != self._pid and self._fd is not None:
                # Close only the child's duplicate, never LOCK_UN the parent's OFD.
                os.close(self._fd)
                self._fd = None
            raise HttpOwnershipError("HTTP_OWNER_FORK_OR_PID_CHANGED")

    def assert_live(self, *, allow_fault: bool = False) -> None:
        self._pid_guard()  # Before any possibly inherited mutex acquisition.
        if self.closed or self._fd is None:
            raise HttpOwnershipError("HTTP_OWNER_CLOSED")
        if self.faulted and not allow_fault:
            raise HttpOwnershipError("HTTP_OWNER_PERSISTENCE_UNCERTAIN")
        if canonical(self.domain) != self._domain_bytes:
            raise HttpOwnershipError("HTTP_OWNER_DOMAIN_CHANGED")
        st = os.fstat(self._fd)
        ls = self.lease_path.stat()
        if (st.st_dev, st.st_ino) != self._stamp or (ls.st_dev, ls.st_ino) != self._stamp:
            raise HttpOwnershipError("HTTP_OWNER_LEASE_CHANGED")
        if os.pread(self._fd, len(self._lease_bytes) + 1, 0) != self._lease_bytes:
            raise HttpOwnershipError("HTTP_OWNER_LEASE_CHANGED")

    def bind_budget(self, budget: Any) -> None:
        self.assert_live()
        if self.budget is not None or budget.path.resolve() != self.path:
            raise HttpOwnershipError("HTTP_OWNER_EXACT_BUDGET_REQUIRED")
        if canonical(budget.state["limits"]) != canonical(self.initial_state["limits"]):
            raise HttpOwnershipError("HTTP_OWNER_BUDGET_LIMITS_CHANGED")
        self.budget = budget

    def assert_budget(self, budget: Any, *, disk: bool = True) -> None:
        self.assert_live()
        if (
            budget is not self.budget
            or budget.http_owner is not self
            or budget.path.resolve() != self.path
            or canonical(asdict(budget.limits)) != canonical(self.initial_state["limits"])
        ):
            raise HttpOwnershipError("HTTP_OWNER_EXACT_BUDGET_REQUIRED")
        if disk:
            raw = self._read_disk()
            if sha(raw) != self._ledger_sha or canonical(self._parse(raw)) != canonical(
                budget.state
            ):
                raise HttpOwnershipError("HTTP_OWNER_LEDGER_STALE")

    def register_client(self, client: Any, budget: Any, config: dict[str, Any]) -> None:
        self._pid_guard()
        with self._metadata:
            if self._active_thread == get_ident():
                raise HttpOwnershipError("HTTP_OWNER_REQUEST_REENTRY")
            self._waiting += 1
        try:
            with self.mutex:
                self.assert_budget(budget)
                value = normalized_config(config)
                encoded = canonical(value)
                if encoded not in {canonical(c) for c in self.domain["clients"]}:
                    raise HttpOwnershipError("HTTP_OWNER_CLIENT_NOT_ALLOWED")
                with self._metadata:
                    self._clients[id(client)] = (client, encoded, False)
        finally:
            with self._metadata:
                self._waiting -= 1

    def abort_client(self, client: Any) -> None:
        self.assert_live(allow_fault=True)
        with self._metadata:
            self._clients.pop(id(client), None)

    def assert_client(
        self, client: Any, budget: Any, config: dict[str, Any], base_url: str, *, disk: bool = False
    ) -> None:
        self.assert_budget(budget, disk=disk)
        item = self._clients.get(id(client))
        value = normalized_config(config)
        if item is None or item[0] is not client or item[2]:
            raise HttpOwnershipError("HTTP_OWNER_CLIENT_CLOSED")
        if canonical(value) != item[1] or normalized_url(base_url) != value["base_url"]:
            raise HttpOwnershipError("HTTP_OWNER_CLIENT_CHANGED")

    @contextmanager
    def request(
        self,
        client: Any,
        budget: Any,
        config: dict[str, Any],
        base_url: str,
        path: str,
        actual_url: str,
        model: Any,
    ) -> Iterator[None]:
        self._pid_guard()
        with self._metadata:
            if self._active_thread == get_ident():
                raise HttpOwnershipError("HTTP_OWNER_REQUEST_REENTRY")
            self._waiting += 1
        acquired = False
        entered = False
        try:
            self.mutex.acquire()
            acquired = True
            with self._metadata:
                self._waiting -= 1
                entered = True
                self.assert_client(client, budget, config, base_url, disk=True)
                if (
                    path not in {"chat/completions", "embeddings"}
                    or model != config["model"]
                    or normalized_url(actual_url) != normalized_url(base_url) + "/" + path
                ):
                    raise HttpOwnershipError("HTTP_OWNER_REQUEST_DOMAIN_CHANGED")
                self._active_thread, self._active_client = get_ident(), client
            yield
        finally:
            with self._metadata:
                if not entered:
                    self._waiting -= 1
                if self._active_thread == get_ident():
                    self._active_thread, self._active_client = None, None
            if acquired:
                self.mutex.release()

    def budget_operation(self, budget: Any) -> None:
        self.assert_budget(budget)
        if self._active_thread != get_ident():
            raise HttpOwnershipError("HTTP_OWNER_RESERVATION_OUTSIDE_REQUEST")

    def persist(self, budget: Any) -> None:
        # Caller already owns request mutex then budget lock; no inverse locking.
        self.assert_budget(budget, disk=False)
        if self._active_thread != get_ident():
            raise HttpOwnershipError("HTTP_OWNER_RESERVATION_OUTSIDE_REQUEST")
        if sha(self._read_disk()) != self._ledger_sha:
            raise HttpOwnershipError("HTTP_OWNER_LEDGER_STALE")
        raw = (
            json.dumps(validate_state(budget.state), ensure_ascii=False, indent=2, allow_nan=False)
            + "\n"
        ).encode()
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.path.parent,
                prefix=self.path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self._ledger_sha = sha(raw)
        except BaseException:
            self.faulted = True
            raise  # Keep actual partial/temp bytes; no retry or refund.

    @contextmanager
    def closing_client(self, client: Any) -> Iterator[None]:
        self.assert_live(allow_fault=True)
        with self._metadata:
            item = self._clients.get(id(client))
            if item is None or item[2]:
                raise HttpOwnershipError("HTTP_OWNER_CLIENT_CLOSED")
            if self._active_thread is not None or self._waiting:
                raise HttpOwnershipError("HTTP_OWNER_REQUEST_ACTIVE")
            self._clients[id(client)] = (item[0], item[1], True)
        yield
        with self._metadata:
            self._clients.pop(id(client))

    def close(self) -> None:
        self.assert_live(allow_fault=True)
        with self._metadata:
            if self._clients or self._active_thread is not None or self._waiting:
                raise HttpOwnershipError("HTTP_OWNER_CLIENTS_STILL_OPEN")
            assert self._fd is not None
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
            self.closed = True
