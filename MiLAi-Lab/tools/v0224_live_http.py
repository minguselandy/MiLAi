"""Fixed endpoint/route/count transport for the prospective B/C batch.

Every call still follows the original Batch admission and owns original raw
receipts. This wrapper does not retry or manage a model service.
"""

import httpx

from v0220_provider_hardened import ProviderStop


class BoundedLiveHTTP(httpx.BaseTransport):
    def __init__(self, *, identity_get: int, tokenize_post: int, generation_post: int):
        self.remaining = {
            "identity_get": identity_get,
            "tokenize_post": tokenize_post,
            "generation_post": generation_post,
        }
        if any(type(value) is not int or value < 0 for value in self.remaining.values()):
            raise ProviderStop("FINITE_ROUTE_COUNTS_REQUIRED")
        self.delegate = httpx.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request):
        if (
            request.url.scheme != "http"
            or request.url.host != "127.0.0.1"
            or request.url.port != 7860
            or request.url.query
        ):
            raise ProviderStop("ONLY_FROZEN_VLLM_ENDPOINT_ALLOWED")
        routes = {
            ("GET", "/v1/models"): "identity_get",
            ("GET", "/version"): "identity_get",
            ("POST", "/tokenize"): "tokenize_post",
            ("POST", "/v1/chat/completions"): "generation_post",
        }
        key = routes.get((request.method, request.url.path))
        if key is None or self.remaining[key] <= 0:
            raise ProviderStop("FIXED_HTTP_ROUTE_OR_COUNT_EXCEEDED")
        # Failed calls consume their attempt. There is no automatic retry.
        self.remaining[key] -= 1
        return self.delegate.handle_request(request)

    def close(self):
        self.delegate.close()
