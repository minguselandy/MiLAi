---
kind: RESEARCH_PROTOTYPE
status: DB_MAIN_AND_VERIFIED_TERMINAL_OVERALL_RESEARCH_PAUSED_BY_USER
date: "2026-09-16"
solver_profiles: 1
---

# ReasoningBank／MiLAi：DB 正式主比较结果

## 当前结论

DB 四方法 F/O 主比较与正确历史回放参考已全部结束，共 820 项任务执行。MiLAi 相对 RB 的正确率点估计在两种协议均提高 5 个百分点，但区间未能确认预定的最小有用收益。MiLAi 的正确率低于 Native，已结算 TEST tokens 约为 Native 的 4.12 倍（F）与 3.89 倍（O）。当前 DB 证据不支持用该候选替换 Native。

MiLAi 的 200 项主任务没有来源回读事件、获准的自然修订请求或修订补丁。实际采用备注进入 Actor 输入已有证据；本域观察到的分数差异无法归因于使用中修订。完整研究已由用户暂停，OS、旅行、贡献／资源比较与普通消费诊断仍待完成。见[暂停开发总结](MILA_EXPERIMENT_DEVELOPMENT_SUMMARY_PAUSED_20260916.md)。

## 设置和覆盖

- 单求解模型 Qwen3.6-35B-A3B-FP8；候选 v0.4、RB 本地基础移植 v0.3，BGE-M3 检索，reranker 关闭。第二求解模型按用户要求暂缓。
- F：每种记忆方法用正式 SUPPORT 的 40 项 DB 任务形成银行；100 项 TEST 独立使用冻结银行，测试后提炼不跨题提交。
- O：每方法五条独立流，每流 20 项，从空银行开始，任务后在线提交；每方法合计仍是同一组 100 个 TEST ID。F/O 使用同一批题，不能合并为 200 个独立来源。
- 主比较每行 100/100 终态且原生评分可用；正确历史参考 20/20。所有计划项进入分母，本表没有缺失任务或未知用量请求。
- DB 原生每题最多 3 轮；主设置每题 300,000 raw tokens／64 次生成／180 秒请求准入上限。进行中的请求受 HTTP 与 worker 截止限制；这不是严格的单题墙钟终止时间。

## 主结果

下表 tokens 为 TEST 中 Actor、采用、自判、提炼、Observer／Reflector 等实际生成的完整结算用量。支持形成成本另列，embedding 独立计量。终态记录与原生 `completed` 状态含义不同。

| 协议 | 方法 | 终态/计划 | 原生正确率 | 生成 | TEST tokens | embedding 请求/tokens |
| --- | --- | --- | --- | --- | --- | --- |
| F | Native | 100/100 | 90% | 236 | 243,946 | 0 / 0 |
| O | Native | 100/100 | 88% | 241 | 249,276 | 0 / 0 |
| F | OM | 100/100 | 93% | 210 | 5,488,092 | 0 / 0 |
| O | OM | 100/100 | 88% | 238 | 2,384,121 | 0 / 0 |
| F | RB | 100/100 | 76% | 488 | 813,100 | 100 / 22,104 |
| O | RB | 100/100 | 77% | 472 | 771,545 | 100 / 21,440 |
| F | MiLAi | 100/100 | 81% | 568 | 1,005,450 | 100 / 22,104 |
| O | MiLAi | 100/100 | 82% | 552 | 968,859 | 100 / 21,440 |

## 配对差异

差值为 MiLAi 减对照，单位为百分点；tokens 比为 MiLAi／对照。按冻结规则执行 10,000 次配对重采样，seed 20260915。F 按 99 个来源簇，O 按五条独立流。

| 协议 | 对照 | 正确率差 | 95% 区间 | TEST tokens 比 | 重采样单位 |
| --- | --- | --- | --- | --- | --- |
| F | Native | -9.00 | [-16.00, -2.02] | 4.122 | 99 source_cluster |
| F | OM | -12.00 | [-19.19, -5.05] | 0.183 | 99 source_cluster |
| F | RB | +5.00 | [-3.00, 13.00] | 1.237 | 99 source_cluster |
| O | Native | -6.00 | [-11.00, 0.00] | 3.887 | 5 stream |
| O | OM | -6.00 | [-14.00, 1.00] | 0.406 | 5 stream |
| O | RB | +5.00 | [0.00, 9.00] | 1.256 | 5 stream |

预定目标为质量至少提高 5 个百分点且 tokens 比不高于 1.25，或质量非劣界为 −2 个百分点且 tokens 比不高于 0.8。MiLAi 对 RB 的 F 点估计恰到质量目标、TEST tokens 比为 1.237，但区间为 [−3, 13]。O 的区间为 [0, 9]，仅有五条流，TEST tokens 比为 1.256。这些结果尚未建立达到使用目标的证据；区间端点为 0 也不证明总体等价。

区间以一个求解模型、每银行一次支持形成与固定解码为条件；不包含跨模型或支持形成随机性的稳定性。OM 的 F 正确率最高（93%），同时消耗约 22.50 倍 Native TEST tokens；质量与成本需一并解释。

## 支持形成与全角色成本

O 从空银行开始，形成经验的调用已计入在线 TEST。F 的支持形成费用如下；这些已结束的 DB 支持流仍属于包含旅行的整体 SUPPORT 阶段，此报告不重复关闭或记账。

| 方法 | 支持任务 | 生成 | 支持 tokens | embedding 请求/tokens |
| --- | --- | --- | --- | --- |
| OM | 40 | 92 | 1,422,803 | 0 / 0 |
| RB | 40 | 190 | 307,560 | 40 / 8,362 |
| MiLAi | 40 | 226 | 387,232 | 40 / 8,362 |

| 方法 | F TEST + 一次 DB 支持形成 tokens |
| --- | --- |
| Native | 243,946 |
| OM | 6,910,895 |
| RB | 1,120,660 |
| MiLAi | 1,392,682 |

计入一次支持形成后，MiLAi／RB 的 F tokens 比为 1.243，仍不改变质量区间未达到预定收益门槛的解释。

| 协议 | 方法 | 角色 | 生成 | tokens |
| --- | --- | --- | --- | --- |
| F | Native | actor | 236 | 243,946 |
| O | Native | actor | 241 | 249,276 |
| F | OM | actor | 210 | 5,488,092 |
| O | OM | actor | 230 | 2,272,005 |
| O | OM | observer | 8 | 112,116 |
| F | RB | actor | 288 | 456,389 |
| F | RB | self_judge | 100 | 152,627 |
| F | RB | extract | 100 | 204,084 |
| O | RB | actor | 272 | 417,499 |
| O | RB | self_judge | 100 | 151,362 |
| O | RB | extract | 100 | 202,684 |
| F | MiLAi | adopt | 100 | 130,308 |
| F | MiLAi | actor | 268 | 528,795 |
| F | MiLAi | self_judge | 100 | 148,067 |
| F | MiLAi | extract | 100 | 198,280 |
| O | MiLAi | actor | 257 | 499,327 |
| O | MiLAi | self_judge | 100 | 149,376 |
| O | MiLAi | extract | 100 | 199,527 |
| O | MiLAi | adopt | 95 | 120,629 |
| O | 正确历史回放 | actor | 48 | 111,998 |

本报告 820 项 TEST／参考合计 3,053 次生成、12,036,387 tokens；embedding 400 请求、87,088 tokens。支持形成和历史 DEV／VALID 另列，服务样例调用另列。没有已知费率，未推算费用；HTTP 时间不视作独占 GPU 时间。

## 正确历史参考与原生终态

DB 正确历史回放在预选 20 项子集上为 18/20（90%），48 次生成、111,998 tokens。它使用原生正确性筛选回放，反馈条件不同，结果独立列出。

| 协议 | 方法 | completed | task_limit_reached | agent_validation_failed |
| --- | --- | --- | --- | --- |
| F | Native | 93 | 7 | 0 |
| O | Native | 92 | 8 | 0 |
| F | OM | 98 | 2 | 0 |
| O | OM | 93 | 7 | 0 |
| F | RB | 76 | 23 | 1 |
| O | RB | 76 | 22 | 2 |
| F | MiLAi | 77 | 23 | 0 |
| O | MiLAi | 82 | 18 | 0 |
| O | 正确历史回放 | 19 | 1 | 0 |

正确率沿用原生 `evaluation_record.outcome`。原生 evaluator 可能把达到步骤上限或 Agent 输出无效时的最终数据库状态判为正确；状态与评分分别保留。所有 worker 退出 0 并不意味着所有任务都以 `completed` 结束。

## 机制证据与限制

MiLAi F 接受 99 次采用补丁，O 接受 94 次；采用只更新临时工作备注／关注点，没有改动经验卡片。两协议各有 1 次采用提案拒绝。所有 200 项任务中，来源回读、获准自然修订与接受的修订补丁均为 0。O 的五条空银行流在首次任务没有已有经验可采用。

按预定顺序检查首项 DB 任务 0：检索三张 SUPPORT 卡片及其 revision，采用器生成工作备注和关注点；三次实际 Actor 请求均包含完整卡片文本和完全相同的备注／关注点。该项原生评分正确，任务后提炼处于 F 的未提交状态。这个检查确认了实际输入链路；单项正确不证明记忆或修订的因果收益。原请求、事件与银行散列保存在外部证明文件。

RB F/O 分别有 2／1 次提炼拒绝，原生任务结果保留。后续贡献／资源子集将补充解释；当前结果不依据这些未完成部分提出修订必要性的结论。

## 制品与剩余工作

- [紧凑 DB 结果](../../data/manifests/reasoningbank-db-results-20260916.json)。
- [整体研究 Goal](MILA_REASONINGBANK_TRANSFER_AND_MULTISESSION_RESEARCH_GOAL_v1.0_20260915.md)、[开发／版本选择](MILA_REASONINGBANK_DEVELOPMENT_RESULTS_20260915.md)、[完整执行清单](../../data/manifests/reasoningbank-transfer-20260915.json)。
- 外部完整样本与区间：`/cra/memory/mx_memory/evidence/reasoningbank-transfer-20260915-_7fzz854/final-analysis/db-terminal/summary.json`。
- 实际输入证明：`/cra/memory/mx_memory/evidence/reasoningbank-transfer-20260915-_7fzz854/final-analysis/first-formal-candidate-memory-input-proof.json`。

OS 和旅行正式覆盖、只追加贡献子集、两个共同资源点、同一输入普通消费诊断、全研究账务与最终报告仍在执行范围内。本报告新增模型调用为 0，不改变正式政策、样本划分或额度。
