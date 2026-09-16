"""Mechanical paging extension, not a memory-use policy or retrieval intervention."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path


def paged_schema(schema: dict) -> dict:
    schema = deepcopy(schema)
    for branch in schema["anyOf"]:
        action = branch["properties"]["delivery"]
        kind = action["properties"]["action"]["const"]
        action["properties"]["offset"] = (
            {"type": "integer", "minimum": 0} if kind == "read" else {"const": 0})
        action["required"].append("offset")
        if kind == "search":
            action["properties"]["query"].update(minLength=1, pattern=r".*\S.*")
    return schema


async def read_pages(helper, binding, refs: tuple, offset: int):
    return list(await asyncio.gather(*(helper.read_source(binding, ref, offset) for ref in refs)))


PAGING_PROTOCOL = (
    "\nread also takes offset, a UTF-8 byte cursor (0 for the first page); use one source_id "
    "when sources need different cursors. Follow a returned next_cursor for additional pages, "
    "or read a search result's start_byte to inspect that range. Each page is bounded to 4096 "
    "bytes. COMPLETE means that range reached EOF, not that earlier unread pages were covered. "
    "Search returns locations only; actual source text comes from read. All previous pages "
    "remain available in this session. Use offset=0 for non-read actions."
)


def mechanical_preflight(owned: Path, root: Path, config: dict) -> dict:
    """No-model real public create/update/restore plus SDK multi-page read roundtrip."""
    from replay_v0213_cost import save, sha
    from run_v0215 import state_write_arguments
    from v0210_v05_product import observer
    from v0214_host_runtime import source_runtime
    from v0214_source_binding import FileSources

    directory = root / "mechanical-preflight"
    directory.mkdir(mode=0o700)
    api, identity = source_runtime(config)
    scope = "v0216-preflight-" + sha(str(root).encode())[:16]
    binding = api.Binding(scope, scope, scope)
    source = directory / "source-01.txt"
    raw = ("Normal authorized UTF-8 page material, αβ.\n" * 350).encode()
    source.write_bytes(raw)
    helper = api.AcquisitionHelper(FileSources({binding: directory}, source_api=api))
    with asyncio.Runner() as loop:
        refs = loop.run(helper.resolve_sources(binding))
        first = loop.run(read_pages(helper, binding, refs, 0))[0]
        pages = [first]
        while pages[-1].next_cursor is not None:
            pages.append(loop.run(read_pages(helper, binding, refs, pages[-1].next_cursor))[0])
        assert len(pages) > 1
        assert "".join(page.text for page in pages).encode() == raw
        assert pages[0].coverage == api.Coverage.PARTIAL
        assert pages[-1].coverage == api.Coverage.COMPLETE
        visible = loop.run(helper.presentation(binding, [page.request_id for page in pages],
                                                "NO_SEND_ASSEMBLY_ONLY"))
        assert visible == pages and helper.presented == []
    calls = []
    expected_note = "Revised ordinary note; αβ. No authority or execution granted."
    with observer(owned, directory / "first", task=scope, principal=scope, project=scope) as public:
        def call(name, arguments):
            value = public(name, arguments)
            calls.append({"tool": name, "arguments": arguments, "result": value})
            assert not value.get("mcp_error"), value
            return value
        absent = call("milai_working_state_get", {"scope": "TASK"})
        assert absent["status"] == "ABSENT"
        created = call("milai_working_state_update", state_write_arguments(
            absent, "First ordinary note.", scope + "-create"))
        updated = call("milai_working_state_update", state_write_arguments(
            created, expected_note, scope + "-update"))
        assert updated["state_id"] == created["state_id"]
        assert updated["version"] == created["version"] + 1
    with observer(owned, directory / "restored", task=scope,
                  principal=scope, project=scope) as public:
        restored = public("milai_working_state_get", {"scope": "TASK"})
        calls.append({"tool": "milai_working_state_get", "scope": scope, "result": restored})
        assert restored["state_id"] == updated["state_id"]
        assert restored["version"] == updated["version"]
        assert restored["payload"] == {"note": expected_note}
    with observer(owned, directory / "other-task", task=scope + "-other",
                  principal=scope, project=scope) as public:
        other = public("milai_working_state_get", {"scope": "TASK"})
        calls.append({"tool": "milai_working_state_get", "scope": scope + "-other",
                      "result": other})
        assert other["status"] == "ABSENT"
    report = {"status": "PASS", "model_requests": 0, "raw_tokens": 0,
        "host_sdk": identity, "page_count": len(pages), "source_bytes": len(raw),
        "source_roundtrip_sha256": sha(raw), "assembled_not_presented": True,
        "cas_create_update_and_fresh_mcp_restore": True, "other_task_absent": True,
        "public_calls": calls, "public_call_count": len(calls),
        "scope": "Owned synthetic preflight; no benchmark result or cognitive claim"}
    save(directory / "result.json", report)
    return report
