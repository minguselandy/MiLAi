"""Fresh frozen-wheel installs and secret-safe DG10 config derivation."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SOURCE_ENV_SHA256 = (
    "fd7c819902c1a33d762b1dfb70b496c816db4a37c482570d57090f66433718e3"
)
DG10_REMOVED_KEYS = frozenset(
    {
        "MILAI_EMBEDDING_PROJECTION_DIMENSIONS",
        "MILAI_RETRIEVAL_RERANKER_MODEL_ID",
        "MILAI_RETRIEVAL_RERANKER_MODEL_PATH",
        "MILAI_RETRIEVAL_RERANKER_MODEL_SHA256",
        "MILAI_RETRIEVAL_RERANKER_POOL_SIZE",
        "MILAI_RETRIEVAL_RERANKER_PROVIDER",
        "MILAI_RETRIEVAL_RERANKER_REVISION",
        "MILAI_RETRIEVAL_TEMPORAL_RERANKER_POOL_SIZE",
    }
)
WHEELS = {
    "dg10": {
        "client": (
            ROOT
            / "var/dg10/final/candidate/packages/milai_client-0.1.0-py3-none-any.whl",
            "a2ea195369b70d96d4cb62378e9f02d51a8d67ec238dc1c90ef0bc9638a93635",
        ),
        "mcp": (
            ROOT / "var/dg10/final/candidate/packages/milai_mcp-0.1.0-py3-none-any.whl",
            "08a08d13be792fc34cd9eb2e1b99b8b9f0a7ed00c5b5c51c30c4b85d0494ee66",
        ),
        "openworker": (
            ROOT
            / "var/dg10/final/candidate/packages/milai_openworker_mcp-0.1.0-py3-none-any.whl",
            "d10c80cb045fac3870dae8219b6ad16c1d774589090e654d0b35b6a44ea619ed",
        ),
        "runtime": (
            ROOT
            / "var/dg10/final/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl",
            "2a22e5d1dadc7dc8716a017845be9adc059962eb6ea653a766db048d8c499f8e",
        ),
    },
    "dg11": {
        "client": (
            ROOT
            / "var/dg11/freeze/candidate/packages/milai_client-0.1.0-py3-none-any.whl",
            "9aca83e322a32c52cda288232ce337ec941860c39ec5d746c703b7f748abbf4d",
        ),
        "mcp": (
            ROOT
            / "var/dg11/freeze/candidate/packages/milai_mcp-0.1.0-py3-none-any.whl",
            "7ef5b1038f38a47fdffa4c9f73e39072a0525174b7220022dbf1ae6ebfc089a2",
        ),
        "openworker": (
            ROOT
            / "var/dg11/freeze/candidate/packages/milai_openworker_mcp-0.1.0-py3-none-any.whl",
            "43adee1776b70fff2c3a34c10ea3aad43dc5060809aecaa10af0301ca9a05b90",
        ),
        "runtime": (
            ROOT
            / "var/dg11/freeze/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl",
            "7fc0b1ab3babed5d99daca1ef92a7160ba0de729a34ccc1b1a10c5c82641e25a",
        ),
    },
}


class MiLAiEnvironmentError(RuntimeError):
    pass


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _env_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").lstrip()
    return stripped.partition("=")[0].strip()


def derive_dg10_env(
    *, source: Path, output: Path, identity_output: Path
) -> dict[str, Any]:
    if output.exists() or identity_output.exists():
        raise MiLAiEnvironmentError("DG10 derived env or identity already exists")
    if sha256_file(source) != EXPECTED_SOURCE_ENV_SHA256:
        raise MiLAiEnvironmentError("candidate-frozen Runtime env identity drifted")
    removed: set[str] = set()
    retained: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        key = _env_key(line)
        if key in DG10_REMOVED_KEYS:
            assert key is not None
            removed.add(key)
        else:
            retained.append(line)
    if removed != DG10_REMOVED_KEYS:
        raise MiLAiEnvironmentError("DG10 config derivation key set drifted")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(retained) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    identity = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "derived_env_sha256": sha256_file(output),
        "removed_keys": sorted(removed),
        "schema": "milai.dg11.paper-dg10-env-derivation.v1",
        "source_env_sha256": EXPECTED_SOURCE_ENV_SHA256,
        "status": "PASS",
    }
    _atomic_json(identity_output, identity)
    return identity


def _install_inventory(python: Path) -> dict[str, Any]:
    code = """
import importlib.metadata
import json
import pathlib
import sys
import milai
values = [
    {"name": dist.metadata["Name"], "version": dist.version}
    for dist in importlib.metadata.distributions()
]
values.sort(key=lambda item: (item["name"].casefold(), item["version"]))
print(json.dumps({
    "distributions": values,
    "milai_origin": str(pathlib.Path(milai.__file__).resolve()),
    "prefix": str(pathlib.Path(sys.prefix).resolve()),
    "python": sys.version,
}, sort_keys=True))
"""
    completed = subprocess.run(
        [str(python), "-c", code], check=True, capture_output=True, text=True
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MiLAiEnvironmentError("fresh install inventory is invalid") from exc
    if not isinstance(value, dict):
        raise MiLAiEnvironmentError("fresh install inventory is not an object")
    return value


def install(
    *, identity: str, environment: Path, manifest_output: Path
) -> dict[str, Any]:
    if identity not in WHEELS:
        raise MiLAiEnvironmentError("unknown MiLAi frozen wheel identity")
    if environment.exists() or manifest_output.exists():
        raise MiLAiEnvironmentError("fresh install target already exists")
    uv = shutil.which("uv")
    if uv is None:
        raise MiLAiEnvironmentError("uv executable is unavailable")
    wheels = WHEELS[identity]
    wheel_records: dict[str, dict[str, Any]] = {}
    for name, (path, expected) in wheels.items():
        observed = sha256_file(path)
        if observed != expected:
            raise MiLAiEnvironmentError(f"{identity} {name} wheel identity drifted")
        wheel_records[name] = {
            "bytes": path.stat().st_size,
            "path": str(path.resolve()),
            "sha256": observed,
        }
    subprocess.run(
        [uv, "venv", "--python", "3.11", str(environment)],
        check=True,
        cwd=ROOT,
    )
    python = environment / "bin/python"
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            str(wheels["client"][0]),
            str(wheels["mcp"][0]),
            f"{wheels['runtime'][0]}[embedding]",
            str(wheels["openworker"][0]),
        ],
        check=True,
        cwd=ROOT,
    )
    installed = _install_inventory(python)
    prefix = Path(str(installed.get("prefix"))).resolve()
    origin = Path(str(installed.get("milai_origin"))).resolve()
    if prefix != environment.resolve() or not origin.is_relative_to(prefix):
        raise MiLAiEnvironmentError("fresh install imported outside its environment")
    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_ai_reviews": 0,
        "distributions": installed["distributions"],
        "environment": str(environment.resolve()),
        "fresh_install": True,
        "identity": identity,
        "milai_origin": str(origin),
        "python": installed["python"],
        "python_executable": str(python.resolve()),
        "schema": "milai.dg11.paper-milai-install.v1",
        "status": "PASS",
        "wheels": wheel_records,
    }
    _atomic_json(manifest_output, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    derive = subparsers.add_parser("derive-dg10-env")
    derive.add_argument("--source", type=Path, default=ROOT / "runtime/.env")
    derive.add_argument("--output", type=Path, required=True)
    derive.add_argument("--identity-output", type=Path, required=True)
    prepare = subparsers.add_parser("install")
    prepare.add_argument("--identity", choices=tuple(WHEELS), required=True)
    prepare.add_argument("--environment", type=Path, required=True)
    prepare.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "derive-dg10-env":
        result = derive_dg10_env(
            source=args.source.resolve(),
            output=args.output.resolve(),
            identity_output=args.identity_output.resolve(),
        )
    else:
        result = install(
            identity=args.identity,
            environment=args.environment.resolve(),
            manifest_output=args.manifest_output.resolve(),
        )
    print(
        json.dumps(
            {
                "identity": result.get("identity", "dg10-env"),
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
