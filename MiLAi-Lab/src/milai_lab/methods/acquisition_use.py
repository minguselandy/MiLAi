"""Source-only acquisition/use decomposition, independent of Product and evaluator gold."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass

TokenCount = Callable[[str], int]
TokenOffsets = Callable[[str], Sequence[tuple[int, int]]]
STOPLIST = frozenset("a an the is are was were be to of for in on at and or with please".split())


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Source:
    source_id: str
    text: str

    @property
    def version(self) -> str:
        return digest(self.text)

    def read(self, start: int, end: int) -> Span:
        raw = self.text.encode()
        if not 0 <= start < end <= len(raw):
            raise ValueError("SOURCE_SPAN_OUT_OF_RANGE")
        return Span(self.source_id, self.version, start, end, raw[start:end].decode())


@dataclass(frozen=True)
class Span:
    source_id: str
    source_version: str
    start_byte: int
    end_byte: int
    text: str


@dataclass(frozen=True)
class LexicalPolicy:
    chunk_tokens: int = 1024
    overlap_tokens: int = 128
    top_k: int = 4
    k1: float = 1.2
    b: float = 0.75
    # This is an evidence-condition control, separate from cumulative token spending.
    evidence_tokens: int = 49152

    @property
    def policy_hash(self) -> str:
        return digest(canonical({**asdict(self), "stoplist": sorted(STOPLIST),
                                 "lexical_rule": r"[^\W_]+; Unicode casefold; no synonyms",
                                 "query": "Q plus every supplied tool/parameter name",
                                 "ordering": "score desc, source_id asc, byte offset asc",
                                 "budget": "whole merged span; stop at first non-fitting span"}))


def terms(text: str) -> list[str]:
    return [word for word in re.findall(r"[^\W_]+", text.casefold()) if word not in STOPLIST]


def retrieval_query(question: str, tools: Sequence[Mapping[str, object]]) -> str:
    """All legitimate tools are treated alike; target labels are not an argument."""
    names = []
    for tool in tools:
        names.append(str(tool["name"]))
        parameters = tool.get("parameters", {})
        if isinstance(parameters, dict):
            names.extend(sorted(parameters.get("properties", {})))
    return "\n".join([question, *names])


def chunks(source: Source, offsets: TokenOffsets, policy: LexicalPolicy) -> list[Span]:
    positions = offsets(source.text)
    byte_positions = [0]
    for char in source.text:
        byte_positions.append(byte_positions[-1] + len(char.encode()))
    result = []
    stride = policy.chunk_tokens - policy.overlap_tokens
    if stride <= 0:
        raise ValueError("OVERLAP_MUST_BE_SMALLER_THAN_CHUNK")
    for start in range(0, len(positions), stride):
        stop = min(len(positions), start + policy.chunk_tokens)
        begin_char = positions[start][0]
        end_char = positions[stop - 1][1]
        result.append(source.read(byte_positions[begin_char], byte_positions[end_char]))
        if stop == len(positions):
            break
    return result


def evidence_text(spans: Sequence[Span]) -> str:
    return canonical({"source_evidence": [asdict(span) for span in spans]})


def merge_overlaps(selected: Sequence[Span], sources: Mapping[str, Source]) -> list[Span]:
    """Union overlaps, retaining the best-ranked member's place in the presentation."""
    groups: list[tuple[int, str, int, int]] = []
    for rank, span in enumerate(selected):
        sid, start, end = span.source_id, span.start_byte, span.end_byte
        remaining = []
        for other_rank, other_sid, other_start, other_end in groups:
            if other_sid == sid and other_start <= end and start <= other_end:
                rank = min(rank, other_rank)
                start, end = min(start, other_start), max(end, other_end)
            else:
                remaining.append((other_rank, other_sid, other_start, other_end))
        groups = [*remaining, (rank, sid, start, end)]
    return [sources[sid].read(start, end) for _, sid, start, end in sorted(groups)]


def retrieve(question: str, tools: Sequence[Mapping[str, object]], sources: Sequence[Source],
             count: TokenCount, offsets: TokenOffsets, policy: LexicalPolicy) -> dict[str, object]:
    ordered = sorted(sources, key=lambda s: s.source_id)
    full = [s.read(0, len(s.text.encode())) for s in ordered if s.text]
    query = retrieval_query(question, tools)
    base: dict[str, object] = {"policy_hash": policy.policy_hash, "query": query,
                              "backend": "LAB_RAW_BM25_NOT_PRODUCT_RETRIEVAL"}
    if count(evidence_text(full)) <= policy.evidence_tokens:
        return {**base, "status": "FULL_HISTORY_FITS", "spans": full,
                "ranking": [], "omitted_for_budget": []}
    pool = [chunk for source in ordered for chunk in chunks(source, offsets, policy)]
    bags = [Counter(terms(span.text)) for span in pool]
    lengths = [sum(bag.values()) for bag in bags]
    average = sum(lengths) / len(lengths) if lengths else 0
    query_terms = set(terms(query))
    frequencies = {word: sum(word in bag for bag in bags) for word in query_terms}
    scored = []
    for span, bag, length in zip(pool, bags, lengths, strict=True):
        score = 0.0
        for word in sorted(query_terms & bag.keys()):
            idf = math.log(1 + (len(pool) - frequencies[word] + 0.5) / (frequencies[word] + 0.5))
            tf = bag[word]
            score += idf * tf * (policy.k1 + 1) / (
                tf + policy.k1 * (1 - policy.b + policy.b * length / average))
        if score > 0:
            scored.append((score, span))
    scored.sort(key=lambda row: (-row[0], row[1].source_id, row[1].start_byte))
    merged = merge_overlaps([span for _, span in scored[:policy.top_k]],
                            {s.source_id: s for s in ordered})
    selected: list[Span] = []
    for span in merged:
        if count(evidence_text([*selected, span])) > policy.evidence_tokens:
            break
        selected.append(span)
    return {**base, "status": "RETRIEVED" if selected else "EMPTY",
            "spans": selected, "ranking": [{"score": score, **asdict(span)}
                                              for score, span in scored[:policy.top_k]],
            "omitted_for_budget": [asdict(span) for span in merged[len(selected):]]}


def source_binding(sources: Sequence[Source]) -> dict[str, object]:
    return {"mode": "SOURCE_FILES_ONLY", "product_history_ingested": False,
            "product_miss_meaning": "DOES_NOT_DESCRIBE_SOURCE_HISTORY",
            "interfaces_covering_history": ["source_read", "source_search"],
            "sources": [{"source_id": s.source_id, "sha256": s.version,
                         "bytes": len(s.text.encode())} for s in sources]}


def oracle_evidence(sources: Sequence[Source], locations: Sequence[Mapping[str, object]],
                    *, sufficient: bool, count: TokenCount, evidence_tokens: int
                    ) -> tuple[str, list[Span]]:
    """Evaluation-side locations only; rendered output contains verbatim source spans."""
    source_map = {s.source_id: s for s in sources}
    selected = []
    try:
        for location in locations:
            source = source_map[str(location["source_id"])]
            if location["source_version"] != source.version:
                return "ORACLE_INVALID", []
            selected.append(source.read(int(str(location["start_byte"])),
                                        int(str(location["end_byte"]))))
    except (KeyError, ValueError, UnicodeDecodeError):
        return "ORACLE_INVALID", []
    if not sufficient or not selected:
        return "ORACLE_INSUFFICIENT", selected
    if count(evidence_text(selected)) > evidence_tokens:
        return "ORACLE_BUDGET_INFEASIBLE", selected
    return "ORACLE_VALID", selected


def valid_intent(actual: object) -> bool:
    """Validate the submitted business artifact at the external model-output boundary."""
    return isinstance(actual, list) and bool(actual) and all(
        isinstance(call, dict) and set(call) == {"name", "arguments"}
        and isinstance(call["name"], str) and isinstance(call["arguments"], dict)
        for call in actual
    )


def business_delivery_status(action: Mapping[str, object]) -> str:
    """A text answer with an empty business plan is not a delivered action intent."""
    if action["action"] == "business":
        return "ANSWERED" if valid_intent(action["calls"]) else "FORMAT_ERROR"
    return "ABSTAINED" if action["action"] == "abstain" else "ACQUISITION"


def score_intent(actual: object, expected: object, *, adjudicable: bool) -> str:
    """First complete action intent, never a claim that a business action executed."""
    if not adjudicable:
        return "UNSCORED"
    if not valid_intent(actual):
        return "FORMAT_ERROR"
    return "CORRECT" if canonical(actual) == canonical(expected) else "INCORRECT"
