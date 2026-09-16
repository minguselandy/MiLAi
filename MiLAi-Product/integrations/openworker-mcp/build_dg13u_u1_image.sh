#!/bin/sh
set -eu

base_id="sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d"
base_tag="milai-openworker-base:afa555cfccdb05c0-local-lock"
expected_platform="linux/amd64"
output_tag="milai-openworker:dg13u-u1-current-local"
relay_sha256="01ebb19a14928754522210ee1fbff17af1068cc1857d1fe68dca695e15d1ad7a"
config_sha256="9dbc6444740b65d4dc548f6d71aa4750fcb7614e22aa9fea2bf922d77339e81f"
plugin_sha256="0cc807fcb968a60b14c7147b2fd4bfe3847335270930237753924e090cd98309"
dockerfile_sha256="45f1c23cc678b4744e17bfebcaae7b492977b83933420739acaa2ee67cea0b57"

relay_path="src/milai_openworker_mcp/relay.py"
config_path="openworker/opencode.json"
plugin_path="openworker/milai-task-metadata.js"
dockerfile_path="openworker/Dockerfile"

fail() {
    printf '%s\n' "$1" >&2
    exit 70
}

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$script_dir"

case "$output_tag" in
    "milai-openworker:dg13u-u0-current-local"|"milai-openworker:dg10-candidate.1-local")
        fail "DG13U U1 output tag collides with a frozen historical tag"
        ;;
esac

observed_relay_sha256=$(sha256sum "$relay_path" | cut -d' ' -f1)
observed_config_sha256=$(sha256sum "$config_path" | cut -d' ' -f1)
observed_plugin_sha256=$(sha256sum "$plugin_path" | cut -d' ' -f1)
observed_dockerfile_sha256=$(sha256sum "$dockerfile_path" | cut -d' ' -f1)

[ "$observed_relay_sha256" = "$relay_sha256" ] \
    || fail "DG13U U1 relay source identity mismatch"
[ "$observed_config_sha256" = "$config_sha256" ] \
    || fail "DG13U U1 OpenCode config identity mismatch"
[ "$observed_plugin_sha256" = "$plugin_sha256" ] \
    || fail "DG13U U1 task metadata plugin identity mismatch"
[ "$observed_dockerfile_sha256" = "$dockerfile_sha256" ] \
    || fail "DG13U U1 Dockerfile identity mismatch"

observed_base_id=$(docker image inspect "$base_tag" --format '{{.Id}}')
observed_base_platform=$(docker image inspect "$base_tag" --format '{{.Os}}/{{.Architecture}}')
[ "$observed_base_id" = "$base_id" ] \
    || fail "DG13U U1 base image identity mismatch"
[ "$observed_base_platform" = "$expected_platform" ] \
    || fail "DG13U U1 base image platform mismatch"

docker build --pull=false --network none \
    --build-arg "OPENWORKER_BASE=$base_tag" \
    --label "io.milai.dg13u.phase=U1" \
    --label "io.milai.dg13u.goal=LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE" \
    --label "io.milai.dg13u.base-image-id=$base_id" \
    --label "io.milai.dg13u.platform=$expected_platform" \
    --label "io.milai.dg13u.source-relay-sha256=$relay_sha256" \
    --label "io.milai.dg13u.source-config-sha256=$config_sha256" \
    --label "io.milai.dg13u.source-task-metadata-plugin-sha256=$plugin_sha256" \
    --label "io.milai.dg13u.source-dockerfile-sha256=$dockerfile_sha256" \
    -f "$dockerfile_path" \
    -t "$output_tag" .

postbuild_base_id=$(docker image inspect "$base_tag" --format '{{.Id}}')
postbuild_base_platform=$(docker image inspect "$base_tag" --format '{{.Os}}/{{.Architecture}}')
[ "$postbuild_base_id" = "$base_id" ] \
    || fail "DG13U U1 base image identity changed during build"
[ "$postbuild_base_platform" = "$expected_platform" ] \
    || fail "DG13U U1 base image platform changed during build"
[ "$(sha256sum "$relay_path" | cut -d' ' -f1)" = "$relay_sha256" ] \
    || fail "DG13U U1 relay source changed during build"
[ "$(sha256sum "$config_path" | cut -d' ' -f1)" = "$config_sha256" ] \
    || fail "DG13U U1 OpenCode config changed during build"
[ "$(sha256sum "$plugin_path" | cut -d' ' -f1)" = "$plugin_sha256" ] \
    || fail "DG13U U1 task metadata plugin changed during build"
[ "$(sha256sum "$dockerfile_path" | cut -d' ' -f1)" = "$dockerfile_sha256" ] \
    || fail "DG13U U1 Dockerfile changed during build"

derived_id=$(docker image inspect "$output_tag" --format '{{.Id}}')
derived_platform=$(docker image inspect "$output_tag" --format '{{.Os}}/{{.Architecture}}')
[ -n "$derived_id" ] && [ "$derived_id" != "$base_id" ] \
    || fail "DG13U U1 derived image identity is invalid"
[ "$derived_platform" = "$expected_platform" ] \
    || fail "DG13U U1 derived image platform mismatch"

base_layers=$(docker image inspect "$base_id" --format '{{json .RootFS.Layers}}')
derived_layers=$(docker image inspect "$derived_id" --format '{{json .RootFS.Layers}}')
if ! python3 - "$base_layers" "$derived_layers" <<'PY'
import json
import sys

base = json.loads(sys.argv[1])
derived = json.loads(sys.argv[2])
if not isinstance(base, list) or not isinstance(derived, list):
    raise SystemExit(1)
if not base or derived[: len(base)] != base:
    raise SystemExit(1)
PY
then
    fail "DG13U U1 derived image does not preserve the locked base layer prefix"
fi

inspect_label() {
    docker image inspect "$derived_id" --format "{{index .Config.Labels \"$1\"}}"
}

[ "$(inspect_label io.milai.dg13u.phase)" = "U1" ] \
    || fail "DG13U U1 derived image label mismatch: phase"
[ "$(inspect_label io.milai.dg13u.goal)" = "LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE" ] \
    || fail "DG13U U1 derived image label mismatch: goal"
[ "$(inspect_label io.milai.dg13u.base-image-id)" = "$base_id" ] \
    || fail "DG13U U1 derived image label mismatch: base image"
[ "$(inspect_label io.milai.dg13u.platform)" = "$expected_platform" ] \
    || fail "DG13U U1 derived image label mismatch: platform"
[ "$(inspect_label io.milai.dg13u.source-relay-sha256)" = "$relay_sha256" ] \
    || fail "DG13U U1 derived image label mismatch: relay"
[ "$(inspect_label io.milai.dg13u.source-config-sha256)" = "$config_sha256" ] \
    || fail "DG13U U1 derived image label mismatch: config"
[ "$(inspect_label io.milai.dg13u.source-task-metadata-plugin-sha256)" = "$plugin_sha256" ] \
    || fail "DG13U U1 derived image label mismatch: task metadata plugin"
[ "$(inspect_label io.milai.dg13u.source-dockerfile-sha256)" = "$dockerfile_sha256" ] \
    || fail "DG13U U1 derived image label mismatch: Dockerfile"

if ! embedded_hashes=$(docker run --rm --network none --read-only \
    --label "io.milai.dg13u.owner=u1-image-verifier" \
    --entrypoint /bin/sh "$derived_id" -c \
    'sha256sum /usr/local/bin/milai-mcp-relay /openworker/image/config/opencode.json /openworker/image/plugins/milai-task-metadata.js')
then
    fail "DG13U U1 embedded file verification failed"
fi
embedded_relay_sha256=$(printf '%s\n' "$embedded_hashes" | awk '$2 == "/usr/local/bin/milai-mcp-relay" {print $1}')
embedded_config_sha256=$(printf '%s\n' "$embedded_hashes" | awk '$2 == "/openworker/image/config/opencode.json" {print $1}')
embedded_plugin_sha256=$(printf '%s\n' "$embedded_hashes" | awk '$2 == "/openworker/image/plugins/milai-task-metadata.js" {print $1}')

[ "$embedded_relay_sha256" = "$relay_sha256" ] \
    || fail "DG13U U1 embedded relay identity mismatch"
[ "$embedded_config_sha256" = "$config_sha256" ] \
    || fail "DG13U U1 embedded OpenCode config identity mismatch"
[ "$embedded_plugin_sha256" = "$plugin_sha256" ] \
    || fail "DG13U U1 embedded task metadata plugin identity mismatch"

relay_exec_output=""
if relay_exec_output=$(docker run --rm --network none --read-only \
    --label "io.milai.dg13u.owner=u1-image-exec-verifier" \
    --entrypoint /usr/local/bin/milai-mcp-relay "$derived_id" 2>&1)
then
    relay_exec_status=0
else
    relay_exec_status=$?
fi
[ "$relay_exec_status" -eq 64 ] \
    || fail "DG13U U1 embedded relay direct execution failed"
[ "$relay_exec_output" = '{"component":"milai-mcp-relay","reason":"ARGUMENTS_REJECTED","status":"FAIL"}' ] \
    || fail "DG13U U1 embedded relay execution diagnostic mismatch"

printf '{"base_image_id":"%s","derived_image_id":"%s","image":"%s","platform":"%s","source_config_sha256":"%s","source_dockerfile_sha256":"%s","source_plugin_sha256":"%s","source_relay_sha256":"%s","verification_container":"EPHEMERAL_AUTO_REMOVED"}\n' \
    "$base_id" "$derived_id" "$output_tag" "$derived_platform" "$config_sha256" \
    "$dockerfile_sha256" "$plugin_sha256" "$relay_sha256"
