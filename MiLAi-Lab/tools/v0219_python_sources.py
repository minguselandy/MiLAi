"""Deterministic source representation with explicit literal credential redactions.

This is not a general secret scanner or permission to execute the input. Callers
must review their D-only source set and retain the original hash/representation loss.
"""

from __future__ import annotations

import ast
import hashlib


def _credential_name(name: object) -> bool:
    return isinstance(name, str) and any(
        part in name.upper() for part in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
    )


def _target_name(node: ast.expr) -> object:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value
    return None


def redact_literal_credentials(raw: bytes, expected_sha256: str) -> dict:
    """Replace only string literals in named credential slots; never emit their values."""
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected_sha256:
        raise ValueError("SOURCE_HASH_CHANGED")
    try:
        text = raw.decode("utf-8")
        tree = ast.parse(text)
    except (SyntaxError, UnicodeError, ValueError):
        raise ValueError("PYTHON_SOURCE_UNPARSEABLE_NO_SOURCE_ECHO") from None
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_credential_name(_target_name(target)) for target in targets):
                candidates.append(node.value)
        elif isinstance(node, ast.Call):
            candidates.extend(
                kw.value for kw in node.keywords
                if kw.arg in {"key", "api_key", "token", "password", "secret"}
            )
    offsets = [0]
    for line in raw.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    ranges = set()
    for node in candidates:
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        assert node.end_lineno is not None and node.end_col_offset is not None
        ranges.add((offsets[node.lineno - 1] + node.col_offset,
                    offsets[node.end_lineno - 1] + node.end_col_offset))
    redacted = raw
    for start, end in sorted(ranges, reverse=True):
        redacted = redacted[:start] + b'"REDACTED_LITERAL_CREDENTIAL"' + redacted[end:]
    return {
        "source_sha256": observed,
        "representation_sha256": hashlib.sha256(redacted).hexdigest(),
        "content": redacted.decode("utf-8"),
        "redacted_literal_count": len(ranges),
        "all_other_source_bytes_preserved": True,
        "foreign_code_executed": False,
        "limits": "Only literal values in specified credential slots; "
        "not comprehensive secret detection.",
    }
