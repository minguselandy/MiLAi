from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations/openworker-mcp"
BUILD_SCRIPT = INTEGRATION / "build_dg13u_u1_image.sh"

BASE_ID = "sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d"
OUTPUT_TAG = "milai-openworker:dg13u-u1-current-local"
SOURCE_PATHS = {
    "relay_sha256": INTEGRATION / "src/milai_openworker_mcp/relay.py",
    "config_sha256": INTEGRATION / "openworker/opencode.json",
    "plugin_sha256": INTEGRATION / "openworker/milai-task-metadata.js",
    "dockerfile_sha256": INTEGRATION / "openworker/Dockerfile",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assignments(source: str) -> dict[str, str]:
    return dict(re.findall(r'^([a-z0-9_]+)="([^"\n]+)"$', source, re.MULTILINE))


def test_relay_source_is_direct_exec_compatible() -> None:
    relay = SOURCE_PATHS["relay_sha256"].read_bytes()

    assert relay.startswith(b"#!/usr/bin/python3\n")
    assert b"\r\n" not in relay.splitlines(keepends=True)[0]


def _install_fake_docker(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    executable = fake_bin / "docker"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
import re
import sys

args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as sink:
    sink.write(json.dumps(args, separators=(",", ":")) + "\\n")

base_tag = "milai-openworker-base:afa555cfccdb05c0-local-lock"
output_tag = "milai-openworker:dg13u-u1-current-local"
base_id = os.environ["EXPECTED_BASE_ID"]
source_labels = {
    "io.milai.dg13u.phase": "BROKEN" if os.environ.get("WRONG_PHASE") else "U1",
    "io.milai.dg13u.goal": "LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE",
    "io.milai.dg13u.base-image-id": base_id,
    "io.milai.dg13u.platform": "linux/amd64",
    "io.milai.dg13u.source-relay-sha256": os.environ["EXPECTED_RELAY_SHA256"],
    "io.milai.dg13u.source-config-sha256": os.environ["EXPECTED_CONFIG_SHA256"],
    "io.milai.dg13u.source-task-metadata-plugin-sha256": os.environ["EXPECTED_PLUGIN_SHA256"],
    "io.milai.dg13u.source-dockerfile-sha256": os.environ["EXPECTED_DOCKERFILE_SHA256"],
}

if args[:2] == ["image", "inspect"]:
    target = args[2]
    template = args[args.index("--format") + 1]
    if template == "{{.Id}}":
        print(base_id if target == base_tag else "sha256:dg13u-u1-derived")
    elif template == "{{.Os}}/{{.Architecture}}":
        print("linux/amd64")
    elif template == "{{json .RootFS.Layers}}":
        print('["sha256:base-layer"]' if target == base_id else '["sha256:base-layer","sha256:u1-layer"]')
    else:
        match = re.search(r'Labels \"([^\"]+)\"', template)
        if match is None:
            raise SystemExit(f"unsupported inspect template: {template}")
        print(source_labels.get(match.group(1), ""))
elif args and args[0] == "build":
    pass
elif args and args[0] == "run":
    if "/usr/local/bin/milai-mcp-relay" in args:
        print(
            '{"component":"milai-mcp-relay","reason":"ARGUMENTS_REJECTED","status":"FAIL"}',
            file=sys.stderr,
        )
        raise SystemExit(64)
    else:
        print(os.environ["EXPECTED_RELAY_SHA256"] + "  /usr/local/bin/milai-mcp-relay")
        print(os.environ["EXPECTED_CONFIG_SHA256"] + "  /openworker/image/config/opencode.json")
        print(os.environ["EXPECTED_PLUGIN_SHA256"] + "  /openworker/image/plugins/milai-task-metadata.js")
else:
    raise SystemExit(f"unexpected docker command: {args}")
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return fake_bin


def _fake_environment(
    tmp_path: Path, *, wrong_phase_label: bool = False
) -> dict[str, str]:
    fake_bin = _install_fake_docker(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.jsonl"),
            "EXPECTED_BASE_ID": BASE_ID,
            "EXPECTED_RELAY_SHA256": _sha256(SOURCE_PATHS["relay_sha256"]),
            "EXPECTED_CONFIG_SHA256": _sha256(SOURCE_PATHS["config_sha256"]),
            "EXPECTED_PLUGIN_SHA256": _sha256(SOURCE_PATHS["plugin_sha256"]),
            "EXPECTED_DOCKERFILE_SHA256": _sha256(SOURCE_PATHS["dockerfile_sha256"]),
        }
    )
    if wrong_phase_label:
        env["WRONG_PHASE"] = "1"
    else:
        env.pop("WRONG_PHASE", None)
    return env


def test_u1_build_entrypoint_pins_exact_current_sources_and_unique_tag() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assigned = _assignments(source)

    assert assigned["base_id"] == BASE_ID
    assert assigned["expected_platform"] == "linux/amd64"
    assert assigned["output_tag"] == OUTPUT_TAG
    assert assigned["output_tag"] not in {
        "milai-openworker:dg13u-u0-current-local",
        "milai-openworker:dg10-candidate.1-local",
    }
    for variable, path in SOURCE_PATHS.items():
        assert assigned[variable] == _sha256(path)
    assert "docker build --pull=false --network none" in source
    assert "io.milai.dg13u.phase=U1" in source
    assert "io.milai.dg13u.goal=LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE" in source
    assert "io.milai.dg13u.base-image-id=$base_id" in source
    assert "io.milai.dg13u.platform=$expected_platform" in source
    assert "io.milai.dg13u.source-relay-sha256=$relay_sha256" in source
    assert "io.milai.dg13u.source-config-sha256=$config_sha256" in source
    assert "io.milai.dg13u.source-task-metadata-plugin-sha256=$plugin_sha256" in source
    assert "io.milai.dg13u.source-dockerfile-sha256=$dockerfile_sha256" in source


def test_u1_build_verifies_labels_platform_layers_and_embedded_files(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [str(BUILD_SCRIPT)],
        cwd=INTEGRATION,
        env=_fake_environment(tmp_path),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt == {
        "base_image_id": BASE_ID,
        "derived_image_id": "sha256:dg13u-u1-derived",
        "image": OUTPUT_TAG,
        "platform": "linux/amd64",
        "source_config_sha256": _sha256(SOURCE_PATHS["config_sha256"]),
        "source_dockerfile_sha256": _sha256(SOURCE_PATHS["dockerfile_sha256"]),
        "source_plugin_sha256": _sha256(SOURCE_PATHS["plugin_sha256"]),
        "source_relay_sha256": _sha256(SOURCE_PATHS["relay_sha256"]),
        "verification_container": "EPHEMERAL_AUTO_REMOVED",
    }
    commands = [
        json.loads(line)
        for line in (tmp_path / "docker.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    build = next(command for command in commands if command[0] == "build")
    assert build[:4] == ["build", "--pull=false", "--network", "none"]
    assert ["-t", OUTPUT_TAG] == build[build.index("-t") : build.index("-t") + 2]
    verification = next(command for command in commands if command[0] == "run")
    assert verification[1:7] == [
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--label",
        "io.milai.dg13u.owner=u1-image-verifier",
    ]
    assert all(
        command[0] not in {"stop", "restart", "kill", "rm", "rmi", "tag"}
        for command in commands
    )
    assert all(command[:2] != ["image", "rm"] for command in commands)
    exec_verification = next(
        command
        for command in commands
        if command[0] == "run" and "/usr/local/bin/milai-mcp-relay" in command
    )
    assert exec_verification[1:7] == [
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--label",
        "io.milai.dg13u.owner=u1-image-exec-verifier",
    ]


def test_source_drift_fails_before_any_docker_mutation(tmp_path: Path) -> None:
    isolated = tmp_path / "openworker-mcp"
    shutil.copytree(INTEGRATION, isolated)
    (isolated / "src/milai_openworker_mcp/relay.py").write_text(
        "# synthetic drift\n", encoding="utf-8"
    )
    log = tmp_path / "docker.jsonl"
    env = _fake_environment(tmp_path / "fake")
    env["FAKE_DOCKER_LOG"] = str(log)

    completed = subprocess.run(
        [str(isolated / "build_dg13u_u1_image.sh")],
        cwd=isolated,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 70
    assert "relay source identity mismatch" in completed.stderr
    assert not log.exists()


def test_post_build_label_drift_fails_closed_without_image_deletion(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [str(BUILD_SCRIPT)],
        cwd=INTEGRATION,
        env=_fake_environment(tmp_path, wrong_phase_label=True),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 70
    assert "derived image label mismatch" in completed.stderr
    commands = [
        json.loads(line)
        for line in (tmp_path / "docker.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(command[0] not in {"rmi", "rm"} for command in commands)
    assert all(command[:2] != ["image", "rm"] for command in commands)
