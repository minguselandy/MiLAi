"""Opt-in native Provider transport gate; no new endpoint or retry policy.

Production dispatch still requires an admitted, source-pinned runner. In
particular the embedding upper bound must be established from the existing
tokenizer/deployment contract, not guessed from characters or reported as zero.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from milai_lab.methods.finite_research_budget import BudgetStop, FiniteResearchBudget
from replay_v0213_cost import save

SOLVER_ORIGIN = "http://127.0.0.1:7860"
EMBEDDING_ORIGIN = "http://36.140.33.19:7861"
SOLVER = "Qwen3.6-35B-A3B-FP8"


class FiniteBudgetTransport(httpx.BaseTransport):
    def __init__(
        self,
        budget: FiniteResearchBudget,
        *,
        kind: str,
        inner=None,
        failure_root: Path | None = None,
    ):
        if kind not in {"text", "embedding"}:
            raise ValueError("UNAUTHORIZED_REQUEST_KIND")
        self.budget, self.kind = budget, kind
        self.failure_root = failure_root
        self.inner = inner if inner is not None else httpx.HTTPTransport(retries=0)

    def _classify(self, request: httpx.Request) -> tuple[str, int]:
        origin = SOLVER_ORIGIN if self.kind == "text" else EMBEDDING_ORIGIN
        url = request.url
        if str(url.copy_with(path="", query=None, fragment=None)) != origin:
            raise BudgetStop("UNAUTHORIZED_ENDPOINT")
        if url.query or url.fragment or url.username or url.password:
            raise BudgetStop("UNAUTHORIZED_ENDPOINT_PARAMETERS")
        if self.kind == "text" and request.method == "GET" and url.path == "/v1/models":
            return "model_info", 0
        if request.method != "POST":
            raise BudgetStop("UNAUTHORIZED_HTTP_METHOD")
        body = json.loads(request.content)
        if body.get("model") != (SOLVER if self.kind == "text" else "bge-m3"):
            raise BudgetStop("UNAUTHORIZED_MODEL")
        if self.kind == "text" and url.path == "/tokenize":
            return "tokenize", 0
        admission = request.extensions.get("milai_batch_reservation", {})
        upper = admission.get("upper_tokens")
        if type(upper) is not int or upper <= 0:
            raise BudgetStop("KNOWN_TOKEN_UPPER_BOUND_REQUIRED")
        if self.kind == "embedding":
            if url.path != "/v1/embeddings" or body.get("encoding_format") != "float":
                raise BudgetStop("EMBEDDING_CONTRACT_CHANGED")
            if not isinstance(body.get("input"), list) or not body["input"]:
                raise BudgetStop("EMBEDDING_INPUT_CONTRACT_CHANGED")
            if not all(isinstance(text, str) for text in body["input"]):
                raise BudgetStop("EMBEDDING_INPUT_CONTRACT_CHANGED")
            return "embedding", upper
        if url.path not in {"/v1/chat/completions", "/v1/completions"}:
            raise BudgetStop("UNAUTHORIZED_MODEL_ROUTE")
        role = admission.get("role")
        if role not in {
            "actor",
            "self_judge",
            "extract",
            "adopt",
            "revise",
            "observer",
            "reflector",
        }:
            raise BudgetStop("UNAUTHORIZED_MODEL_ROLE")
        output = 4096 if role == "actor" else 64 if role == "self_judge" else 2048
        if (
            body.get("max_tokens") != output
            or body.get("temperature") != (1 if role == "extract" else 0)
            or body.get("top_p") != 1
            or body.get("seed") != 213
            or body.get("stream") is not False
            or not output <= upper <= 65536
        ):
            raise BudgetStop("M1_PROFILE_CHANGED")
        if url.path == "/v1/chat/completions":
            if (
                body.get("chat_template_kwargs") != {"enable_thinking": False}
                or body.get("add_generation_prompt") is not True
                or body.get("add_special_tokens") is not False
            ):
                raise BudgetStop("M1_TEMPLATE_CHANGED")
        elif body.get("add_special_tokens") is not False:
            raise BudgetStop("M1_TEMPLATE_CHANGED")
        return "generation", upper

    @staticmethod
    def _reported(response: httpx.Response, purpose: str) -> int | None:
        if purpose in {"model_info", "tokenize"}:
            return 0  # These endpoints perform no generation or embedding inference.
        try:
            usage = response.json().get("usage", {})
            total = usage.get("total_tokens")
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens", 0 if purpose == "embedding" else None)
            if (
                type(total) is int
                and type(prompt) is int
                and type(completion) is int
                and min(total, prompt, completion) >= 0
                and total == prompt + completion
            ):
                return total
        except (ValueError, AttributeError):
            pass
        return None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        purpose, upper = self._classify(request)
        key = self.budget.reserve(
            self.kind,
            upper_tokens=upper,
            purpose=purpose,
            payload_sha256=hashlib.sha256(request.content).hexdigest(),
        )
        request.extensions["milai_batch_request_id"] = key
        try:
            remaining = self.budget.remaining_seconds()
            request.extensions["timeout"] = {
                phase: min(cap, remaining) if cap is not None else remaining
                for phase, cap in request.extensions.get(
                    "timeout",
                    {
                        "connect": remaining,
                        "read": remaining,
                        "write": remaining,
                        "pool": remaining,
                    },
                ).items()
            }
            response = self.inner.handle_request(request)
            response.read()
        except BaseException:
            # A failed/uncertain generation is NOT free. Auxiliary inference cost is known zero.
            self.budget.settle(key, reported_tokens=0 if upper == 0 else None, failed=True)
            raise
        reported = self._reported(response, purpose)
        if self.failure_root is not None and (reported is None or reported > upper):
            # Provider parsing will not run after this transport raises. Preserve
            # the failed response at its normal external artifact root first.
            save(
                self.failure_root / f"batch-{key:06d}-http.json",
                {
                    "batch_request_id": key,
                    "status_code": response.status_code,
                    "body": response.text,
                },
            )
        try:
            self.budget.settle(
                key, reported_tokens=reported, failed=not response.is_success or reported is None
            )
        except BaseException:
            response.close()
            raise
        if reported is None:
            response.close()
            raise BudgetStop("USAGE_UNKNOWN_UPPER_BOUND_RETAINED")
        return response

    def close(self) -> None:
        self.inner.close()
