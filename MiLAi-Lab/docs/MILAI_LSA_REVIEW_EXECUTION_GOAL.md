---
status: ACTIVE
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
reference_commit: a9290f3bc621ee7a00a61d4c9cf8c3a01d92bd46
plan_sha256: c8e7dc82f8d70665f731e1b9ff331ab100eeeee429ba90a073a125574bea9e43
---

# 16 轮复盘后的执行 Goal

用户已明确要求详细阅读并执行[新计划](MILAI_LSA_16_ROUND_REVIEW_AND_NEXT_PLAN_20260927.md)。
已完整阅读587行并核对实际 Goal 为 active；原文的“待恢复/PAUSED”是写作时状态，
此记录承接新授权，保留原规划字节和[旧16轮报告](MILAI_LOCAL_STATE_ATTENTION_OVERALL_EXPERIMENT_REPORT_20260927.md)。
不把完成定义收缩为一次修复、几条诊断或绿色检查。

## 当前基线与职责

main=a9290f3；最后实际实验源码bc5a5c8。启动时只有新计划及旧v27草稿未跟踪。
未见仍在运行的实验/下载进程。连续账本起点2677次生成、3296791 generation tokens、
18445 embedding tokens，SHA256 `64db6395c91316236291e32c5f233e823f96b98cc7a906a8a3fe985524948085`。
不清零旧失败、重试或观察费用，开发代理成本另算。

复用Sol xhigh源码负责人，独占源码/config/runner/相关窄测；Root负责本文、AGENTS、
输入/rubric、冻结、全部真实模型/embedding调用、评分和账本；Luna high负责需要的下载与
已授权Git发布；Astra xhigh只处理具体难题。每文件一个写入者，HTTP并发1。
现有Qwen/bge服务与参数作为起始参考，允许一次检验明确解释的参数变化，不擅自改共享部署。
历史上“不可调参数”的阶段规定不覆盖新授权。

## 完整交付与验收证据

| 阶段 | 要求及证明方式 | 状态 |
|---|---|---|
| D0 / P0 | 三类真实首断点+四类对照；完整合法前缀、旧State、新事件、原输出、错误位置、离线哈希/故障矩阵；部分提交重试风险复现 | COMPLETE_OFFLINE |
| D1 / P1 | 独立entry更新与回合snapshot原型；同事件重放、独立同文本、无关保持、部分成功；E1/E2分开冻结，少量重复，再测组合和真实动作 | NOT_RUN |
| D2 / P2 | 同bank全读/query检索或rerank/State A；swap/missing/oracle分列；固定前态all/U/U=A/oracle U且都可创建；约12–24对起步 | NOT_RUN |
| D3 / P3 | 最新统一底座full/G/L/最小有效LSA；4–6独立开发情景、2–3完整重复起步；逐情景strict/整轨迹/事实/ID/动作/无依据断言/State/费用 | NOT_RUN |
| D4 / P4 | N/d/a/r/H少数独立代表点；真实互动增长；full可容纳历史与超窗策略；query/summary；R与U=A必要消融及维护摊销边界 | NOT_RUN |
| D5 / P5 | 按模板/工具/约束族留出；新MERIT前瞻selection且官方scorer；MemoryArena隔离适配与原生评分；核心冻结后两模型小matched | NOT_RUN |
| D6（条件） | 只有oracle/正确State有用而在线selector仍差才训练；训练来源/费用与测试隔离 | NOT_TRIGGERED |
| P6 / 论文最小包 | 主claim、强基线、同bank A/固定U/U=A/R消融、敏感/保持反例、在线未见、独立模型方向、全费用和适用边界；无益机制明确收缩 | NOT_DONE |

数目是起点，不是永久runtime限制。新增重复由噪声或明确疑问决定，不择优拼接。
所有阶段可依证据缩小具体机制主张，不能用尚未运行冒充无效或已完成。
第二模型端点与MemoryArena原生隔离/评分仍未完成；MERIT seeds0–4已暴露。
归档/物理删除继续列未完成，当前算法诊断不以其为前置；Product NO-GO，旧v27部署不恢复。

## 执行纪律

先静态/离线定位确定缺陷，再由Sol修复和必要窄检查，冻结源码/输入/模型合同/scorer/顺序/
隔离后由Root串行真实调用。旧批次只用于故障选择/方差，不混算成新源码成绩。
运行输入只能来自相同owner、已发生的合法历史；rubric/oracle与runtime隔离。
条件能力和在线formation分开；oracle不能计入方法分数。每项保留失败及总成本。

失败记录含Observed、Expected、实际因果链、首断点、两种可区分解释、最小通用修复、
新反例、混杂、费用和Continue/Pivot/Kill。支持实际文本保持不等于支持语义正确；
Store成功不等于维护正确，Host完成不等于动作正确，合法引用不等于语义支持。
相同信息简单方法更优时删掉无益调用；不无限提示补丁，也不以单次失败停止整个研究。

## D0 当前检查

Root正在从既有维护反例、LR保持失败与完整历史对象key错误中提取只读前缀，
保留原消息/工具schema和真实输出；另覆盖无变化、同文本不同事件、用户改值、部分成功。
Sol验证§3.5的混合edit风险：H1为部分成功写入后整批pending重解释，H2为相同内容写入
实际幂等且已观察二次应用发生在独立Host；两者可以同时成立，不能以静态风险改写历史根因。
当前没有新增实验模型/embedding调用，没有新参数比较。

D0已完成：见[故障矩阵](MILAI_LSA_REVIEW_D0_FAILURE_MATRIX_20260927.md)。十个前缀逐一匹配
旧已发布trace hash，runtime只保存完整原HTTP request；rubric/旧输出另存。三类首断点及
无变化、同文本不同事件、真实改值、内部回执、部分成功对照齐备。确定的重复create缺陷
已修复，最终相关6项窄测及目标静态通过，旧State兼容；仅证明精确事件集合/编辑槽重试。
根链路为120个文档本地链接和十组输入/evaluator哈希核对通过，计划和账本原字节不变。
D1下一步按新计划先做时间边界小诊断和最小原型，再独立检验局部entry；不增加无益审核器。
