"""Deterministic complete text extraction from reviewed HTML documents, without fetching.

No selectors or relevance filters: preserve every data node outside HTML head,
script and style, in document order, with explicit boundaries. Original bytes
and hashes must remain in the preparation receipt. This is not image OCR.
"""

from html.parser import HTMLParser


class DocumentText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.suppressed = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"head", "script", "style"}:
            self.suppressed.append(tag)

    def handle_endtag(self, tag):
        if self.suppressed and tag == self.suppressed[-1]:
            self.suppressed.pop()

    def handle_data(self, data):
        if not self.suppressed and data.strip():
            self.parts.append(data.strip())


def complete_html_text(raw: str) -> str:
    parser = DocumentText()
    parser.feed(raw)
    parser.close()
    if parser.suppressed:
        raise ValueError("UNTERMINATED_NONCONTENT_ELEMENT")
    return "\n".join(parser.parts)
