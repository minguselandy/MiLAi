#!/bin/sh
# Standalone Product packaging. No Lab, credentials, runtime data or model calls.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output="${1:-$root/integrations/mcp/dist/delivery}"
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$root/integrations/mcp/src/milai_mcp/__init__.py")
[ -n "$version" ]
name="milai-mcp-delivery-$version"
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
stage="$temporary/$name"
mkdir -p "$stage/packages" "$stage/runtime/packages" "$stage/docs/runbooks" "$stage/contracts/mcp" \
    "$stage/docs/releases" "$stage/docs/adr" "$stage/docs/goals" "$stage/examples/codex-mcp"
(cd "$root/integrations/python-client" && uv lock --check && uv build --out-dir "$stage/packages")
(cd "$root/integrations/mcp" && uv lock --check && uv build --out-dir "$stage/packages")
(cd "$root/runtime" && uv lock --check && uv build --out-dir "$stage/runtime/packages")
(cd "$root/integrations/mcp" && uv export --frozen --no-dev --no-editable --no-emit-project \
    --no-emit-package milai-client --format requirements-txt --output-file "$stage/requirements.lock" >/dev/null)
(cd "$root/runtime" && uv export --frozen --no-dev --no-editable --no-emit-project \
    --format requirements-txt --output-file "$stage/runtime/requirements.lock" >/dev/null)
(cd "$root/runtime" && uv export --frozen --extra embedding --no-dev --no-editable \
    --no-emit-project --format requirements-txt \
    --output-file "$stage/runtime/requirements-embedding.lock" >/dev/null)
install -m 0644 "$root/examples/mcp-release/README.md" "$stage/README.md"
install -m 0755 "$root/examples/mcp-release/install.sh" "$stage/install.sh"
for file in aigcit-http-mcp.md private-working-memory.md mcp-contract-repair-v07.md \
    mcp-contract-repair-v08.md memory-retrieval.md mcp-host-descriptions.md compact-memory.md; do
    install -m 0644 "$root/docs/runbooks/$file" "$stage/docs/runbooks/$file"
done
install -m 0644 "$root/docs/releases/MCP_${version}_HANDOFF_20260908.md" "$stage/docs/releases/"
if [ "$version" != 0.1.10 ]; then
    install -m 0644 "$root/docs/releases/MCP_0.1.10_HANDOFF_20260908.md" "$stage/docs/releases/"
fi
install -m 0644 "$root/docs/goals/MILA_V02_08_EXECUTION_20260908.md" "$stage/docs/goals/"
install -m 0644 "$root/docs/goals/MILA_V02_09_MCP工具精简与统一记忆入口_GOAL_20260908.md" "$stage/docs/goals/"
install -m 0644 "$root/docs/adr/ADR-050-full-private-mcp-capabilities.md" "$stage/docs/adr/"
install -m 0644 "$root/docs/adr/ADR-051-host-notes-and-mcp-contract-repair.md" "$stage/docs/adr/"
install -m 0644 "$root/docs/adr/ADR-052-bounded-cross-type-memory-discovery.md" "$stage/docs/adr/"
install -m 0644 "$root/docs/adr/ADR-053-ordinary-mcp-advisory-and-admin-boundary.md" "$stage/docs/adr/"
install -m 0644 "$root/docs/adr/ADR-054-compact-memory-tool-catalog.md" "$stage/docs/adr/"
install -m 0644 "$root/contracts/mcp/ordinary-memory-v1.md" "$stage/contracts/mcp/"
install -m 0644 "$root/contracts/mcp/compact-memory-v1.md" "$stage/contracts/mcp/"
for file in "$root"/contracts/mcp/*.json; do
    install -m 0644 "$file" "$stage/contracts/mcp/"
done
for file in milai-aigcit-client.toml.example milai-private-workflow.toml.example \
    milai-aigcit.env.example milai-aigcit.service.example milai-aigcit-7960.nginx.conf.example; do
    install -m 0644 "$root/examples/codex-mcp/$file" "$stage/examples/codex-mcp/$file"
done
printf '%s\n' "$version" > "$stage/VERSION"
cp "$root/integrations/mcp/uv.lock" "$stage/mcp.uv.lock"
cp "$root/integrations/python-client/uv.lock" "$stage/client.uv.lock"
cp "$root/runtime/uv.lock" "$stage/runtime/uv.lock"
(cd "$stage" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
    -C "$temporary" -cf - "$name" | gzip -n > "$output/$name.tar.gz"
(cd "$output" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")
printf '%s\n' "$output/$name.tar.gz"
