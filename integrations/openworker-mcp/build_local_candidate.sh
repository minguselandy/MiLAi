#!/bin/sh
set -eu

base_source="openworker-v2:2026.5.9.1"
base_id="sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d"
base_lock_tag="milai-openworker-base:afa555cfccdb05c0-local-lock"
output_tag="milai-openworker:dg10-candidate.1-local"

observed_id=$(docker image inspect "$base_source" --format '{{.Id}}')
observed_platform=$(docker image inspect "$base_source" --format '{{.Os}}/{{.Architecture}}')
if [ "$observed_id" != "$base_id" ] || [ "$observed_platform" != "linux/amd64" ]; then
    echo "base image identity or platform mismatch" >&2
    exit 70
fi

docker image tag "$base_id" "$base_lock_tag"
if [ "$(docker image inspect "$base_lock_tag" --format '{{.Id}}')" != "$base_id" ]; then
    echo "local base lock tag mismatch" >&2
    exit 70
fi

docker build --pull=false --network none \
    --build-arg "OPENWORKER_BASE=$base_lock_tag" \
    -f openworker/Dockerfile \
    -t "$output_tag" .

if [ "$(docker image inspect "$base_source" --format '{{.Id}}')" != "$base_id" ]; then
    echo "source base tag changed during build" >&2
    exit 70
fi
if [ "$(docker image inspect "$base_lock_tag" --format '{{.Id}}')" != "$base_id" ]; then
    echo "local base lock tag changed during build" >&2
    exit 70
fi

python3 - "$base_id" "$output_tag" <<'PY'
import json
import subprocess
import sys

base_id, output_tag = sys.argv[1:]


def inspect(target: str) -> dict[str, object]:
    completed = subprocess.run(
        ["docker", "image", "inspect", target],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise SystemExit("unexpected docker image inspect response")
    return value[0]


base = inspect(base_id)
derived = inspect(output_tag)
base_layers = base["RootFS"]["Layers"]
derived_layers = derived["RootFS"]["Layers"]
if derived_layers[: len(base_layers)] != base_layers:
    raise SystemExit("derived image does not preserve the locked base layer prefix")
if derived.get("Os") != "linux" or derived.get("Architecture") != "amd64":
    raise SystemExit("derived image platform drift")
labels = derived["Config"].get("Labels") or {}
if labels.get("io.milai.dg10.base-image-id") != base_id:
    raise SystemExit("derived image base label drift")
print(json.dumps({
    "base_image_id": base_id,
    "base_layer_count": len(base_layers),
    "derived_image_id": derived["Id"],
    "derived_layer_count": len(derived_layers),
    "platform": "linux/amd64",
}, sort_keys=True))
PY
