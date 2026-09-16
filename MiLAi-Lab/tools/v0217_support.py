"""Shared epistemic metadata, not a memory controller or semantic absence judge."""

from __future__ import annotations

from v0214_source_binding import FileSources

PROTOCOL = (
    "\nSource coverage is mechanical, not a semantic absence verdict. Search scans and returns "
    "locations, never proves that source text was presented. Use actual next_cursor values; "
    "4096 is a JSON output bound, not a guaranteed body length. EOF on a tail page does not "
    "cover earlier holes. If needed evidence was not obtained, describe what remains unchecked "
    "instead of saying it does not exist anywhere. Even complete byte coverage only licenses "
    "claims about the specified eligible source versions, not arbitrary semantic absence. "
    "Positive decisions need sufficient relevant evidence, not exhaustive unrelated reading."
)


class CalibratedSources(FileSources):
    async def search(self, binding, query, business_tools):
        value = await super().search(binding, query, business_tools)
        internal = value.pop("query_status")
        value.update(internal_selection_status=internal, query_status="LOCATIONS_ONLY",
            located_range_kind="WHOLE_CANDIDATE_FILES_NOT_MATCHES" if
                internal == "FULL_HISTORY_FITS" else "RANKED_CANDIDATE_RANGES",
            source_text_returned=False, source_text_presented=False,
            semantic_absence_established=False)
        return value


def coverage(refs, pages) -> dict:
    """Union only eligible, current-version ranges assembled in this one request."""
    rows = []
    for ref in refs:
        if not ref.eligible:
            continue
        spans = sorted((page.cursor, page.cursor + len(page.text.encode())) for page in pages
            if page.source_id == ref.source_id and page.version == ref.version and page.text)
        merged = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        complete = ref.size_bytes == 0 or merged == [[0, ref.size_bytes]]
        rows.append({"source_id": ref.source_id, "version": ref.version,
            "size_bytes": ref.size_bytes, "assembled_byte_ranges": merged,
            "whole_source_bytes_assembled": complete})
    return {"scope": "ELIGIBLE_CURRENT_VERSIONS_IN_THIS_REQUEST_NOT_TRANSPORT_RECEIPT",
            "sources": rows, "semantic_absence_established": False}


def public_work_history(actions: list[dict], tool_results: list[dict]) -> dict:
    """Normal visible work, never the optional notebook or State update/restore receipts."""
    fields = ("action", "source_ids", "offset", "query", "decision", "explanation", "citations")
    return {"kind": "ORDINARY_SHARED_WORK_RECORD_NOT_NOTE_SUMMARY",
        "actions": [{key: item["action"][key] for key in fields if key in item["action"]}
                    for item in actions],
        "tool_facts": [{"action": item["action"], "result": item["result"]}
                       for item in tool_results]}
