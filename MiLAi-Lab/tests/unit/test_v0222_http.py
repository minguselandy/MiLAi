"""Wall time is distinct from per-phase timeout; malformed accounting is rejected."""

import signal
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0220_provider_hardened import ProviderStop
from v0222_http import bounded_request, strict_http_json, wall_bound


@pytest.mark.parametrize(
    "raw", ['{"count":1,"count":2}', '{"usage":NaN}', '{"usage":{"total_tokens":1e999}}']
)
def test_ambiguous_or_nonfinite_receipts_rejected(raw):
    with pytest.raises(ValueError):
        strict_http_json(raw)


def test_wall_clock_interrupts_mock_response_even_without_socket_timeout():
    def slow(request):
        time.sleep(1)
        return httpx.Response(200, json={})

    previous = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    with httpx.Client(
        transport=httpx.MockTransport(slow), base_url="http://example.invalid"
    ) as client:
        with pytest.raises(httpx.ReadTimeout, match="TOTAL_WALL_CLOCK"):
            bounded_request(client, "POST", "/mock", timeout=0.02)
    assert time.monotonic() - started < 0.5
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) == previous


def test_existing_timer_not_replaced():
    signal.setitimer(signal.ITIMER_REAL, 10)
    try:
        with pytest.raises(ProviderStop, match="EXISTING_PROCESS_TIMER"):
            with wall_bound(1):
                pytest.fail("must not enter")
        assert signal.getitimer(signal.ITIMER_REAL)[0] > 9
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
