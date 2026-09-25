---
version: v12.0
date: 2026-09-25
status: IMPLEMENTED_PENDING_SMALL_VALIDATION
scope: MiLAi-Lab
baseline_commit: 822efff48e92f03a493385646a5520a409f2123a
---

# v12 写入与维护修复开发记录

用户已授权执行 [v12 Goal](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v12.0_20260925.md)。[规划诊断](../data/manifests/contextual-memory-v12-planning-diagnosis.json)作为 A 包的起点；规划的五项纯主体校验重建不冒充完整历史重放。核心实现和窄检查已完成，第一段金额更正诊断在后续业务成功后的维护阶段中断，恢复准备另有确定性错误。用户要求发布全部已有开发，本次提交保留验证未完成状态；不将发布等同于 Goal 验收完成。

一个 Sol xhigh 负责 Host、材料交付、维护、恢复及公共工具投影的集成；主控制器负责冻结、必要诊断选择、连续费用和交付。Host 实验并发为 1。Luna high 仅按用户既有授权处理下载或 Git 发布；本轮已有本地源码，无须下载。

| 工作包 | 实施状态 | 验收证据 |
| --- | --- | --- |
| A 故障固定 | 完成 | 原失败提案/准确绑定的规划证据；合成合同用例；无 benchmark 正文复制入测试 |
| B 合法写入 | 实现及窄检查完成 | 当前可见准确对象及范围；主体锚点/继承 delta；错误字段及合法去向；真实无效仍拒绝 |
| C 失败收敛 | 实现及窄检查完成 | preflight/core 失败均保留；显式 repair_of 关联；可选放弃/pending；两进程恢复不重做业务 |
| D 公共合同 | 完成零模型测量 | 同一九工具 schema：4015 → 1850 本地 tokens；完整验证/解码不变 |
| E 原生诊断 | 未完成 | 第一段两次金额更正提交、下一集退款成功，但维护中断；R2 恢复准备失败，其余两段未执行 |

已存在旧状态与配置均先检查真实兼容性。只接受显式支持的恢复路径，不编辑旧 identity/hash/CAS 以装载。若不兼容，从原生初态重建必要前缀，保留全部费用。片段和混合来源前缀不报告为当前版本完整 arc。

费用从新的 v12 账本连续累计；引用封存 v11 的 238 次生成、2453097 generation tokens、14274 embedding tokens，unknown=0、Judge=0。失败和恢复均计入，开发代理费用与 benchmark provider 用量分列。累计上限为 null；单工作流容量和问题驱动的调用依据仍保留。

本轮不重跑 v11 六臂、不追加方法比较。ordinary 默认；Product API、Schema、权限和 Canonical 不变。只有明确的剩余截断或 sidecar 证据才进入对应可选分支。

## 已确定的诊断输入

[选择清单](../data/manifests/contextual-memory-v12-diagnostic-selection.json)固定三个已暴露后缀，共五条原生消息：arc2 A1 的 episode 1 闭合 bank/world → 原 episode 2、3；arc1 A0 的 episode 3 → 原 episode 4；arc1 A2 的 episode 1 → 原 episode 2。它们分别检查金额更正后消费、退款后恢复、已完成业务的当前卡维护。

三份 bank 已通过现有 `ContextualMemory.restore` 的零模型核验，来源、内容、准确版本和向量保持不变。该接口原本明确允许 `task=None` 时切换 decision policy；A1/A2 只切换为 notes/off，A0 bank 完全相同。新运行不导入旧 active session 或旧 RuntimeIdentity，不修改原 checkpoint。最终准备还将按最终代码格式核验。

恢复诊断将在真实退款成功且原执行日志保存结果后，注入一次控制器中断，然后重新打开同一个运行库、同一 session/turn，使用原十二次响应容量的剩余部分继续。该受控中断与自然模型失败分别报告；完整业务工具保持可用，检查后续操作和世界以确认无重复退款。

v4 新 Host 字段的初次部署 grammar 检查已通过：vLLM 0.27.1、xgrammar 0.2.3、`any_order=False`，notes/basis 的 `repair_of`、普通 finish、带理由放弃、拒绝缺失理由、最终响应放弃共十个探针全部符合。调用模型次数为零；若 schema 后续变化，需核对新的冻结语法身份。

## 首次开发冻结

[R1 冻结](../data/manifests/contextual-memory-v12-development-freeze.json)包含 49 份运行/模板文件，映射 `14a4ddb1cc5af67113980684e1516a8d86ebeead3833cce42ecfb1b59a035f5f`。Host 权重、thinking=true、4096 输出 tokens、每条原生消息十二次响应和 embedding 配置沿用。新配置为 `contextual-task-v12`，action 为 `contextual-json-action-v4`，maintenance 为 `turn-maintenance-v4`；原 Memory checkpoint、view、write、operation 格式保持。新 Host 字段在 dispatch 前处理，不进入 core 写入 schema。

四份实际受影响测试文件合计 71 passed，覆盖失败拒绝、显式修复、放弃、零写入、未决快照及 v3/v4 两进程业务恢复。随后补全错种类引用的字段/短别名/合法去向，单独真实 Host 用例 1 passed；没有把后一次结果冒称整套 72 项重跑。相关 Ruff、五源 mypy 以及最后 Host/adapter 静态检查通过。未跑全套测试、打包或 Product 迁移；无包移动和依赖变更。

正式[工具投影对照](../data/manifests/contextual-memory-v12-contract-projection.json)在同一 schema 上比较原完整 JSON 展示与短说明，减少约 53.9% 的该文本段 tokens。该比例不是总任务节约；工具目的和实际验证/解码能力保留。最终 schema 与上述十个部署探针的输入相等，因此没有重复编译或增加模型调用。

## 本次发布时的实际诊断状态

[发布检查点](../data/manifests/contextual-memory-v12-publication-checkpoint.json)记录状态、连续费用和本地证据哈希。R1 金额诊断的原 episode 2 两条消息均完成：两张原卡通过 delta 提交了新金额，其中一次错误的 `repair_of` 被拒后，下一次提案使用准确失败操作身份完成了显式修复。随后原 episode 3 按新金额成功退款，但完成状态写入先因真实未读来源被拒，补读后又连续输出截断，最终耗尽该工作流的十二次响应容量。未解决尝试保留在 maintenance 中，没有被标为 processed。

R1 共 20 次生成，147649 输入、52478 输出、200127 generation tokens；6 次 embedding、1313 tokens。9 次截断的 106346 tokens 已包含在总计内，不能重复相加。unknown=0、Judge=0。已封存 v11 费用另行引用，不作为本轮新增调用重复计算。

这一剩余截断触发 Goal 已授权的单项配置诊断。[R2 冻结](../data/manifests/contextual-memory-v12-reasoning-freeze.json)只将 Host 与 tokenizer 容量配置中的 `enable_thinking` 同步改为 false，保留同权重、4096 输出容量、十二次响应容量及全部工具。当前提交的模板使用此设置，尚无 R2 真实模型验证。运行/模板映射为 `e8d101e07d46e7a0856d6159e20358d8da9522c1a597a76474185fcbb497280e`；冻结中的 compatibility 描述的是拟采用的导入方式，不能视为实际兼容性验证通过。

R2 的零模型准备在新 RuntimeStore 重新载入 session 时触发 `ValueError: RUNTIME_SESSION_BINDING_INVALID`，位置为 `contextual_runtime_store._binding`；准备进程退出码为 1，未生成成功准备清单。该次准备未调用模型、embedding 或业务工具，部分目标状态与 R1 原始证据保留在 ignored artifacts。真实恢复成功、无重复业务以及当前原卡完成状态均尚待验证；不能用已有合成恢复测试替代这次实际失败。另两个选定后缀仅完成 R1 准备，未执行，也未使用变更后的模板冒充 R1 运行。

后续需先定位并修复绑定快照恢复错误，再冻结必要变更并续接小范围验证。本次仅发布已有代码、测试、配置、文档和紧凑清单，不追加模型请求或大规模测试。Product API、Schema、权限、Canonical 与依赖边界均未改动；没有包移动，未重复运行边界检查或构建。发布前回滚基点为 `822efff48e92f03a493385646a5520a409f2123a`。
