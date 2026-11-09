"""Reconcile all original plan text blocks with current bounded evidence and required open work."""
# Report prose intentionally retains Chinese punctuation.
# ruff: noqa: RUF001

import argparse
import ast
import json
import re
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def blocks(lines):
    result, index, section = [], 0, "source-context"
    while index < len(lines):
        line = lines[index]
        start, end, kind = index, index, "paragraph"
        if line.startswith("#"):
            found = re.match(r"^#{2,3} (\d+(?:\.\d+)?)(?:\.)? ", line)
            section = found.group(1) if found else "source-context"
            kind = "heading"
        elif not line.strip():
            kind = "blank"
        elif line.startswith("```"):
            kind, end = "code", index + 1
            while end < len(lines) and not lines[end].startswith("```"):
                end += 1
            assert end < len(lines)
        elif line.startswith("|"):
            kind = (
                "table-structure" if set(line.strip("| ")) <= {"-", ":", "|", " "} else "table-row"
            )
        elif re.match(r"^\[[A-Z]\d+\]: ", line):
            kind = "reference"
        elif re.match(r"^(?:- |\d+\. )", line):
            kind = "list-item"
        else:
            while (
                end + 1 < len(lines)
                and lines[end + 1].strip()
                and not lines[end + 1].startswith(("#", "```", "|"))
                and not re.match(r"^(?:- |\d+\. |\[[A-Z]\d+\]: )", lines[end + 1])
            ):
                end += 1
        result.append(
            dict(
                line_start=start + 1,
                line_end=end + 1,
                kind=kind,
                section=section,
                literal_original_lines="\n".join(lines[start : end + 1]),
            )
        )
        index = end + 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    lab = root.parent.parent
    initial = read(root / "original-plan-requirements-audit-v1.json")
    plan = Path(initial["original_plan"])
    text = plan.read_text()
    assert text == initial["literal_original_plan_utf8"]
    with plan.open() as stream:
        lines = [line.rstrip("\n") for line in stream]
    assert len(lines) == 763
    source_paths = dict(
        P0=lab / "data/manifests/a100-plan-runtime-p0-audit-20261109-v1.json",
        A=lab / "data/manifests/a100-plan-A-audit-20261109-v1.json",
        B64=lab / "data/manifests/a100-plan-B64-audit-20261109-v1.json",
        BC=lab / "data/manifests/a100-plan-B-repair-C-audit-20261109-v1.json",
        D=lab / "data/manifests/a100-plan-D-audit-20261109-v1.json",
        FREEZE=root / "original-plan-allocation-freeze-v1.json",
        TRAIN=lab / "data/manifests/a100-closed-training-compute-20261107-v1.json",
        CONF=lab / "data/manifests/a100-confirmation256-quality-results-20261107-v1.json",
        CONF_RAW=root / "final-confirmation-v1/source-author-quality-all4-methods-closeout-v1.json",
        Q64=lab / "data/manifests/a100-reserved64-native-results-20261107-v1.json",
        LME=root / "verify-lme-primary-archive-closed-v1.json",
        LME_RESULTS=lab / "data/manifests/a100-lme-native-comparison-20261109-v1.json",
        COST=lab / "data/manifests/a100-known-paid-cost-through-lme-20261109-v1.json",
        DEVELOPMENT=root / "task-dev64-development-selection.json",
    )
    evidence = {name: read(path) for name, path in source_paths.items()}
    assert [len(evidence[name]["obligations"]) for name in ("P0", "A", "B64", "BC", "D")] == [
        12,
        16,
        16,
        16,
        18,
    ]
    assert all(evidence[name]["passed"] for name in ("P0", "A", "B64", "BC", "D", "FREEZE", "LME"))
    assert len(evidence["TRAIN"]["rows"]) == 8
    assert evidence["CONF_RAW"]["whole_manual_judgments"] == 1024
    assert (
        evidence["CONF_RAW"]["primary_remains_frozen_seed0_not_reselected"]
        and not evidence["CONF_RAW"]["adopted"]
    )
    assert (
        evidence["Q64"]["all12999_first_outputs_audited"]
        and evidence["Q64"]["all_three_4333_input_token_sequences_literal_equal"]
    )
    assert (
        not evidence["Q64"]["native_labels_or_masks_changed"]
        and not evidence["Q64"]["new_fits_or_checkpoint_selection"]
    )
    closures = []
    for path in evidence["LME"]["all_six_LME_stage_closures"]:
        closure = read(path)
        owner = read(closure["actual_owner"])
        assert closure["passed"] and closure["positions"] == 451
        assert owner["exit_code"] == 0 and owner["client_CPU_recorded"]
        assert not any(Path("/proc", str(owner[key])).exists() for key in ("pid", "child_pid"))
        closures.append(
            dict(
                closure=path,
                owner=closure["actual_owner"],
                positions=451,
                actual_exit0_paid_processes_absent=True,
            )
        )
    assert len(closures) == 6 and evidence["LME_RESULTS"]["all_six_LME_stage_closures_closed"]
    assert (
        evidence["COST"]["actual_cutoff_idle"] == 137
        and not evidence["COST"]["current_Mem2Act_or_full_project_costs_complete"]
    )
    assert evidence["COST"]["known_paid_goal_CPU_seconds"] == 156772.30469547494
    replication = read(root / "e3-retained-replication/family-comparison.json")
    mean = replication["within_family_seed_mean_comparison"]
    values = [
        value / mean["difference_unit_denominator"] for value in mean["difference_units_per_family"]
    ]
    variance = statistics.variance(values)
    assert (
        abs(
            variance
            - replication["conditional_power_planning"]["family_difference_sample_variance"]
        )
        < 1e-14
    )
    development = evidence["DEVELOPMENT"]
    b0 = development["comparisons"]["b0-u33-minus-incumbent-delivery-u16"]
    b1 = development["comparisons"]["b1-u33-minus-incumbent-delivery-u16"]
    coverage = development["comparisons"]["b1-u33-minus-b0-u33"]
    assert [b0["delta"], b1["delta"], coverage["delta"]] == [0.125, 0.109375, -0.015625]
    assert b0["family_bootstrap_95_percent"] == [0.0, 0.25] and b1[
        "family_bootstrap_95_percent"
    ] == [-0.046875, 0.265625]

    mem_owner = read(
        root / "external-own-policy-v1/stages-mem2act-v1/fixed-prefix-prediction400-v1-owner.json"
    )
    mem_plan = read(mem_owner["plan"])
    mem_driver = read(Path(mem_plan["output"]) / "driver.json")
    assert mem_owner["status"] == "RUNNING" and not mem_owner["client_CPU_recorded"]
    for key in ("pid", "child_pid"):
        directory = Path("/proc", str(mem_owner[key]))
        command = (directory / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        assert mem_plan["name"] in command and (directory / "stat").read_text().split()[2] != "Z"
        assert (
            "own_external_mem2act_stage_v1.py"
            if key == "pid"
            else "run_mem2act_predictions_with_shared_host_v1.py"
        ) in command
    mem_counts = dict(Counter(case["status"] for case in mem_driver["cases"]))
    assert sum(mem_counts.values()) == 400 and mem_counts["NOT_RUN"] > 0
    open_work = [
        dict(
            id="MEM-FIXED",
            requirement=(
                "固定Mem2Act400所有原始首结果、实际owner退出/支付"
                "、完整Source/Store/Saver/SDK/Host审计"
                "及原定稿"
            ),
            status="ACTIVE_REQUIRED",
            evidence=str(Path(mem_owner["plan"])),
        ),
        dict(
            id="MEM-PRIMARY",
            requirement=(
                "预定primary400由真实同一pre-first-Host快"
                "照完整配置覆盖运行，全量原生Source/输入/首结果审计"
            ),
            status="REQUIRED_AFTER_FIXED_FULL_AUDIT",
            evidence="original frozen Mem2Act protocol; no primary firsts substituted",
        ),
        dict(
            id="MEM-SCORE",
            requirement="两方法400适配评分、原生失败保留、评分审计、范围/暴露/分组与比较",
            status="REQUIRED_AFTER_PREDICTIONS",
            evidence="frozen scorer and protocol, no completed400cohort yet",
        ),
        dict(
            id="MEM-ARCHIVE",
            requirement="两方法400原始Source/状态/输入/首结果/评分/日志可重建归档及原生关闭",
            status="REQUIRED_AFTER_AUDITS",
            evidence="original native archive protocol",
        ),
        dict(
            id="FINAL-COST",
            requirement=(
                "实际idle138及之后普通/失败CPU、Mem2Act原生/w"
                "hole/parent/存储差额一次计量，最终全项目已知与未知成"
                "本"
            ),
            status="REQUIRED_AFTER_ACTUAL_IDLE",
            evidence=str(source_paths["COST"]),
        ),
        dict(
            id="FINAL-PAPER",
            requirement="完整内外部/冻结确认的最终论文与结果包、总体图表、能主张/不能主张的结论",
            status="REQUIRED_AFTER_EXTERNAL_CLOSE",
            evidence=str(lab / "docs/MILAI_A100_DEVELOPMENT_RESULTS_DRAFT_20261107.md"),
        ),
        dict(
            id="FINAL-AUDIT",
            requirement=(
                "以最终实际状态重新完成全763行要求/命令/门禁/交付物逐项审计"
                "，不能用本执行中清单宣布完成"
            ),
            status="REQUIRED_FINAL",
            evidence=str(plan),
        ),
    ]
    section_evidence = {
        "1": ["P0", "A", "B64", "BC", "D", "FREEZE", "CONF", "LME"],
        "2": ["P0", "A", "B64", "BC", "D"],
        "3": ["P0", "TRAIN"],
        "4": ["P0"],
        "5": ["FREEZE", "A", "B64", "BC", "D", "Q64"],
        "6": ["A", "Q64"],
        "7": ["B64", "BC", "DEVELOPMENT"],
        "8": ["BC"],
        "9": ["D"],
        "10": ["TRAIN", "A", "B64", "FREEZE"],
        "11": ["FREEZE", "CONF", "CONF_RAW", "Q64", "LME", "LME_RESULTS"],
        "12": ["A", "B64", "BC", "D", "FREEZE", "CONF", "LME", "COST"],
        "13": ["P0", "A", "B64", "BC"],
        "14": ["P0", "A", "B64", "BC", "D", "CONF", "Q64", "LME_RESULTS", "COST"],
    }
    descriptions = {
        "1": (
            "真实功能/机制/Host/反馈拟合与冻结确认各自已有证据；正效果"
            "与泛化/实用的层级不能替代，外部Mem2Act及最终交付仍未齐。"
        ),
        "2": (
            "原E1至E5事实与既有执行器能力是本计划背景；保留历史失败，不包"
            "装已试目标为创新，也不把旧暂停快照当实时状态。"
        ),
        "3": (
            "实际P0和A/B单卡配对、BF16/FP32/窗口/显存/原版本"
            "声明已核对；E3追加训练随机性保留其原FP32两GPU配方另报，"
            "不声称全部训练都变单卡。"
        ),
        "4": (
            "P0实际512合法行/121完整pair、32更新、后28稳态、"
            "完整输出及真实导出/重载已核对。原61tests摘要没有直接ex"
            "it凭据不补造；真实GPU短测证据单列。"
        ),
        "5": (
            "TRAIN/DEVELOPMENT/CONFIRMATION身份"
            "按真实parent allocation次序与论文整体分组重建；"
            "原native分区与研究角色不同，保留共享语料/预训练/作者暴露"
            "限制。"
        ),
        "6": (
            "原A10k两组成/完整已知负例与unknown、1pass/28"
            "05更新及旧32/新128/保留64实际评测已核对；未获得支持A"
            "1相对A0的任务优势，不自动扩量/新loss/组合。"
        ),
        "7": (
            "B64真实共享三分支支持、完整参数/Source/首次结果、qu"
            "ality-before-resource监督与匹配拟合已核对；"
            "coverage-vs-current无稳健优势。B0/B1相对"
            "初始化有正点估计，不能概括纯delivery完全无任务改善。"
        ),
        "8": (
            "C同真实已读池/原完整菜单、初始/保存模型/补7池的实际交付和首"
            "次Host结果已核对；已有合法好集合，未证具体表达缺口，无men"
            "u扩展或新拟合。"
        ),
        "9": (
            "原8/新32完整自主轨迹、最小无关0→1会话/相关到达/旧输出可"
            "检索性分因素与knownK控制核对。没有多规模增长或View学习"
            "收益主张；Source忠实不等事实真值。"
        ),
        "10": (
            "八实际作业=2profile+4A/B主拟合+2固定E1起点E3种子追加，12完"
            "整拟合是条件上限；draw/tokens/GPU/wall实际值与可选规模/J分"
            "别报告。"
        ),
        "11": (
            "内部1024首结果/配对家族统计、实际分配与预冻结、保留64原生"
            "12999输出、LME两451六关闭已核对；Mem2Act全80"
            "0仍未完成，不能声明整体外部或独立泛化成立。"
        ),
        "12": (
            "停止规则用于无证据扩量、保留首失败和确认不复现。已知成本仅为id"
            "le137后/preMem截止，实际在运行段和post137未结"
            "CPU/存储及最终项目成本仍未闭合。"
        ),
        "13": (
            "原命令是待P0后使用的模板；实际argv/config已按原E2"
            "/E3配方与wrapper绑定，不能逐字重跑例子当额外必须矩阵。"
            "readout互斥/knownK/full-frame/完整菜单"
            "保持。"
        ),
        "14": (
            "已有各包可复核代码/协议/结果/PNG-PDF与真实artifa"
            "ct范围；最终外部/成本/论文图表仍待完成。贡献方向不是已证学习"
            "优势，保持Host工具架构/权限/原账本/首结果。"
        ),
    }
    conditional_sections = {
        "3.4": (
            "DDP与精确optimizer/scheduler/RNG恢复未"
            "被单卡容量或长训练瓶颈实际需要触发；warm-start与模型导"
            "出按真实语义命名。"
        ),
        "5.3": (
            "A20k/32k/64k需有依据条件/任务响应和新合法来源；A1"
            "对A0旧32为15/32相同，保留64A1条件指标更低，没有扩量"
            "资格。"
        ),
        "8.2": (
            "新增有界add/remove/swap仅在具体集合表达缺口时触发"
            "；C原菜单已有较好集合、学习未胜rules，未证明该缺口。"
        ),
        "10.2": (
            "本轮未进行条件未触发的规模扩展；等曝光/等更新/等tokens/"
            "FLOPs不混称，A与B实际预算分别由完整draw与paddin"
            "g核对。"
        ),
    }
    all_blocks = blocks(lines)
    assert [
        line for block in all_blocks for line in range(block["line_start"], block["line_end"] + 1)
    ] == list(range(1, 764))
    source_obligations = [
        (name, row)
        for name in ("P0", "A", "B64", "BC", "D")
        for row in evidence[name]["obligations"]
    ]
    for index, block in enumerate(all_blocks):
        section = block["section"]
        major = section.split(".")[0]
        low, high = block["line_start"], block["line_end"]
        citations = section_evidence.get(major, [])
        links = []
        for name, row in source_obligations:
            if any(low <= line <= high for line in row["original_plan_lines"]):
                links.append(
                    dict(
                        audit=name,
                        obligation=row.get("id", row.get("requirement_id")),
                        requirement=row["requirement"],
                    )
                )
        status, reason = (
            "EVIDENCE_SCOPED_WITH_LIMITATIONS",
            descriptions.get(major, "原标题/参考/上下文保留；参考链接本身不证明实验已执行。"),
        )
        if (
            block["kind"] in ("heading", "blank", "table-structure", "reference")
            or section == "source-context"
        ):
            status, reason = (
                "STRUCTURE_OR_HISTORICAL_REFERENCE",
                "原文逐行保留，不把标题、空行、表格结构、引用或历史上下文计成完成的实验。",
            )
        elif major == "2" or section == "5.1":
            status = "HISTORICAL_CONTEXT_PRESERVED"
        elif section == "1.3" or section == "14.2":
            status, reason = (
                "CLAIM_THRESHOLD_NOT_A_SUCCESS_CERTIFICATE",
                (
                    "功能/机制/任务/泛化/实用及三贡献方向分别需要实际证据；当前确"
                    "认没有支持采用学习策略质量优势，不把研究目标自动当已达成正结论。"
                ),
            )
        elif section in conditional_sections:
            status, reason = "CONDITIONAL_NOT_ADMITTED", conditional_sections[section]
        elif major == "13":
            status = "TEMPLATE_OR_INTERFACE_BOUND_TO_ACTUAL_EVIDENCE"
        elif section in ("10.3", "11.4", "12.1", "14.1"):
            status = "PARTIAL_REQUIRED_EXTERNAL_OR_FINAL_DELIVERABLES"
        elif section == "11.1":
            status = "PARTIAL_REQUIRED_MEM2ACT_LAYER"
        elif section == "12.2":
            status, reason = (
                "MILESTONE_RESULTS_SCOPED_M5_STILL_OPEN",
                (
                    "M0至M4已执行相应实验并报告不支持的假设；M5外部全量/最终成"
                    "本/论文图表未完成。里程碑下一步依据不等价于必须造出正结果。"
                ),
            )
        elif section in ("12.3", "14.3"):
            status = "ONGOING_INVARIANT_WITH_RETAINED_FAILURES"
        elif section == "7.6":
            reason += (
                " answer-first比较的复合前提不因粗材料tie中答案差"
                "异自动成立；同初始化B0/B1各+12.5/+10.9375pp"
                "，CI跨或触零，原目标停止决定不等于已证纯delivery不能改"
                "善。"
            )
        if major == "7" and "后续采集效率实验" in block["literal_original_lines"]:
            status, reason = (
                "OPTIONAL_EFFICIENCY_STUDY_NOT_CLAIMED",
                (
                    "相同采集槽位的效率实验是另一个条件问题；本轮真实共享三分支监督比"
                    "较不声称等采集成本效率优势，因此未自动启动该实验。"
                ),
            )
        block.update(
            id=f"PLAN-{index + 1:03d}",
            assessment=status,
            assessment_scope=reason,
            evidence_files=[str(source_paths[name]) for name in citations],
            direct_original_line_obligation_links=links,
            direct_line_link_is_not_by_itself_a_broader_completion_proof=True,
        )
    trainer = lab / "tools/train_bounded_laya.py"
    argument_nodes = [
        node
        for node in ast.walk(ast.parse(trainer.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
    ]
    declared_arguments = {
        value.value
        for node in argument_nodes
        for value in node.args
        if isinstance(value, ast.Constant)
        and isinstance(value.value, str)
        and value.value.startswith("--")
    }
    training_code = "\n".join(
        block["literal_original_lines"]
        for block in all_blocks
        if block["kind"] == "code" and block["section"] in ("13.2", "13.3", "13.4")
    )
    training_template_arguments = sorted(set(re.findall(r"--[a-z][a-z0-9-]*", training_code)))
    assert set(training_template_arguments) <= declared_arguments
    assert {"--device", "--parallel-mode", "--precision"} <= declared_arguments
    assert (
        "--resume" not in declared_arguments
        and "--gradient-accumulation-steps" not in declared_arguments
    )
    assert "--bf16" not in declared_arguments
    template_details = [
        dict(
            block_id=block["id"],
            section=block["section"],
            line_start=block["line_start"],
            line_end=block["line_end"],
            literal_command_or_schema=block["literal_original_lines"],
            named_shell_variables=sorted(
                set(re.findall(r"\$([A-Z][A-Z0-9_]*)", block["literal_original_lines"]))
            ),
            named_optional_arguments=sorted(
                set(re.findall(r"--[a-z][a-z0-9-]*", block["literal_original_lines"]))
            ),
        )
        for block in all_blocks
        if block["kind"] == "code"
    ]
    result = dict(
        passed=True,
        status=(
            "ALL763_ORIGINAL_LINES_CURRENT_COMPLETION_EVIDENCE_RECONCILED_REQUIRED_OP"
            "EN_WORK_REMAINS"
        ),
        timestamp_utc=datetime.now(UTC).isoformat(),
        original_plan=str(plan),
        original_line_count=763,
        entire_original_UTF8_literal_equal_initial_frozen_plan=True,
        all763_lines_in_exact_nonoverlapping_blocks=True,
        literal_original_plan_utf8=text,
        blocks=all_blocks,
        original_heading_units=73,
        total_text_blocks=len(all_blocks),
        nonblank_text_blocks=sum(block["kind"] != "blank" for block in all_blocks),
        block_counts_by_kind=dict(Counter(block["kind"] for block in all_blocks)),
        block_counts_by_assessment=dict(Counter(block["assessment"] for block in all_blocks)),
        all8_original_command_or_schema_blocks_and_named_options_preserved=template_details,
        actual_trainer_source=str(trainer),
        all_training_template_options_exist_in_current_actual_parser=training_template_arguments,
        added_P0_device_precision_parallel_mode_present=True,
        no_fabricated_resume_or_gradient_accumulation_option=True,
        completion_percentage_not_computed_because_blocks_have_different_weight=True,
        scoped_P0_A_B64_BrepairC_D_concrete_obligations=78,
        scope_audits={name: str(source_paths[name]) for name in ("P0", "A", "B64", "BC", "D")},
        new_global_source_allocation_seed_freeze_actual_source_audit=str(source_paths["FREEZE"]),
        source_freeze_18932_actual_Source_units_and_all_actual_initialization_recipe_checks_passed=True,
        conditional_power_variance_recomputed_from_actual64_family_seed_mean_differences=variance,
        original12_complete_fit_cap_is_conditional_not_quota=True,
        actual_new_training_profile_jobs=8,
        actual_full_fits=6,
        B_objective_gate_clarification=dict(
            B0_minus_common_initialization=b0,
            B1_minus_common_initialization=b1,
            coverage_minus_current_nomination=coverage,
            conclusion=(
                "Do not conflate no stable coverage-vs-current improvement with proven "
                "no benefit of pure-delivery learning. No new answer-first fit is "
                "automatically mandated by a condition whose pure-delivery-failure "
                "premise is unproven; original fixed final candidate and results remain "
                "unchanged."
            ),
        ),
        old64_reserved_query_required_evaluation_now_closed=True,
        all12999_first_native_outputs_audited=True,
        LME_both451_all6_actual_closures_paid_and_gone=closures,
        LME_failed50_per_method_unscored_and_cohort_metrics_unavailable_not_imputed=True,
        actual_Mem2Act_fixed_native_status=mem_driver["status"],
        actual_Mem2Act_fixed_native_counts=mem_counts,
        actual_Mem2Act_fixed_named_owner_and_child_alive=True,
        actual_Mem2Act_primary400_firsts_complete=False,
        known_paid_preMem_cutoff_CPU_seconds=156772.30469547494,
        known_paid_preMem_cutoff_is_current_full_cost=False,
        required_open_work=open_work,
        old_initial_v66_open_list_superseded_without_modifying_original_audit=True,
        semantic_scope=(
            "Current requirement-by-text-block evidence reconciliation, not a final "
            "completion certificate or an inference from headings/file "
            "existence/green checks. Direct scoped original-line obligations and "
            "source audits are cited, while references/templates/conditions/claim "
            "limits/ongoing invariants remain distinct. All declared original "
            "requirements, checkpoints, modes, source splits, failures and final "
            "deliverables remain in scope. Re-run the full completion audit on "
            "actual final native state only after required external/cost/paper work "
            "closes."
        ),
        source_author_not_independent_or_blind=True,
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        original_Source_inputs_labels_models_or_firsts_changed=False,
        CPU_pending_actual_idle138=True,
        no_sha_validation=True,
        full763_line_completion_proven=False,
        goal_complete=False,
    )
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(
        "ALL763_LINES_CURRENT_EVIDENCE_BLOCKS_RECONCILED_GOAL_ACTIVE",
        len(all_blocks),
        "blocks;requiredOpen",
        len(open_work),
        "MemFixed",
        mem_counts,
        flush=True,
    )


if __name__ == "__main__":
    main()
