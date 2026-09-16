"""Frozen, offline Reader prompt-envelope token accounting for DG-23."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined, Template
from tokenizers import Tokenizer

from evals.dg14.benchmark import DEFAULT_CHAT_TEMPLATE, DEFAULT_TOKENIZER
from evals.paper.provider import EXPECTED_PROMPT_CONTRACT_SHA256, messages

EXPECTED_READER_TOKENIZER_SHA256 = (
    "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
)
EXPECTED_READER_CHAT_TEMPLATE_SHA256 = (
    "e84f32a23fdda27689f868aa4a1a5621f41133e51a48d7f3efcbea2839574259"
)


class FrozenReaderTokenAccountingError(RuntimeError):
    """The frozen local Reader accounting inputs or result are invalid."""


class FrozenReaderTokenCounter:
    """Count the Reader-authoritative memory delta without a Provider call.

    The presentation ceiling applies to the token delta between the frozen
    prompt with and without ``memory_context``. Counting the bare Context is
    insufficient because token boundaries can merge with the surrounding
    frozen user-message template.
    """

    def __init__(
        self,
        *,
        tokenizer_path: Path = DEFAULT_TOKENIZER,
        chat_template_path: Path = DEFAULT_CHAT_TEMPLATE,
        expected_tokenizer_sha256: str = EXPECTED_READER_TOKENIZER_SHA256,
        expected_chat_template_sha256: str = EXPECTED_READER_CHAT_TEMPLATE_SHA256,
    ) -> None:
        if not tokenizer_path.is_file() or not chat_template_path.is_file():
            raise FrozenReaderTokenAccountingError(
                "frozen Reader tokenizer or chat template is unavailable"
            )
        self.tokenizer_path = tokenizer_path.resolve()
        self.chat_template_path = chat_template_path.resolve()
        self.tokenizer_sha256 = _sha256(tokenizer_path)
        self.chat_template_sha256 = _sha256(chat_template_path)
        if (
            self.tokenizer_sha256 != expected_tokenizer_sha256
            or self.chat_template_sha256 != expected_chat_template_sha256
        ):
            raise FrozenReaderTokenAccountingError(
                "frozen Reader tokenizer or chat template identity drifted"
            )
        # This is a model chat template, not HTML; escaping would change tokens.
        environment = Environment(
            undefined=StrictUndefined,
            autoescape=False,  # noqa: S701 -- model text, not HTML
        )
        environment.globals["raise_exception"] = _raise_template_error
        self._template: Template = environment.from_string(
            chat_template_path.read_text(encoding="utf-8")
        )
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.accounting_identity = hashlib.sha256(
            json.dumps(
                {
                    "chat_template_sha256": self.chat_template_sha256,
                    "prompt_contract_sha256": EXPECTED_PROMPT_CONTRACT_SHA256,
                    "tokenizer_sha256": self.tokenizer_sha256,
                    "measure": "with_memory_prompt_tokens-minus-no_memory_prompt_tokens",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def prompt_tokens(
        self,
        *,
        question: str,
        question_as_of: str,
        memory_context: str,
    ) -> int:
        """Count the frozen serialized chat prompt exactly and locally."""

        return self.message_tokens(messages(question, question_as_of, memory_context))

    def message_tokens(self, value: Sequence[Mapping[str, Any]]) -> int:
        """Count an already-built frozen Reader message sequence."""

        rendered = self._template.render(
            messages=list(value),
            tools=None,
            add_generation_prompt=True,
            enable_thinking=False,
            add_vision_id=False,
        )
        return len(self._tokenizer.encode(rendered, add_special_tokens=False).ids)

    def memory_tokens(
        self,
        *,
        question: str,
        question_as_of: str,
        memory_context: str,
    ) -> int:
        """Return the exact prompt token delta attributable to memory."""

        with_memory = self.prompt_tokens(
            question=question,
            question_as_of=question_as_of,
            memory_context=memory_context,
        )
        without_memory = self.prompt_tokens(
            question=question,
            question_as_of=question_as_of,
            memory_context="",
        )
        observed = with_memory - without_memory
        if observed < 0:
            raise FrozenReaderTokenAccountingError(
                "Reader memory token delta cannot be negative"
            )
        return observed

    def bind(self, *, question: str, question_as_of: str) -> Callable[[str], int]:
        """Bind case prompt fields so a Context compiler can count text."""

        if not question or not question_as_of:
            raise ValueError("question and question timestamp are required")

        def count(memory_context: str) -> int:
            return self.memory_tokens(
                question=question,
                question_as_of=question_as_of,
                memory_context=memory_context,
            )

        return count


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raise_template_error(message: str) -> None:
    raise FrozenReaderTokenAccountingError(message)


__all__ = [
    "EXPECTED_READER_CHAT_TEMPLATE_SHA256",
    "EXPECTED_READER_TOKENIZER_SHA256",
    "FrozenReaderTokenAccountingError",
    "FrozenReaderTokenCounter",
]
