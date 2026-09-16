"""Disposable HTTP wire cut before forwarding or after a real Runtime commit."""

import http.client
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import urlsplit


class FaultProxy:
    def __init__(self, upstream: str) -> None:
        destination = urlsplit(upstream)
        self.faults: dict[str, str] = {}
        self.forwarded: list[str] = []
        self.state_fault: str | None = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version: ClassVar[str] = "HTTP/1.1"

            def log_message(self, _format: str, *args: object) -> None:
                pass

            def dispatch(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                operation = self.headers.get("Idempotency-Key", "")
                fault = (owner.faults.pop(operation, None)
                         if self.path == "/v1/notes/write" else None)
                state_write = self.path == "/v1/working-state/update"
                if state_write:
                    fault, owner.state_fault = owner.state_fault, None
                if fault == "before":
                    self.cut()
                    return
                connection = http.client.HTTPConnection(destination.hostname, destination.port,
                                                        timeout=10)
                try:
                    connection.request(self.command, self.path, body=body,
                                       headers=dict(self.headers))
                    response = connection.getresponse()
                    data = response.read()
                    if self.path == "/v1/notes/write" or state_write:
                        owner.forwarded.append(operation)
                    if fault == "after":
                        assert response.status in {200, 201}
                        if state_write:
                            assert json.loads(data)["status"] == "ACTIVE"
                        else:
                            assert json.loads(data)["commit_status"] == "COMMITTED"
                        self.cut()
                        return
                    self.send_response(response.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                finally:
                    connection.close()

            def cut(self) -> None:
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()

            do_GET = dispatch
            do_POST = dispatch

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self) -> Any:
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
