"""Reconcile a saved post-Mem2Act cutoff without opening the operational ledger."""

import argparse
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def equal_cpu(left, right):
    assert math.isclose(left, right, rel_tol=0, abs_tol=1e-7), (left, right)


def prepare(root):
    prior_path = root / "known-paid-cost-through-LME-closed-before-Mem2Act-v2.json"
    prior = read(prior_path)
    external = root / "external-own-policy-v1"
    protocol_path = external / "frozen-mem2act-v1/protocol-before-public-task-projection-v1.json"
    protocol = read(protocol_path)
    before_path = Path(prior["closed_snapshot"])
    assert before_path.resolve() != Path(protocol["original_ledger"]).resolve()
    before = read(before_path)
    assert prior["all_six_LME_canonical_closures_closed"]
    assert prior["all295_added_compute_phases_explained_once"]
    assert prior["known_paid_goal_CPU_seconds"] == 156772.30469547494
    gates = [Path(path) for path in protocol["archive_required_gates"]]
    gates += [Path(protocol["archive_output"]) / "closeout.json"]
    return prior_path, prior, before_path, before, protocol_path, protocol, gates


def native_owners(protocol, after):
    rows = []
    seen = set()
    for method in ("fixed", "primary"):
        closure = read(protocol[method + "_closure"])
        audit = read(protocol[method + "_full_audit"])
        assert closure["passed"] and audit["passed"] and audit["positions"] == 400
        assert closure["all400_entire_earliest_case_records_literal_equal"]
        chain = closure["ancestor_owners_oldest_first"]
        assert chain and Path(chain[-1]).resolve() == Path(audit["actual_owner"]).resolve()
        for path in chain:
            owner = read(path)
            plan = read(owner["plan"])
            assert plan["method"] == method and owner["client_CPU_recorded"]
            assert "exit_code" in owner
            assert all(not Path("/proc", str(owner[key])).exists() for key in ("pid", "child_pid"))
            phase = owner["client_compute_phase"]
            assert phase not in seen
            seen.add(phase)
            paid = after["compute"][phase]
            assert paid["runs"] == 1
            assert (
                paid["cpu_seconds"]
                == owner["client_CPU_residual"] + owner["parent_CPU_seconds_through_billing"]
            )
            equal_cpu(
                owner["whole_child_CPU_seconds"],
                owner["client_CPU_residual"] + sum(owner["already_recorded_native_CPU"].values()),
            )
            rows.append(
                dict(
                    owner=str(Path(path).resolve()),
                    method=method,
                    phase=phase,
                    exit_code=owner["exit_code"],
                    whole_child_plus_measured_parent_CPU_seconds=(
                        owner["whole_child_CPU_seconds"]
                        + owner["parent_CPU_seconds_through_billing"]
                    ),
                    named_residual_plus_parent_CPU_seconds=paid["cpu_seconds"],
                    included_native_CPU_by_phase=owner["already_recorded_native_CPU"],
                    shared_generation_admissions=owner["shared_generation_admissions"],
                    known_generation_tokens=owner["known_generation_tokens"],
                    new_unknown_usage=owner["new_unknown_usage"],
                )
            )
        assert read(chain[-1])["validated_stage_terminal"]
    return rows


def reconcile(root, prior, before, protocol, snapshot, last_idle):
    assert snapshot.resolve() != Path(protocol["original_ledger"]).resolve()
    after = read(snapshot)
    assert before["limits"] == after["limits"] and before["embedding"] == after["embedding"]
    assert set(before["compute"]) <= set(after["compute"])
    added = {key: value for key, value in after["compute"].items() if key not in before["compute"]}
    changed = {key for key in before["compute"] if before["compute"][key] != after["compute"][key]}
    assert all("a100" in key.lower() and value["runs"] == 1 for key, value in added.items())
    assert all("a100" not in key.lower() for key in changed)
    generic_cpu = {
        key: after["compute"][key]["cpu_seconds"] - before["compute"][key]["cpu_seconds"]
        for key in changed
    }
    assert all(value > 0 for value in generic_cpu.values())
    owners = native_owners(protocol, after)
    explained_generic = Counter()
    for owner in owners:
        explained_generic.update(owner["included_native_CPU_by_phase"])
    assert set(explained_generic) == changed
    for key in changed:
        equal_cpu(explained_generic[key], generic_cpu[key])
    assert last_idle >= 138
    sys.path.insert(0, str(root))
    from offline_time_receipts import read_timer

    seen_timers = set()
    idles = []
    commands = []
    for version in range(1, last_idle + 1):
        path = root / f"idle-cost-settlement-v{version}.json"
        receipt = read(path)
        entries = receipt["new_commands" if version == 1 else "commands"]
        for command in entries:
            timer_path = str(Path(command["path"]).resolve())
            if version >= 138:
                assert timer_path not in seen_timers
            seen_timers.add(timer_path)
            if version >= 138:
                assert read_timer(timer_path) == command and command["known_exit_code"] is not None
                commands.append(dict(actual_idle=version, **command))
        if version < 138:
            continue
        assert receipt["generation_and_limits_unchanged"]
        assert not receipt["native_model_client_parent_or_earlier_CPU_rebilled"]
        assert "separate_storage_phase" not in receipt
        assert after["compute"][receipt["phase"]]["runs"] == 1
        assert after["compute"][receipt["phase"]]["cpu_seconds"] == receipt["CPU_seconds"]
        equal_cpu(sum(row["CPU_seconds"] for row in entries), receipt["CPU_seconds"])
        idles.append(
            dict(
                version=version,
                receipt=str(path),
                phase=receipt["phase"],
                CPU_seconds=receipt["CPU_seconds"],
                closed_commands=len(entries),
            )
        )
    phases = [row["phase"] for row in owners] + [row["phase"] for row in idles]
    assert len(phases) == len(set(phases)) == len(added)
    assert set(phases) == set(added)
    native_whole = sum(row["whole_child_plus_measured_parent_CPU_seconds"] for row in owners)
    native_named = sum(row["named_residual_plus_parent_CPU_seconds"] for row in owners)
    generic_total = sum(generic_cpu.values())
    equal_cpu(native_whole, native_named + generic_total)
    ordinary_cpu = sum(row["CPU_seconds"] for row in idles)
    delta_cpu = sum(row["cpu_seconds"] for row in added.values()) + generic_total
    equal_cpu(delta_cpu, native_whole + ordinary_cpu)
    named_goal = (
        sum(
            value["cpu_seconds"] for key, value in after["compute"].items() if "a100" in key.lower()
        )
        - prior["excluded_carried_old_debt_CPU_seconds"]
    )
    generic_goal = prior["generic_goal_CPU_seconds"] + generic_total
    total = named_goal + generic_goal
    equal_cpu(total, prior["known_paid_goal_CPU_seconds"] + delta_cpu)
    generation = {
        key: after["generation"][key] - before["generation"][key] for key in before["generation"]
    }
    assert generation["known_tokens"] == sum(row["known_generation_tokens"] for row in owners)
    assert generation["unknown_usage"] == sum(
        row["new_unknown_usage"]["generation"] for row in owners
    )
    assert all(row["new_unknown_usage"]["embedding"] == 0 for row in owners)
    admissions = after["generation_requests"] - before["generation_requests"]
    assert admissions == sum(row["shared_generation_admissions"] for row in owners)
    archive = read(Path(protocol["archive_output"]) / "closeout.json")
    assert archive["passed"] and archive["positions"] == len(archive["records"]) == 800
    assert archive["every_reconstructed_byte_compared_before_raw_removal"]
    assert archive["base_retained_outside_all_case_and_archive_trees"]
    assert Path(archive["immutable_common_base"]).is_dir()
    return dict(
        status="POST_MEM2ACT_ALL800_SOURCE_SCORE_ARCHIVE_CLOSED_KNOWN_PAID_CUTOFF_RECONCILED",
        closed_snapshot=str(snapshot.resolve()),
        final_actual_idle=last_idle,
        previous_known_paid_goal_CPU_seconds=prior["known_paid_goal_CPU_seconds"],
        added_named_phase_count=len(added),
        generic_native_CPU_delta_by_phase=generic_cpu,
        new_native_residual_plus_measured_parent_CPU_seconds=native_named,
        new_native_whole_child_plus_measured_parent_CPU_seconds=native_whole,
        new_native_CPU_included_in_whole_not_readded=generic_total,
        new_ordinary_closed_GNU_CPU_seconds=ordinary_cpu,
        new_total_CPU_seconds=delta_cpu,
        named_goal_CPU_seconds=named_goal,
        generic_goal_CPU_seconds=generic_goal,
        known_paid_goal_CPU_seconds=total,
        known_paid_goal_CPU_hours=total / 3600,
        known_Host_generation_tokens_since_first_functional_request=(
            prior["known_Host_generation_tokens_since_first_functional_request"]
            + generation["known_tokens"]
        ),
        new_generation_field_deltas=generation,
        new_generation_admission_counter=admissions,
        legacy_and_new_unknown_generation_usage_retained=after["generation"]["unknown_usage"],
        embedding_state_and_limits_unchanged=True,
        all_added_CPU_phases_explained_once=True,
        all_actual_native_owner_ancestors_including_retained_failures=owners,
        actual_idle_receipts=idles,
        closed_ordinary_commands=commands,
        closed_ordinary_command_count=len(commands),
        retained_nonzero_exit_ordinary_command_count=sum(
            row["known_exit_code"] != 0 for row in commands
        ),
        new_charges_or_resets_refunds=False,
        all800_native_audits_scores_and_archives_closed=True,
        scope=(
            "Known paid, observed cost through the saved cutoff only. "
            "This report's own GNU timer and later publication/analysis lie after that snapshot "
            "until a subsequent actual idle settlement. "
            "Unmetered author, launcher, inspection, settler and cleanup CPU is unknown_not_zero; "
            "the old-output observed child199.51-second lower bound "
            "does not establish lost parent cost. "
            "Historical base model/Source acquisition amortization, Host GPU busy time, "
            "energy and money remain separate or unmeasured. "
            "CPU, native/load and whole/residual are not added twice."
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--last-idle", type=int)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    prior_path, prior, before_path, before, protocol_path, protocol, gates = prepare(root)
    pending = [str(path) for path in gates if not path.exists()]
    if args.preflight_only:
        report = dict(
            status="FINAL_COST_INPUT_BOUNDARY_PREFLIGHT_ONLY_NO_POST_MEM2ACT_COSTS_COMPUTED",
            pending_actual_required_gates=pending,
            actual_final_project_cost_computed=False,
            static_pre_Mem2Act_paid_CPU_seconds=prior["known_paid_goal_CPU_seconds"],
            static_pre_Mem2Act_known_Host_tokens=prior[
                "known_Host_generation_tokens_since_first_functional_request"
            ],
        )
    else:
        assert not pending, pending
        assert all(read(path)["passed"] for path in gates)
        assert args.snapshot is not None and args.last_idle is not None
        report = reconcile(root, prior, before, protocol, args.snapshot, args.last_idle)
    report.update(
        passed=True,
        timestamp_utc=datetime.now(UTC).isoformat(),
        prior_exact_cutoff=str(prior_path),
        prior_closed_snapshot=str(before_path),
        protocol=str(protocol_path),
        original_live_ledger_opened_or_written=False,
        new_model_tokenizer_GPU_HTTP_business_calls=0,
        no_sha_validation=True,
        true_unmeasured_cost_filled_with_zero=False,
        goal_complete=False,
    )
    with args.output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(report["status"], flush=True)


if __name__ == "__main__":
    main()
