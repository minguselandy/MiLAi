"""Literal evidence matching with an optional paired quotation delimiter.

This validates location only. It does not certify semantic entailment, repair a
paraphrase, alter the stored quotation, or make a reference into delivered text.
"""
from __future__ import annotations

import re
from typing import Any


def quote_in_text(quote: str, text: str) -> bool:
    if not quote.strip():
        return False
    if quote in text:
        return True
    pairs = {"\"": "\"", "'": "'", "\u201c": "\u201d", "\u2018": "\u2019"}
    candidate = quote.strip()
    if len(candidate) > 2 and pairs.get(candidate[0]) == candidate[-1]:
        literal = candidate[1:-1].strip()
        return bool(literal) and literal in text
    return False


def quote_in_evidence(quote: str, evidence: list[dict[str, Any]]) -> bool:
    """Keep an optional trailing item citation bound to that actual delivered item."""
    if any(quote_in_text(quote, source["content"])
           for item in evidence for source in item["evidence"]):
        return True
    citation = re.search(r"\s*(?:\[(e\d+)\]|\((e\d+)\))\s*$", quote)
    if citation is None:
        return False
    literal, label = quote[:citation.start()].rstrip(), citation.group(1) or citation.group(2)
    return any(quote_in_text(literal, source["content"])
               for item in evidence if item.get("label") == label for source in item["evidence"])
