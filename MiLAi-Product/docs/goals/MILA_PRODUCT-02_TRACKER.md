---
document_id: MILA-PRODUCT-02-TRACKER
version: "1.2"
status: PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE
created_at: "2026-09-02T00:01:11+08:00"
updated_at: "2026-09-02T08:19:40+08:00"
goal: MILA-PRODUCT-02
execution_authorized: true
---

# MiLAi Product-02 轻量执行 Tracker

本 Tracker 是唯一日常执行记录。单点开发失败不创建 terminal/receipt；只更新一行 issue，修复后继续。

## 阶段状态

| 阶段 | 目标 | 最小验证 | 状态 | 下一动作 |
| --- | --- | --- | --- | --- |
| U0 | 当前 S4 repair 与真实指标基线 | Wrong COMPLETE 正反例、turn/span metric、单 case trace | `PASS` | 93 个受影响 Product tests、8 个 Lab metric tests、精确 serialization 与双仓 import boundary 通过 |
| U1 | answer-turn-first 一次 acquisition | A0/A1/A2 targeted + 24-case | `PASS_KEEP_A0` | 8-case 三臂 coverage 均为 0.625；A1/A2 无净增益且保持 OFF；选中 A0 的 outcome-blind 24/24 通过 |
| U2 | Requirement EvidenceSet 与 operator | failure-family 单点修复、known-false、24/128 | `PASS_PROTOTYPE_DEFAULT_OFF` | EvidenceSet、AcceptedOperatorInputs、ordinary/strict 分离与 role-first atomic Context 完成；B2 在下游效果门被停放 |
| U3 | 本地可用性交付与 128/500 决策 | golden flow、24、100 warm、fresh 128 | `PASS_KEEP_SIMPLER_BASELINE` | 本地门 PASS；128 硬门 PASS 但 B2 效果退化，选择 B0/B1 等价基线；不进入 500 |
| U4 | 条件式复杂能力 | 每种能力独立 Entry/Effect | `NOT_ENTERED_NO_MEASURED_OPPORTUNITY` | Core 已完成；无默认开启、API 或 Schema 扩张 |

## 首批运行队列

| Run ID | 阶段 | 目的 | 范围 | 状态 |
| --- | --- | --- | --- | --- |
| P02-R001 | U0 | 审阅当前未提交 repair | 3 dirty files，只读 diff | `PASS_PRESERVED` |
| P02-R002 | U0 | Wrong COMPLETE 单点正反例 | 1 known-false + 1 fake-status negative + 1 legal binding-backed operator；相关 Product 93 passed | `PASS` |
| P02-R003 | U0 | 修正 session/span 指标 | `ReaderVisibleGoldSessionCoverage` + exact turn/span metrics；Lab 8 passed，boundary PASS | `PASS` |
| P02-R004 | U1 | direct-turn quota | role-first + per-channel opportunity + identity lineage；62 targeted tests | `PASS` |
| P02-R005 | U1 | bounded local expansion | opened-dev exact-label 8-case A0/A1/A2；turn/span 0.625/0.625/0.625 | `PARKED_NO_EFFECT_DEFAULT_OFF` |
| P02-R006 | U1 | acquisition 24-case gate | 最终树 `product02-u1-selected-a0-24-002`；outcome-blind 24/24，identity/serialization/atomic/leak hard gates全通过 | `PASS_SELECTED_A0` |
| P02-R007 | U2 | multi-operand EvidenceSet | 最终树 `product02-u2-micro-b2-004` 8/8 + `product02-u2-b2-24-003` 24/24；0 Reader/Judge/mutation | `PASS_PROTOTYPE` |
| P02-R008 | U2 | temporal/current operator | `AcceptedOperatorInputs` only；relative-time 双 anchor、state/as-of 正反例 | `PASS` |
| P02-R009 | U2 | role-first atomic Context | exact turn/span/lineage；ordinary/strict 分离；无 atomic 截断/Canonical 读写变更 | `PASS` |
| P02-R010 | U3 | local Product handoff | final `product02-u3-local-final-006`；golden + 24/24 + 100/100 | `PASS_SELECTED_BASELINE` |
| P02-R011 | U3 | matched decision | final sealed `product02-u3-longmemeval-128-007`；B0/B1/B2 | `PASS_KEEP_BASELINE_PARK_B2` |
| P02-R012 | U3 | conditional confirmation | 500-case Product/Answer/Judge | `NOT_ENTERED_128_EFFECT_FAIL_NO_AUTHORITY` |

## 单点 Issue / Reflection

| ID | 阶段 | 最早首损 | 代表 case/fixture | 根因假设 | 单一改动 | 正反例结果 | 状态 | 反思/下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P02-I001 | U0 | OPERATOR | Product-01 S4 strict false COMPLETE | Raw lookup 修复正确，但 completion-shaped operator mapping 仍可凭 status 与槽位提升 COMPLETE | DecisionEngine 仅接受与当前 operator、完整 slots、MATCH Binding 精确来源闭合的 operands；preview 复用同一 typed lineage | fake status/Raw lookup 均 PARTIAL；合法时间与数量 operator COMPLETE；Product 93 passed | `RESOLVED` | `LOCAL_FIX_SUFFICIENT`；拒绝放宽 status 或新增第二 completion owner |
| P02-I002 | U0 | HARNESS | `reader_visible_gold_span_coverage` | session proxy 被命名为 span coverage | 改为 `reader_visible_gold_session_coverage`；新增 sealed-trace 后 exact turn/span scorer | session-hit/turn-miss=0；exact turn/span=1；无 exact span 时为 N/A；Lab 8 passed | `RESOLVED` | 借鉴历史 DG17 label-free trace→gold join；拒绝把 session hit 推断为 span hit |
| P02-I003 | U1 | ADMISSION | session hit / answer-turn miss family | session/global score 未定位 answer turn | direct-turn role/channel floor + bounded same-session atomic admission | synthetic 正例命中、跨 session/scope/revoke 负控为 0；opened-dev 8-case A0/A1/A2 exact turn/span 均 0.625；A0 24/24 | `RESOLVED_KEEP_A0` | ReFind/OpenViking 的最小局部模式已验证，但 slice 无效果且 A2 更慢；A1/A2 保持默认 OFF，不引入递归层级或 Agent |
| P02-I004 | U2 | OPERATOR/CONTEXT | multi-operand、relative temporal、current-state families | 全局 Top-k 与 lookup readiness 不能表达 role coverage，strict operator 可消费非精确绑定候选 | 新增内部 `LeanRecallPlan`/`EvidenceSet`；operator 仅消费 `AcceptedOperatorInputs`；Context role-first 且只序列化 atomic units | B2 8/8 与 24/24 契约门通过；strict 错误关系/时间负控拒绝；canonical mutation=0 | `RESOLVED_PROTOTYPE` | `LOCAL_FIX_SUFFICIENT`；不新增公开 API、Schema、持久化 Store 或模型 planner |
| P02-I005 | U3 | SEMANTIC/OPERATOR | superseded sealed run `128-002` 的 3 个 strict Wrong COMPLETE | relative-time query 只解析一个 anchor，且 event entity/action 兼容约束不足 | 解析双 temporal anchors；收紧 strict event compatibility；为普通 temporal/formation 设置最小证据 profile | 68 个 targeted Product tests PASS；最终 `128-007` strict Wrong COMPLETE=0 | `RESOLVED` | 只修复最早契约首损，未根据参考答案增加 case 特规则 |
| P02-I006 | U3 | EFFECT | sealed B2 vs B1 | 过窄 EvidenceSet 在当前通用查询上丢失 answer-bearing turns/roles | 按预注册决策停放 B2，不在看到 128 结果后调 Top-k/Prompt/seed | turn coverage `0.41813→0.05263`；role `0.35427→0.05124`；Judge `0.265625→0.078125`；25 losses/1 win | `PARKED_NO_EFFECT_DEFAULT_OFF` | 保留 B0/B1 等价简单基线；B2 不获得 default-on 或扩大运行权 |
| P02-I007 | U3 | HARNESS | diagnostic `128-003` 的单次 provider strict-JSON failure | provider/system failure 被误归为 semantic wrong answer | 只修正 matched-success 评分与 Answer/Judge success hard gate，然后 fresh 重跑 | 最终 `128-007` 的 384 Answer + 384 Judge 全部成功 | `RESOLVED_SUPERSEDED_003` | `128-001/002/003` 仅为 incomplete/diagnostic/superseded，不用于最终效果结论 |
| P02-I008 | U3 | SEMANTIC/OPERATOR | anti-special-case audit 与 superseded `128-005` 的 entity-only event distractor | fixture-shaped entity expansion 不可接受；通用 event action morphology 缺口仍可使同实体错事件进入 strict COMPLETE | 删除词义特例；改为要求全部 action anchors 与最小具体 entity overlap；扩展通用 action morphology 并增加 entity-only 负控 | 47 targeted 与 635 个 Runtime tests PASS；单例重放 ABSTAINED；`128-007` strict Wrong COMPLETE=0 | `RESOLVED_SUPERSEDED_005` | 修复来自最早 Binding 契约首损，不保留 fixture synonym；`128-004/005` 不用于最终效果结论 |
| P02-I009 | U3 | PRODUCT_BOUNDARY | completion audit 发现历史测试中的真实 case identity、sealed exact quote 与实例→类别映射 | 即使不在默认路径，Product 中保留这些材料也违反 Product/Lab 隔离与 anti-claim | 用 opaque/synthetic fixture 保留契约测试；删除显式实例类别映射；对 500 case IDs 与 exact quotes 做机器比对 | leak audit 0 match；155 targeted + 635 Runtime PASS；最终树 A0 24/24、B2 8/8 + 24/24、`local-final-006` 与 `128-007` PASS | `RESOLVED` | `128-006` 因完成审计后行为树变化被取代；不使用标签内容调参 |

新增 issue 时只增加一行；同一根因的后续尝试更新原行，不复制新文档。

## 参考项目修复模式

参考项目从 U0 起就是失败反思工具，不是 U4 才允许使用的升级清单。每次定位首损后，先选择与该首损
对应的最小机制；只有完整子系统、持久化对象、外部依赖、模型化策略、多轮执行或默认启用才需要进入
U4 的独立 Entry/Effect gate。

| 首损类型 | 优先参考 | 当前阶段可直接采用的最小机制 | 不随单点修复自动引入 |
| --- | --- | --- | --- |
| Raw discovery / 单通道漏召回 | Hindsight、ReFind | Raw-turn first；BM25/Dense 独立小 quota；保留来源 lineage | 全量 graph fusion、自由搜索 Agent |
| session 命中、answer turn 丢失 | ReFind、OpenViking | same-session bounded expansion；目录只导航，Raw turn 作证 | 递归层级系统、LLM planner |
| 多 requirement 相互挤占 | Hindsight、OpenViking | role-first breadth-first coverage，再分配剩余预算 | learned global fusion、完整目录 Store |
| relation/source/time Binding 错误 | Hindsight、Mem0、Graphiti | grounded span、source/scope metadata、occurrence time 分离 | 自动 fact promotion、自动覆盖 Canonical State |
| Raw 存在但表示不可达 | Mem0、Graphiti | source-linked ADD-only noncanonical sidecar，保留 Raw fallback | 新权威 Store、自动 merge/update/delete |
| 首轮后出现新 cue | ReFind | seen-region 记录；只补 missing role 的一次 reformulation | 默认多轮 ReAct、模型 `finish`/`COMPLETE` 权限 |
| Recall 后需要综合 | Hindsight | Recall 与 Reflect 分离，先固定 EvidenceSet 再分析 | always-on Reflect、mental-model authority |

每个进入 `ACTIVE_REPAIR` 的 issue 在“反思/下一步”中追加：

```text
参考项目 / 模式：
本次借用的最小机制：
明确拒绝的复杂部分：
为什么适用于当前首损：
```

不要求为了形式完整而引用外部项目；如果 MiLA 本地简单修复已足够，应明确记录
`LOCAL_FIX_SUFFICIENT`。

## 自动执行规则

```text
PASS
→ 更新当前阶段
→ 自动激活下一 WAITING 阶段

RECOVERABLE FAILURE
→ 当前阶段保持 ACTIVE_REPAIR
→ 单 case 定位最早首损
→ 查询参考项目修复模式或采用 LOCAL_FIX_SUFFICIENT
→ 只借一个与首损直接相关的最小机制
→ 一个通用修复
→ 正例 + 对照 + 负控
→ 8/24/128 逐级恢复
→ PASS 后自动继续当前阶段和下一 WAITING 阶段

OPTIONAL NO EFFECT
→ PARKED_NO_EFFECT
→ 回退简单 profile
→ 继续 Core
```

只有以下条件暂停请求用户：

```text
需要 public API 或 PostgreSQL schema 变更
需要默认启用复杂 feature
需要破坏性数据操作
权限或目标范围不明确
不可替代的外部依赖阻塞
```

## 状态写入规则

- 同一时刻最多一个 Core 阶段为 `ACTIVE` 或 `ACTIVE_REPAIR`；
- 可并行的是该阶段内部互不依赖的 unit/static/adapter 或不同 Lab model pools；
- 可恢复失败不写 `FAIL` terminal；
- treatment 无增益只关闭 treatment，不把 Product 标为失败；
- 阶段完成时更新一次 `PRODUCT_CURRENT_STATUS.md`；
- U3 local handoff 和 128/500 sealed run 可在 Lab 保存正式四件套；
- Product 代码和文档不得包含 LongMemEval case ID、gold text 或 Judge prompt。

## 阶段验收摘要

### 冻结身份与 labels

```text
Product Git HEAD provenance          1b5e4a7122da2b38b9a57bba143215cc0afa3387
Product behavior tree SHA-256        3c7cc1b1304263d1bb41d60952efe2feadfb0a9db86087e86fd017780e5df5ba
Product manifest SHA-256             4088a605f6d5b2767c286985468c20500c2797feae0e52863cc40d9d1a577db2
Lab Product lock logical digest       6f2869254659bf1c5f7710785a65016cb21b36d06b5411da978e9ffe98c68d1b
Lab Product lock file SHA-256          792db4da0c8582e45e4176842c122b18289ccc94e1e0b8e3f0f14daf0502fbe2
LongMemEval dataset SHA-256           d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442
sealed label manifest SHA-256         6238c10cb7d6203715043a1437add55e3cd8114d20cec9e7ceded11c92831412
```

`product02-longmemeval-answer-turns-qwen36-v4.json` 是决策唯一使用的 label manifest：500/500
精确回放并校验 source/session/turn/text hash，470 个正例使用 Qwen3.6-35B-A3B-FP8、
temperature 0、无 semantic retry/投票标注，30 个 `_abs` 负例为 deterministic empty。标注器只读
question/date/reference/oracle sessions，不读 Product、Reader 输出或 native `has_answer`。它含 249 个
direct-answer cases、308 个 direct-answer exact spans、822 个 role selections 和 10 个 duplicate
merges。这是
model-assisted evaluation labels，不是独立人工裁决的 benchmark ground truth，也不声称 leaderboard
等价。`v1`–`v3` 只是合同收紧过程的 diagnostic 产物，未加入决策 run。

生成全 500 例 label 清单属于评测准备，不是 500 例 Product/Answer/Judge 执行；
`formal_holdout_consumed=false`。

### U3 本地 Product 门

权威制品：MiLAi-Lab `artifacts/product02-u3-local-final-006`。

```text
terminal                              PASS_PRODUCT02_U3_LOCAL_USABILITY
selected arm                          B0_B1_EQUIVALENT_BASELINE
golden flow                           PASS
24 scenarios                          24/24
warm typed requests                   100/100
read-after-write searchable P95       1095.955 ms
retrieval + Context P95               60.454 ms
warm control P95                      16.566 ms
deterministic fallback                1.0
governance leak / read mutation       0 / 0
one flag restores baseline            true
candidate default enabled             false
```

该 run 在 fresh PostgreSQL 上完成 install/start/migration/smoke、capture/query/trace、restart、
revoke/delete，运行后停止栈但保留精确命名 volume。`local-final-001` 仅为 incomplete；
`local-final-002/003/004` 属于更早行为树；`local-final-005` 保留了调用方未先启动 fresh
stack 导致的 F0 incomplete `run.json`。显式启动同一 fresh stack 后，新输出 `local-final-006`
取代它们。权威四件套文件 SHA-256：

```text
run.json       b0bf565b2a99626bd86ac0401c0c3d3a1989339a5f6ef6f0be2a3f2c1b6d223c
cases.jsonl    3525c0ccfdd6dcb9c9b80b8c9dff3588f84f399a0d93fdaefc292fcec493ea3c
metrics.json   2a747ac4138949ce6380ab71b47a470f7f207c1e41e8522534e5f183e0abf94b
terminal.json  6b59d06d630eefd4bb99ceabd218debd5f80b9ab04bc24d148c274f4e42729ca
```

### U3 密封 128-case 决策

权威制品：MiLAi-Lab `artifacts/product02-u3-longmemeval-128-007`。B0 为 U0 repaired
control，B1 为选中的 A0 且与 B0 精确等价，B2 为 U2 EvidenceSet。共 384 个逻辑单元；
B1 等价别名使 Product Context 实际执行 256 次，384 个 Answer 与 384 个 Judge 全部成功。

| Metric | B0/B1 baseline | B2 EvidenceSet | B2 − B1 |
| --- | ---: | ---: | ---: |
| Answer-bearing turn recall / visible coverage | 0.418129 | 0.052632 | -0.365497 |
| Exact answer-span coverage | 0.407738 | 0.053571 | -0.354167 |
| Required-role coverage | 0.354270 | 0.051240 | -0.303030 |
| Qwen Judge accuracy | 0.265625 | 0.078125 | -0.187500 |
| P95 latency | 2153.474 ms | 1837.239 ms | 0.853151x |

paired Judge 为 1 win / 25 losses，10,000 次 bootstrap 95% CI 为
`[-0.2578125, -0.1171875]`。Answer/Judge provider success、Product pin、Context success、trace/config
exactness、worker health、zero contamination、zero strict Wrong COMPLETE、zero governance leak、zero read
mutation 和 complex-default-OFF 硬门全部 PASS；候选只通过 latency 效果门。因此：

```text
terminal                     PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE
selected disposition         B0_B1_EQUIVALENT_BASELINE
B2                            PARKED_NO_EFFECT_DEFAULT_OFF
candidate entry              false
500-case confirmation        NOT_ENTERED
formal holdout consumed      false
```

`128-001`为 incomplete diagnostic，`128-002` 触发可修复 strict 契约问题，`128-003` 暴露
provider failure 分类问题，`128-004` 在最终 anti-special-case audit 前结束，`128-005` 则保留了
一个 entity-only distractor 引发的 strict 硬门失败。通用 action/entity Binding 修复后的 fresh
`128-006` 在完成性审计发现 Product 测试泄漏后被新行为树取代；仅 `128-007` 是权威决策 run。
先前产物均保留但不支持最终效果结论。权威
四件套文件 SHA-256：

```text
run.json       59960996ffbb2d4e0414e449510ae7b9e0bfeeb26c67ac0b556be7539ddeedae
cases.jsonl    64acf8c10199ca22956eff8c6955011e1208b5df14b4baa30d4332a35f4e30a2
metrics.json   71d3eacd10a875b34b5fbe5a5ffa1b6c50ba02828f255a95822b1bc7c37d6028
terminal.json  84cf0d596c0ca46b2eef6db21e57186a1ba84ceffd0a05cda5dd52f35724b9c2
```

### 最终回归与交付边界

```text
Runtime official offline suite        635 passed, 127 deselected (integration)
Runtime Ruff / strict mypy             PASS / PASS (163 source files)
Runtime wheel + sdist                  PASS
six adapter tests                      164 + 48 + 102 + 6 + 5 + 6 = 331 passed
six adapter lint/builds                PASS / PASS
architecture validate + release lock   PASS / PASS
Lab Ruff / strict mypy / pytest         PASS / PASS (25 files) / 41 passed
Lab Product lock verification           PASS
public interface hashes                 UNCHANGED
```

Product-02 的 fresh local stack 是本次 PostgreSQL 端到端证据。官方 Runtime 回归明确排除
127 个 integration tests，因此不宣称全量 DB pytest。未在密封评测数据库上运行可清空/
变更数据的 integration suite。所有本次 Product-02 API/PostgreSQL 服务均已停止，精确
命名的实验 volume 保留。没有 public API 或 Schema 变更，不宣称 production-ready。

## Core 完成检查

- [x] U0 PASS
- [x] U1 选择最简单有效 acquisition（A0；A1/A2 `PARKED_NO_EFFECT`）
- [x] U2 strict Wrong COMPLETE = 0
- [x] U2 EvidenceSet/atomic Context 完成，但因效果回退保持默认 OFF
- [x] U3 local Product gate PASS
- [x] U3 fresh 128 decision 完成
- [x] 500 仅在 entry PASS 时运行；本次 entry FAIL，故未运行
- [x] U4 全部 NOT_ENTERED/PARKED，不影响 Core PASS
- [x] Schema 仍为 `NO-GO FOR FREEZE`
