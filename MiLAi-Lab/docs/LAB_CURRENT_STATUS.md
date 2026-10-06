# MiLAi Lab 当前状态

更新：**2026-10-06 10:58:17 Asia/Shanghai**。继续 I2、B0/B1/B2/M 和现有 Qwen3.6 家族。
最新固定 `2335ea9` 的思考模式原分支完成 **44 次/184,643 known token**，39 stop/
5 length；共同条件分支 **0/36，未启动**。M 实际增加/撤销例外并保留已存在的一般
规则，但初始形成截断、旧限定缺失、最终 Reader 不完整，尚无可用候选或方法优势。
四组空查询正确返回空维护并保持实际状态、版本和支持。**Product NO_GO。**

此前 `8ed7826` 非思考复核/来源控制 132 次/236,165 token 的失败全部保留。
新表示的显式条件绑定与分组视图正在实施，源码未稳定、检查未完成，未纳入本次报告。
旧 `4357d46` B0 277/277、B1 115/277 完整边界收尾、B2/M 未开始；当前无模型队列
运行。剩余完整历史、原生/漂移、保留用户、外部任务和 Host 功能未完成，完整计划
仍在执行。发布新增模型调用 0；PR85 保持 draft、未合并。

`2335ea9` 自身 Fast/Full 均已成功（Full 21/21）；此前 `8ed7826` 自身 Fast/Full 成功。
新报告自身 CI 单独核对。当前结果见 [v2 进度](MILAI_EDIT_V2_PROGRESS_20261005.md)、
[状态清单](../data/manifests/milai-edit-v2-current-status-20261006.json)、
[44 次模式诊断聚合](../data/manifests/milai-edit-post-b0-model-mode-results-20261006.json)及
[复现入口](MILAI_EDIT_REPRODUCTION.md)。v1 M 已 FAILED 收口，历史快照不代表等待跑完。

## 2026-10-05 v1 历史快照

更新：2026-10-05。当前执行 [MiLAi-Edit 原计划](MILAI_EDIT_LITERATURE_AND_EXPERIMENT_PLAN.md)，
从 PR82 main `fc1c6c9` 隔离开发；按用户指令仅用现有 Qwen3.6 家族。
08:22 的发布快照中 B0/B1 各完成 277 个会话，B2 完成 46/277，M 未开始。
工程实现与准备工作已完成多项检查，四组配对分析、E2–E5 实际实验和最终贡献结论仍未完成。
实验继续运行，发布不表示暂停或合并。完整指标、失败、消耗和后续工作见
[本次进度报告](MILAI_EDIT_CHECKPOINT_20261005.md)、
[结构化快照](../data/manifests/milai-edit-progress-20261005.json)与
[执行记录](MILAI_EDIT_PROGRESS.md)。Product 仍为 NO_GO。

## 封存的 r52 状态记录

更新：2026-10-04。PR81合并后，原v13.5规定的同版本开发实验及140项终态回填已执行。**功能验收PARTIAL，无稳定推荐配置，Product NO_GO。** [终态报告](V13_5_R52_TERMINAL_REPORT.md)说明已验证路径和仍失败的语义／协议边界。

| 范围 | 当前证据与限制 |
|---|---|
| GitHub | [PR81](https://github.com/minguselandy/MiLAi/pull/81)已合并为0359fc0a6930d67b4f97ab32a418234d9d01b02d；[PR82](https://github.com/minguselandy/MiLAi/pull/82)承载后续修复与终态交付 |
| 源码／配置 | 2166cc746cff1665bfa809a9fc59757bf0b8b5d6／configs/v13-5-functional-r52.json；全部r52队列内源码、模型、额度不变 |
| 修复 | v7自然续办解析旧明确保存请求，并明确待解析／固定／必须为空的字段；实时工具来源支持实际结果，旧unknown不改写 |
| 工程 | 34直接回归、10生产tokenizer探针；Fast37167346609成功且执行366相关检查；Full37167346588跳过。文档提交的远端结果按PR实际head另核对 |
| W1定向 | r51两案失败；r52两案限定通过。与完整L2分开，不拼分 |
| L1 | 原24案／48消息全部完成；原rubric24 PASS；新增合同23限定通过／1普通回答失败 |
| L2 | 12故事／26消息全数尝试：9限定通过／3失败，含4条预设W1 UNKNOWN；两次多余动作被拦截，一次核对截断未保存 |
| L3形成 | 57请求：41限定通过／16失败；52条记录中11条语义失败，5请求无记录；56 COMPLETED／1 BUDGET_EXHAUSTED |
| L3读取 | 30题全COMPLETED：17限定通过／13失败；原题25满分／4部分／1零分；4题仍缺必要边界或正文 |
| 新L4 | 方法冻结后12故事／31消息全数尝试：9限定通过／3失败；限定语支持不足、未知开始周丢失、遗忘前提供方截断分别保留 |
| 已曝光遗忘复核 | 预先限定一次相同配置重复，3条模型消息限定通过；实际撤销1记录／3来源，后续HTTP及缓存/显式重放无旧正文。原L4失败不变 |
| FUNC与详细终态 | FUNC01–16：10 PASSED_SCOPED／5 PARTIAL／1 NOT_PASSED；140项：106／29／5。阶段F1–F4及L1–L4仍PARTIAL |
| 原历史 | 原48项状态及各轮首失败保留；v13.4 Simplify、T1–T3退出和F5后置不变 |

当前未观察到跨owner暴露、假保存、重复实际业务效果或来源身份损坏，但这不证明一般语义或授权正确。同模型核对有误拒、漏判和反复提案；当前意图仍可能解释偏差。新值正确也不能抵消支持来源或时间范围错误，正常返回不等于完整任务成功。

PR81合并后共981次生成／6,837,116 tokens；r52为968次／6,769,711 tokens，含直接与已曝光复核，分层分数不相加。v13.5累计5,664次／32,171,526 tokens。原连续总账15,390次generation、59,863,812 known／59,894,199 charged，历史unknown 1及30,387差额、964,645 embedding tokens保持。本阶段无新unknown或embedding；不含开发代理开销，美元/GPU/物理IO未知。

八个后续队列3,052文件逐hash封存核验。当前r52没有孤立HTTP或缺终态；历史r25便捷CLI副本覆盖、r28一项缺终态仍披露。已曝光遗忘复核的两次0HTTP恢复另存VISIBILITY_REVOKED attempt，latest脱敏结果与原COMPLETED模型attempt区分，原始记录不覆盖。

## 证据与操作入口

- [终态报告](V13_5_R52_TERMINAL_REPORT.md)、[终态机器清单](../data/manifests/v13-5-r52-terminal-results.json)。
- [r51/r52修复与逐轮结果](V13_5_R51_CONTINUATION_REPAIR.md)、[L3结果](V13_5_R52_L3_RESULTS.md)、[L4结果](V13_5_R52_L4_RESULTS.md)。
- [使用／恢复／遗忘／回滚](V13_5_FUNCTIONAL_USAGE.md)、[FUNC汇总及历史](V13_5_PROGRESS.md)、[140项终态](V13_5_REQUIREMENTS_AND_ACCEPTANCE.md)。
- [原计划](MILAI_FUNCTIONAL_DEVELOPMENT_EXPERIMENT_PLAN_v13_5.md)、[执行协议](V13_5_EXECUTION_PROTOCOL.md)、[PR81合并记录](V13_5_DEVELOPMENT_MERGE_20261004.md)、[历史暂停原件](V13_5_PAUSE_STATUS_20261003.md)。
