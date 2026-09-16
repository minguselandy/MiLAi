"""Explicit process-local socket denial for a fresh CPU-only replay process.

Importing has no effect. The dedicated bootstrap must enable this before loading
the replay stack; it is not a security sandbox against arbitrary native code or
unapproved subprocesses. Approved replay children must install their own guard.
No device, service, credential or network inspection is performed.
"""

from __future__ import annotations

import sys

CPU_MODE = "CPU_MOCK_ONLY"
_installed = False


def enable_cpu_network_guard() -> None:
    """Irreversibly deny Python socket audit events in this process only."""
    global _installed
    if _installed:
        return

    class SocketDenied(RuntimeError):
        """Invocation-private type confirms our hook, not an unrelated hook."""

    def deny_socket(event, args):
        if event.startswith("socket."):
            raise SocketDenied("CPU_REPLAY_SOCKET_FORBIDDEN")

    sys.addaudithook(deny_socket)
    # CPython may silently decline registration when an existing audit hook
    # rejects sys.addaudithook. Probe a synthetic audit event, never a socket.
    try:
        sys.audit("socket.v0222_cpu_guard_probe")
    except SocketDenied:
        _installed = True
    else:
        raise RuntimeError("CPU_NETWORK_GUARD_REGISTRATION_NOT_CONFIRMED")


def require_cpu_network_guard() -> None:
    if not _installed:
        raise RuntimeError("FRESH_CPU_PROCESS_NETWORK_GUARD_REQUIRED")
