---
version: v12.0
date: 2026-09-25
status: COMPLETE_WITH_SCOPED_ENGINEERING_VALIDATION
scope: MiLAi-Lab
baseline_commit: 822efff48e92f03a493385646a5520a409f2123a
final_source_mapping_sha256: f39d8170f168a56d21057a3079fdaed21a5cb6d32e852687544dd740df8955d0
---

# v12 写入、维护与恢复结果

v12 的 A—E 开发及所选小规模诊断已完成。已读材料通过其他别名合法用于原卡修订；失败尝试不能被 `processed` 静默清除；实际退款后的维护能够恢复且不重复业务。零尝试漏维护在第一次诊断仍出现，随后仅澄清结束工具说明，在相同原生消息的隔离复核中更新了原卡。该结果限于已暴露的开发片段，不证明通用可靠性、完整 arc 成功或方法收益。

[最终冻结](../data/manifests/contextual-memory-v12-final-freeze.json)、[结果及费用清单](../data/manifests/contextual-memory-v12-small-results.json)、[开发记录](CONTEXTUAL_USER_MEMORY_V12_DEVELOPMENT_20260925.md)记录源码、配置、实际调用、失败和制品哈希。先前 [Git 发布检查点](../data/manifests/contextual-memory-v12-publication-checkpoint.json)仍保留当时未完成的真实状态。

## 范围与身份

[选择清单](../data/manifests/contextual-memory-v12-diagnostic-selection.json)固定三条已暴露 MERIT 后缀，共五条不同的原生消息；最后仅对漏维护的同一条消息追加一次修复后复核。金额维护恢复没有增加原生消息。MERIT 源码固定为 `293933d96b1d1849e1f20d1bb324def5de9ed33f`，原消息、工具及 scorer 不变；旧 v11 闭合 bank/world 经原有接口导入，没有把 gold 加入方法输入。

所有调用均为 ordinary/notes/off，同一 Qwen3.6-35B-A3B-FP8 和 bge-m3，单控制器、模型并发 1，temperature=0，单工作流最多十二次响应、输出 4096 tokens。R1 使用 thinking=true；实际反复截断后，R2 仅把 Host 和配套 tokenizer 的 `enable_thinking` 同步改为 false，R3/R4 沿用。累计请求、tokens 和验证次数不设停止上限，账本连续保留全部失败。

| 阶段 | 源码映射 | 实际范围 |
| --- | --- | --- |
| R1 | `14a4ddb1cc5af67113980684e1516a8d86ebeead3833cce42ecfb1b59a035f5f` | 金额更正及下一集消费；退款后维护中断 |
| R2 | `e8d101e07d46e7a0856d6159e20358d8da9522c1a597a76474185fcbb497280e` | 仅调整推理设置；零模型恢复准备失败 |
| R3 | `e3811c365337ce93418cf7c0445cea4b0891d109c8f4d83e0c47d46cf5744319` | 快照修复；自然维护恢复、受控恢复和漏维护诊断 |
| R4 | `f39d8170f168a56d21057a3079fdaed21a5cb6d32e852687544dd740df8955d0` | 仅澄清 v4 结束工具目的；复核漏维护片段 |

R3/R4 配置 SHA 为 `163b8dd74c4cf34ab67e662e154072c47db89e414bb9a931650d52c3ae8efc60`。当前配置为 contextual-task-v12，action v4、maintenance v4；Memory v16、view v9、write v13、operation v2 及 RuntimeStore 磁盘格式保持。新配置身份通过正常新 Store API 导入，旧 identity/hash 不重写。三条成功路径的当前卡在最终源码下重新正常 restore/read，正文、当前版本及成功业务来源均可读取，无模型调用；这不是重新执行 R3 的模型轨迹。

## 真实结果与失败去向

| 诊断 | 原生业务 | Host / 维护 | 原卡语义及限制 |
| --- | --- | --- | --- |
| 金额更正及消费 | 两张原卡更正，下一集使用第一张的新金额成功退款 | R1 前两条消息 complete，第三条维护中断；R3 原轮恢复 complete | 两卡金额进入 revision 2；恢复后第一张到 revision 3 并记录完成；第二张保持正确待办 |
| 成功退款后恢复 | 原生 checker 通过；本诊断退款执行一次 | 在成功日志落盘、来源交付前注入中断；同 Store/turn 恢复 complete | 原 card:2 到 revision 3，正文记录完成；恢复期间无新业务调用，世界不变 |
| 零尝试漏维护 | R3、R4 原生 checker 均通过 | R3 零写 `processed`；R4 完成一次修订再结束 | R3 原 card:1@2 仍待办；R4 原卡到 revision 3 并记录完成，没有重复卡 |

R1 首次金额提案误把卡片别名当 `repair_of`，系统拒绝并记录失败。下一次提案使用准确失败操作身份，真实 COMMITTED 后清除此项。第二张卡也按原始新消息完成 delta 修订。随后业务已执行，但维护提案引用真实未读来源被拒，补读后反复截断，未决失败继续保留，未伪装为完成。

R2 准备暴露了确定性错误：`asdict(MaterialBinding)` 在内存中保留 tuple 范围，而恢复器只接受 JSON list；读磁盘正常，同 Store 写入后立即恢复失败。R3 在快照出口将 aliases 和 delivery bindings 统一为已有 JSON 格式，严格读取校验不变，无格式迁移。旧失败状态和部分准备目标均保留。真实新身份导入逐项核对 checkpoint、session、当前 turn 和 settled action 完全相同，原 R1 文件哈希不变。

R3 自然恢复用三次请求完成原卡维护，无新业务调用。成功修订没有携带旧失败的 `repair_of`，第一次 finish 因未决尝试被拒，模型随后明确、有理由地放弃已被新提交取代的旧提案才结束。受控恢复也发生了一次写入拒绝和一次 finish 拒绝，随后更新同一原卡并明确处理旧提案。两者不能误称为程序自动识别了同义修复，也不能删除这些失败费用。

R3 漏维护属于另一类问题：当前待办卡与实际成功回执均已交付，模型仍以零写结束。失败追踪本来不能证明任意正文在语义上充分。R4 仅在 v4 `finish_turn` 工具说明中区分“约定/计划”与“已执行结果”，保留合理零写入，没有新增强制保存、订单规则、语义审核器或额外模型。复核使用同一个旧原生前缀的新隔离世界；初始与最终业务世界均与 R3 相同，但 R4 更新了原卡。R3 世界没有被再次执行或覆盖。

## 费用与公共合同

| 实际阶段 | 生成请求 | 输入 tokens | 输出 tokens | 生成合计 | embedding tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| R1 金额诊断（含中断） | 20 | 147649 | 52478 | 200127 | 1313 |
| R2 准备失败 | 0 | 0 | 0 | 0 | 0 |
| R3 金额维护恢复 | 3 | 28462 | 597 | 29059 | 0 |
| R3 受控恢复 | 7 | 46351 | 1079 | 47430 | 332 |
| R3 漏维护 | 3 | 14857 | 365 | 15222 | 369 |
| R4 漏维护复核 | 5 | 31509 | 645 | 32154 | 369 |
| 连续 v12 总计 | **38** | **268828** | **55164** | **323992** | **2383** |

embedding 共十二次请求；unknown=0、Judge=0。九次截断都发生在 R1，其 106346 tokens 已计入总量，不能再次相加。R3/R4 无截断；这支持所选失败前缀可在调整后的配置下继续，但不是一般成本收益或匹配方法比较。开发代理费用独立于上述 provider 用量，未将跨模型 tokens 换算为精确货币金额。

已封存 v11 的 238 次生成 / 2453097 generation tokens / 14274 embedding tokens 仅作为历史引用；其 F 子集及导入前缀不重复累加。所有旧错误证据哈希已核对，只有当前 v12 账本按实际用量增长。

最终[同 schema 工具表达对照](../data/manifests/contextual-memory-v12-r4-contract-projection.json)为完整 JSON **4080 → 紧凑说明 1915 tokens**，节省该文本段约 **53.1%**；此前 R1 的 4015 → 1850 对照保留。R4 澄清在两种表达中都增加 65 tokens，工具目的和全部参数能力保留。这里比较的是同一版九工具的两种表达，不是总运行成本，亦不把共享推理归因给 State。

所有阶段实际有效 memory search、自动 gap 查询、版本通知均为零。原生 get_order 属于业务调用；没有将其计作记忆机制使用。没有依据启动 sidecar 优化或 Attention 比较。

## 逐项验收与检查

| Goal 项 | 当前证据 | 结论边界 |
| --- | --- | --- |
| A 固定错误 | 原规划诊断、R1/R2/R3 失败与不可变哈希；独立合成合同用例 | 原五项主体纯校验仍只称重建，不冒充完整历史重放 |
| B1 准确可见性 | HostSession 按当前 resident exact ref/kind/hash 合并范围；跨别名真实 Host delta 用例；未交付材料/正文范围检查 | 旧版本、清理的正文或其他对象不能借用；准确目标及 core CAS 保留 |
| B2 可行动修订 | 当前卡的 identity anchor / lineage 交付；错引用字段及合法去向；主体错误修复建议；R1 两卡真实 delta 提交 | 完整替换与真实拒绝仍保留，没有自动补来源 |
| C1 失败去向 | preflight/core 失败、显式修复、可选放弃、pending、合法零写入、跨轮拦截；R1 修复链及 R3 finish 拒绝 | 任意同卡成功不会自动清空全部失败；程序不证明正文语义充分 |
| C2 实际业务与维护分开 | R3 自然和受控恢复、操作身份和成功来源、零重复业务；R3 漏维护失败及 R4 原卡修订；最终正常 read | 有限片段工程结论，不能推广为所有零尝试情况可靠 |
| D 共享表达成本 | 最终同九工具静态对照、完整参数 schema 不变、部署解码证据 | 不声称总成本或方法优势 |
| E 所选原生诊断 | 三条固定后缀、五条原始消息、一次有明确修复依据的单消息复核；连续账本 | 混合前缀与分阶段源码，不是最终版本完整 arc |
| 格式与交付 | 明确配置/action/maintenance 身份、原磁盘格式兼容、最终冻结、开发及结果文档 | 原运行库不覆盖；原始制品继续 ignored |

实施阶段四份相关测试文件 71 passed；之后错误提示补充的一个实际 Host 用例单独 1 passed。R3 在既有多跨度恢复用例中加入同 Store restore 断言，先稳定复现失败，修复后恢复文件 **9 passed**。后者与此前覆盖有重叠，不能把 71+1+9 当成全量或互不重叠的总数。

相关源码与测试 Ruff、mypy 通过；最终 R4 只改工具 description，维护源码静态检查通过。vLLM 0.27.1 / xgrammar 0.2.3、any_order=False 的十个既有部署探针已通过，最终 notes/basis 的 action/final 四份生成 schema 与探针输入完全相等；未为纯说明改动重复编译或调用模型。

未运行全套测试、广泛 benchmark、六臂重跑、新 seed、额外候选、Attention 对比、LLM Judge、最终完整 arc 或 Product 迁移。没有包移动、依赖或打包变更，因此未重复构建/跨包边界测试；全部实现局限 Lab，无新增 Product import，Product API、Schema、权限与 Canonical 不变。ordinary 仍为默认。已有发布基点 `4affa206c205cb3fd11863c9ace7b91b43a7611c` 可用于回滚本次收尾修改；更早基点 `822efff48e92f03a493385646a5520a409f2123a` 保留 v12 前状态。
