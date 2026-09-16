"""Extract explicitly selected D source material without executing benchmark Python.

Inputs are reviewed D-only specifications, never a corpus sweep. PDF support is
optional and pinned by the caller. Images and evaluation functions are not read.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


def extract_python(raw: bytes, selection: dict) -> object:
    tree = ast.parse(raw)
    if selection["kind"] == "literal":
        matches = [node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == selection["name"]
                           for t in node.targets)]
        if len(matches) != 1:
            raise ValueError("LITERAL_SELECTION_NOT_UNIQUE")
        return ast.literal_eval(matches[0])
    if selection["kind"] != "call_keywords":
        raise ValueError("UNKNOWN_SOURCE_SELECTION")
    functions = [node for node in tree.body
                 if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
                 and node.name == selection["function"]]
    if len(functions) != 1:
        raise ValueError("FUNCTION_SELECTION_NOT_UNIQUE")
    result = []
    for node in ast.walk(functions[0]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == selection["method"]):
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            if not set(selection["keywords"]).issubset(kwargs):
                raise ValueError("CALL_KEYWORD_MISSING")
            result.append({key: ast.literal_eval(kwargs[key]) for key in selection["keywords"]})
    if len(result) != selection["count"]:
        raise ValueError("CALL_COUNT_CHANGED")
    return result


def extract(source: Path, expected_sha256: str, selection: dict) -> dict:
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("SOURCE_HASH_CHANGED")
    if selection["kind"] == "pdf_embedded_text":
        from io import BytesIO

        from pypdf import PdfReader

        content = [page.extract_text() for page in PdfReader(BytesIO(raw)).pages]
        if not content or any(not isinstance(page, str) or not page.strip() for page in content):
            raise ValueError("PDF_EMBEDDED_TEXT_UNAVAILABLE_NO_OCR_FALLBACK")
    else:
        content = extract_python(raw, selection)
    return {"source_sha256": expected_sha256, "selection": selection, "content": content}
