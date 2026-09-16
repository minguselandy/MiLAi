# V0218 E5：完整研究决策与验收

日期：2026-09-11。范围：[Goal v0.2](MILA_V0218_行为真值测试床建设_GOAL_20260910.md)
的 T0–T5/E0–E5；不是 Product 发布或对旧实验结论的重写。

## 决策

本批关闭为 **KEEP_SIMPLE_NO_CANDIDATE + ENGINEERING_GAIN_ONLY**；
测试床单列 **TESTBED_CONTRIBUTION_CANDIDATE**，仍需外部复核。
合格机制候选 0，E3/E4 均 NOT_TRIGGERED；不是偷偷省略必需确认，也没有把 D 改称 C。

E0 已显示真实失败，故不使用 BASELINE_SUFFICIENT_IN_TESTED_SCOPE。
E1 的 C2 在同一个日程更新 root 的两次冷运行都提高了完整任务成功，工程信号保留。
但 [E2 同信息对照](MILA_V0218_E2_RESULTS_20260911.md) 中普通复核 R1 达到与 C2
逐对相同的结果，C2 特定结构指令的独立必要性未获支持；新闻更新及两种未决任务均仍有失败。
不把 R1 临时改名为第三个“新机制”绕过筛选；不继续重复直到显著。
保持 N1 为研究比较基线和简单方案；这不表示现有功能已经充分可靠。
本 Goal 完成的是有界实验和明确决策，不是“创新成立”。

## 全阶段验收

| 阶段 | 实际产物 / 原始依据 | 判定 |
| --- | --- | --- |
| T0 来源与边界 | [获取清单](MILA_V0218_BENCHMARK_ACQUISITION_20260910.md)、pin/license/hash、适配声明 | COMPLETE；MemTrap 匹配制品仍 HOLD，不冒充已下载 |
| T1 世界合同 | [执行合同](MILA_V0218_TESTBED_CONTRACT_20260910.md)、12 原 lineage/9 coarse family 的 SQLite/world/source manifests | COMPLETE_LIMITED_ADAPTED_PROFILE |
| T2 校准 | `t5-validation-v1` 49 实际脚本分支、gold/身份/类型/漏写/CAS/无关/未决/reset/clone 反例 | COMPLETE；不是只跑单测 |
| T3/T4 真实链和扩展 | [T3](MILA_V0218_T3_PRELIMINARY_20260910.md)、[T4](MILA_V0218_T4_PROGRESS_20260911.md)，2 独立原 root 自写 Note/冷公开读取/真实 HTTP 旧新双呈现，NO_WRITE 保留 | COMPLETE_LIMITED_PROFILE；金融 Note 混合正确性如实记录 |
| T5 建设门 | [复核](MILA_V0218_T5_REVIEW_20260911.md)、`t5-seal-v1/testbed-manifest.json` | G_TESTBED PASSED；开发者自审，非独立人审 |
| E0 强简单基线 | [共同 v4](MILA_V0218_E0_V4_20260911.md)，固定六原 root/42 episodes + 两重复 root/20 probes；N0/N1/N2、统一 S*=N1 | COMPLETE；未混合旧协议分数 |
| E1 有界发现 | [两批](MILA_V0218_E1_DISCOVERY_20260911.md)，2 候选、2 原 root、28 episodes/24 冷双呈现 | COMPLETE；只追加一次有触发依据的冷复验 |
| E2 消融/筛选 | [完整结果与两张不晋级卡](MILA_V0218_E2_RESULTS_20260911.md)，32 episodes/五臂/同资料/同机会/近邻概念 | COMPLETE；选中机制卡 0 |
| E3 冻结 pilot | 无合格机制候选 | NOT_TRIGGERED，0 requests |
| E4 独立确认 | 无合格候选；且全部 12D、未打开 C=0 | NOT_TRIGGERED，0 requests；不支持独立机制确认 |
| E5 最终判断 | 本报告、成本/负例/近邻/不足与下一步、终结审计 | COMPLETE |

§17.2 六项验收分别由上表 G、E0、E1/E2、E3/E4 明确条件、E5 报告、全账结算/清理支撑。
不以 token 消耗、论文收益或测试数量替代任何一项。

## 收益与反证

E0 标准 B：N0 8/12、N1 7/12、N2 5/12；probes 另报，不能因 Note 没有写就换题。
其失败包含未自主取得、部分交付、错误算术/类型、CAS/参数拒绝、不必要暂停、
正确新事实已在上下文但未行动，以及未实际提出澄清。它们并非自动等于记忆因果错误。

E1：C2 8/8 B、N1/C1 各 6/8，胜例集中于同一日程更新；两次复验不是新增任务。
E2：C2/R1 各 3/6、N1/C1/P1 各 2/6。全部 Stable 通过，只有日程更新 C2/R1 通过。
E2 有新自然 A、共同公开预读，不能与 E1 普通入口直接算前后增益。
C2 少于 R1 的调用/输入成本可以记录，但只有一矩阵，且实际文本长度不同，不构成创新证据。

最有约束力的负例：

- 日程未决确实提交了澄清，仍留下旧 confirmed=true；“有问题单”不能掩盖活动记录错误。
- 新闻更新 C2 保存了一份错误的“已验证、已完成”检查点，却完全没有实际业务修改。
- P1 有时读懂更新/冲突并执行部分修改，但混用旧引用或未实际提交澄清，完整 checker 仍失败。
- E1 新闻更新的效率收益第二次并不稳定；旧协议截断/解析失败均留在总成本，不删去。

组件消融比较的是明确指令及行为，不证明隐含认知过程。R1 会自发写旧新关系；
这阻止对特定结构必要性的正主张，但也不能据此证明任何形式的状态表征都无作用。

## 近邻与贡献边界

[候选明确后的全文/代码定位复核](MILA_V0218_PRIOR_ART_20260911.md)记录日期与 v1 版本。
StateMemWrapper 已覆盖先追踪更新再决断及普通摘要对照；P1 是本轮披露的动作世界概念适配，
不是原生 StateMem/官方成绩复现。没有定位匹配官方代码的缺口保留。
已有 proactive memory、executive memory、规则记忆和 E-P-R 行为诊断，
使“主动提醒/工作状态/旧新关系/恢复”这些名称本身不足以建立新颖性。
不存在未经同条件验证的“超越最近邻”结论。

测试床的实际差异是外部 task 派生、完整对象 postcondition、缺陷反例校准、
真实公开 Note 冷持久及实际请求字节链、Stable/更新/未决/Helpful/无关控制。
但自建 checker 不自动成为学术贡献，T5 为开发者自审；需要外部独立实现/审查。
因此只保留 TESTBED_CONTRIBUTION_CANDIDATE，不用它替代机制贡献。

## 全流程成本与失败保留

| 批次范围 | requests | raw tokens |
| --- | ---: | ---: |
| T3/T4 建设（含两次兼容与失败协议） | 210 | 384080 |
| 旧 E0 三波 v1（含第三波停止） | 240 | 499308 |
| 共同 v4 E0 三标准波 | 314 | 729451 |
| E0 单列 probes | 177 | 555600 |
| E1 首次 | 139 | 393907 |
| E1 第二次冷运行 | 130 | 342620 |
| E2 完整五臂控制 | 130 | 448148 |
| 总计 | **1340** | **3353114** |

E0/E1/E2 自然共享 A 只计一次；兼容 2 次已包含，E1/E2 新兼容 0。
Judge/embedding/OCR/caption/training 新调用均为 0；累计 raw cap=null。
全部实际 Provider 账本已结算，pending/violations/unknown=0；不是把上界当作实际消耗。
E2 130/512 次、32/32 FINISHED，351.68 秒；没有任何 E2 episode 用尽生成上限。
所有本批自有 API/compose 已停止，卷和失败证据均保留；共享模型服务未被停止。

## 原始证据定位

统一基目录：`/cra/memory/mx_memory/evidence/v0218/`。

- `20260910/{t3-note-chain-v1,t3-note-chain-v2,t3-note-chain-v3,t4-note-chain-v1}`：建设完整账。
- `20260911/e0-baseline-wave{1,2,3}-v1`：旧协议；第三波停止证据保留。
- `20260911/e0-baseline-wave{1,2,3}-v2`、`e0-probes-v4-v1`：共同协议 E0。
- `20260911/e0-v4-summary-v1.json`：所有前 E1 run/result hash 索引与已审计分母，
  SHA256 `1b469d4318ca993dca96ee2b59e7d3e2fed915caa7f3276fb5bb7e0a4d13f643`。
- `20260911/e1-discovery-v1`：result `2c656f30aec3f4663337ee634e11eb075a8ff2466e01b4e07e11371a2a2903e5`。
- `20260911/e1-discovery-r2-v1`：result `ab921ec71c608f63d1f236b5ebb1144865336872ce993d558a47142832a76cad`。
- `20260911/e2-controls-v1`：result `b1242e740baa3ef67c8c32a4ca4eee5de75ba271830623d558ac2fbcd0979f74`；
  audit `4c478b986c69a6406042649bfa721210352f488a99dafdc9c4108c945b6d6dcf`；
  summary `3445b902dd9d15a9f764987d07edcfbdb291c8810acafd57a2bb9c96f08a87f9`。
- `20260911/t5-seal-v1/testbed-manifest.json`：G seal
  `b2b0937bc4167a4276986264069ee158fd07fb1b40a71bcb9cb1497caa71d5a9`。
- `20260911/final-decision-v1/completion-audit.json`：离线终结检查、14 个已关闭模型批次、
  当前报告/代码/门日志 hash；由 `tools/finalize_v0218.py` 生成，不调用模型。

## 限制与下一步

只研究一个本地模型、12 已暴露原 task 的适配；E0 用 6 root，候选筛选用 2 root。
两种 Helpful 来自同一 coarse family；测试床全部内容是 D，没有独立 C，
也没有从本实验推断人类/ADHD/临床或普遍记忆机制。
移除了部分原生多模态/外部服务能力，不宣称 ClawMark/WMA/Supersede 原生成绩。
许可遵循 pin 对应上游（包括非商业数据）；benchmark corpus/凭据不进入 Git。

功能后续可优先研究通用的“取消失效确认 + 实际澄清交付”与防虚假完成检查，
但需另立模型前合同、强简单复核对照和独立来源；不在本次失败后直接修题改分。
如追求机制确认，先取得真正未打开 C 和最近邻可比实现，再预冻主指标与必要消融。
这些是下一研究建议，不是本 Goal 未执行的强制工作，也不是部署授权。

最终软件门：1258 tests passed / 1 optional SDK skip；boundary、Ruff、mypy、build、diff-check PASS。
无 Product 行为/API/schema/权限变更、A0 切换、旧保护池访问或公网部署。
