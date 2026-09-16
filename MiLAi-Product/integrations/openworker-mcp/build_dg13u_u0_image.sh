#!/bin/sh
set -eu

base_id="sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d"
base_tag="milai-openworker-base:afa555cfccdb05c0-local-lock"
output_tag="milai-openworker:dg13u-u0-current-local"
relay_sha256="d7d1044b0d3c7679c5fadaf298882f0088122b45926a4f39c63f2f4861b8a148"
config_sha256="9f5789ab13e20c5f26eb926fae5540aa9a42f25f1c6401d20a8a21325c19f46e"

observed_base_id=$(docker image inspect "$base_tag" --format '{{.Id}}')
observed_platform=$(docker image inspect "$base_tag" --format '{{.Os}}/{{.Architecture}}')
observed_relay_sha256=$(sha256sum src/milai_openworker_mcp/relay.py | cut -d' ' -f1)
observed_config_sha256=$(sha256sum openworker/opencode.json | cut -d' ' -f1)

if [ "$observed_base_id" != "$base_id" ] || [ "$observed_platform" != "linux/amd64" ]; then
    echo "DG13U base image identity or platform mismatch" >&2
    exit 70
fi
if [ "$observed_relay_sha256" != "$relay_sha256" ]; then
    echo "DG13U relay source identity mismatch" >&2
    exit 70
fi
if [ "$observed_config_sha256" != "$config_sha256" ]; then
    echo "DG13U OpenWorker config identity mismatch" >&2
    exit 70
fi

docker build --pull=false --network none \
    --build-arg "OPENWORKER_BASE=$base_tag" \
    --label "io.milai.dg13u.phase=U0" \
    --label "io.milai.dg13u.source-relay-sha256=$relay_sha256" \
    --label "io.milai.dg13u.source-config-sha256=$config_sha256" \
    -f openworker/Dockerfile \
    -t "$output_tag" .

derived_id=$(docker image inspect "$output_tag" --format '{{.Id}}')
derived_platform=$(docker image inspect "$output_tag" --format '{{.Os}}/{{.Architecture}}')
derived_relay_label=$(docker image inspect "$output_tag" --format '{{index .Config.Labels "io.milai.dg13u.source-relay-sha256"}}')
derived_config_label=$(docker image inspect "$output_tag" --format '{{index .Config.Labels "io.milai.dg13u.source-config-sha256"}}')

if [ "$derived_platform" != "linux/amd64" ]; then
    echo "DG13U derived image platform mismatch" >&2
    exit 70
fi
if [ "$derived_relay_label" != "$relay_sha256" ] || [ "$derived_config_label" != "$config_sha256" ]; then
    echo "DG13U derived image source labels mismatch" >&2
    exit 70
fi

printf '{"base_image_id":"%s","derived_image_id":"%s","image":"%s","platform":"%s"}\n' \
    "$base_id" "$derived_id" "$output_tag" "$derived_platform"
