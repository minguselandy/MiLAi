# v2 N3 / X4：固定前态的更新选择

状态：**已按 dfbc59d 固定方法完成八条真实维护诊断；输入/rubric未改。结果见 [N3结果](MILAI_NEXT_DEVELOPMENT_V2_N3_RESULTS_20260928.md)。**
依据 [v2 计划 §9](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v2.0.md)，独立于已完成的
[N2 读取结果](MILAI_NEXT_DEVELOPMENT_V2_N2_RESULTS_20260928.md)。运行时不读取 rubric，也不按 case ID/gold 决定动作。

## 问题与竞争解释

N2 在两个充分历史前缀上没有显示独立 A 的额外任务收益，但它没有进行任何维护，不能回答 U 的问题。
H1：按真实新观察选 U 能保留当前读取任务之外的必要更新，并减少无关候选成本。
H2：小 bank 全候选维护已足够，或实际 A 也会包含变化对象，独立 U 主要增加调用费用。
固定同一前态和共同维护合同，才能把这些解释与各自形成内容的差异分开。

## 固定数据与沿革

两个前缀共享原 Workshop handout/field/welcome 三条 State。
background_change 使用历史实际控制前态和真实 pending 用户事件：field 从 3 / west dock W-4 更新为 8 / north rack N-6，
包装保持 rigid cases，当前读取仍要求 handout 总结。new_topic 在相同前态上构造新的辅助台 A-6、08:00–16:00 长期事项。
后一项是已声明的合成开发诊断，不称未见或原生连续轨迹。

原 trace SHA256 为 `38ea180cbd0cf1e34e24f3e67b13cf2c072ba0b4a7c4056ea4e6f76942bf1a17`。
Root 将两份 State 前态与实际 trace 第 11 行（从零计数）的请求逐字段核对；background pending 的 ID/kind/content
及当前 query 与该请求相同。原 archived=False 字段为存储表示，目录视图不携带它。
原事件缺少的 actor/tool_call_id 分别归一为同 owner 与 null，所有臂一致；既有来源 ID 和正文不改。

暂停前 ignored 草案使用固定 retrieval_top2，未执行也未冻结方法。本轮按最新 v2 的观察/目录 U 目标，
采用已有事件影响提示的模型选择，允许实际空集/多选；旧草案保留，不改任何旧结果。
这轮不评价 retrieval-based U，也不把它称为已无效。

## 四臂与共同维护合同

| 条件 | 更新候选产生方式 |
| --- | --- |
| all | 全部三条既有 State，无选择调用 |
| u_selector | 一次事件影响选择，输入实际 pending 观察和同前态短目录，返回实际 update_ids |
| u_equals_a | 一次 N2 的真实目录 A helper，输入当前 query、实际 pending 与同目录；直接使用其实际 read_ids，并计费 |
| oracle_u | 显式诊断输入：background 仅 field，new_topic 空集合；人工信息只进入该臂，不读评分文件 |

U 不额外接收 current_task 字段，但实际 pending 原文已经提到当前任务，须完整保留；
不能删掉这些语句来强造 A/U 差异，也不能声称 U 从未见过当前任务的文字。
实际 A 与 U 如果相同就照实记录，不手工提供“正确 A”。

各臂使用相同现有 `local` 表示、整体 edits-only 维护、candidate_only 提示、模型和容量。
维护器只看到实际候选正文、共同 pending 和合法来源目录；来源可见不等于已绑定。
`allowed_existing_ids` 只限制既有记录，`allow_create=True` 对全部臂成立，空集合不能阻断新事项 CREATE。
使用现有 bank.apply 的实际回执、部分成功与 pending 语义，不新增 patch、语义仲裁或自动答案修正。
选择阶段不能写 bank；维护阶段只有一次提案。看到失败后不只为该臂补一次修复。

本切片为 State-only 维护诊断，ordinary memory 统一为空、没有其写入工具；ordinary 质量记 NA。
不执行 Host 回答或业务动作，不能把 State 成功扩大成两库正确或完整任务成功。
N4 反馈关闭，N5 才检查维护是否用于后续真实行动。

## 输入身份、顺序与隔离

| 文件 | SHA256 |
| --- | --- |
| [inputs](../data/diagnostics/next-development-v2-n3-fixed-update-r1/inputs.json) | `f0a835f550bfb7ce1a7046bfd504ddff1cf11089979884cc62b17edac0a58e4f` |
| [config](../data/diagnostics/next-development-v2-n3-fixed-update-r1/config.json) | `d339c9b260e221b58591cebc0fde5f02c034e46376529b9d9a30c341129d97bc` |
| [rubric](../data/diagnostics/next-development-v2-n3-fixed-update-r1/rubric.json) | `1ce5e0fae92040944bd5f72c05d70cf2e180c988ffe73b96518a2f1e7c3681a7` |

顺序固定：background all/U/U=A/oracle，然后 new_topic all/U/U=A/oracle，共八次维护诊断。
每 job 使用新的 run_id:job_id、arm、owner namespace 和独立 runtime/checkpoint 路径；初始正文、版本、needs、来源与 pending 完全匹配。
Root 在源码提交、prepare、模型 schema/参数和 scorer 都绑定后才串行执行真实调用。
控制输出上限 2048、每公开消息控制上限 13，temperature=0、thinking=false，共享服务不变。

## 验收、费用与决定

必要更新、无关保持、误改、重复事项、真实来源关系、实际提交、ack/pending 分别评价。
background 必须沿原 field ID 更新并保留 handout/welcome；new_topic 必须创建一个新事项并保持三条原记录。
拒绝所有操作或仅回执成功不算维护成功。空 oracle U 的合法 CREATE 与实际 U 是否选择空集分别报告。
当前版本仍不是真值权威，工具有效参数也不保证正确内容。

全部 U/A 选择、维护、embedding（若实际发生）、初始化、失败、Store 和观测开销保留。
生成按实际请求角色/阶段互斥计数，provider ID 去重，原连续账本只追加；固定前态诊断的形成成本没有测量，不填零替代全生命周期。
N2 终点是 2818 / 3504405 / 20093，正式运行以前的实际账本才是 N3 起点。

Continue：U 在必要变化和保持不劣下减少维护负担，或修复简单候选没有解决的缺口。
Pivot：all 或实际 U=A 已足够，则下一最小候选不保留独立 U 生成阶段。
若 oracle 也失败，先定位共享维护/消费断点；不追加 selector 训练或换样本。旧失败、费用和所有条件终态保留。
八个诊断仍来自一个已暴露历史前态，不能作为八个独立样本或泛化结论。

## 执行准入与复现入口

[检查清单](../data/manifests/next-development-v2-n3-checks-20260928.json)绑定最终源码、依赖与失败记录。
新增 N3 12项、相邻读取7项及原控制合同71项最终均通过；这是已通过分组的并集，不称一次90项运行。
最初测试账本键名、slotted Store测试替身与Mypy局部命名问题均保留，修复后只复核受影响项。
Ruff/Mypy、归属矩阵与包/工具边界通过；零模型prepare为8 jobs，身份覆盖154文件。
只做一次新入口所需离线构建，wheel/sdist源码一致；之后纯文档发布不重跑构建。
Root另核对原 UPDATE_SELECTOR_PROMPT 字节相等，旧controller的payload/schema/stage不变。
本轮测试使用MockTransport、InMemoryStore和临时账本；实际Postgres/HTTP链由后续冻结运行核查。

入口为 `PYTHONPATH=src <foundation-python> tools/run_fixed_state_update.py prepare|run-job`。
共同参数为 `--config`、`--inputs`、`--run`、`--runtime-root`；prepare另传`--output`，
run-job另传`--prepared`、`--job`、`--stage`。真实运行由Root注入私密DSN，使用原连续账本、固定八job顺序；
禁止同身份重新尝试已尝试job。正式prepare、输入、rubric、源码提交与账本快照绑定在ignored execution-freeze。
