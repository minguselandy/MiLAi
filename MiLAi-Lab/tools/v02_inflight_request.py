"""One loopback HTTP request: interrupt after forwarding, withhold its response.

The relay provides a reproducible client-unknown boundary. Sending all bytes does not
prove server admission or commit. Upstream observations are a separate test oracle.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

import httpx


def interrupt_after_forward(base_url, token, payload, operation_id, interrupt, timeout=10,
                            phase="AFTER_FORWARD"):
    target = urlsplit(base_url)
    if target.scheme != "http" or target.hostname != "127.0.0.1" or target.path not in {"", "/"}:
        raise ValueError("FAULT_TARGET_MUST_BE_LOOPBACK_RUNTIME")
    if phase not in {"AFTER_FORWARD", "AFTER_UPSTREAM_RESPONSE"}:
        raise ValueError("UNKNOWN_FAULT_PHASE")
    body = json.dumps(payload, ensure_ascii=False).encode()
    report = {"client_operation_outcome": "UNKNOWN", "physical_forwards": 0, "phase": phase,
              "forwarded_body_sha256": None, "upstream_status": None,
              "server_admission": "UNKNOWN", "commit_at_interrupt": "UNKNOWN"}

    def apply_fault():
        report["fault"] = interrupt()
        report["fault_complete_monotonic"] = time.monotonic()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log authorization, headers, body or URLs.

        def do_POST(self):
            try:
                incoming = self.rfile.read(int(self.headers["Content-Length"]))
                assert incoming == body and self.path == "/v1/working-state/update"

                def trace(event, info):
                    if event == "http11.send_request_body.complete":
                        report["physical_forwards"] += 1
                        report["forwarded_body_sha256"] = hashlib.sha256(incoming).hexdigest()
                        report["forward_complete_monotonic"] = time.monotonic()
                        if phase == "AFTER_FORWARD":
                            apply_fault()

                with httpx.Client(timeout=timeout, trust_env=False) as upstream:
                    response = upstream.post(
                        base_url + "/v1/working-state/update", content=incoming,
                        headers={"Content-Type": "application/json",
                                 "Authorization": "Bearer " + token,
                                 "Idempotency-Key": operation_id},
                        extensions={"trace": trace})
                    # Oracle only; never returned to the client or used as its receipt.
                    report["upstream_status"] = response.status_code
                    report["upstream_response_monotonic"] = time.monotonic()
                    if phase == "AFTER_UPSTREAM_RESPONSE":
                        apply_fault()
            except Exception as exc:
                report["upstream_error_type"] = type(exc).__name__
            finally:
                self.close_connection = True

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = timeout
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        try:
            with httpx.Client(timeout=timeout + 5, trust_env=False) as client:
                response = client.post(
                    f"http://127.0.0.1:{server.server_port}/v1/working-state/update", content=body)
                report["client_status"] = response.status_code
        except httpx.TransportError as exc:
            report["client_transport_error"] = type(exc).__name__
        finally:
            thread.join(timeout + 2)
            report["relay_terminal"] = not thread.is_alive()
    return report


def verify_unknown_boundary(report, payload):
    assert report["physical_forwards"] == 1
    assert report["forwarded_body_sha256"] == hashlib.sha256(
        json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
    assert report["fault"]["terminal_confirmed"]
    assert report["forward_complete_monotonic"] <= report["fault_complete_monotonic"]
    assert report["client_transport_error"] and "client_status" not in report
    assert report["relay_terminal"] and report["client_operation_outcome"] == "UNKNOWN"
    if report["phase"] == "AFTER_UPSTREAM_RESPONSE":
        assert report["upstream_status"] == 200
        assert report["upstream_response_monotonic"] <= report["fault_complete_monotonic"]
