"""Opaque UTF-8 file observations, independent of task family and document fields."""

from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import quote, urlsplit


def file_material(source: dict, project: str) -> tuple[dict, list, dict]:
    if set(source) != {"schema_version", "files"} or source["schema_version"] != (
        "v02-file-source-only-v1"
    ):
        raise ValueError("Invalid file source package")
    files, events, refs, identities = {}, [], {}, set()
    for item in source["files"]:
        if set(item) != {"path", "source_uri", "observed_at", "content", "sha256"}:
            raise ValueError("Invalid file observation fields")
        name, uri, content = item["path"], item["source_uri"], item["content"]
        if (not isinstance(name, str) or not name or name.startswith("/")
                or any(p in {"", ".", ".."} for p in name.split("/")) or "\\" in name):
            raise ValueError("Invalid relative file path")
        if name in files or uri in identities or not urlsplit(uri).scheme:
            raise ValueError("Duplicate file identity or invalid source URI")
        if any(name.startswith(old + "/") or old.startswith(name + "/") for old in files):
            raise ValueError("File and directory paths conflict")
        observed = datetime.fromisoformat(item["observed_at"])
        if observed.tzinfo is None:
            raise ValueError("Observation time needs timezone")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Public text capture requires nonblank UTF-8 content")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest != item["sha256"]:
            raise ValueError("File bytes differ from frozen hash")
        identity = hashlib.sha256(uri.encode()).hexdigest()
        source_id = f"file-snapshot://{quote(project, safe='')}/{identity}/{digest}"
        session = "file-observation-" + hashlib.sha256(source_id.encode()).hexdigest()
        events.append({
            "schema_version": "host-agent-event-v1", "event_id": session,
            "event_type": "TOOL_RESULT", "session_id": session, "source_id": source_id,
            "subject_id": uri, "content": content, "observed_at": item["observed_at"],
            "turn_id": session + ":0", "turn_ordinal": 0,
            "round_id": session + ":0", "round_ordinal": 0,
        })
        files[name], refs[name] = content, [source_id]
        identities.add(uri)
    if not files:
        raise ValueError("File source package is empty")
    return files, events, refs
