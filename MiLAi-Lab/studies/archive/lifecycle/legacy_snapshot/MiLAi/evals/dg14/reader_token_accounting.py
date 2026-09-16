"""Frozen local Qwen Reader-envelope token accounting for context preflight."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, StrictUndefined, Template
from tokenizers import Tokenizer

from evals.paper.provider import EXPECTED_PROMPT_CONTRACT_SHA256, messages

DEFAULT_READER_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
DEFAULT_READER_CHAT_TEMPLATE = Path("/cra/qwen36-35B/chat_template.jinja")
EXPECTED_READER_TOKENIZER_SHA256 = (
    "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
)
EXPECTED_READER_CHAT_TEMPLATE_SHA256 = (
    "e84f32a23fdda27689f868aa4a1a5621f41133e51a48d7f3efcbea2839574259"
)


class FrozenReaderTokenAccountingError(RuntimeError):
    """The frozen tokenizer/template identity or local accounting is invalid."""


class FrozenReaderTokenCounter:
    """Count and locate context bytes in the exact frozen Reader prompt."""

    def __init__(
        self,
        *,
        tokenizer_path: Path = DEFAULT_READER_TOKENIZER,
        chat_template_path: Path = DEFAULT_READER_CHAT_TEMPLATE,
        expected_tokenizer_sha256: str = EXPECTED_READER_TOKENIZER_SHA256,
        expected_chat_template_sha256: str = EXPECTED_READER_CHAT_TEMPLATE_SHA256,
    ) -> None:
        if not tokenizer_path.is_file() or not chat_template_path.is_file():
            raise FrozenReaderTokenAccountingError(
                "frozen Reader tokenizer or chat template is unavailable"
            )
        self.tokenizer_path = tokenizer_path.resolve()
        self.chat_template_path = chat_template_path.resolve()
        self.tokenizer_sha256 = _sha256(self.tokenizer_path)
        self.chat_template_sha256 = _sha256(self.chat_template_path)
        if (
            self.tokenizer_sha256 != expected_tokenizer_sha256
            or self.chat_template_sha256 != expected_chat_template_sha256
        ):
            raise FrozenReaderTokenAccountingError(
                "frozen Reader tokenizer or chat template identity drifted"
            )
        environment = Environment(
            undefined=StrictUndefined,
            autoescape=False,
        )
        environment.globals["raise_exception"] = _raise_template_error
        self._template: Template = environment.from_string(
            self.chat_template_path.read_text(encoding="utf-8")
        )
        self._tokenizer = Tokenizer.from_file(str(self.tokenizer_path))
        self.accounting_identity = hashlib.sha256(
            json.dumps(
                {
                    "chat_template_sha256": self.chat_template_sha256,
                    "measure": (
                        "with_memory_prompt_tokens-minus_no_memory_prompt_tokens"
                    ),
                    "prompt_contract_sha256": EXPECTED_PROMPT_CONTRACT_SHA256,
                    "tokenizer_sha256": self.tokenizer_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def render_prompt(
        self, *, question: str, question_as_of: str, memory_context: str
    ) -> str:
        return self._template.render(
            messages=messages(question, question_as_of, memory_context),
            tools=None,
            add_generation_prompt=True,
            enable_thinking=False,
            add_vision_id=False,
        )

    def prompt_tokens(
        self, *, question: str, question_as_of: str, memory_context: str
    ) -> int:
        rendered = self.render_prompt(
            question=question,
            question_as_of=question_as_of,
            memory_context=memory_context,
        )
        return len(self._tokenizer.encode(rendered, add_special_tokens=False).ids)

    def memory_tokens(
        self, *, question: str, question_as_of: str, memory_context: str
    ) -> int:
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

    def unit_prompt_token_span(
        self,
        *,
        question: str,
        question_as_of: str,
        memory_context: str,
        context_char_start: int,
        context_char_end: int,
    ) -> tuple[int, int]:
        """Return the exact absolute Reader-prompt token interval for one unit."""

        if not 0 <= context_char_start < context_char_end <= len(memory_context):
            raise FrozenReaderTokenAccountingError(
                "Reader-visible serialized unit offset is invalid"
            )
        rendered = self.render_prompt(
            question=question,
            question_as_of=question_as_of,
            memory_context=memory_context,
        )
        prompt_context_start = rendered.find(memory_context)
        if prompt_context_start < 0 or rendered.find(
            memory_context, prompt_context_start + 1
        ) >= 0:
            raise FrozenReaderTokenAccountingError(
                "serialized Context is not uniquely replayable in Reader prompt"
            )
        absolute_start = prompt_context_start + context_char_start
        absolute_end = prompt_context_start + context_char_end
        encoding = self._tokenizer.encode(rendered, add_special_tokens=False)
        token_indexes = [
            index
            for index, (start, end) in enumerate(encoding.offsets)
            if end > absolute_start and start < absolute_end
        ]
        if not token_indexes:
            raise FrozenReaderTokenAccountingError(
                "Reader-visible unit has no token coverage"
            )
        return token_indexes[0], token_indexes[-1] + 1


@lru_cache(maxsize=1)
def frozen_reader_token_counter() -> FrozenReaderTokenCounter:
    """Load the frozen Qwen accounting identity once per local process."""

    return FrozenReaderTokenCounter()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raise_template_error(message: str) -> None:
    raise FrozenReaderTokenAccountingError(message)


__all__ = [
    "DEFAULT_READER_CHAT_TEMPLATE",
    "DEFAULT_READER_TOKENIZER",
    "EXPECTED_READER_CHAT_TEMPLATE_SHA256",
    "EXPECTED_READER_TOKENIZER_SHA256",
    "FrozenReaderTokenAccountingError",
    "FrozenReaderTokenCounter",
    "frozen_reader_token_counter",
]
