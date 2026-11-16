"""Literal evidence matching with an optional paired quotation delimiter.

This validates location only. It does not certify semantic entailment, repair a
paraphrase, alter the stored quotation, or make a reference into delivered text.
"""
from __future__ import annotations


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
