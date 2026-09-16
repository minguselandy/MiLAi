#!/bin/sh
set -eu

name="milai"
url="${MILAI_MCP_URL:-}"
token_file=""
replace=0
allow_insecure_http=0

usage() {
    cat <<'EOF'
Usage: ./install.sh --url URL --token-file PATH [options]

Options:
  --url URL                 deployment-specific MCP URL ending in /mcp
  --name NAME               Codex MCP registration name (default: milai)
  --token-file PATH         separately transferred inbound Bearer token
  --allow-insecure-http     acknowledge plaintext HTTP token exposure
  --replace                 replace a different existing registration
  -h, --help                show this help
EOF
}

fail() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --url)
            [ "$#" -ge 2 ] || fail "--url requires a value"
            url="$2"
            shift 2
            ;;
        --name)
            [ "$#" -ge 2 ] || fail "--name requires a value"
            name="$2"
            shift 2
            ;;
        --token-file)
            [ "$#" -ge 2 ] || fail "--token-file requires a value"
            token_file="$2"
            shift 2
            ;;
        --allow-insecure-http)
            allow_insecure_http=1
            shift
            ;;
        --replace)
            replace=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *) fail "unknown argument: $1" ;;
    esac
done

command -v codex >/dev/null 2>&1 || fail "Codex CLI is not installed or not on PATH"
command -v python3 >/dev/null 2>&1 || fail "Python 3 is required for MCP verification"
[ -n "${HOME:-}" ] || fail "HOME is not set"
[ -n "$name" ] || fail "registration name cannot be empty"
[ -n "$url" ] || fail "provide --url or export MILAI_MCP_URL"

codex_home="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$codex_home"
chmod 700 "$codex_home"

case "$url" in
    http://*)
        [ "$allow_insecure_http" -eq 1 ] || fail \
            "plain HTTP requires --allow-insecure-http; prefer HTTPS or a trusted tunnel"
        ;;
    https://*) ;;
    *) fail "MCP URL must use http:// or https:// (WebSocket is not supported)" ;;
esac
case "$url" in
    */mcp) ;;
    *) fail "MCP URL must end with /mcp" ;;
esac

if [ -n "$token_file" ]; then
    [ -r "$token_file" ] || fail "token file is not readable: $token_file"
    token=$(tr -d '\r\n' < "$token_file")
elif [ -n "${MILAI_CODEX_TOKEN:-}" ]; then
    token="$MILAI_CODEX_TOKEN"
else
    fail "provide --token-file or export MILAI_CODEX_TOKEN"
fi
[ "${#token}" -ge 32 ] || fail "Bearer token must contain at least 32 characters"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MILAI_CODEX_TOKEN="$token" python3 "$script_dir/verify_mcp.py" --url "$url"

existing=$(codex mcp get "$name" 2>/dev/null || true)
if [ -n "$existing" ]; then
    if printf '%s\n' "$existing" | grep -F "url: $url" >/dev/null; then
        already_registered=1
    elif [ "$replace" -eq 1 ]; then
        codex mcp remove "$name"
        already_registered=0
    else
        fail "registration '$name' already exists with different settings; use --replace"
    fi
else
    already_registered=0
fi

config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/milai"
mkdir -p "$config_dir"
chmod 700 "$config_dir"

if [ "$already_registered" -eq 0 ]; then
    codex mcp add "$name" \
        --url "$url" \
        --bearer-token-env-var MILAI_CODEX_TOKEN
fi

set -- \
    --codex-config "$codex_home/config.toml" \
    --generic-config "$config_dir/mcpServers.json" \
    --name "$name" \
    --url "$url"
if [ "$replace" -eq 1 ]; then
    set -- "$@" --replace
fi
MILAI_CODEX_TOKEN="$token" python3 "$script_dir/configure_clients.py" "$@"

printf '%s\n' "MiLAi MCP registration ready: $name -> $url"
if [ -n "$token_file" ]; then
    printf '%s\n' "Export MILAI_CODEX_TOKEN from the same private token file, then run Codex."
else
    printf '%s\n' "Keep the current MILAI_CODEX_TOKEN exported when starting Codex."
fi
