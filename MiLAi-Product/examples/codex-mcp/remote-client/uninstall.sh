#!/bin/sh
set -eu

name="milai"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --name)
            [ "$#" -ge 2 ] || { printf '%s\n' "--name requires a value" >&2; exit 1; }
            name="$2"
            shift 2
            ;;
        -h|--help)
            printf '%s\n' "Usage: ./uninstall.sh [--name NAME]"
            exit 0
            ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
    esac
done

if command -v codex >/dev/null 2>&1 && codex mcp get "$name" >/dev/null 2>&1; then
    codex mcp remove "$name"
fi

generic_config="${XDG_CONFIG_HOME:-$HOME/.config}/milai/mcpServers.json"
if [ -f "$generic_config" ]; then
    rm -f "$generic_config"
fi

printf '%s\n' "MiLAi MCP registration removed"
