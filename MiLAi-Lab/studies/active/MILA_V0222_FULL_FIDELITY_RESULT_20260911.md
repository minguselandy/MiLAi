# V0222 完整动作保真：有界失败终态

日期：2026-09-11。独立审查：`/root/v222_review`。实验为研究验证，不是 Product 或 Memory 能力证明。

结论：`STRING_RULE_SIGNAL / FULL_FIDELITY_NOT_MET / MEMORY_NOT_ADMITTED`。
唯一 D11 候选 `STRING_RULES_RUNTIME_V1` 已完成离线审查和完整 HTTP 容量预检，
但 P3 首个真实请求未保真，按冻结规则永久停批。P3 实际 1 次、通过 0 次，另 15 个位置未运行；
P4 全部 24 条链未触发，不能把未运行位置计作实测失败或宣称完整矩阵完成。

## 实际证据

批目录：`/cra/memory/mx_memory/evidence/v0222/20260911-http-r1`。
请求：`p3-01-89efa5c536a24293bcffe13103a44013`。
独立审查制品：该目录 `P3-independent-review.json`；原始内容留在证据目录，不复制到 Git。

| 层次 | 独立复核结果 |
| --- | --- |
| 输入与 wire | 实际 canonical、D11 编译结果、冻结参考、HTTP payload hash 精确相符；完整资料和授权动作确实发送 |
| HTTP / 容量 | HTTP 200；输入 27,844，预约输出 4,096，合计 31,940 ≤ 65,536；参考输出 278 tokens 可容纳 |
| 原始输出 | `finish_reason=stop`，输出 494 tokens，HTTP 7.267 秒；不是达到输出上限或超时 |
| JSON / 原完整 Schema | 严格解析及全部原完整合同校验通过，原文与 visible 回执一致，未做值修补 |
| 意图 | 授权 `put_record(manager_report)`，实际 `put_record(S01)`；预期 6 个 data 字段、实际 31 个，独立差异共 38 处 |
| 放行与停止 | `NOT_RELEASED_TO_EXECUTOR`；永久锁 `FULL_INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH`，无业务 World、派发或 Note 写入 |

实际 `S01` 是 Schema 允许的另一对象，不是本次授权目标；Schema 合法不等于其业务值正确。
输出含 280 字符的 `risk_and_negotiation_actions`，但不能据此认定未输出的 manager_report 字段已恢复。
worker 退出码为 1；外层 runner 收口失败报告后退出 0，不代表实验 PASS。
worker 在放行前异常终止，所以没有成功 `worker-result.json`，实际 raw、usage、差异与失败记录均保留。
账本的 `DISPATCH_STARTED` 指模型 HTTP 发送，不是业务派发。

## 费用与未触发门

| 账项 | 请求 / 用量 |
| --- | --- |
| P1 生成 | 24 次，4,451 raw |
| P3 生成 | 1 次，27,844 输入 + 494 输出 = 28,338 raw |
| 本批生成合计 | 25 次，32,789 raw；新未知 0 |
| 跨历史已知实际 | 30,085 + 32,789 = 62,874 raw |
| 旧未知 | 唯一预约 28,284 保留；跨历史实际总额仍未知，预约不是消费 |
| HTTP tokenize | P1 共 72 + P3/P4 参考容量 192 + P3 实际输入 1 = 265 次 |
| HTTP 身份 GET | 62 次；不计作模型生成 |

上述不是货币账单；Agent 自身用量另账，当前报告无可用计数，不能填 0。
Judge / 云端回退为 0。费用状态 `new_generation_allowed=true` 只说明费用账可结算，
不覆盖永久 batch stop；只读复核确认 `check_journal` 返回 `BATCH_STOPPED_NO_RETRY`。
P4 虽已做 80 份参考容量检查，但真实执行仍为 0；E1、E2、M0、M1 均 `NOT_TRIGGERED`。

## 解释与下一安全工作

[P1 的重复字符串信号](MILA_V0222_P1_STRING_DIAGNOSTIC_20260911.md)保留：
D00/D10/D01/D11 为 0/6、2/6、0/6、6/6。它与本次完整对象目标偏离可以同时成立：
合法字符串表达的改善并不足以保证完整目标选择和意图使用。不能倒推 P1 无效，也不能把本次失败归为 Memory 失效。
线上解码后端及根因仍未被观察确认；P2 相对旧候选还有共同 notice 的 +372 UTF-8 字节变化，
旧新完整输出不是 decoder 单变量因果对照。

安全下一步是零网络重建实际请求的指令层级、完整来源、授权动作边界和候选对象呈现，
将“目标选择 / 呈现干扰”作为待检验假设，制定一个独立有界的新版本合同。
这不是自动触发原文“无字符串信号”分支，也不是认定长上下文或 Schema 分支顺序已经导致失败。
若研究明确动作块，应保持同一模型、D11 decoder、完整资料、原授权值和完整 checker，精确记录提示 diff；
不能只留答案、收窄目标、增加答案 const、代填值或用剩余额度试多个提示。

任何第二修复/提示候选的真实请求都须新版本、新批合同、明确具体授权来源与独立 subagent 范围审查，
事前冻结条件、变量、顺序、次数、时间、成本、判据、停止规则和历史承接；审查意见本身不生成新用户同意。
不解除本批停止锁，不合并调参后成绩，不接触保护池，不操作 GPU/容器/共享服务。
本次有界失败审计可以完成获授权的检查交付，但不满足进入 P4 或后续 Memory 路线的前置门。
