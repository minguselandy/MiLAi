from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx2 as httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from milai_mcp.aigcit_auth import AigcitTokenVerifier, JwksCache
from milai_mcp.auth_policy import (
    READ_SCOPES,
    AdmissionDenied,
    AdmissionPolicy,
    AuthDependencyUnavailable,
    principal_for,
)

ISSUER = "https://auth.example.test"
RESOURCE = "https://memory.example.test:7960/mcp"


class Fixture:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(self.private.public_key()))
        self.public.update(kid="one", alg="ES256", use="sig")
        self.keys = [self.public]
        self.clock = 1000.0
        self.requests: list[str] = []
        self.fail = False
        self.doc: dict[str, Any] = {
            "version": 1,
            "issuer": ISSUER,
            "project_id": "project-one",
            "owners": [
                {
                    "sub": "owner",
                    "principal_id": principal_for(ISSUER, "owner", "project-one"),
                    "enabled": True,
                    "allowed_scopes": sorted(READ_SCOPES),
                }
            ],
        }
        self.write()

    def write(self) -> None:
        self.path.write_text(json.dumps(self.doc))
        self.path.chmod(0o640)

    def policy(self) -> AdmissionPolicy:
        return AdmissionPolicy(
            self.path,
            issuer=ISSUER,
            project_id="project-one",
            trusted_owner_uid=os.getuid(),
            mode=self.doc.get("mode", "explicit_owners"),
        )

    def token(self, *, headers: dict[str, Any] | None = None, **changes: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": RESOURCE,
            "sub": "owner",
            "client_id": "client-one",
            "iat": now,
            "exp": now + 900,
            "scope": " ".join(sorted(READ_SCOPES)),
            **changes,
        }
        return jwt.encode(
            claims,
            self.private,
            algorithm="ES256",
            headers={"typ": "at+jwt", "kid": "one", **(headers or {})},
        )

    async def response(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        await asyncio.sleep(0)
        if self.fail:
            raise httpx.ConnectError("fixture offline")
        if request.url.path.endswith("oauth-authorization-server"):
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": ISSUER + "/jwks"})
        return httpx.Response(200, json={"keys": self.keys})

    def verifier(self, client: httpx.AsyncClient) -> AigcitTokenVerifier:
        return AigcitTokenVerifier(
            cache=JwksCache(ISSUER, client=client, monotonic=lambda: self.clock),
            resource_url=RESOURCE,
            scope_digest="a" * 64,
            policy=self.policy(),
        )


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path / "bindings.json")


def test_verified_scopes_and_principal_ignore_token_authority(fixture: Fixture) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.response)) as client:
            verifier = fixture.verifier(client)
            first = await verifier.verify_token(
                fixture.token(
                    scope="milai.state.read milai.state.write milai.operations.admin",
                    tenant="forged",
                    project="forged",
                    role="operator",
                    milai_scope_sha256="forged",
                    milai_external_sub="forged",
                    headers={"jku": "https://attacker.test/jwks", "x5u": "http://attacker.test"},
                )
            )
            second = await verifier.verify_token(fixture.token(client_id="client-two"))
            assert first and second
            assert first.subject == second.subject == principal_for(ISSUER, "owner", "project-one")
            assert first.scopes == ["milai.state.read"]
            assert first.client_id != second.client_id
            assert first.claims and first.claims["milai_scope_sha256"] == "a" * 64
            assert first.claims["milai_granted_scopes"] == [
                "milai.operations.admin",
                "milai.state.read",
                "milai.state.write",
            ]
            assert len(fixture.requests) == 2
            assert all(url.startswith(ISSUER + "/") for url in fixture.requests)

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.test"},
        {"aud": RESOURCE + "/"},
        {"aud": None},
        {"aud": [RESOURCE]},
        {"aud": RESOURCE.replace(":7960", "")},
        {"aud": "https://zhishi.aigcit.com/mcp"},
        {"exp": 1},
        {"exp": "9999999999"},
        {"exp": True},
        {"exp": None},
        {"iat": "1"},
        {"iat": None},
        {"iat": 9999999999},
        {"nbf": 9999999999},
        {"nbf": "1"},
        {"sub": ""},
        {"sub": 1},
        {"sub": None},
        {"client_id": None},
        {"client_id": []},
        {"client_id": "  "},
        {"scope": ["milai.state.read"]},
        {"scope": "milai.state.read\tmilai.state.write"},
    ],
)
def test_invalid_claims(fixture: Fixture, changes: dict[str, Any]) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.response)) as client:
            assert await fixture.verifier(client).verify_token(fixture.token(**changes)) is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "headers",
    [
        {"typ": "JWT"},
        {"kid": ""},
        {"kid": "x" * 257},
        {"crit": ["custom"]},
    ],
)
def test_header_rejection_without_network(fixture: Fixture, headers: dict[str, Any]) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.response)) as client:
            assert (
                await fixture.verifier(client).verify_token(fixture.token(headers=headers)) is None
            )
            assert not fixture.requests

    asyncio.run(run())


def test_bad_signatures_algorithms_and_no_scope(fixture: Fixture) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.response)) as client:
            verifier = fixture.verifier(client)
            valid = fixture.token()
            payload = jwt.decode(valid, options={"verify_signature": False})
            for alg, key in [("none", None), ("HS256", "synthetic-test-signing-key-long-enough")]:
                bad = jwt.encode(
                    payload, key, algorithm=alg, headers={"typ": "at+jwt", "kid": "one"}
                )
                assert await verifier.verify_token(bad) is None
            other = ec.generate_private_key(ec.SECP256R1())
            bad = jwt.encode(
                payload, other, algorithm="ES256", headers={"typ": "at+jwt", "kid": "one"}
            )
            assert await verifier.verify_token(bad) is None
            assert await verifier.verify_token("not-a-jwt") is None
            assert await verifier.verify_token("x" * 16385) is None
            payload.pop("scope")
            token = jwt.encode(
                payload, fixture.private, algorithm="ES256", headers={"typ": "at+jwt", "kid": "one"}
            )
            result = await verifier.verify_token(token)
            assert result and result.scopes == []

    asyncio.run(run())


def test_admission_reloaded_disable_narrow_corrupt_and_missing(fixture: Fixture) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.response)) as client:
            verifier = fixture.verifier(client)
            token = fixture.token()
            assert await verifier.verify_token(token)
            fixture.doc["owners"][0]["allowed_scopes"] = ["milai.state.read"]
            fixture.doc["version"] = 2
            fixture.write()
            result = await verifier.verify_token(token)
            assert result and result.scopes == ["milai.state.read"]
            assert result.claims and result.claims["milai_policy_version"] == 2
            with pytest.raises(AdmissionDenied):
                await verifier.verify_token(fixture.token(sub="unadmitted"))
            fixture.doc["owners"][0]["enabled"] = False
            fixture.write()
            with pytest.raises(AdmissionDenied):
                await verifier.verify_token(token)
            fixture.path.write_text("broken")
            with pytest.raises(AuthDependencyUnavailable):
                await verifier.verify_token(token)
            fixture.path.unlink()
            with pytest.raises(AuthDependencyUnavailable):
                await verifier.verify_token(token)
            assert len(fixture.requests) == 2

    asyncio.run(run())


def test_jwks_coalescing_rotation_deletion_failure_expiry(fixture: Fixture) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.response)) as client:
            verifier = fixture.verifier(client)
            token = fixture.token()
            results = await asyncio.gather(*(verifier.verify_token(token) for _ in range(8)))
            assert all(results) and len(fixture.requests) == 2
            fixture.clock += 31
            fixture.keys = [{**fixture.public, "kid": "two"}]
            assert await verifier.verify_token(fixture.token(headers={"kid": "two"}))
            assert await verifier.verify_token(token) is None
            count = len(fixture.requests)
            results = await asyncio.gather(
                *(verifier.verify_token(fixture.token(headers={"kid": str(i)})) for i in range(100))
            )
            assert all(r is None for r in results) and len(fixture.requests) == count
            fixture.clock += 31
            fixture.fail = True
            with pytest.raises(AuthDependencyUnavailable):
                await verifier.verify_token(fixture.token(headers={"kid": "missing"}))
            assert await verifier.verify_token(fixture.token(headers={"kid": "two"}))
            fixture.clock += 601
            with pytest.raises(AuthDependencyUnavailable):
                await verifier.verify_token(fixture.token(headers={"kid": "two"}))
            count = len(fixture.requests)
            with pytest.raises(AuthDependencyUnavailable):
                await verifier.verify_token(token)
            assert len(fixture.requests) == count

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["redirect", "oversized", "private", "duplicate", "off-origin"])
def test_jwks_external_io_fails_closed(fixture: Fixture, kind: str) -> None:
    async def response(request: httpx.Request) -> httpx.Response:
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "https://attacker.test"})
        if kind == "oversized":
            return httpx.Response(200, content=b" " * 262145)
        if request.url.path.endswith("oauth-authorization-server"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "jwks_uri": "https://attacker.test/keys"
                    if kind == "off-origin"
                    else ISSUER + "/jwks",
                },
            )
        keys = (
            [{**fixture.public, "d": "private"}]
            if kind == "private"
            else [fixture.public, fixture.public]
        )
        return httpx.Response(200, json={"keys": keys})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            with pytest.raises(AuthDependencyUnavailable):
                await fixture.verifier(client).verify_token(fixture.token())

    asyncio.run(run())


def test_refresh_cancellation_does_not_block_warm_key(fixture: Fixture) -> None:
    async def run() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        slow = False

        async def response(request: httpx.Request) -> httpx.Response:
            if slow:
                entered.set()
                await release.wait()
            return await fixture.response(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            verifier = fixture.verifier(client)
            token = fixture.token()
            assert await verifier.verify_token(token)
            fixture.clock += 31
            slow = True
            refresh = asyncio.create_task(
                verifier.verify_token(fixture.token(headers={"kid": "new"}))
            )
            await entered.wait()
            # This must finish even though the refresh deliberately never returns.
            assert await asyncio.wait_for(verifier.verify_token(token), timeout=0.5)
            refresh.cancel()
            with pytest.raises(asyncio.CancelledError):
                await refresh
            release.set()
            slow = False
            fixture.clock += 31
            assert await verifier.verify_token(fixture.token(headers={"kid": "new"})) is None
            assert await verifier.verify_token(token)

    asyncio.run(run())


def test_total_refresh_deadline_and_shared_failure_cooldown(fixture: Fixture) -> None:
    async def response(request: httpx.Request) -> httpx.Response:
        fixture.requests.append(str(request.url))
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            verifier = fixture.verifier(client)
            start = time.monotonic()
            with pytest.raises(AuthDependencyUnavailable):
                await verifier.verify_token(fixture.token())
            assert 2.5 <= time.monotonic() - start < 5
            with pytest.raises(AuthDependencyUnavailable):
                await verifier.verify_token(fixture.token())
            assert len(fixture.requests) == 1

    asyncio.run(run())


@pytest.mark.skipif(os.environ.get("MILAI_AUTH_TIMING") != "1", reason="opt-in auth calibration")
def test_warm_auth_calibration(fixture: Fixture) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.response)) as client:
            verifier = fixture.verifier(client)
            token = fixture.token()
            assert await verifier.verify_token(token)
            fixture.requests.clear()

            async def measured() -> float:
                start = time.perf_counter()
                assert await verifier.verify_token(token)
                return (time.perf_counter() - start) * 1000

            single = [await measured() for _ in range(100)]
            concurrent = []
            for _ in range(20):
                concurrent.extend(await asyncio.gather(*(measured() for _ in range(8))))

            def summary(values: list[float]) -> dict[str, float]:
                values.sort()
                return {
                    name: values[min(int(len(values) * p), len(values) - 1)]
                    for name, p in [("p50_ms", 0.5), ("p95_ms", 0.95), ("p99_ms", 0.99)]
                }

            assert not fixture.requests
            print(
                json.dumps(
                    {
                        "kind": "auth_local_calibration",
                        "single": summary(single),
                        "concurrent_8": summary(concurrent),
                        "warm_network_requests": 0,
                        "requests": len(single) + len(concurrent),
                        "timeouts": 0,
                        "signed_fixture": True,
                        "public_user_login": False,
                    }
                )
            )

    asyncio.run(run())


def test_real_tls_rejects_untrusted_certificate(tmp_path: Path) -> None:
    import ssl
    import threading
    from datetime import UTC, datetime, timedelta
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=5))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / "test-cert.pem", tmp_path / "test-key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.touch(mode=0o600)
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    observed: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            observed.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def run() -> None:
        cache = JwksCache(f"https://localhost:{server.server_port}")
        try:
            with pytest.raises(AuthDependencyUnavailable):
                await cache.key("one")
        finally:
            await cache.aclose()

    try:
        asyncio.run(run())
        assert observed == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize(
    "kind", ["project", "issuer", "principal", "duplicate", "two-owners", "writable", "symlink"]
)
def test_policy_rejects_invalid_bindings(fixture: Fixture, kind: str) -> None:
    if kind == "project":
        fixture.doc["project_id"] = "other-project"
    elif kind == "issuer":
        fixture.doc["issuer"] = "https://other.test"
    elif kind == "principal":
        fixture.doc["owners"][0]["principal_id"] = "existing-owner"
    elif kind == "duplicate":
        fixture.doc["owners"] *= 2
    elif kind == "two-owners":
        fixture.doc["owners"].append(
            {
                **fixture.doc["owners"][0],
                "sub": "two",
                "principal_id": principal_for(ISSUER, "two", "project-one"),
            }
        )
    fixture.write()
    if kind == "writable":
        fixture.path.chmod(0o666)
    if kind == "symlink":
        target = fixture.path.with_suffix(".real")
        fixture.path.rename(target)
        fixture.path.symlink_to(target)
    with pytest.raises(AuthDependencyUnavailable):
        fixture.policy().load()
