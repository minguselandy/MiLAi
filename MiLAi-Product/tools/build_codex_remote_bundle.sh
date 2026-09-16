#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir="$root/examples/codex-mcp/remote-client"
output_dir="${1:-$root/integrations/mcp/dist/remote-client}"
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' \
    "$root/integrations/mcp/src/milai_mcp/__init__.py")
[ -n "$version" ] || {
    printf '%s\n' "cannot determine milai-mcp version" >&2
    exit 1
}
package="milai-codex-remote-client-$version"
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM

mkdir -p "$temporary/$package" "$output_dir"
for file in README.md config.toml.example mcpServers.json.example configure_clients.py install.sh uninstall.sh verify_mcp.py; do
    install -m 0644 "$source_dir/$file" "$temporary/$package/$file"
done
printf '%s\n' "$version" > "$temporary/$package/VERSION"
chmod 0755 \
    "$temporary/$package/install.sh" \
    "$temporary/$package/uninstall.sh" \
    "$temporary/$package/verify_mcp.py"

(
    cd "$temporary/$package"
    find . -type f ! -name MANIFEST.sha256 -print0 \
        | sort -z \
        | xargs -0 sha256sum > MANIFEST.sha256
)

archive="$output_dir/$package.tar.gz"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
    -C "$temporary" -cf - "$package" | gzip -n > "$archive"
(
    cd "$output_dir"
    sha256sum "$package.tar.gz" > "$package.tar.gz.sha256"
)
printf '%s\n' "$archive"
