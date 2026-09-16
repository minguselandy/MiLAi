from __future__ import annotations

import milai.application  # noqa: F401 - initializes the application's repository import order
from milai.persistence.retrieval_repository import _fts_query


def test_fts_query_keeps_content_words_and_uses_or_semantics() -> None:
    assert _fts_query("What is the name of my cat?") == "name | cat"
    assert _fts_query("How long is my daily commute to work?") == "long | daily | commute | work"


def test_fts_query_is_bounded_deduplicated_and_syntax_safe() -> None:
    query = _fts_query("pear pear '); DROP TABLE claim; --")

    assert query == "pear | drop | table | claim"
    assert len(_fts_query(" ".join(f"term{index}" for index in range(40))).split(" | ")) == 32


def test_fts_query_has_a_stopword_only_fallback() -> None:
    assert _fts_query("what is it") == "what | is | it"
