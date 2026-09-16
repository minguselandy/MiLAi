from __future__ import annotations

import asyncio
import hashlib
import json
import logging

import httpx
import pytest

from milai_client import HttpxAsyncTransport
from milai_client.client import _HttpStatusError


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("outcome", ["success", "status_error", "timeout", "cancelled"])
def test_optional_transport_timing_preserves_outcome_and_never_logs_payload(
    caplog, enabled, outcome,
):
    attempts = []

    async def handler(request):
        attempts.append(request)
        assert request.content == b'PRIVATE_REQUEST_BODY'
        assert request.headers['Authorization'] == 'Bearer PRIVATE_TOKEN'
        trace = request.extensions.get('trace')
        assert bool(trace) is enabled
        if trace:
            await trace('http11.send_request_body.started', {'headers': 'PRIVATE_HEADERS'})
            await trace('http11.send_request_body.complete', {'return_value': 'PRIVATE_INFO'})
            await trace('unrecognized.PRIVATE_EVENT.started', {})
        if outcome == 'timeout':
            raise httpx.ReadTimeout('PRIVATE_EXCEPTION')
        if outcome == 'cancelled':
            raise asyncio.CancelledError('PRIVATE_CANCEL')
        return httpx.Response(503 if outcome == 'status_error' else 200,
                              headers={'X-Request-ID': 'request-fingerprint-source'},
                              json={'value': 'PRIVATE_RESPONSE_BODY'})

    async def run():
        transport = HttpxAsyncTransport(
            'http://127.0.0.1', 2, transport=httpx.MockTransport(handler), timing_enabled=enabled)
        try:
            if outcome == 'success':
                response = await transport.send('POST', '/private-path', b'PRIVATE_REQUEST_BODY',
                                                {'Authorization': 'Bearer PRIVATE_TOKEN'})
                assert response.body == {'value': 'PRIVATE_RESPONSE_BODY'}
            else:
                exception = {'timeout': httpx.ReadTimeout, 'cancelled': asyncio.CancelledError,
                             'status_error': _HttpStatusError}[outcome]
                with pytest.raises(exception):
                    await transport.send('POST', '/private-path', b'PRIVATE_REQUEST_BODY',
                                         {'Authorization': 'Bearer PRIVATE_TOKEN'})
        finally:
            await transport.close()

    caplog.set_level(logging.INFO)
    asyncio.run(run())
    logs = [r.getMessage() for r in caplog.records
            if r.getMessage().startswith('MILAI_HTTP_TRANSPORT_TIMING ')]
    assert len(attempts) == 1 and len(logs) == int(enabled)
    if enabled:
        assert 'PRIVATE_' not in logs[0] and 'private-path' not in logs[0]
        assert 'request-fingerprint-source' not in logs[0]
        value = json.loads(logs[0].split(' ', 1)[1])
        assert len(value['trace_events']) == 2
        assert value['status_code'] == {'success': 200, 'status_error': 503}.get(outcome)
        assert value['runtime_request_id_fingerprint'] == (
            hashlib.sha256(b'request-fingerprint-source').hexdigest()[:16]
            if outcome in {'success', 'status_error'} else None)
        assert value['started_monotonic_s'] <= value['trace_events'][0]['monotonic_s']
        assert value['trace_events'][-1]['monotonic_s'] <= value['finished_monotonic_s']


def test_trace_bound_does_not_drop_response_or_add_requests(caplog):
    async def handler(request):
        for _ in range(40):
            await request.extensions['trace']('http11.receive_response_body.started', {})
        return httpx.Response(200, json={'full': 'preserved'})

    async def run():
        transport = HttpxAsyncTransport('http://127.0.0.1', 2,
                                       transport=httpx.MockTransport(handler), timing_enabled=True)
        try:
            assert (await transport.send('GET', '/', None, {})).body == {'full': 'preserved'}
        finally:
            await transport.close()

    caplog.set_level(logging.INFO)
    asyncio.run(run())
    logs = [r.getMessage() for r in caplog.records
            if r.getMessage().startswith('MILAI_HTTP_TRANSPORT_TIMING ')]
    assert len(logs) == 1
    value = json.loads(logs[0].split(' ', 1)[1])
    assert len(value['trace_events']) == 32 and value['dropped_events'] == 8
