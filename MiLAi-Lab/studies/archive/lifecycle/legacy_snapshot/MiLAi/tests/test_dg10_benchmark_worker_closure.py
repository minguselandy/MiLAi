from __future__ import annotations

import zipfile

from scripts import build_dg10_benchmark_worker_closure as closure
from scripts import build_dg10_candidate4_identities as identities


def test_benchmark_worker_is_independent_locked_and_binds_historical_hash() -> None:
    report = closure.build_report(run_dynamic=False, capture_root=closure.DEFAULT_CAPTURE_ROOT)
    assert report["status"] == "R2_AUTHOR_CANDIDATE_REVIEW_REQUIRED"
    assert report["runtime_venv_reused"] is False
    assert report["stage_state"] == "AUTHOR_CANDIDATE"
    assert report["independent_acceptance"] is False
    assert report["environment"]["python"]["executable_path_class"] == "EVALS_DG10_VENV"
    assert report["environment"]["lock"]["path"] == "evals/dg10/uv.lock"
    assert report["environment"]["mpmath"] == {
        "version": "1.3.0",
        "file_count": 87,
        "tree_sha256": (
            "376efeae63abdfd9378ce98ddb38509387ba0237c82e8e70429ddea11089079b"
        ),
    }
    assert report["historical_worker_freeze"]["policy"] == (
        "IMMUTABLE_CANDIDATE_2_ONLY_NOT_UPDATED"
    )
    assert report["bfcl"]["git_head"] == "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"


def test_runner_closure_excludes_post_r2_bfcl_preregistration_artifacts() -> None:
    inventory = closure._runner_closure()
    paths = {entry["path"] for entry in inventory["entries"]}
    assert "docs/contracts/DG-10-attempt-ledger.schema.json" in paths
    assert not any(
        path.startswith(
            (
                "docs/contracts/DG-10-bfcl-case-manifest-",
                "docs/contracts/DG-10-bfcl-execution-identity-",
            )
        )
        for path in paths
    )


def test_runtime_package_data_is_materialized_in_both_source_closures() -> None:
    package_assets = {
        "runtime/src/milai/py.typed",
        "runtime/src/milai/static/milai.css",
        "runtime/src/milai/static/milai.js",
        "runtime/src/milai/templates/index.html",
    }
    runner_paths = {
        entry["path"] for entry in closure._runner_closure()["entries"]
    }
    source_paths = {
        path.relative_to(closure.ROOT).as_posix() for path in identities.source_paths()
    }
    assert package_assets <= runner_paths
    assert package_assets <= source_paths
    with zipfile.ZipFile(
        closure.ROOT / "evals/dg10/wheels/milai_runtime-0.1.0-py3-none-any.whl"
    ) as wheel:
        wheel_members = {
            name
            for name in wheel.namelist()
            if name.startswith("milai/") and not name.endswith("/")
        }
        source_members = {
            path.relative_to(closure.ROOT / "runtime/src").as_posix()
            for path in (closure.ROOT / "runtime/src/milai").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        assert wheel_members == source_members
        assert len(source_members) == 65
        for archive_path in source_members:
            source = closure.ROOT / "runtime/src" / archive_path
            assert wheel.read(archive_path) == source.read_bytes()
