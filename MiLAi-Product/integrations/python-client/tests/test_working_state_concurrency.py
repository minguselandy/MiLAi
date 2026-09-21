from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from milai_client import AsyncMilaiClient, HttpxAsyncTransport, MilaiClient, UnavailableError
from support.contracts import TOKEN, _capabilities


@pytest.mark.parametrize("failure", ["disconnect", "unavailable"])
def test_state_write_never_automatically_retries_even_with_a_stable_operation_id(failure) -> None:
    attempts = []

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=_capabilities())
        attempts.append(request.headers["Idempotency-Key"])
        if failure == "disconnect":
            raise httpx.RemoteProtocolError("connection closed before response")
        return httpx.Response(503, json={"error": {
            "code": "UNAVAILABLE", "message": "unavailable", "retryable": True,
        }})

    async def run() -> None:
        async with AsyncMilaiClient(token=TOKEN, max_retries=3, transport=HttpxAsyncTransport(
            "http://127.0.0.1", 2, transport=httpx.MockTransport(handle),
        )) as client:
            with pytest.raises(UnavailableError):
                await client.update_working_state({"payload": {}}, operation_id="original")

    asyncio.run(run())
    assert attempts == ["original"]


def test_shared_sync_client_serializes_blocked_state_reads() -> None:
    entered, release, second_started, second_entered = (Event() for _ in range(4))

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=_capabilities())
        binding = json.loads(request.content)
        if binding["scope_ref"] == "first":
            entered.set()
            assert await asyncio.to_thread(release.wait, 2)
        else:
            second_entered.set()
        return httpx.Response(200, json={"payload": binding})

    client = MilaiClient(
        token=TOKEN, max_retries=0,
        transport=HttpxAsyncTransport("http://127.0.0.1", 2, transport=httpx.MockTransport(handle)),
    )

    def second() -> dict:
        second_started.set()
        return client.get_working_state({"scope_ref": "second"})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.get_working_state, {"scope_ref": "first"})
            try:
                assert entered.wait(1)
                next_read = pool.submit(second)
                assert second_started.wait(1)
                # A controlled outstanding request holds the shared facade's loop lock.
                assert not second_entered.wait(0.1)
            finally:
                release.set()
            assert first.result(timeout=2)["payload"]["scope_ref"] == "first"
            assert next_read.result(timeout=2)["payload"]["scope_ref"] == "second"
    finally:
        client.close()


def test_async_reads_overlap_and_cancellation_preserves_other_binding() -> None:
    async def run() -> None:
        both_entered, release = asyncio.Event(), asyncio.Event()
        requests: list[dict] = []
        active = 0

        async def handle(request: httpx.Request) -> httpx.Response:
            nonlocal active
            if request.url.path == "/v1/capabilities":
                return httpx.Response(200, json=_capabilities())
            assert request.headers["Authorization"] == "Bearer " + TOKEN
            binding = json.loads(request.content)
            requests.append(binding)
            active += 1
            if active == 2:
                both_entered.set()
            try:
                await release.wait()
                return httpx.Response(200, json={"payload": binding})
            finally:
                active -= 1

        client = AsyncMilaiClient(
            token=TOKEN, max_retries=0,
            transport=HttpxAsyncTransport(
                "http://127.0.0.1", 2, transport=httpx.MockTransport(handle)
            ),
        )
        await client.capabilities()
        bindings = [
            {"principal_binding_digest": name * 64, "project_id": name, "scope_ref": "same"}
            for name in ("a", "b")
        ]
        tasks = [asyncio.create_task(client.get_working_state(binding)) for binding in bindings]
        try:
            await asyncio.wait_for(both_entered.wait(), 1)
            assert active == 2 and requests == bindings
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            assert active == 1 and not tasks[1].done()
            release.set()
            assert (await tasks[1])["payload"] == bindings[1]
            assert active == 0
        finally:
            release.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await client.close()

    asyncio.run(run())
