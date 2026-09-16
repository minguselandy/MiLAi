---
document_id: MILA-V02-04-LAB-PLAN
version: "0.2"
date: "2026-09-06"
status: COMPLETED_NON_MODEL_INCREMENT
execution_authorized: true
executed_scope: C0_C1_C2_NON_MODEL
C3: NOT_ENTERED_COST_CONTROL_UNVERIFIED
priority: ABSOLUTE_COST_FIRST
immediate_scope: EXISTING_ARTIFACT_COST_AUDIT
n5_supplement: PARKED_COST
historical_allocations: 17
historical_known_tokens: 2402257
new_experimental_model_allocations_authorized: 0
new_experimental_token_budget_authorized: 0
conditional_pilot_max_allocations: 2
formal_500_scoring: false
public_deployment: false
automatic_maintenance: false
---

# 成本优先：暂停补样本，先修复单次任务的高消耗

## 1. 变更决定

本文件替代 v0.1 的直接补齐安排，对应 [开发 Goal v0.2](../../../MiLAi-Product/docs/goals/MILA_V02_04_保存确认补齐与显式使用验证_GOAL_20260906.md)。原“4+2 次 / 追加 100 万 token”，以及条件“12+2 次 / 另加 200 万 token”提案撤回，不再作为当前执行入口；从未激活过这些额度。

当前新实验模型预算仍为0。用户要求执行后，C0–C2非模型增量已完成：历史重算一致、实际
容器读取修复/24条命令重放/12份完整历史分页还原通过。C2未核验单任务累计硬限，C3不进入。
见 [工程交付与成本审查](MILA_V02_COST_FIRST_RESULTS_20260906.md)。本文后续条件安排不构成
新增模型授权。

原 [修复与续做报告](MILA_V02_PAYLOAD_FIDELITY_CORRECTION_20260906.md)、[总账](MILA_V02_PAYLOAD_FIDELITY_RESULTS.json)、[C 任务合同](MILA_V02_FIDELITY_CONFIRMATION_C.json) 不覆盖。N5 的未运行项继续为未观察，不构成负向结果，也不是必须花钱补齐的交付配额。

## 2. 已有证据的只读成本初查

### 2.1 任务成本与保存成本分开

以下按原总账中 `model_started=true` 分组计算，未运行项不填零：

| 组 | 完成会话数 | 累计 raw tokens | 平均 raw tokens | 平均非缓存 input | 平均 output | 平均在线秒 |
|---|---:|---:|---:|---:|---:|---:|
| 普通 G | 4 | 982,824 | 245,706 | 36,675 | 2,343 | 123.58 |
| F：完整 A0 + 文件 | 6 | 794,365 | 132,394.17 | 28,113.67 | 920.50 | 60.92 |
| S：同文件 + 实际保存笔记 | 6 | 625,068 | 104,178 | 17,070.83 | 749.83 | 55.71 |

这些是整个 Host 任务累计用量，不是单次记忆工具调用。S 范围为 78,259–137,938 tokens。原样保存动作本身没有模型调用，四条历史 `Delta_save` 为约 0.086–0.238 秒，不应把 Host 的全部成本都归给保存 API。

总计 input 2,382,863，output 19,394；cached input 1,965,056 是 input 的子集，非缓存 input 417,807。输入占 raw 总量约 99.19%，缓存占输入约 82.47%。raw、缓存、非缓存、输出和实际费用分别记；没有费用数据则金额未知，不能统一按 uncached 单价换算。

### 2.2 可以直接定位的工程问题

从 12 个已完成 F/S 的 `events.jsonl` 中，只读取工具结果与 usage，不重新运行任何模型：

| 非零退出原因 | 次数 |
|---|---:|
| `python: command not found` | 12 |
| `python3: command not found` | 11 |
| `jq: command not found` | 1 |
| 合计 | 24 |

此外，`r-ba358f49-advisor_email-F` 的两次命令输出各 540,357 字节，摘要相同；整个会话命令输出合计 1,082,729 字节。其他续做亦有数万至数十万字节的历史输出。该例的 S 并没有因此必然更便宜，故不能只凭“大输出减少”推断最终 token 收益。

原始来源为总账指向的：
`artifacts/v02-state-payload-fidelity/run-20260906a/sessions/<allocation_id>/events.jsonl`。
计数取 `item.completed / command_execution`，失败取非零 exit code；重复输出按 `aggregated_output` 原始 UTF-8 字节摘要判定，不把命令开始/结束重复算两次。

逐请求模型输入仍是 `UNOBSERVED`。日志输出可能被 Host 截断或重新装配，因此 54 万日志字节不能写成 54 万模型输入，更不能换算成已证实的节省量。每会话一条 `turn.completed` 汇总也不证明内部只发生一个 Provider 请求。先记录已确认的失败与重复，不夸大归因。

## 3. C0/C1：不新增实验模型调用的开发增量

第一优先级是通用运行环境，而不是摘要算法：

1. 检查容器内实际支持的 JSON/文本读取程序，提供至少一种能处理既有历史结构的可用通用方式；不能靠模型每轮尝试不存在的工具来发现环境。
2. 在容器启动 smoke 中确认工具可执行、可访问允许文件、可输出实际结果；验证 Unicode、换行、空字段、文件不存在和正常失败反馈。不需要启动 Host 模型来确认解释器是否存在。
3. 检查历史文件结构及普通输出尺寸。若简单、可用的解析方式还不能避免巨量输出，再做最小有界读取/分页示例；保留原文、来源身份、时间及继续读取入口，不生成模型摘要或新事实。
4. 用旧命令的非模型重放或固定通用 fixture 验证运行与内容一致；该重放只能证明工具修复，不证明模型会采用它或总 tokens 已下降。
5. 固定提示、bootstrap、工具描述等只统计实际可读配置/文件，不为测量追加昂贵的 prompt 导出调用。后续逐请求输入拿不到，就保留未知。

优先落点是 Lab 容器/runner 及相邻测试；不把病例 ID、gold、答案关键词或“应该读哪个 turn”写进通用工具。公开 Product 行为默认不变。

无模型回归应覆盖依赖可用性、正常和非法路径、允许来源完整性、分页继续读取、尺寸上限与显式截断反馈、错误结果；F/S 使用相同工具环境。只修一个有证据的瓶颈后交付，不预建新的调度平台、预算平台或完整检索系统。

Lab改动先相邻测试，再按仓库合同跑boundary、pytest、Ruff、mypy、build。本轮已完成新检查，
180项测试通过；另含6种首尾位置及可选字段删除变体，读取完整性不依赖这些结构。
Product源码未改，只复核pin，不把旧Runtime检查作为新证据。

## 4. C2：先确定绝对成本门槛，不能只比百分比

普通短续做以“万级而不是十万级累计 raw tokens”为降本方向；可将每任务 20,000 raw input+output 作为待验证工程目标。它不是已批准额度、已具备的硬上限，也不是由当前数据证明可达到的指标。固定 Host 开销若已超过目标，先报告并提出更轻路径的独立比较，不发起注定昂贵的试跑。

在任何新实验前明确：

- 单任务和整个 pilot 的 raw token、缓存/非缓存 input、output、墙钟；有实际账单再列金额。
- 预算控制究竟是每请求可执行限制，还是仅已知累计用量的下一次启动闸门；在途请求可能超额多少、用户接受什么范围。
- 不存在可信控制、usage 未知或不能验证当前配置时，暂停付费试跑；120k 提醒与 300 秒 watchdog 不能伪装成 token 硬限。
- 接受的单次成本与时延要先冻结，然后再运行；质量差、超限或费用不值得都停止，不因相对省 10% 自动扩样本。

当前不自动给出另一笔几十万 token 的额度来替换旧 100 万提案；由 C0/C1 的证据和可验证成本控制支撑一个新的小额度请求。实验预算为 0 不表示执行者分析和开发劳动免费，工程投入仍应单列。

## 5. C3：有条件的单配对 pilot，不是原 N5 续跑

若 C1 工程检查完成、C2 成本边界可接受且获执行授权，首轮最多一个既有任务 F/S 各一次，共 2 个 Host 会话；没有 G、额外 Judge、技术备用分配或自动重试。任何启动失败占本次分配，先诊断并收尾，不立即加额度。

默认选已开放的 `ba358f49 / advisor_email` 作为工程复核，原因是已有完整 G/保存/两臂记录，且发现了可复核的重复历史输出。原问题和来源不改；这不是按效果选择的未见测试，必须标为 opened-development 工程 pilot。

新配对要求：

- F 与 S 使用同一修复后环境、模型配置、完整 A0、实际任务文件及允许历史；S 唯一区别仍是已真实保存的笔记。
- 不调用模型生成新笔记；原 G 与 checkpoint 只读核验，通过公开接口作隔离分支初始化，当前权限与撤销仍生效。
- 未来任务互不串入、标签不挂载、F 保留全部查源与保存能力；有界读取不等于剥夺完整历史。
- 环境修复会改变新的运行条件，记录新版本/批次，与旧结果分开。旧 F/S 仅为历史参照，不冒充新条件下的对照。
- 若改变模型、推理设置、Host 或装配方式，先声明为新的干预并建立同条件基线，不拼入原 N5。

一个配对只能检验低成本运行路径的初步可用性。质量与绝对成本先判，二者满足后再报告相对成本；结果再好也不能宣布 N5 已补齐、自动维护有效或普遍泛化。两次不够或失败，就保留不完整，不自动扩大到旧 4+2 / 12+2 配额。

## 6. 历史预算、身份与收尾

以下冻结身份保留，不因降本修订变更：

- Product tree：`c5561412b0440f84e628d69a7c271c96d66bae7f89d4e3f1db46ede97a1608bf`。
- 原机器总账文件 SHA-256：`9bfa7b2addd16c87a804b7435d06ad42736b39f88a46c696276f23598814c256`。
- 原 C 合同 SHA-256：`4eb47387aeb98c43998fb052e7dd63c219ad7c1b0bb0bfe52959965acad910a8`。
- 原 [确认配置](../../configs/v02-fidelity-confirmation.json) 的启动闸门仍为 2,400,000；17 次分配 / 16 次实际模型 / 2,402,257 tokens 全部保留。
- 未完成 `cf22b7bf` 的原顺序仍是 coach_message/S、coach_message/F、progress_table/F、progress_table/S；全部继续未运行。未来若真的要原样补齐，另作独立取舍和授权，不因本 pilot 借用历史额度。

将来的新实验独立记录授权、配置、分配与结果，并展示旧研究累计成本；不清零旧账、不覆盖失败、不把新环境结果重新评分进旧确认。

本轮已完成非模型隔离验证，仅管理12个本轮断网容器，全部已移除，无认证副本；镜像、输入
副本和回执保留。未启动MCP/Runtime/PG或模型，不修改旧卷/公网，不直接写Canonical。

产品仍为 `0.1.0-candidate`，A0默认、D2 SHADOW、Schema `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
前轮Runtime971/1不是本轮验收；本轮Lab180项及静态/boundary/build通过。
