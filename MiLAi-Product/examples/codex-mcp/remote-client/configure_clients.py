from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MANAGED_KEYS = {
    "bearer_token_env_var",
    "env_http_headers",
    "http_headers",
    "http_headers_helper",
}


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def configure_codex(path: Path, *, name: str, bearer_token_env_var: str) -> None:
    section = f"[mcp_servers.{name}]"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.strip() == section]
    if len(starts) != 1:
        raise RuntimeError(f"expected exactly one Codex section {section}")
    start = starts[0]
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].lstrip().startswith("[")
        ),
        len(lines),
    )
    block = lines[start:end]
    filtered = [
        line
        for line in block
        if line.split("=", 1)[0].strip() not in MANAGED_KEYS
    ]
    url_positions = [
        index
        for index, line in enumerate(filtered)
        if line.split("=", 1)[0].strip() == "url"
    ]
    if len(url_positions) != 1:
        raise RuntimeError(f"Codex section {section} must contain exactly one URL")
    header_line = f"bearer_token_env_var = {toml_string(bearer_token_env_var)}\n"
    filtered.insert(url_positions[0] + 1, header_line)
    updated = "".join([*lines[:start], *filtered, *lines[end:]])
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(updated)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def configure_generic(
    path: Path,
    *,
    name: str,
    url: str,
    token: str,
    replace: bool,
) -> None:
    payload: dict[str, object]
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise RuntimeError("generic MCP config root must be a JSON object")
        payload = loaded
    else:
        payload = {}
    raw_servers = payload.get("mcpServers")
    if raw_servers is None:
        servers: dict[str, object] = {}
        payload["mcpServers"] = servers
    elif isinstance(raw_servers, dict):
        servers = raw_servers
    else:
        raise RuntimeError("generic MCP config mcpServers must be a JSON object")
    if name in servers and not replace:
        existing = servers[name]
        if not isinstance(existing, dict) or existing.get("url") != url:
            raise RuntimeError(
                f"generic MCP registration {name!r} already exists; use --replace"
            )
    servers[name] = {
        "type": "http",
        "url": url,
        "headers": {
            "Authorization": f"Bearer {token}",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install direct MiLAi MCP headers")
    parser.add_argument("--codex-config", type=Path, required=True)
    parser.add_argument("--generic-config", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("MILAI_CODEX_TOKEN", "")
    if len(token) < 32 or "\n" in token or "\r" in token:
        parser.error("MILAI_CODEX_TOKEN must be one line with at least 32 characters")
    if not NAME_PATTERN.fullmatch(args.name):
        parser.error("--name must use 1-64 letters, digits, underscores or hyphens")
    parsed = urlsplit(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path != "/mcp":
        parser.error("--url must be an absolute HTTP(S) URL whose path is /mcp")
    configure_codex(
        args.codex_config,
        name=args.name,
        bearer_token_env_var="MILAI_CODEX_TOKEN",
    )
    configure_generic(
        args.generic_config,
        name=args.name,
        url=args.url,
        token=token,
        replace=args.replace,
    )
    print(f"Codex static headers configured for {args.name}")
    print(f"Generic mcpServers JSON written to {args.generic_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
