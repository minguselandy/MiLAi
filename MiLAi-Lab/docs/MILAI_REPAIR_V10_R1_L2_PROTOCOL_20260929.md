# R1 L2：完整轨迹标签预防诊断

2026-09-29，预先登记，真实调用尚未开始。实际完整 v10 Goal 已授权；[L1](MILAI_REPAIR_V10_R1_L1_RESULTS_20260929.md)仅允许继续独立冻结的 L2，未晋级。方法源码 c0bec6a7；执行提交在发布本协议后记录于私有 execution-freeze.json，结果报告将公开其 SHA。两份旧的工程 prepare 保留，不复用其运行目录。

## 变量、样本、顺序

[选择清单](../data/manifests/repair-v10-r1-l2-selection.json)保留原生输入和初始世界字节。d2-arc18、20、22 为已曝光异常；19 为正常多步对照。各五个完整 episode，共四个独立 arc 来源，两个条件八次尝试、40个 episode、52条公开消息；不称八个独立样本或 unseen。

两份诊断输入：[legacy](../data/diagnostics/repair-v10/r1-l2-legacy.json)、[native_roles_only](../data/diagnostics/repair-v10/r1-l2-native_roles_only.json)。只允许标签开关和隔离身份不同，继续使用 ordinary_milai、原生 native Agent/业务工具/checker、原有记忆位置、原文历史、模型参数与12次消息容量。无 R2 保护、额外 writer、来源补充、全局字符串清洗或重新评分。

固定全局顺序：arc18 legacy→candidate；arc20 candidate→legacy；arc22 legacy→candidate；arc19 candidate→legacy。每组内部顺序均18、20、22、19；Root串行完成一条后才启动下一条。一组一条 arc 一个独立 run ID、namespace、Store作用域、checkpoint、journal和初始合成业务 world。绝不续跑旧失败世界。不以结果选择重试或替换。

## 执行边界与停止条件

本批业务部署、配置与工单均为 MERIT 的隔离 SQLite 合成效果，不接入真实变更服务。既有每公开消息最多12次生成、65536上下文、4096输出、temperature=0、thinking=false保持；容量中断保留未完成状态与已发生效果。已知的、仍受此合同约束的沙盒额外动作是本批观测量，不能静默拦截后当成 Agent 成功。原生 checker 仅用于评估，不决定停机。

Root检查实际请求、journal与世界；发现跨owner/namespace、非沙盒外部变更、并发/计账/容量保护失效或新的无法约束的变更链，立即停止受影响进程并保存外部停止记录，暂停同一故障路径。SIGINT由runner最外层BaseException保留FAILED；内部episode可能只有pending，不能补造完成记录。未返回HTTP用量或尚无回执的效果标UNKNOWN，保留实际账本和SQLite，禁止自动重试。普通答案错误、原生格式失败、正常容量中断不取消其他隔离且安全的已冻结任务。

这不是任务授权防护：首次额外动作和新call ID重复动作仍分别分析，不能声称12次上限证明行动必要性。R2独立。

## 冻结与验收

正式 prepare 在本协议发布的同一HEAD进行，使用新的 r1-l2-execution-r1 目录。冻结源码及依赖、原生输入/world/tools/checker、两组recipe、tokenizer/template、服务参数、prepared identity、上述顺序和账本起点。重建身份失败不调用模型。所有请求/embedding仍计入原始连续账本，失败和观察成本不删除。

先保留原生 episode/arc结果、已完成和未知分母，再独立报告真实标签复述、普通重复、finish_reason、首次额外动作、重复变更、合法多步控制、工具与最终状态、实际记忆CRUD/后续交付和全过程费用。零CRUD不自动判错，也不把答对算作维护成功。结果必须关联实际HTTP、工具参数/ID、journal、世界与checkpoint，不能用退出码验收。

只在机械合同成立、完整回归没有新的严重副作用、目标故障有可复查改善时考虑标签候选晋级；输出改善不代替动作可靠性。两组均未出现故障时保留因果不确定性，不追加抽样求显著。全部样本是已曝光开发诊断；独立确认仍需R7门槛。
