"""Ordinary literal file search over the current allowed immutable snapshot."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from v02_e2e_state import FileDisclosure, LocalGateError, file_path


def search_files(workspace: Path, frozen: dict, queries: list[str], offset: int = 0,
                 disclosure: FileDisclosure | None = None) -> dict:
    if (not isinstance(queries, list) or not 1 <= len(queries) <= 8
            or any(not isinstance(q, str) or not 1 <= len(q) <= 128 for q in queries)
            or type(offset) is not int or offset < 0):
        raise ValueError("LITERAL_QUERIES_1_TO_8_AND_NONNEGATIVE_OFFSET_REQUIRED")
    pattern = re.compile("|".join(re.escape(q) for q in queries), re.IGNORECASE)
    hits, seen = [], 0
    for name, version in sorted(frozen.items()):
        if disclosure:
            try:
                disclosure.read(name)
            except LocalGateError:
                continue  # Do not disclose paths or bytes for ineligible files.
        raw = file_path(workspace, name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != version:
            raise ValueError("SOURCE_CHANGED")
        text = raw.decode("utf-8")
        for match in pattern.finditer(text):
            if seen >= offset:
                if len(hits) == 16:
                    return {"hits": hits, "next_offset": seen, "status": "MORE"}
                start, end = max(0, match.start() - 160), min(len(text), match.end() + 160)
                hits.append({"path": name, "sha256": version,
                             "match_byte_offset": len(text[:match.start()].encode()),
                             "excerpt": text[start:end],
                             "excerpt_is_partial": start > 0 or end < len(text)})
            seen += 1
    return {"hits": hits, "next_offset": None, "status": "EOF"}
