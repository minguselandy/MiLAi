"""Expose only mounted Unix sockets as loopback HTTP endpoints in a networkless container."""

from __future__ import annotations

import argparse
import os
import selectors
import socket
import socketserver
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def socket_path(directory: Path, name: str):
    """Linux fd-relative bind avoids AF_UNIX's pathname limit for deep artifact roots."""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        yield f"/proc/self/fd/{descriptor}/{name}"
    finally:
        os.close(descriptor)


def relay(left: socket.socket, right: socket.socket) -> None:
    with selectors.DefaultSelector() as ready:
        ready.register(left, selectors.EVENT_READ, right)
        ready.register(right, selectors.EVENT_READ, left)
        while ready.get_map():
            for key, _ in ready.select():
                data = key.fileobj.recv(65536)
                if not data:
                    ready.unregister(key.fileobj)
                    key.data.shutdown(socket.SHUT_WR)
                else:
                    key.data.sendall(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-socket", required=True)
    parser.add_argument("--mcp-socket")
    parser.add_argument("--mcp-port", type=int, default=18081)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    servers = []
    for port, path in ((18080, args.provider_socket), (args.mcp_port, args.mcp_socket)):
        if path is None:
            continue

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                with socket.socket(socket.AF_UNIX) as upstream:
                    upstream.connect(self.server.upstream_path)
                    relay(self.request, upstream)

        server = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
        server.daemon_threads = True
        server.upstream_path = path
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
    try:
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        # Exact operator-selected Codex command; no model-generated command expansion here.
        return subprocess.run(command, check=False).returncode  # noqa: S603
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
