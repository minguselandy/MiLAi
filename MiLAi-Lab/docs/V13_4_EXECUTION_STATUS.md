# v13.4 执行终态（2026-10-03）

**已按条件退出路径收口：G1 NOT_PASSED_SCOPED → Simplify。** 完整结果、失败分析、费用、研究主张和复核入口见 [T0结果与退出报告](V13_4_T0_RESULTS_AND_EXIT.md)。本轮完成N0/N1、N2/T0实际执行和N6收口；T1/T2/T3因G1未通过而未准入，不将条件退出写成全部科研要求通过。

已执行32个开发历史、128题、B1/B2共256次真实Reader，全部HTTP200、0重试、bank不变。另有64次真实query-free形成及8次入口诊断，合计328次生成、685,409 known及charged tokens，0新增embedding/unknown费用。形成7/64通过结构/逐字quote检查，57份unknown保持原样；评分方法盲冻结后解盲，原答与gold未修改。

123个可解题均在K32内有2048完整单元预算见证；实际已枚举E*覆盖B1为99/123、B2为97/123。覆盖失败主要是原子组装包与次序；完整证据送达后的7条未满分是普通Reader解释错误。未建立跨历史重复关系消歧机制，保留opt-in简单入口，停止本批复杂方法推进。所有数据仍属开发；原生近邻、第二家族、独立语义Judge与正式泛化未验证。

七模块最终机械验证包括136项受影响测试、35项独立工程窄测、7组真实tokenizer控制、ruff/mypy/依赖边界及wheel/sdist逐字一致。统计、未知项、来源依赖、许可限制、聚合初次机械失败和历史R0/R1失败均保留。离线复核脚本不执行provider或更改账本。

原48项保持4限定通过/27部分/1未通过/16未验证，E0未通过、D4未准入，Product NO_GO。分支feat/lab-correction-evidence-v13-4-20261003仅本地提交，无远端发布/合并。此前逐步检查点由Git历史及其各自冻结manifest保留，不回写成终态。

- [最终统计](../data/manifests/v13-4-t0-final-results.json)
- [G1决定](../data/manifests/v13-4-g1-decision.json)
- [N6封存清单](../data/manifests/v13-4-n6-closeout.json)
- [122项要求与原48项继承](../data/manifests/v13-4-requirements.json)
- [本轮进度终态](../data/manifests/v13-4-progress.json)
