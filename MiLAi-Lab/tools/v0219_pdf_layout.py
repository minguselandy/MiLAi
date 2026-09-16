"""Full-page deterministic PDF text layout; no OCR, model or relevance selection."""

import hashlib
import re
from io import BytesIO


def normalize_horizontal_space(text: str) -> str:
    return re.sub(r"[^\S\n]+", " ", text).strip()


def full_pdf_text(raw: bytes, expected_sha256: str) -> list[str]:
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("SOURCE_HASH_CHANGED")
    from pypdf import PdfReader

    pages = [normalize_horizontal_space(page.extract_text(extraction_mode="layout"))
             for page in PdfReader(BytesIO(raw)).pages]
    if not pages or any(not text for text in pages):
        raise ValueError("PDF_TEXT_UNAVAILABLE_NO_OCR_FALLBACK")
    return pages
