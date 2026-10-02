"""Query-free lossless source partitions; no source-specific parsing or query access."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from itertools import pairwise

from milai_lab.contracts.correction_relation import SegmentProfile

# Keep the blank-line separator in the preceding paragraph. CRLF remains two codepoints.
_NEWLINE = r"(?:\r\n|\r(?!\n)|(?<!\r)\n)"
_PARAGRAPH = re.compile(_NEWLINE + r"(?:[^\S\r\n]*" + _NEWLINE + r")+")


def segment_body(
    body: str, *, token_count: Callable[[str], int], profile: SegmentProfile,
) -> tuple[tuple[int, int], ...]:
    """Prefer complete paragraphs, then lines, whitespace boundaries, Unicode prefixes.

    All spans partition the original Python string exactly. No normalization, overlap,
    header removal, semantic interpretation, future question or annotation is involved.
    Empty bodies return no spans. A cap unable to fit any prefix fails explicitly.
    """
    if type(body) is not str:
        raise ValueError("CORRECTION_SEGMENT_TEXT_REQUIRED")
    if not body:
        return ()
    cache: dict[tuple[int, int], int] = {}

    def count(start: int, end: int) -> int:
        key = (start, end)
        if key not in cache:
            result = token_count(body[start:end])
            if type(result) is not int or result < 0:
                raise ValueError("CORRECTION_TOKEN_COUNT_INVALID")
            cache[key] = result
        return cache[key]

    def prefixes(start: int, end: int) -> Iterator[tuple[int, int]]:
        while start < end:
            if count(start, end) <= profile.max_body_tokens:
                yield start, end
                return
            low = start + 1
            # Token counts need not be monotone. Establish a genuinely fitting prefix.
            while low <= end and count(start, low) > profile.max_body_tokens:
                low += 1
            if low > end:
                raise ValueError("CORRECTION_SEGMENT_CAP_CANNOT_FIT_PREFIX")
            high = end
            while low < high:
                middle = (low + high + 1) // 2
                if count(start, middle) <= profile.max_body_tokens:
                    low = middle
                else:
                    high = middle - 1
            # Search is merely an efficiency heuristic, not a monotonicity assumption.
            if low <= start or count(start, low) > profile.max_body_tokens:
                raise ValueError("CORRECTION_SEGMENT_PREFIX_INVALID")
            yield start, low
            start = low

    def partition(start: int, end: int, level: int = 0) -> list[tuple[int, int]]:
        if count(start, end) <= profile.max_body_tokens:
            return [(start, end)]
        text = body[start:end]
        if level == 0:
            boundaries = [start + match.end() for match in _PARAGRAPH.finditer(text)]
        elif level == 1:
            lengths = [len(line) for line in text.splitlines(keepends=True)]
            boundaries = []
            position = start
            for length in lengths:
                position += length
                boundaries.append(position)
        elif level == 2:
            boundaries = [start + match.end() for match in re.finditer(r"\s+", text)]
        else:
            return list(prefixes(start, end))
        if not boundaries or boundaries[-1] != end:
            boundaries.append(end)
        result = []
        pending_start, pending_end = start, start
        for boundary in boundaries:
            if (pending_end > pending_start
                    and count(pending_start, boundary) > profile.max_body_tokens):
                result.append((pending_start, pending_end))
                pending_start = pending_end
            if count(pending_start, boundary) <= profile.max_body_tokens:
                pending_end = boundary
            else:
                smaller = partition(pending_start, boundary, level + 1)
                result.extend(smaller[:-1])
                pending_start, pending_end = smaller[-1]
        result.append((pending_start, pending_end))
        return result

    result = partition(0, len(body))
    if (not result or result[0][0] != 0 or result[-1][1] != len(body)
            or any(left[1] != right[0] for left, right in pairwise(result))
            or any(start >= end or count(start, end) > profile.max_body_tokens
                   for start, end in result)):
        raise ValueError("CORRECTION_SEGMENT_PARTITION_INVALID")
    return tuple(result)
