"""Expose one operator-selected local MCP via Unix socket without altering HTTP bytes."""

from __future__ import annotations

import socket
import socketserver
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from v02_native_bridge import relay, socket_path


@contextmanager
def connection(root: Path, url: str):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path != "/mcp":
        raise ValueError("ONLY_RUN_OWNED_LOOPBACK_MCP")
    connections = set()
    lock = threading.Lock()
    closing = threading.Event()

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.create_connection((parsed.hostname, parsed.port), timeout=20) as upstream:
                upstream.settimeout(None)
                pair = (self.request, upstream)
                with lock:
                    connections.add(pair)
                try:
                    relay(*pair)
                except OSError:
                    if not closing.is_set():
                        raise
                finally:
                    with lock:
                        connections.discard(pair)

    with socket_path(root / "sockets", "mcp.sock") as address, (
        socketserver.ThreadingUnixStreamServer(address, Handler)
    ) as server:
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield
        finally:
            closing.set()
            server.shutdown()
            with lock:
                for pair in connections:
                    for sock in pair:
                        try:
                            sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass  # Peer may already have closed after native client exit.
            thread.join(timeout=2)
