"""Fetch only the pinned official artifacts used by the memory-control release."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import tarfile
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import quote

HISTORY_PATH = re.compile(r"data/chat_history_32k/[^/\\]+\.json")


def csv_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        required = {
            "persona_id",
            "chat_history_32k_link",
            "user_query",
            "related_conversation_snippet",
            "updated",
        }
        if reader.fieldnames is None or not required <= set(reader.fieldnames):
            raise ValueError(f"Unexpected PersonaMem header in {path.name}")
        for row in reader:
            if None in row or None in row.values():
                raise ValueError(f"Incomplete PersonaMem CSV row at line {reader.line_num}")
            yield row


def history_file(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("metadata"), dict)
        or not isinstance(data.get("chat_history"), list)
    ):
        raise ValueError(f"{path.name} lacks the metadata/chat_history wrapper")
    return data


def archive_members(path: Path, config: dict[str, Any]) -> dict[str, int]:
    expected = set(config["members"].values())
    if path.name.removesuffix(".part").endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            actual = {i.filename: i.file_size for i in archive.infolist()}
    else:
        with tarfile.open(path) as archive:
            actual = {i.name: i.size for i in archive if i.isfile()}
    if not expected <= actual.keys() or not all(actual[name] for name in expected):
        raise ValueError(f"{path.name} is missing expected nonempty train/validation members")
    return {name: actual[name] for name in sorted(expected)}


def download(url: str, path: Path, inspect: Any) -> tuple[int, Any]:
    """Publish a file only after inspection. Completed files are reused by later runs."""
    if path.is_file():
        return path.stat().st_size, inspect(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    # Public, pinned HTTPS routes only. Curl handles redirects and transient failures.
    subprocess.run(  # noqa: S603
        [
            "/usr/bin/curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--retry",
            "2",
            "--connect-timeout",
            "20",
            "--max-time",
            "900",
            "--output",
            str(part),
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = inspect(part)
    size = part.stat().st_size
    part.replace(path)
    return size, result


def reference(path: str) -> str:
    if not HISTORY_PATH.fullmatch(path):
        raise ValueError(f"Invalid 32k history reference {path!r}")
    return path


def acquire(raw: Path, sources: dict[str, Any], workers: int = 12) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    references: dict[str, set[str]] = {}
    csv_counts: dict[str, dict[str, int]] = {}

    def fetch(source: str, name: str, url: str, inspect: Any) -> dict[str, Any]:
        try:
            size, result = download(url, raw / source / name, inspect)
        except (
            OSError,
            ValueError,
            tarfile.TarError,
            zipfile.BadZipFile,
            subprocess.CalledProcessError,
        ) as exc:
            return {
                "source": source,
                "path": name,
                "url": url,
                "parsed": False,
                "error": getattr(exc, "stderr", "").strip() or str(exc),
            }
        return {"source": source, "path": name, "url": url, "bytes": size, "parsed": True, **result}

    def collect(receipt: dict[str, Any]) -> None:
        files.append(receipt)
        if not receipt["parsed"]:
            errors.append({key: receipt[key] for key in ("source", "path", "error")})

    for source, cfg in sources.items():
        if "archive" not in cfg:
            continue

        def inspect_archive(path: Path, cfg: dict[str, Any] = cfg) -> dict[str, Any]:
            return {
                "members": archive_members(path, cfg),
                "declared_bytes": cfg["declared_archive_bytes"],
            }

        collect(fetch(source, cfg["archive"], cfg["url"], inspect_archive))

    source = "personamem_v2"
    cfg = sources[source]
    base = cfg["base"] + "/" + cfg["revision"]
    for split, name in cfg["members"].items():
        split_references: dict[str, set[str]] = {}

        def inspect_csv(
            path: Path, split_references: dict[str, set[str]] = split_references
        ) -> dict[str, Any]:
            split_references.clear()
            rows = 0
            for row in csv_rows(path):
                rows += 1
                link = reference(row["chat_history_32k_link"])
                split_references.setdefault(link, set()).add(row["persona_id"])
            return {"rows": rows, "history_references": len(split_references)}

        receipt = fetch(source, name, f"{base}/{name}", inspect_csv)
        collect(receipt)
        if receipt["parsed"]:
            csv_counts[split] = {k: receipt[k] for k in ("rows", "history_references")}
            for link, ids in split_references.items():
                references.setdefault(link, set()).update(ids)

    def fetch_history(name: str) -> dict[str, Any]:
        def inspect_history(path: Path) -> dict[str, Any]:
            data = history_file(path)
            return {
                "persona_id": str(data["metadata"].get("persona_id")),
                "raw_message_count": len(data["chat_history"]),
                "referencing_personas": sorted(references[name]),
            }

        return fetch(source, name, f"{base}/{quote(name)}", inspect_history)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for i, receipt in enumerate(executor.map(fetch_history, sorted(references)), 1):
            collect(receipt)
            if i % 100 == 0:
                print(f"PersonaMem history files inspected: {i}/{len(references)}", flush=True)
    return {
        "files": files,
        "errors": errors,
        "persona_splits": csv_counts,
        "distinct_history_references": len(references),
    }
