"""Prepare explicit frozen Mem2Act closeout commands; never dispatch a stage or read its ledger."""

import argparse
import ast
import importlib.metadata
import json
import shlex
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def action(name: str, argv: list[str], gates: list[str], metering: str, env: dict) -> dict:
    return {
        "name": name,
        "argv": argv,
        "environment": env,
        "shell_command_for_explicit_review": shlex.join(
            ["env", *[f"{key}={value}" for key, value in env.items()], *argv]
        ),
        "required_actual_gates": gates,
        "metering": metering,
        "dispatch_status": "PREPARED_NOT_DISPATCHED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    external = root / "external-own-policy-v1"
    frozen = external / "frozen-mem2act-v1"
    protocol_path = frozen / "protocol-before-public-task-projection-v1.json"
    protocol = read(protocol_path)
    revision_path = (
        external / "frozen-mem2act-audit-execution-v2" / "observation-protocol-before-audit-v2.json"
    )
    revision = read(revision_path)
    bindings = protocol["frozen_code_bindings"]
    assert len(bindings) == 1147
    for binding in [*bindings, revision["additional_observational_code_binding"]]:
        assert Path(binding["source"]).read_bytes() == Path(binding["frozen"]).read_bytes()
    observer = Path(revision["additional_observational_code_binding"]["frozen"])
    assert (
        observer.read_bytes()
        == (
            root.parent.parent / "tools/audit_a100_mem2act_predictions_execution_v2.py"
        ).read_bytes()
    )
    assert revision["exact_audit_code_replacements"] == 3
    assert revision["inverse_replacement_entire_original_literal_equal"]

    fixed = protocol["initial_stage_plans"]["fixed-prefix-prediction400-v1"]
    primary = protocol["initial_stage_plans"]["primary-seed0-u32-prediction400-v1"]
    assert fixed == read(Path(fixed["plan_path"]))
    assert primary == read(Path(primary["plan_path"]))
    owner = read(Path(fixed["owner"]))
    assert owner["status"] == "RUNNING" and not owner["client_CPU_recorded"]
    for key, entry in (
        ("pid", "own_external_mem2act_stage_v1.py"),
        ("child_pid", "run_mem2act_predictions_with_shared_host_v1.py"),
    ):
        directory = Path("/proc", str(owner[key]))
        command = (directory / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        assert entry in command and fixed["name"] in command
        assert (directory / "stat").read_text().split()[2] != "Z"
    driver = read(Path(fixed["output"]) / "driver.json")
    assert driver["status"] == "RUNNING" and driver["planned_positions"] == 400
    assert not Path(primary["owner"]).exists()
    tasks = []
    with Path(protocol["public_tasks"]).open() as stream:
        tasks = [json.loads(line) for line in stream]
    assert len(tasks) == len(driver["cases"]) == 400
    terminal = [row for row in driver["cases"] if row["status"] in ("COMPLETED", "FAILED")]
    checked = []
    for index in sorted({0, 2, terminal[-1]["row"]}):
        case = driver["cases"][index]
        assert case["status"] in ("COMPLETED", "FAILED")
        captured = Path(case["first_host_capture"])
        host = read(captured / "host.json")
        assert host["status"] == "CAPTURED_PRE_HOST"
        assert host["initial_baseline_context"] is not None
        assert host["initial_tool_catalog"] is not None
        assert host["public_message"]["content"] == tasks[index]["query"]
        assert host["public_message"]["recorded_tool_schemas"] == [
            tasks[index]["target_tool_schema"]
        ]
        control = read(captured / "before/input-freeze.json")["config"]["memory_control"]
        merged = {**control, **protocol["primary_policy_override"]}
        changed = {key for key in control if control[key] != merged[key]}
        assert changed <= {"policy", "checkpoint"}
        assert len(merged) == len(control)
        assert merged["max_len"] == 16384 and merged["head_max_len"] == 2048
        checked.append(
            {
                "row": index,
                "native_status": case["status"],
                "actual_capture": str(captured),
                "initial_context_and_catalog_available": True,
                "actual_control_keys_preserved": sorted(control),
                "override_changes": sorted(changed),
                "complete_control_merge_preserves_all_other_keys": True,
            }
        )
    replay_source = Path(protocol["runtime"]) / "src/milai_lab/runners/frozen_host_message.py"
    source = replay_source.read_text()
    (replay_function,) = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "replay_host_message"
    ]
    literal = ast.get_source_segment(source, replay_function)
    assert 'policy_override = {**settings["memory_control"], **copy.deepcopy(control_policy)}' in (
        literal
    )
    assert "earliest-first400 closure alias then full400" in protocol["serial_order"][3]
    assert "earliest-first400 closure alias then full400" in protocol["serial_order"][5]
    assert protocol["fixed_closure"] in primary["required_stage_gates"]
    assert protocol["fixed_full_audit"] in primary["required_stage_gates"]

    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    for directory in protocol["site_packages"]:
        sys.path.append(directory)
    assert {
        name: importlib.metadata.version(name) for name in protocol["SDK_versions"]
    } == protocol["SDK_versions"]
    cuda_python = primary["argv"][0]
    http_python = str(Path(cuda_python).parents[2] / "http-env/bin/python")
    runtime = Path(protocol["runtime"])
    common_env = {
        "PYTHONPATH": ":".join([str(frozen), str(runtime / "src"), str(runtime / "tools")]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
    }
    bootstrap = (
        "import json,runpy,sys,transformers,tokenizers; "
        "assert transformers.__version__=='4.52.3'; "
        "assert tokenizers.__version__=='0.21.4'; "
        f"protocol=json.load(open({str(protocol_path)!r})); "
        "sys.path.extend(protocol['site_packages']); "
        "entry=sys.argv[1]; sys.argv=sys.argv[1:]; "
        "runpy.run_path(entry,run_name='__main__')"
    )
    commands = []
    for method, plan in (("fixed", fixed), ("primary", primary)):
        alias = protocol["fixed_predictions" if method == "fixed" else "primary_predictions"]
        closure = protocol["fixed_closure" if method == "fixed" else "primary_closure"]
        audit = protocol["fixed_full_audit" if method == "fixed" else "primary_full_audit"]
        commands.append(
            action(
                f"{method}-earliest-first400-canonical-alias",
                [
                    http_python,
                    str(frozen / "finalize_external_mem2act_predictions_v1.py"),
                    plan["owner"],
                    alias,
                    closure,
                ],
                ["all400 terminal native firsts", "actual owner CPU paid and PIDs gone"],
                "ordinary GNU CPU timer; no native/model/residual rebill",
                common_env,
            )
        )
        commands.append(
            action(
                f"{method}-full400-frozen-observer-v2-audit",
                [
                    cuda_python,
                    "-u",
                    "-c",
                    bootstrap,
                    str(observer),
                    str(protocol_path),
                    alias,
                    plan["owner"],
                    audit,
                ],
                [closure, "actual all400 canonical first records", "owner paid and PIDs gone"],
                "ordinary GNU CPU timer; exact original audit output path",
                common_env,
            )
        )
        if method == "fixed":
            commands.append(
                action(
                    "primary400-original-owner-explicit-launch",
                    [
                        http_python,
                        "-u",
                        str(frozen / "own_external_mem2act_stage_v1.py"),
                        primary["plan_path"],
                    ],
                    [
                        *primary["required_stage_gates"],
                        "all400 fixed first Host snapshots replayable",
                        "no live experimental model/HTTP worker",
                    ],
                    "native owner UNWRAPPED; native plus whole residual/parent once at actual exit",
                    common_env,
                )
            )
    for method in ("fixed", "primary"):
        prefix = "fixed" if method == "fixed" else "primary"
        alias = protocol[prefix + "_predictions"]
        audit = protocol[prefix + "_full_audit"]
        scores = protocol[prefix + "_scores"]
        score_audit = protocol[prefix + "_score_audit"]
        commands.append(
            action(
                method + "-all400-adapted-score",
                [
                    cuda_python,
                    "-u",
                    "-c",
                    bootstrap,
                    str(frozen / "score_closed_mem2act_predictions_v1.py"),
                    str(protocol_path),
                    alias,
                    audit,
                    scores,
                ],
                [protocol["fixed_full_audit"], protocol["primary_full_audit"]],
                "ordinary GNU CPU timer; no model/HTTP/business/ledger calls",
                common_env,
            )
        )
        commands.append(
            action(
                method + "-all400-adapted-score-audit",
                [
                    cuda_python,
                    "-u",
                    "-c",
                    bootstrap,
                    str(frozen / "audit_mem2act_scores_v1.py"),
                    str(protocol_path),
                    alias,
                    scores,
                    score_audit,
                ],
                [scores, audit],
                "ordinary GNU CPU timer; every original proposal and metric payload checked",
                common_env,
            )
        )
    commands.append(
        action(
            "both400-original-lossless-archives-after-all-gates",
            [
                cuda_python,
                "-u",
                "-c",
                bootstrap,
                str(frozen / "archive_closed_mem2act_cases_v1.py"),
                str(protocol_path),
                protocol["archive_output"],
            ],
            protocol["archive_required_gates"],
            "ordinary GNU CPU timer; script and archive_case have no ledger accounting",
            common_env,
        )
    )
    assert len(commands) == 10
    report = {
        "passed": True,
        "status": "FROZEN_MEM2ACT_EXPLICIT_CLOSEOUT_COMMANDS_AND_ACTUAL_CAPTURE_CONFIGS_VERIFIED",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "original_protocol": str(protocol_path),
        "original_scientific_code_bindings_literal_equal": 1147,
        "additional_frozen_observer_binding_literal_equal": 1,
        "SDK_versions": protocol["SDK_versions"],
        "actual_closed_capture_config_checks": checked,
        "canonical_alias_then_full_audit_is_original_serial_order": True,
        "previous_audit_before_alias_instruction_corrected_without_protocol_change": True,
        "primary_actual_merge_implementation_preserves_full_config": str(replay_source),
        "actual_native_fixed_counts_at_observation": dict(
            Counter(row["status"] for row in driver["cases"])
        ),
        "actual_fixed_owner_and_child_named_processes_alive": True,
        "full400_fixed_closeout_ready": False,
        "primary400_launch_ready": False,
        "original_native_owner_check_only_not_executed_because_it_reads_live_ledger": True,
        "commands": commands,
        "commands_executed_by_preparation": 0,
        "automatic_queue_or_background_dispatch_created": False,
        "owner_resolution": (
            "Commands bind the original current plans. Re-resolve the actual terminal owner "
            "if an unexpected failure requires an explicitly reflected NOT_RUN continuation. "
            "Never rerun or replace any already closed native first outcome."
        ),
        "archive_scope": (
            "Original archive_case compares every reconstructed byte before raw removal. "
            "Archive only after both primary replay and all six Source/score/closure gates. "
            "Retain the immutable complete common base and first-capture metadata."
        ),
        "new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls": 0,
        "original_Source_plans_models_labels_or_firsts_changed": False,
        "CPU_pending_actual_idle138": True,
        "no_sha_validation": True,
        "full763_line_completion_proven": False,
        "goal_complete": False,
    }
    with args.output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("MEM2ACT_ORIGINAL_ALIAS_THEN_FULL400_AUDIT_HANDOFF_VERIFIED_NOT_DISPATCHED", flush=True)


if __name__ == "__main__":
    main()
