# v13.2 E2真实SDK预检：原接口、并发版本与限定范围

原E2三配置、曝光开发输入和设计方向均保持。39项实际schema/Source/角色/hash/读取版本/历史检查退出0；独立的三接口SQLite/Store控制使用合成公开Source，完成关闭后重开，0真实生成/embedding。

| 原身份接口 | 中文Source查询英文卡 | 两个提案基于同一旧读版本 | 最后版本 |
| --- | --- | --- | --- |
| 旧target_query、回链关闭 | 0候选 | 第二提案内部填提交时latest后仍commit | 3 |
| 来源回链、ID/revision | 1候选 | 第二提案revision_conflict/rejected | 2 |
| 来源回链、read handle/patch | 1候选 | 第二提案revision_conflict/rejected | 2 |

本表三格交错控制均走manage_memory/action=update，以对应查询、ID/revision或handle绑定；patch专门入口仅由既有39项检查覆盖，本表不另称新增patch证据。

每库只保留一个记录，初版历史与scope/exclusion保持，真实SDK重开DB hash不变。旧查询没有读取版本冲突保护是这里保留的基线行为，未改成新接口。跨语言卡由机械控制构造，不是模型生成或自然任务成绩；自由文本含义仍unchecked，不能据此宣布泛化、用户纠正或最终回答通过。

共同审查候选为compact_v1、shape_feedback_v1、typed_read_v1、completed_receipt_v1和已验收serialized_ledger_owner_v1的真实完整9字段Host/embedding domain。三格只变来源回链和候选合同，原读入策略、一次after_host_final_v1形成、repair0、Host12/output4096、普通2048/max6和原账本保持。direct_support_v1/selected_snapshot_v1都要求read_handle，不能共同强加给原旧查询/ID接口，三格对此均维持legacy。以上仍是离线审查副本，模型运行未冻结、未启动。

Root首预检用了不生效的vllm_http_ownership字段，实际prepare走legacy并无binding；在模型前复查真实http_ownership_profile/domain后，新副本/actual freeze明确完整domain与原canonical ledger。原错误文件/result保持，39检查不重跑，实际模型HTTP0。三接口首控制另因Root把read_memory.value.revision错读为顶层revision退出1；原失败库/代码/before maps保留，缺当时after maps不倒补。恢复克隆原首库继续其已真实创建的卡、不重新create；新结果和新增诊断读都另存，不改原失败。两者均是Root审计工具/配置问题，不称Source或模型失败。

原账本SHA8547f1ef8d32455ad121799e5c0132a3de24a992067408c4fbbb73d2fb199ca5及四组Source/tests/configs/tools全量maps保持；0升级/部署/实际模型HTTP。新通用可选工程在独立Source工作树验证，尚未转入该快照。

[机器结果与原件索引](../data/manifests/v13-2-e2-root-admissibility.json)。原48要求行、E0 NOT_PASSED/D4 NOT_ADMITTED/Product NO_GO与完整计划ACTIVE保持；本结果不能替代新E2自由模型切片、E0正常24/48或独立Judge。后续先验收独立通用opt-in工程，再冻结实际模型身份与成本。
