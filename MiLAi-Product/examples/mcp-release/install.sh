#!/bin/sh
set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    printf '%s\n' 'Usage: sh install.sh /absolute/path/to/new-venv [mcp|runtime]' >&2
    exit 2
fi
case "$1" in
    /*) ;;
    *) printf '%s\n' 'Provide an absolute path to a new virtual environment.' >&2; exit 2 ;;
esac
[ ! -e "$1" ] || { printf '%s\n' 'Destination already exists; use a new directory.' >&2; exit 2; }
command -v uv >/dev/null 2>&1
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
(cd "$root" && sha256sum -c SHA256SUMS)
case "${2:-mcp}" in
    mcp) package_root="$root"; entrypoint=milai-codex-full-mcp ;;
    runtime) package_root="$root/runtime"; entrypoint=milai-api ;;
    *) printf '%s\n' 'Unknown component; choose mcp or runtime.' >&2; exit 2 ;;
esac
uv venv --python "${MILAI_INSTALL_PYTHON:-3.11}" "$1"
uv pip install --python "$1/bin/python" --require-hashes -r "$package_root/requirements.lock"
if [ "${2:-mcp}" = runtime ] && [ "${MILAI_INSTALL_EMBEDDING:-0}" = 1 ]; then
    uv pip install --python "$1/bin/python" --require-hashes \
        -r "$package_root/requirements-embedding.lock"
fi
uv pip install --python "$1/bin/python" --no-deps "$package_root"/packages/*.whl
uv pip check --python "$1/bin/python"
if [ "$entrypoint" = milai-codex-full-mcp ]; then
    "$1/bin/$entrypoint" --help >/dev/null
else
    "$1/bin/python" -I -c 'import milai.api'
fi
printf 'Installed MiLA %s in %s; no service or database was changed.\n' "${2:-mcp}" "$1"
