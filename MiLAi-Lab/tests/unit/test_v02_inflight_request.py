from __future__ import annotations

import copy
import importlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
faults = importlib.import_module("v02_inflight_request")


@pytest.mark.parametrize("upstream_reply", [True, False])
@pytest.mark.parametrize("phase", ["AFTER_FORWARD", "AFTER_UPSTREAM_RESPONSE"])
def test_single_forward_preserves_body_and_client_never_receives_oracle(upstream_reply, phase):
    payload = {"first": "首\r\n\t", "nested": [None, False, {}], "last": "尾"}
    received = []
    interrupted = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(
                int(self.headers["Content-Length"]))), self.headers["Idempotency-Key"]))
            if phase == "AFTER_FORWARD":
                assert interrupted.wait(3)
            if upstream_reply:
                body = b'{"version":3,"private":"oracle-only"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            self.close_connection = True

    def interrupt():
        interrupted.set()
        return {"terminal_confirmed": True}

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.handle_request, daemon=True)
        worker.start()
        result = faults.interrupt_after_forward(
            f"http://127.0.0.1:{server.server_port}", "test-secret-token", payload,
            "same-operation", interrupt, timeout=3, phase=phase)
        worker.join(5)
        assert not worker.is_alive()
    if phase == "AFTER_UPSTREAM_RESPONSE" and not upstream_reply:
        assert "fault" not in result and result["upstream_status"] is None
        with pytest.raises(KeyError):
            faults.verify_unknown_boundary(result, payload)
        return
    faults.verify_unknown_boundary(result, payload)
    assert received == [("/v1/working-state/update", payload, "same-operation")]
    assert result["upstream_status"] == (200 if upstream_reply else None)
    assert "oracle-only" not in json.dumps(result) and "test-secret-token" not in json.dumps(result)
    for key, value in [("physical_forwards", 2), ("relay_terminal", False),
                       ("client_status", 200), ("forwarded_body_sha256", "wrong"),
                       ("fault", {"terminal_confirmed": False})]:
        bad = copy.deepcopy(result)
        bad[key] = value
        with pytest.raises(AssertionError):
            faults.verify_unknown_boundary(bad, payload)


def test_reject_nonlocal_target_before_sending():
    with pytest.raises(ValueError, match="LOOPBACK"):
        faults.interrupt_after_forward("https://example.com", "secret", {}, "op", None)
