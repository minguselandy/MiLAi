"""Losslessly store only closed D captures, retaining their native restore paths."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def free_bytes(path):
    values = os.statvfs(path)
    return dict(
        including_root_reserved=values.f_bfree * values.f_frsize,
        ordinary_available=values.f_bavail * values.f_frsize,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    lab = root.parent.parent
    evidence_path = lab / "data/manifests/a100-plan-D-audit-20261109-v1.json"
    evidence = read(evidence_path)
    assert (
        evidence["passed"]
        and evidence["all_first_failures_unknowns_and_original_judgments_preserved"]
    )
    assert read(evidence["private_audits"]["execution"])["actual_new_native_jobs"] == 5
    assert all(read(path)["passed"] for path in evidence["private_audits"].values())
    external = root / "external-own-policy-v1"
    mem_protocol = read(
        external / "frozen-mem2act-v1/protocol-before-public-task-projection-v1.json"
    )
    runtime_source = external / "frozen-mem2act-v1/runtime/src"
    helper_path = runtime_source / "milai_lab/harness/case_archive.py"
    (binding,) = [
        row
        for row in mem_protocol["frozen_code_bindings"]
        if Path(row["frozen"]).resolve() == helper_path.resolve()
    ]
    assert helper_path.read_bytes() == Path(binding["source"]).read_bytes()
    sys.path.insert(0, str(runtime_source))
    from milai_lab.harness.case_archive import archive_case

    names = [
        "old8-e3-aggregate-u32",
        "old8-view_cache_incremental",
        "new32-view_cache",
        "new32-view_cache_incremental",
        "new32-e3-aggregate-u32",
    ]
    jobs = []
    targets = []
    for name in names:
        job = root / "d-update32-execution" / name
        driver_path = job / "driver.json"
        original_driver = driver_path.read_bytes()
        driver = json.loads(original_driver)
        assert driver["status"] == "COMPLETED_WITH_FAILURES"
        assert driver["finished_epoch"] > driver["started_epoch"]
        assert not Path("/proc", str(driver["pid"])).exists()
        jobs.append(
            dict(
                name=name,
                driver=str(driver_path),
                original=original_driver,
                actual_pid=driver["pid"],
            )
        )
        for kind in ("frozen-retrieval-calls", "frozen-host-messages"):
            target = job / kind
            assert target.is_dir() and not target.is_symlink()
            assert not external.is_relative_to(target) and not target.is_relative_to(external)
            for code in mem_protocol["frozen_code_bindings"]:
                assert not any(
                    Path(code[key]).resolve().is_relative_to(target) for key in ("source", "frozen")
                )
            targets.append(dict(job=name, kind=kind, original=str(target)))
    output = root / "closed-D-capture-storage-v1"
    output.mkdir(exist_ok=False)
    base = output / "immutable-empty-base"
    base.mkdir()
    protocol = dict(
        status="FIVE_CLOSED_D_JOBS_CAPTURE_STORAGE_ONLY_BEFORE_EXECUTION",
        timestamp_utc=datetime.now(UTC).isoformat(),
        Source_evidence=str(evidence_path),
        targets=targets,
        immutable_empty_base=str(base),
        archive_helper=str(helper_path),
        native_drivers=[
            {key: value for key, value in job.items() if key != "original"} for job in jobs
        ],
        free_bytes_before=free_bytes(root),
        every_reconstructed_byte_must_equal_before_raw_removal=True,
        original_file_mode_and_mtime_ns_retained_in_archive=True,
        Mem2Act_or_LME_or_models_or_reviews_or_first_records_targeted=False,
        scientific_protocols_Source_budgets_or_model_inputs_changed=False,
        model_HTTP_business_or_original_ledger_calls=0,
        no_sha_validation=True,
        restore_requirement=(
            "Use the frozen native case_archive.restore_case with "
            "this retained empty base and the recorded original path "
            "before optional D reinspection or final native replay. "
            "No model or Host prefix is rerun by restoration."
        ),
    )
    write_new(output / "protocol-before-storage.json", protocol)
    records = []
    for target in targets:
        path = Path(target["original"])
        destination = output / (target["job"] + "-" + target["kind"] + ".tar.gz")
        result = archive_case(path, destination, base)
        row = {
            **target,
            **result,
            "actual_raw_directory_absent_after_byte_verification": not path.exists(),
        }
        assert row["actual_raw_directory_absent_after_byte_verification"]
        write_new(output / (destination.stem + "-receipt.json"), row)
        records.append(row)
        print(
            "D_CAPTURE_ALL_BYTES_VERIFIED_AND_STORED",
            target["job"],
            target["kind"],
            result["uncompressed_bytes"],
            result["archive_bytes"],
            flush=True,
        )
    assert len(records) == 10
    assert all(Path(job["driver"]).read_bytes() == job["original"] for job in jobs)
    report = dict(
        passed=True,
        status="ALL10_CLOSED_D_CAPTURE_TREES_LOSSLESSLY_STORED_NATIVE_DRIVERS_UNCHANGED",
        timestamp_utc=datetime.now(UTC).isoformat(),
        protocol=str(output / "protocol-before-storage.json"),
        records=records,
        original_uncompressed_bytes=sum(row["uncompressed_bytes"] for row in records),
        archives_bytes=sum(row["archive_bytes"] for row in records),
        free_bytes_after=free_bytes(root),
        immutable_empty_base=str(base),
        every_reconstructed_byte_compared_before_raw_removal=True,
        native_original_drivers_literal_unchanged=True,
        source_values_labels_firsts_models_and_scientific_protocols_changed=False,
        Mem2Act_snapshots_and_current_worker_untouched=True,
        model_HTTP_business_or_original_ledger_calls=0,
        ordinary_GNU_CPU_pending_next_actual_idle=True,
        no_sha_validation=True,
        full763_line_completion_proven=False,
        goal_complete=False,
    )
    write_new(output / "closeout.json", report)
    print(
        report["status"],
        report["original_uncompressed_bytes"],
        report["archives_bytes"],
        flush=True,
    )


if __name__ == "__main__":
    main()
