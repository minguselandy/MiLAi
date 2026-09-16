"""DG-23 exact Reader identity, seed, tokenizer, and reuse boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from evals.dg14.benchmark import DEFAULT_TOKENIZER
from evals.dg14.provider import (
    MatchedVllmProvider,
    ProviderResult,
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.dg23.reader_token_accounting import FrozenReaderTokenCounter

DG23_SEED_NAMESPACE = "milai-dg23-matched-v1"
FROZEN_READER_CONTRACT_SHA256 = (
    "25e40b1a978251ddd08df317e16d85f111fdb00a725b928a300979e6f071cd72"
)


class DG23ReaderBoundaryError(RuntimeError):
    """A typed fail-closed Reader boundary failure."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.metadata = dict(metadata or {})


@dataclass(frozen=True, slots=True)
class ReaderInputIdentity:
    reader_context_digest: str
    reader_contract_digest: str
    sampling_seed: int
    generation_settings_digest: str

    @property
    def identity_digest(self) -> str:
        return _digest(
            {
                "reader_context_digest": self.reader_context_digest,
                "reader_contract_digest": self.reader_contract_digest,
                "sampling_seed": self.sampling_seed,
                "generation_settings_digest": self.generation_settings_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class ReaderAccountingReceipt:
    estimated_tokens: int
    exact_reader_tokens: int
    reader_tokenizer_path_or_id: str
    reader_tokenizer_sha256: str
    budget_ceiling: int
    accounting_delta: int
    reader_chat_template_path_or_id: str
    reader_chat_template_sha256: str
    reader_accounting_identity: str


@dataclass(frozen=True, slots=True)
class ReaderBoundaryResult:
    identity: ReaderInputIdentity
    logical_request_id: str
    provider_result: ProviderResult
    accounting: ReaderAccountingReceipt
    disposition: Literal[
        "PROVIDER_CALL",
        "RESTORED_PROVIDER_RESULT",
        "EXACT_IDENTITY_REUSE",
    ]


class ExactReaderIdentityRegistry:
    """In-memory execution-scoped checkpoint; it is not a semantic cache."""

    def __init__(self) -> None:
        self._records: dict[str, ReaderBoundaryResult] = {}
        self._unclaimed_restored: set[str] = set()
        self.provider_calls = 0
        self.fresh_provider_calls = 0
        self.restored_provider_calls = 0
        self.exact_identity_reuses = 0

    def get(self, identity: ReaderInputIdentity) -> ReaderBoundaryResult | None:
        return self._records.get(identity.identity_digest)

    def seal(self, result: ReaderBoundaryResult) -> None:
        digest = result.identity.identity_digest
        if digest in self._records:
            raise DG23ReaderBoundaryError(
                "EXACT_IDENTITY_DUPLICATE_CALL",
                "Reader input identity was already sealed",
            )
        self._records[digest] = result
        self.provider_calls += 1
        self.fresh_provider_calls += 1

    def restore(self, result: ReaderBoundaryResult) -> None:
        """Restore one previously sealed call result without reissuing it."""

        digest = result.identity.identity_digest
        if digest in self._records:
            raise DG23ReaderBoundaryError(
                "EXACT_IDENTITY_DUPLICATE_RESTORE",
                "Reader input identity was already restored or sealed",
            )
        self._records[digest] = result
        self._unclaimed_restored.add(digest)
        self.provider_calls += 1
        self.restored_provider_calls += 1

    def claim_restored(self, identity: ReaderInputIdentity) -> bool:
        """Associate a restored call with its first logical cell in this run."""

        digest = identity.identity_digest
        if digest not in self._unclaimed_restored:
            return False
        self._unclaimed_restored.remove(digest)
        return True

    def mark_reuse(self) -> None:
        self.exact_identity_reuses += 1


class DG23ReaderBoundary:
    """Invoke the frozen Reader once per exact identity with no send-time fitting."""

    def __init__(
        self,
        provider: MatchedVllmProvider,
        *,
        registry: ExactReaderIdentityRegistry | None = None,
        tokenizer_path: Path = DEFAULT_TOKENIZER,
        reader_contract_digest: str = FROZEN_READER_CONTRACT_SHA256,
    ) -> None:
        if full_provider_contract_sha256() != FROZEN_READER_CONTRACT_SHA256:
            raise DG23ReaderBoundaryError(
                "READER_CONTRACT_DRIFT",
                "frozen Reader contract identity drifted",
            )
        if reader_contract_digest != FROZEN_READER_CONTRACT_SHA256:
            raise DG23ReaderBoundaryError(
                "READER_CONTRACT_DRIFT",
                "DG-23 may not replace the frozen Reader contract",
            )
        self.provider = provider
        self.registry = registry or ExactReaderIdentityRegistry()
        try:
            self.reader_tokens = FrozenReaderTokenCounter(tokenizer_path=tokenizer_path)
        except RuntimeError as exc:
            raise DG23ReaderBoundaryError(
                "TOKENIZER_UNAVAILABLE_OR_DRIFTED",
                "exact Reader token accounting inputs are unavailable or drifted",
            ) from exc
        self.tokenizer_path = self.reader_tokens.tokenizer_path
        self.tokenizer_sha256 = self.reader_tokens.tokenizer_sha256
        self.reader_contract_digest = reader_contract_digest
        self.generation_settings_digest = _digest(
            full_provider_contract()["generation"]
        )

    def read(
        self,
        *,
        run_id: str,
        case_id: str,
        method_id: str,
        presentation_budget: int,
        source_snapshot_digest: str,
        replicate_index: int,
        question: str,
        question_as_of: str,
        memory_context: str,
        reader_context_digest: str,
        estimated_tokens: int,
        readiness: str = "READY",
    ) -> ReaderBoundaryResult:
        if readiness != "READY":
            raise DG23ReaderBoundaryError(
                "CONTEXT_BUDGET_INFEASIBLE_REQUIRED_UNITS",
                "Reader cannot be called for an infeasible protected closure",
            )
        observed_context_digest = hashlib.sha256(memory_context.encode()).hexdigest()
        if observed_context_digest != reader_context_digest:
            raise DG23ReaderBoundaryError(
                "READER_CONTEXT_IDENTITY_DRIFT",
                "Reader Context bytes do not match the sealed digest",
            )
        seed = dg23_matched_seed(source_snapshot_digest, replicate_index)
        identity = ReaderInputIdentity(
            reader_context_digest=reader_context_digest,
            reader_contract_digest=self.reader_contract_digest,
            sampling_seed=seed,
            generation_settings_digest=self.generation_settings_digest,
        )
        logical_id = dg23_logical_request_id(
            run_id=run_id,
            case_id=case_id,
            method_id=method_id,
            presentation_budget=presentation_budget,
            replicate_index=replicate_index,
        )
        exact_reader_tokens = self.reader_tokens.memory_tokens(
            question=question,
            question_as_of=question_as_of,
            memory_context=memory_context,
        )
        if exact_reader_tokens > presentation_budget:
            raise DG23ReaderBoundaryError(
                "TOKEN_ACCOUNTING_MISMATCH",
                "exact Reader memory exceeds the sealed presentation ceiling",
                metadata={
                    "exact_reader_tokens": exact_reader_tokens,
                    "budget_ceiling": presentation_budget,
                    "accounting_delta": exact_reader_tokens - presentation_budget,
                    "completion_call_attempted": False,
                },
            )
        existing = self.registry.get(identity)
        if existing is not None:
            if existing.accounting.exact_reader_tokens != exact_reader_tokens:
                raise DG23ReaderBoundaryError(
                    "RESTORED_TOKEN_ACCOUNTING_DRIFT",
                    "sealed exact identity has a different Reader token count",
                )
            restored = self.registry.claim_restored(identity)
            if not restored:
                self.registry.mark_reuse()
            return ReaderBoundaryResult(
                identity=identity,
                logical_request_id=logical_id,
                provider_result=existing.provider_result,
                accounting=ReaderAccountingReceipt(
                    estimated_tokens=estimated_tokens,
                    exact_reader_tokens=exact_reader_tokens,
                    reader_tokenizer_path_or_id=str(self.tokenizer_path),
                    reader_tokenizer_sha256=self.tokenizer_sha256,
                    budget_ceiling=presentation_budget,
                    accounting_delta=exact_reader_tokens - estimated_tokens,
                    reader_chat_template_path_or_id=str(
                        self.reader_tokens.chat_template_path
                    ),
                    reader_chat_template_sha256=(
                        self.reader_tokens.chat_template_sha256
                    ),
                    reader_accounting_identity=self.reader_tokens.accounting_identity,
                ),
                disposition=(
                    "RESTORED_PROVIDER_RESULT"
                    if restored
                    else "EXACT_IDENTITY_REUSE"
                ),
            )
        result = self.provider.answer(
            run_id=run_id,
            case_id=case_id,
            method_id=method_id,
            question=question,
            question_as_of=question_as_of,
            memory_context=memory_context,
            token_budget=presentation_budget,
            sampling_seed=seed,
            exact_context=True,
        )
        if (
            result.context_truncated
            or result.context != memory_context
            or result.seed != seed
        ):
            raise DG23ReaderBoundaryError(
                "EVAL_PRODUCT_PATH_DIVERGENCE",
                "Provider did not preserve the exact sealed Reader input",
            )
        if result.memory_tokens != exact_reader_tokens:
            raise DG23ReaderBoundaryError(
                "READER_TOKEN_ACCOUNTING_AUTHORITY_DRIFT",
                "Provider and frozen local Reader token accounting disagree",
                metadata={
                    "local_exact_reader_tokens": exact_reader_tokens,
                    "provider_exact_reader_tokens": result.memory_tokens,
                },
            )
        accounting = ReaderAccountingReceipt(
            estimated_tokens=estimated_tokens,
            exact_reader_tokens=exact_reader_tokens,
            reader_tokenizer_path_or_id=str(self.tokenizer_path),
            reader_tokenizer_sha256=self.tokenizer_sha256,
            budget_ceiling=presentation_budget,
            accounting_delta=exact_reader_tokens - estimated_tokens,
            reader_chat_template_path_or_id=str(
                self.reader_tokens.chat_template_path
            ),
            reader_chat_template_sha256=self.reader_tokens.chat_template_sha256,
            reader_accounting_identity=self.reader_tokens.accounting_identity,
        )
        boundary_result = ReaderBoundaryResult(
            identity=identity,
            logical_request_id=logical_id,
            provider_result=result,
            accounting=accounting,
            disposition="PROVIDER_CALL",
        )
        self.registry.seal(boundary_result)
        return boundary_result


def dg23_matched_seed(
    source_snapshot_digest: str,
    replicate_index: int,
    *,
    namespace: str = DG23_SEED_NAMESPACE,
) -> int:
    """Budget/arm/case-independent seed for one source snapshot replicate."""
    if (
        len(source_snapshot_digest) != 64
        or any(character not in "0123456789abcdef" for character in source_snapshot_digest)
        or replicate_index < 0
        or not namespace
    ):
        raise ValueError("DG-23 matched seed identity is invalid")
    material = f"{namespace}\0{source_snapshot_digest}\0{replicate_index}"
    return int(hashlib.sha256(material.encode()).hexdigest()[:16], 16) & (
        (1 << 63) - 1
    )


def dg23_logical_request_id(
    *,
    run_id: str,
    case_id: str,
    method_id: str,
    presentation_budget: int,
    replicate_index: int,
) -> str:
    if (
        not run_id
        or not case_id
        or not method_id
        or presentation_budget <= 0
        or replicate_index < 0
    ):
        raise ValueError("DG-23 logical Reader request identity is invalid")
    digest = hashlib.sha256(
        (
            f"{run_id}\0{case_id}\0{method_id}\0{presentation_budget}\0"
            f"{replicate_index}"
        ).encode()
    ).hexdigest()[:24]
    return f"dg23-{case_id}-{presentation_budget}-r{replicate_index}-{digest}"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


__all__ = [
    "DG23_SEED_NAMESPACE",
    "FROZEN_READER_CONTRACT_SHA256",
    "DG23ReaderBoundary",
    "DG23ReaderBoundaryError",
    "ExactReaderIdentityRegistry",
    "ReaderAccountingReceipt",
    "ReaderBoundaryResult",
    "ReaderInputIdentity",
    "dg23_logical_request_id",
    "dg23_matched_seed",
]
