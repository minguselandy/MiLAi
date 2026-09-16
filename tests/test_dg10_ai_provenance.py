from __future__ import annotations

import base64
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import dg10_ai_provenance as provenance
from scripts import dg10_remediation as remediation


def test_active_policy_freezes_distinct_workspace_and_authority_identities() -> None:
    policy = provenance.load_authority_policy()
    runner = Path(policy["authority_runner_path"])

    assert policy["workspace_author_uid"] != policy["authority_uid"]
    assert policy["workspace_author_gid"] != policy["authority_gid"]
    assert runner.stat().st_uid == 0
    assert runner.stat().st_gid == 0
    assert stat.S_IMODE(runner.stat().st_mode) & 0o022 == 0
    assert remediation.sha256_file(runner) == policy["authority_runner_sha256"]
    assert policy["codex_executable_mode"] == "0555"
    assert policy["codex_executable_uid"] == 0
    assert policy["codex_executable_gid"] == 0
    assert policy["codex_code_mode_host_mode"] == "0555"
    assert policy["codex_code_mode_host_uid"] == 0
    assert policy["codex_code_mode_host_gid"] == 0
    assert policy["codex_model_catalog_mode"] == "0444"
    assert policy["codex_model_catalog_uid"] == 0
    assert policy["codex_model_catalog_gid"] == 0


def test_audit_command_disables_incompatible_zsh_execution_paths() -> None:
    command = provenance.build_command(
        codex=Path("/authority/codex"),
        bundle=Path("/review/bundle"),
        output=Path("/attempt/review-output.json"),
    )
    disabled = {
        command[index + 1]
        for index, item in enumerate(command[:-1])
        if item == "--disable"
    }
    assert disabled == {
        "shell_snapshot",
        "shell_zsh_fork",
        "unified_exec_zsh_fork",
    }
    assert f'model_catalog_json="{Path("/authority/model-catalog.json")}"' in command


def _signed_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], dict[str, object], Path, Path, Path]:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    code_sources = tmp_path / "current-source"
    code_root = tmp_path / "authority-code-sha256-placeholder"
    code_payloads = {
        relative: f"# protected authority code: {relative}\n".encode()
        for relative in provenance.AUTHORITY_CODE_RELATIVE_PATHS
    }
    for root in (code_sources, code_root):
        (root / "scripts").mkdir(parents=True)
        for relative, raw in code_payloads.items():
            path = root / relative
            path.write_bytes(raw)
            path.chmod(0o444)
        (root / "scripts").chmod(0o555)
        root.chmod(0o555)
    manifest_basis = [
        {
            "relative_path": relative,
            "sha256": remediation.sha256_file(code_root / relative),
            "mode": "0444",
            "uid": 0,
            "gid": 0,
        }
        for relative in sorted(provenance.AUTHORITY_CODE_RELATIVE_PATHS)
    ]
    manifest_sha256 = remediation.sha256_bytes(
        remediation.encoded_json({"files": manifest_basis})
    )
    final_code_root = code_root.with_name(f"authority-code-sha256-{manifest_sha256}")
    code_root.rename(final_code_root)
    code_root = final_code_root
    runner = code_sources / "scripts/run_dg10_candidate4_ai_audit.py"
    protected_runner = code_root / "scripts/run_dg10_candidate4_ai_audit.py"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    output = tmp_path / "attempts/candidate.4-primary-test/review-output.json"
    output.parent.mkdir(parents=True, mode=0o700)
    output.write_text("{}\n")
    codex = tmp_path / "authority-bin/codex"
    codex.parent.mkdir()
    codex.write_bytes(b"pinned codex test executable\n")
    codex.chmod(0o555)
    codex_host = codex.with_name("codex-code-mode-host")
    codex_host.write_bytes(b"pinned code-mode host test executable\n")
    codex_host.chmod(0o555)
    codex_catalog = codex.with_name("model-catalog.json")
    codex_catalog.write_bytes(
        remediation.encoded_json({"models": [{"slug": provenance.MODEL}]})
    )
    codex_catalog.chmod(0o444)
    codex_resources: dict[str, Path] = {}
    for relative in provenance.CODEX_RESOURCE_PATHS:
        resource = codex.parent / relative
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_bytes(f"pinned resource {relative}\n".encode())
        resource.chmod(0o555)
        codex_resources[relative] = resource
    for relative in reversed(provenance.CODEX_RESOURCE_DIRECTORIES):
        (codex.parent / relative).chmod(0o555)

    python_distribution = tmp_path / "python-3.11"
    python_venv = tmp_path / "venv"
    python_executable = python_distribution / "bin/python3.11"
    python_executable.parent.mkdir(parents=True)
    python_executable.write_bytes(b"protected test Python executable\n")
    python_executable.chmod(0o755)
    python_launcher = python_venv / "bin/python"
    python_launcher.parent.mkdir(parents=True)
    python_launcher.symlink_to(python_executable)
    (python_distribution / "lib/python3.11").mkdir(parents=True)
    (python_venv / "lib/python3.11/site-packages").mkdir(parents=True)
    for root in (python_distribution, python_venv):
        for path in [root, *root.rglob("*")]:
            if not path.is_symlink():
                path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o022)
    runtime_root_paths = (python_distribution, python_venv)
    runtime_roots = {
        "distribution": remediation.protected_tree_identity(
            python_distribution,
            allowed_symlink_roots=runtime_root_paths,
        ),
        "venv": remediation.protected_tree_identity(
            python_venv,
            allowed_symlink_roots=runtime_root_paths,
        ),
    }
    loaded_library = tmp_path / "system-libraries/libauthority-test.so"
    loaded_library.parent.mkdir()
    loaded_library.write_bytes(b"protected external library\n")
    loaded_library.chmod(0o444)
    loaded_library_identity = {
        str(loaded_library): {
            "path": str(loaded_library),
            "sha256": remediation.sha256_file(loaded_library),
            "mode": "0444",
            "uid": 0,
            "gid": 0,
        }
    }

    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_sha256 = remediation.sha256_bytes(public_raw)
    policy_path = tmp_path / "docs/contracts/authority.json"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text("{}\n")
    policy = {
        "key_id": f"ed25519-sha256-{public_sha256}",
        "public_key_base64": base64.b64encode(public_raw).decode("ascii"),
        "public_key_sha256": public_sha256,
        "authority_uid": os.geteuid(),
        "authority_gid": os.getegid(),
        "workspace_author_uid": os.geteuid() + 1,
        "workspace_author_gid": os.getegid() + 1,
        "codex_executable_path": str(codex),
        "codex_executable_sha256": remediation.sha256_file(codex),
        "codex_executable_mode": "0555",
        "codex_executable_uid": codex.stat().st_uid,
        "codex_executable_gid": codex.stat().st_gid,
        "codex_code_mode_host_path": str(codex_host),
        "codex_code_mode_host_sha256": remediation.sha256_file(codex_host),
        "codex_code_mode_host_mode": "0555",
        "codex_code_mode_host_uid": codex_host.stat().st_uid,
        "codex_code_mode_host_gid": codex_host.stat().st_gid,
        "codex_model_catalog_path": str(codex_catalog),
        "codex_model_catalog_sha256": remediation.sha256_file(codex_catalog),
        "codex_model_catalog_mode": "0444",
        "codex_model_catalog_uid": codex_catalog.stat().st_uid,
        "codex_model_catalog_gid": codex_catalog.stat().st_gid,
        "codex_runtime_resources": {
            relative: remediation.sha256_file(path)
            for relative, path in codex_resources.items()
        },
        "codex_home_path": str(tmp_path / "authority-home/codex-home"),
        "codex_child_static_environment": {
            "CODEX_HOME": str(tmp_path / "authority-home/codex-home"),
            "HOME": str(tmp_path / "authority-home"),
            "PATH": f"{codex.parent / 'codex-path'}:/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
        },
        "authority_code_root": str(code_root),
        "authority_code_manifest_sha256": manifest_sha256,
        "authority_code_files": {
            relative: {
                "path": str(code_root / relative),
                "sha256": remediation.sha256_file(code_root / relative),
                "mode": "0444",
                "uid": 0,
                "gid": 0,
            }
            for relative in provenance.AUTHORITY_CODE_RELATIVE_PATHS
        },
        "authority_runner_path": str(protected_runner),
        "authority_runner_sha256": remediation.sha256_file(protected_runner),
        "authority_python_launcher_path": str(python_launcher),
        "authority_python_launcher_target": str(python_executable),
        "authority_python_executable_path": str(python_executable),
        "authority_python_executable_sha256": remediation.sha256_file(
            python_executable
        ),
        "authority_python_executable_mode": "0755",
        "authority_python_executable_uid": 0,
        "authority_python_executable_gid": 0,
        "authority_python_runtime_roots": runtime_roots,
        "authority_python_loaded_libraries": loaded_library_identity,
        "authority_python_sys_path": [
            str(code_root),
            str(python_distribution / "lib/python3.11"),
            str(python_venv / "lib/python3.11/site-packages"),
        ],
        "authority_python_isolated_flag": 1,
        "authority_python_dont_write_bytecode_flag": 1,
        "authority_process_static_environment": {
            "HOME": str(tmp_path / "authority-home"),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
        },
    }
    policy["codex_child_static_environment_sha256"] = remediation.sha256_bytes(
        remediation.encoded_json(policy["codex_child_static_environment"])
    )
    policy["authority_process_static_environment_sha256"] = remediation.sha256_bytes(
        remediation.encoded_json(policy["authority_process_static_environment"])
    )
    monkeypatch.setattr(provenance, "AUTHORITY_POLICY", policy_path)
    monkeypatch.setattr(provenance, "load_authority_policy", lambda: policy)

    process_claims: dict[str, object] = {
        "schema": "milai.dg10.ai-audit-process.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": output.parent.name,
        "scope": "R0_R2_PRIMARY",
        "audit_role": "PRIMARY",
        "model": provenance.MODEL,
        "reasoning_effort": provenance.REASONING_EFFORT,
        "cli_version": "codex-cli test",
        "process_exit_code": 0,
        "termination_reason": "COMPLETED",
        "timeout_seconds": 60,
        "bundle_directory_id": bundle.name,
        "prompt_sha256": "1" * 64,
        "response_schema_sha256": "2" * 64,
        "events_sha256": "3" * 64,
        "stderr_sha256": "4" * 64,
        "output_sha256": remediation.sha256_file(output),
        "sandbox": "read-only",
        "ephemeral": True,
        "ignore_user_config": True,
        "ignore_rules": True,
    }
    command = provenance.build_command(codex=codex, bundle=bundle, output=output)
    nonce = bytes.fromhex("05" * 32)
    child_environment = provenance.codex_child_environment(
        policy=policy,
        launch_nonce=nonce,
    )
    runtime = {
        "authority_code": provenance.pinned_authority_code(
            policy,
            materialized_runner=runner,
        ),
        "authority_python_runtime": provenance.pinned_authority_python_runtime(policy),
        "authority_runner_path": str(protected_runner),
        "authority_runner_sha256": remediation.sha256_file(protected_runner),
        "codex_executable_path": str(codex),
        "codex_executable_sha256": remediation.sha256_file(codex),
        "codex_executable_mode": "0555",
        "codex_executable_uid": codex.stat().st_uid,
        "codex_executable_gid": codex.stat().st_gid,
        "codex_code_mode_host_path": str(codex_host),
        "codex_code_mode_host_sha256": remediation.sha256_file(codex_host),
        "codex_code_mode_host_mode": "0555",
        "codex_code_mode_host_uid": codex_host.stat().st_uid,
        "codex_code_mode_host_gid": codex_host.stat().st_gid,
        "codex_model_catalog_path": str(codex_catalog),
        "codex_model_catalog_sha256": remediation.sha256_file(codex_catalog),
        "codex_model_catalog_mode": "0444",
        "codex_model_catalog_uid": codex_catalog.stat().st_uid,
        "codex_model_catalog_gid": codex_catalog.stat().st_gid,
        "codex_runtime_resources": {
            relative: {
                "path": str(path),
                "sha256": remediation.sha256_file(path),
                "mode": "0555",
                "uid": path.stat().st_uid,
                "gid": path.stat().st_gid,
            }
            for relative, path in codex_resources.items()
        },
        "command_sha256": provenance.command_sha256(command),
        "proc_cmdline_sha256": provenance.command_sha256(command),
        "proc_exe_sha256": remediation.sha256_file(codex),
        "child_pid": 1234,
        "launcher_uid": os.geteuid(),
        "launcher_gid": os.getegid(),
        "pidfd_opened": True,
        "codex_child_environment": child_environment,
        "codex_child_environment_sha256": remediation.sha256_bytes(
            remediation.encoded_json(child_environment)
        ),
        "proc_environ_sha256": remediation.sha256_bytes(
            remediation.encoded_json(child_environment)
        ),
        "launch_nonce_hex": nonce.hex(),
        "launch_nonce_sha256": remediation.sha256_bytes(nonce),
        "launch_nonce_observed_in_child": True,
        "stdin_transport": "DIRECT_SUBPROCESS_PIPE",
        "stdout_transport": "DIRECT_SUBPROCESS_PIPE",
        "stderr_transport": "DIRECT_SUBPROCESS_PIPE",
        "process_identity_observed_before_output_read": True,
    }
    statement = {
        "schema": "milai.dg10.ai-execution-signed-statement.v3",
        "authority_uid": os.geteuid(),
        "authority_gid": os.getegid(),
        "process": process_claims,
        "runtime_observations": runtime,
        "signed_after_terminal_output_hashes": True,
    }
    signature = private_key.sign(remediation.encoded_json(statement))
    attestation: dict[str, object] = {
        "schema": "milai.dg10.ai-execution-attestation.v3",
        "channel": "ISOLATED_ROOT_CODE_PYTHON_ENV_ED25519_LIVE_CODEX_V3",
        "authority_policy_sha256": remediation.sha256_file(policy_path),
        "key_id": policy["key_id"],
        "public_key_sha256": public_sha256,
        "signed_statement": statement,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
    process = {**process_claims, "execution_attestation": attestation}
    return attestation, process, bundle, output, runner


def test_separate_authority_signature_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path, monkeypatch
    )

    result = provenance.validate_execution_attestation(
        attestation,
        bundle=bundle,
        output=output,
        materialized_runner=runner,
        process=process,
    )

    assert result["channel"] == "ISOLATED_ROOT_CODE_PYTHON_ENV_ED25519_LIVE_CODEX_V3"


def test_post_hoc_statement_or_process_tampering_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path, monkeypatch
    )
    statement = dict(attestation["signed_statement"])
    statement["signed_after_terminal_output_hashes"] = False
    forged = {**attestation, "signed_statement": statement}
    with pytest.raises(
        provenance.AIProvenanceError,
        match="signed execution statement drift",
    ):
        provenance.validate_execution_attestation(
            forged,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )

    changed_process = {**process, "timeout_seconds": 61}
    with pytest.raises(
        provenance.AIProvenanceError,
        match="signed AI process claims drift",
    ):
        provenance.validate_execution_attestation(
            attestation,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=changed_process,
        )


def test_runtime_resource_or_directory_tampering_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path, monkeypatch
    )
    resources = attestation["signed_statement"]["runtime_observations"][
        "codex_runtime_resources"
    ]
    resource = Path(resources[provenance.CODEX_RESOURCE_PATHS[0]]["path"])
    resource.chmod(0o755)
    with pytest.raises(
        provenance.AIProvenanceError,
        match="runtime resource identity drift",
    ):
        provenance.validate_execution_attestation(
            attestation,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )
    resource.chmod(0o555)

    directory = resource.parent
    directory.chmod(0o755)
    with pytest.raises(
        provenance.AIProvenanceError,
        match="runtime resource directory drift",
    ):
        provenance.validate_execution_attestation(
            attestation,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )


def test_model_catalog_tampering_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path, monkeypatch
    )
    observations = attestation["signed_statement"]["runtime_observations"]
    catalog = Path(observations["codex_model_catalog_path"])
    catalog.chmod(0o644)

    with pytest.raises(
        provenance.AIProvenanceError,
        match="model catalog identity drift",
    ):
        provenance.validate_execution_attestation(
            attestation,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )


@pytest.mark.skipif(os.geteuid() != 0, reason="requires temporary ownership mutation")
@pytest.mark.parametrize(
    "runtime_path_key",
    ["codex_executable_path", "codex_code_mode_host_path"],
)
def test_non_root_codex_executable_or_helper_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime_path_key: str,
) -> None:
    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path, monkeypatch
    )
    observations = attestation["signed_statement"]["runtime_observations"]
    target = Path(observations[runtime_path_key])
    os.chown(target, 12345, 12345)

    with pytest.raises(
        provenance.AIProvenanceError,
        match="identity drift",
    ):
        provenance.validate_execution_attestation(
            attestation,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )


def test_authority_module_or_materialized_source_substitution_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path, monkeypatch
    )
    observations = attestation["signed_statement"]["runtime_observations"]
    protected_module = Path(
        observations["authority_code"]["files"][
            "scripts/dg10_ai_provenance.py"
        ]["path"]
    )
    protected_module.write_bytes(b"# substituted protected module\n")
    with pytest.raises(
        provenance.AIProvenanceError,
        match="protected authority code file identity drift",
    ):
        provenance.validate_execution_attestation(
            attestation,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )

    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path / "materialized", monkeypatch
    )
    materialized_module = runner.parents[1] / "scripts/dg10_ai_provenance.py"
    materialized_module.write_bytes(b"# substituted materialized module\n")
    with pytest.raises(
        provenance.AIProvenanceError,
        match="materialized authority code differs from protected code",
    ):
        provenance.validate_execution_attestation(
            attestation,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )

    policy = provenance.load_authority_policy()
    protected = policy["authority_code_files"]
    provenance.validate_imported_authority_modules(
        policy=policy,
        runner_path=Path(policy["authority_runner_path"]),
        provenance_module_path=Path(
            protected["scripts/dg10_ai_provenance.py"]["path"]
        ),
        remediation_module_path=Path(
            protected["scripts/dg10_remediation.py"]["path"]
        ),
    )
    with pytest.raises(
        provenance.AIProvenanceError,
        match="imported module closure drift",
    ):
        provenance.validate_imported_authority_modules(
            policy=policy,
            runner_path=runner,
            provenance_module_path=runner.parents[1]
            / "scripts/dg10_ai_provenance.py",
            remediation_module_path=runner.parents[1] / "scripts/dg10_remediation.py",
        )


def test_authority_python_runtime_tree_tampering_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path, monkeypatch
    )
    runtime = attestation["signed_statement"]["runtime_observations"][
        "authority_python_runtime"
    ]
    distribution = Path(runtime["runtime_roots"]["distribution"]["path"])
    injected = distribution / "lib/python3.11/injected.py"
    injected.write_text("raise RuntimeError('substituted')\n")
    injected.chmod(0o444)

    with pytest.raises(
        provenance.AIProvenanceError,
        match="Python runtime tree identity drift",
    ):
        provenance.validate_execution_attestation(
            attestation,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )

    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path / "loaded-library", monkeypatch
    )
    libraries = attestation["signed_statement"]["runtime_observations"][
        "authority_python_runtime"
    ]["loaded_libraries"]
    library = Path(next(iter(libraries)))
    library.write_bytes(b"substituted external library\n")
    with pytest.raises(
        provenance.AIProvenanceError,
        match="loaded-library closure drift",
    ):
        provenance.validate_execution_attestation(
            attestation,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )


def test_codex_child_environment_is_exact_and_never_inherits_host_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    static = {
        "CODEX_HOME": "/authority/codex-home",
        "HOME": "/authority",
        "PATH": "/authority/codex-path:/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    policy = {
        "codex_child_static_environment": static,
        "codex_child_static_environment_sha256": remediation.sha256_bytes(
            remediation.encoded_json(static)
        ),
    }
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-cross-boundary")
    monkeypatch.setenv("HTTP_PROXY", "http://unattested.invalid")
    nonce = bytes.fromhex("ab" * 32)

    observed = provenance.codex_child_environment(
        policy=policy,
        launch_nonce=nonce,
    )

    assert observed == {
        **static,
        "MILAI_DG10_AI_LAUNCH_NONCE": nonce.hex(),
    }
    assert "AWS_SECRET_ACCESS_KEY" not in observed
    assert "HTTP_PROXY" not in observed
    raw = b"".join(
        key.encode() + b"=" + value.encode() + b"\0"
        for key, value in observed.items()
    )
    assert provenance._validated_proc_environment(raw, observed) == observed
    with pytest.raises(
        provenance.AIProvenanceError,
        match="environment identity drift",
    ):
        provenance._validated_proc_environment(
            raw + b"AWS_SECRET_ACCESS_KEY=unexpected\0",
            observed,
        )
    descendant = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,os;print(json.dumps(dict(os.environ),sort_keys=True))",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=observed,
    )
    assert json.loads(descendant.stdout) == observed


def test_v1_execution_attestation_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attestation, process, bundle, output, runner = _signed_execution(
        tmp_path, monkeypatch
    )
    legacy = {
        **attestation,
        "schema": "milai.dg10.ai-execution-attestation.v1",
        "channel": "PINNED_CODEX_PIDFD_PROC_NONCE_DIRECT_PIPE_V1",
    }

    with pytest.raises(
        provenance.AIProvenanceError,
        match="execution authority identity drift",
    ):
        provenance.validate_execution_attestation(
            legacy,
            bundle=bundle,
            output=output,
            materialized_runner=runner,
            process=process,
        )


def test_workspace_process_cannot_invoke_separate_authority_signer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provenance,
        "load_authority_policy",
        lambda: {
            "authority_uid": os.geteuid() + 1,
            "authority_gid": os.getegid() + 1,
        },
    )

    with pytest.raises(
        provenance.AIProvenanceError,
        match="protected authority identity",
    ):
        provenance.sign_execution_attestation(
            process_claims={},
            runtime_observations={},
        )
