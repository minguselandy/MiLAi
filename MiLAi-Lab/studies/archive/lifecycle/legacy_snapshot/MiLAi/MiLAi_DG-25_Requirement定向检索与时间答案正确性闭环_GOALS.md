# MiLAi DG-25：Requirement 定向检索、时间完备性与答案正确性闭环 Goal

> Goal ID：DG-25  
> 方法名：Requirement-Complete Acquisition / Temporal Proof / Typed Answer Closure  
> 文档版本：0.1.22 TERMINAL / SUCCESSOR ROUTE CORRECTED  
> 起草日期：2026-08-29（Asia/Shanghai）  
> 当前状态：`FAIL_SAFETY_OR_REGRESSION` / `STOP_DG25_S4B_POST_SCORE_GATE`  
> 前置终态：DG-24 = `PASS_RETRIEVAL_FIRST_LOSS_LOCALIZED`  
> 关联未闭合终态：DG-23 = `PARKED_READER_SEMANTIC_NON_MONOTONICITY`  
> 本次 Owner 意图：制定一个可直接执行的后续 Goal，覆盖 DG-24 已定位的全部检索、时间证明和答案消费开发调试；文档存在本身不等于代码、数据库、模型或实验已经执行  
> 主目标终态：`PASS_REQUIREMENT_COMPLETE_ACQUISITION_TEMPORAL_ANSWER_CLOSURE`  
> Candidate 默认：OFF  
> Formal holdout：UNTOUCHED / NOT AUTHORIZED  
> Public MCP schema：禁止修改  
> PostgreSQL schema：默认禁止修改  
> architecture/v1.0：禁止修改  
> Canonical mutation：0  
> Retrieval Planner / Controller / Residual Provider calls：0  
> Automatic retry：0  
> vLLM / ReFind Agent / graph retrieval：本 Goal 不进入  
> 消融方案审查：原审查为 `APPROVE_WITH_REQUIRED_EDITS`；post-S2、readiness-002、readiness-004 与 readiness-006 fresh 复核均为 `REQUIRE_EDITS`；readiness-006 已通过 635 项重算且旧 edits 无回归，但新增 capture boundary、resolved provenance、isolated negative fixtures 与 AST execution-surface 四项 blocker；E1/E2 official replay、effect scoring、E3 和 Reader calls 当前均未授权

> 终态修正（2026-08-30）：后续阶段实际已进入 S4B 并完成一次权威评分。最低 `AcceptedBindingPrecision=2/3`，8 个 routing arms 合计 `Wrong COMPLETE=16`，因此 S5～S9 未进入，Candidate 保持 OFF。旧阶段描述和 checklist 保留为执行历史，不得覆盖终态回执：`var/dg25/terminal/dg25-s10-terminal-20260830-001/receipt.json`。

---

# 执行状态（2026-08-29—30）

## S0-001 技术冻结结果

已执行：

```text
run_id = dg25-s0-baseline-freeze-20260829-001
status = PENDING_INDEPENDENT_ABLATION_REVIEW_OR_OWNER_WAIVER
technical_gate = PASS
stage_gate = PENDING
S1 contract work = AUTHORIZED
S2 treatment execution = NOT AUTHORIZED
```

权威回执：

```text
var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/receipt.json
var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/baseline-freeze.json
var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/denominator-freeze.json
var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/source-config-index-snapshot-manifest.json
var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/preexisting-worktree-receipt.json
var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/ablation-review-status.json
```

机器验证事实：

```text
bound predecessor artifacts                 20/20
Runtime source identities                   15/15
opened-development cases                    10
evidence equivalence groups                 23
proof obligations                           37
proof baseline                              35 SATISFIED / 2 VALIDATION_FAILED
DG-23 RequiredEvidenceCoverage@B_ref         22/23
DG-23 AcceptedBindingPrecision               1.0
DG-23 additional calls / hydrated            4 / 18
DG-23 Reader EM                              4 / 4 / 4
DG-23 Reader normalized F1                   0.474263765 / 0.470909091 / 0.478605605
candidate default                            OFF
formal holdout consumed                      0
canonical mutations                          0
Runtime case-ID findings                     0
```

S0 没有被写成 PASS 的唯一原因是独立消融 review/Owner waiver 尚不存在。该门禁保持 fail closed；
S1 只实现 label-free typed contracts 与 synthetic falsification，不接触 E1–E4 treatment。

## 失败反思（append-only）

S0 阶段向 `var/dg25/failure-index.jsonl` 追加了 7 条失败，不覆盖旧输出，automatic retry 为 0：

| Failure family | Root cause | General repair |
| --- | --- | --- |
| denominator schema inspection | 将 top-level array 错当成 object wrapper | 先检查 JSON type，再按真实 array schema 计数 |
| Python command bootstrap（3 条） | 使用了机器不存在的裸 `python` | 全部 DG-25 Python 命令固定使用 `runtime/.venv/bin/python` 与显式 `PYTHONPATH` |
| Ruff gate | unused import、无效 noqa、runner mode 缺失 | 最小修正并使用 fresh run；Ruff 已 PASS |
| orchestration parse | captured output 中反引号破坏 JavaScript template literal | 使用 parse-safe escape，不把未转义工具输出嵌入命令 |
| review fixture boundary | 测试把 `/tmp` artifact 传给 repository-relative identity gate | 保持生产路径拒绝仓库外回执，测试改为隔离纯 review gate |

fresh rerun 结果：

```text
tests/test_dg25_s0_baseline_freeze.py         4 passed
DG-25 S0 Ruff scope                           PASS
DG-25 S0 py_compile scope                     PASS
```

以上失败不支持放松 artifact identity、review gate 或环境锁定；修复均作用于通用合同。

## S1-002 Typed contracts 与 synthetic falsification 结果

已执行：

```text
run_id = dg25-s1-contracts-20260829-002
status = PASS_DG25_S1_TYPED_CONTRACTS_SYNTHETIC_MATRIX
hard_gate = PASS
S2 treatment execution = NOT AUTHORIZED
```

权威回执：

```text
var/dg25/s1/dg25-s1-contracts-20260829-002/receipt.json
var/dg25/s1/dg25-s1-contracts-20260829-002/contract-schema-bundle.json
var/dg25/s1/dg25-s1-contracts-20260829-002/synthetic-matrix.json
var/dg25/s1/dg25-s1-contracts-20260829-002/negative-contract-report.json
var/dg25/s1/dg25-s1-contracts-20260829-002/source-manifest.json
```

机器验证事实：

```text
synthetic matrix                           39/39 PASS
PLAN / TEMPORAL / IDENTITY / PROOF / ANSWER 9 / 11 / 3 / 10 / 6
negative contracts                        19/19 PASS
targeted tests                            15 passed
full Runtime unit / contract              494 / 14 passed
Runtime strict mypy                       131 source files PASS
Ruff / py_compile                         PASS / PASS
architecture validate / bundle release lock PASS / PASS
Runtime case-ID or eval-import findings  0
candidate default                         OFF
labels / formal holdout consumed          0 / 0
provider calls / automatic retries        0 / 0
canonical mutations                       0
public MCP / PostgreSQL / architecture drift 0 / 0 / 0
```

S1 新增内部、query-local typed contracts：`RequirementAcquisitionPlanV01`、
`EventTimeIntervalV02`、`EventIdentityV01`、`BoundedRangeScanProofV02` 和
`TypedAnswerDecisionV01`；历史 proof V01 仅保留读适配器。本阶段未改动 public MCP schema、
PostgreSQL schema 或 `architecture/v1.0`，也未运行 E1–E4 treatment。

S1 阶段另追加 11 条失败，累计 failure index 为 18 条：

| Failure family | Root cause | General repair |
| --- | --- | --- |
| domain inventory/path（3 条） | 由 application 名称推测了不存在的 domain 文件 | 先用实际文件 inventory 定位 domain/application 边界，再读取合同 |
| contract Ruff | 聚合导出未排序且保留未使用 import | 只做确定性导入排序和无用 import 删除 |
| interval digest unit | 手写 ISO UTC `+00:00` 与 Pydantic canonical JSON `Z` 不一致 | 由 typed provisional object 的 canonical dump 生成 digest，统一 writer/validator |
| harness Ruff | 新 runner 导入顺序与非 object JSON 的异常类型不符合 lint 合同 | 应用确定性 import order，无效类型改为 `TypeError` |
| full unit bootstrap | 从 `runtime/` 执行时未把 repository root 加入 `PYTHONPATH`，DG-22 测试无法 import `evals` | 使用 `PYTHONPATH=src:..` 重跑原 suite，不改测试或 package boundary |
| Runtime strict mypy | 3 个新 builder 将异构 dict `**` 展开到 typed Pydantic constructor，另有 optional lookup 未窄化 | 改为显式 typed keyword construction 和独立窄化变量，canonical material 与行为不变 |
| architecture release CLI（3 条） | 依次使用了不存在的 `--release`、遗漏 external manifest anchor、以及误用默认 all-project scope | 使用 `--scope bundle --mode release --expected-manifest-sha256 <S0 frozen hash>`，另行校验 MCP/migration/architecture tree |

类型修复后未覆盖 S1-001，而是用 fresh S1-002 重新 seal 当前源码；该 source manifest 已重算且无漂移。
所有失败 receipt 与 stdout/stderr 仍保留于
`var/dg25/failures/`。这些修复没有引入 case-specific 分支，也没有放松 stale-state、proof closure 或 typed-answer fail-closed 规则。

## Independent ablation review-001

独立 secondary Codex reviewer 已完成 reviewer-perspective 审查：

```text
artifact = var/dg25/reviews/dg25-ablation-independent-review-20260829-001/review.json
sha256 = f20edc2860bc28363931e2b9373ed97ba8e3e77854301d9a277b6c40133455ac
verdict = APPROVE_WITH_REQUIRED_EDITS
s2_authorized = true, limited to zero-model label-free implementation/equivalence
reader/provider/controller/model calls authorized = 0
formal holdout authorized = false
candidate default = false
```

执行者接受全部 8 项 required edits，不做静默删减：

| ID | 落地决定 | 生效门 |
| --- | --- | --- |
| RE-01 | 新建 immutable arm/K/channel-cap/budget/query/scorer manifest | S2 运行前 |
| RE-02 | 新增 R0P；累计 arm 只报告 order-conditional increment；最终候选做 full-minus-one | E1 前 |
| RE-03 | T0–T4 共享同一 raw rows；T2 允许 `NOT_APPLICABLE`；T4 作为 safety necessity | E2 disposition 前 |
| RE-04 | 明确 opened-development 已受历史 label 定位影响，不做统计/泛化声明 | 所有 effect/terminal receipts |
| RE-05 | 分离 logical action、physical/replay calls、rows、hydration、Binding、Reader 与 latency | final policy 前 |
| RE-06 | 先冻结 answer routing strata；A1–A2/A3 仅同 case 配对；A0 只作历史参照 | E4/Reader calls 前 |
| RE-07 | 每个 block receipt 机器化 stop-rule evaluation，禁止评分后调参 | effect execution 前 |
| RE-08 | S2 精确绑定 S1-002 receipt/source manifest | S2 seal 前 |

当前只允许 S2 的 compiler/validator、synthetic/contract、R0→R0P compatibility 和
label-free official-execution equivalence。E1/E2 scorer 读取、E3 opened-dev treatment、E4 Reader 调用、
latency repeats 均没有被该 receipt 授权。

### Review gate-001 结果

```text
run_id = dg25-review-gate-20260829-001
status = PASS_DG25_INDEPENDENT_REVIEW_GATE_S2_AUTHORIZED
hard_gate = PASS (15/15 checks)
exact channel-query identities = 75
final K = 8
verified Dense ceiling = 30
S2 arm order = R0 → R0P
effect scoring / Reader calls = NOT AUTHORIZED / 0
```

权威回执：

```text
var/dg25/reviews/dg25-review-gate-20260829-001/receipt.json
var/dg25/reviews/dg25-review-gate-20260829-001/pre-treatment-arm-manifest.json
var/dg25/reviews/dg25-review-gate-20260829-001/stop-rule-registry.json
var/dg25/reviews/dg25-review-gate-20260829-001/executor-feasibility-review.json
var/dg25/reviews/dg25-review-gate-20260829-001/required-edit-disposition.json
```

arm manifest SHA-256 为 `d6565873e1e188b186c20d53d9151c5c3d1dabc542d886a9eee1a714a0944f24`，
内部 `manifest_digest` 为 `b9c4015d699c073d8936a47d0ed132c527d5b8df8aa29ad98f588d05ec9a2aec`。
它精确冻结 S1-002、10/23/37、75 个 channel-query identities、各 channel replay/live caps、
预算、scorer identities、全部 arm 顺序、成本账本和 10 条机器停止规则。

review gate 首轮另追加 2 条失败，DG-25 failure index 累计 20 条：一条把具名 `run_identity`
误当 SHA-256，一条为 `__all__` 排序。修复后 targeted tests 为 19 passed，Ruff 与 pycompile 均 PASS；
未改变任何 review、K、cap、budget 或授权字段。

## S2-003 Unified plan compiler / validator / official batch execution 结果

已执行：

```text
run_id = dg25-s2-plan-execution-20260829-003
status = PASS_DG25_S2_UNIFIED_PLAN_OFFICIAL_BATCH_EXECUTION
hard_gate = PASS (29/29 checks)
S3 effect execution = NOT AUTHORIZED
```

权威回执：

```text
var/dg25/s2/dg25-s2-plan-execution-20260829-003/receipt.json
var/dg25/s2/dg25-s2-plan-execution-20260829-003/requirement-acquisition-plan-traces.json
var/dg25/s2/dg25-s2-plan-execution-20260829-003/plan-validation-report.json
var/dg25/s2/dg25-s2-plan-execution-20260829-003/official-execution-equivalence-report.json
var/dg25/s2/dg25-s2-plan-execution-20260829-003/source-manifest.json
```

文件 identity：

```text
receipt                                  b79fea0f2efd858fc651df2f0fcfbcc3fd0bfdf27e63d9c731f070c433ca7d77
plan traces                              b2f40b59401ff7ca452df9f5a420f67b27e0633eb4d1f1b69f50a309bbf74f59
validation report                        46e7a2c63787ccf80a6870d3c5b3596a0a79e49bdf769f7d5b396bc7aca1f5e1
official equivalence report              7dc31ea2492a349b55a4ade16c3eef195fc4a6690e38a79a2cc534ed438be664
source manifest                          e2836a4603cf0d37911732b823be448ce0b1425a021f9637360fb167976e6b2c
```

S2 新增 label-free `RequirementAcquisitionPlanCompiler` 与 official
`EvidenceAcquisitionExecutor.execute_plan(...)` candidate execution boundary。执行前必须完成
query/state/epoch/capability/policy/snapshot/access identity、exact feasible membership、
action uniqueness 与 aggregate call/hydration budget 校验；任一失败整个 plan 在仓库调用前拒绝。
多 action 路径先执行全部预声明 official probes，再做一次 union 和一次完整
Span/Interpretation/Binding/RequirementState/Sufficiency 重算；旧单 action 路径保持不变。

机器验证事实：

```text
R0 → R0P semantic dimensions             exact equality
R0 / R0P repository calls                  1 / 1
R0P action digest / candidate cap           preserved / 8
fresh plans accepted                        2
stale / unregistered / budget negatives     3/3 rejected before repository call
proof + discovery actions                   2 composed
composed repository calls                   2
composed planned candidate cap sum          16
full semantics recomputations                1
RequirementState epoch increment             1
retained channel lineage                    FTS_RAW + TEMPORAL_EVENT
targeted S2 tests                            9 passed
full Runtime unit/contract + DG25 regression 527 passed
strict mypy                                 149 source files PASS
Ruff / pycompile                            PASS / PASS
architecture validate / release lock        PASS / PASS
labels / formal holdout / effect scoring    0 / 0 / 0
Reader / Provider / model / controller      0 / 0 / 0 / 0
automatic retries / canonical mutations     0 / 0
public MCP / PostgreSQL / architecture drift 0 / 0 / 0
```

S2 receipt 精确绑定 S1-002 receipt/source manifest、independent review gate receipt 与
pre-treatment arm manifest。S2 只证明合同、R0P 等价与 synthetic official execution 可行性；
没有读取 opened-development labels，没有执行 E1/E2 effect scoring，也没有将 candidate 接入
default product path。因此 S3 必须先获得 post-S2 independent authorization，不得直接评分。

S2 阶段追加 11 条 append-only failure，failure index 累计 31 条：

| Failure family | Root cause | General repair |
| --- | --- | --- |
| initial source patch | 多文件 patch 使用了不存在的 export anchor；原子 patch 未应用 | 先读取精确 export 内容，再拆分有界 patch |
| source Ruff | 新 application import 和 `__all__` 未按确定性顺序插入 | 只调整 import/export 顺序，行为不变 |
| targeted strict mypy | test repository 构造器对 invariant `dict` 类型过窄 | 移除未使用构造参数，不改 Runtime |
| harness Ruff | R0 拆分后留下未使用 compilation local | 删除无用绑定，保持 R0→R0P 顺序 |
| transitive strict mypy | S0 冻结 dict 的 `protected_diffs` 被推断为 `object` | 在 `.items()` 前加 `Mapping` 类型窄化，冻结值不变 |
| S2 runner-001 | runner 读取了不存在的 `live_action_caps` 键 | 按 immutable manifest 真实键 `live_action_candidate_caps` 校验，使用 fresh 002 run |
| full regression S0 live recomputation | 历史 S0 test 在 S2 source 改动后仍期待 live source identity 与 S0 冻结一致 | 分离 immutable S0 receipt 断言与当前 live drift 断言；不放松 freeze |
| expanded strict mypy | S1 时 strict gate 未覆盖全部 DG25 synthetic/test helpers | 对 typed builders 使用 `model_validate`，补全 helper return types，case/expected 不变 |
| synthetic option narrowing | 异构 `dict[str, object]` 在 `int()` 边界未窄化 | 新增通用 fail-fast integer option validator |
| synthetic import Ruff | 新 return type import 的顺序不符合 lint | 仅调整 import 顺序 |
| architecture command path | 首次将 scripts 误定位在 `architecture/` 根 | 使用已发现的 `architecture/v1.0/scripts/` 和冻结 external anchor |

`dg25-s2-plan-execution-20260829-001` 保留为未封存的失败 run；002 保留为质量注解前的历史 PASS；
003 重新绑定当前 13 个 source files 且独立重算无 drift。
所有修复都未改变 R0/R0P arm、K=8、channel caps、budget 或授权边界。

## Post-S2 independent review 与 S3 readiness-001

post-S2 independent reviewer 在 writer terminal 后封存最终审查：

```text
artifact = var/dg25/reviews/dg25-post-s2-independent-review-20260829-001/review.json
sha256 = f8dfeb27cb45c3ce1935f1eeee24b8ca34e7ca6879216ad319a485f399e5b7d5
verdict = REQUIRE_EDITS
S2 technical verification = PASS
E1/E2 official replay / effect scoring = NOT AUTHORIZED / NOT AUTHORIZED
readiness manifest + scorer + contract/synthetic tests = AUTHORIZED
```

该 review 不允许把 arm 名称当成可执行 preregistration。它要求在任何 official arm replay 或 label
读取前补齐 `POSTS2-RE-01..07`：逐 arm 精确组件矩阵、effect scorer source/contract seal、
E2 共同 raw-row subset、一次性全 arm seal 协议、fresh source manifest、绑定式 stop evaluator，
以及对第 10 节顺序冲突的 fail-closed 解释。

顺序现冻结为：

```text
S3A  仅生成并封存全部 11 个 label-free E1 arms
 ↓ labels/scoring forbidden
S4A  实现时间组件，并从同一冻结输入生成/封存全部 5 个 label-free E2 arms
 ↓ 两个 all-arm seals + combined seal
Fresh independent scoring authorization（必须绑定 combined seal）
 ↓
S4B  pre-score stop gate → 一次性打开 scorer registries → joint E1/E2 score → post-score stop gate
```

readiness package 已在不打开 gold/proof registry 内容、不运行 official replay、不执行 effect scorer 的条件下
封存：

```text
run_id = dg25-s3-readiness-20260830-002
status = PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION
receipt sha256 = 65f004e02416516767c05af191027c1fd18bfc0d8b9981f7fed4a7330fce399c
execution delta sha256 = 31478bd57d2f193eb1cab407fca249d57afa716c861691dfd0d57042396b5ab1
execution delta canonical digest = 1028f75d2c3d6a8c1b01f474fd3e32d0d08db0fd844710f6eb080f2995c79493
effect scorer contract sha256 = 047532b20c7b25f8246ac007d5896366fc2f36747e3075c6fe99b8c4effbac92
effect scorer source sha256 = 6451b9cdd48974eff39562c2f9f63e93a7b705edc80deeb47fde70df5e9d3622
effect scorer contract digest = f2905b2a3c2347591331b2f3de8d9b157346676fb54b3098b482e4991532d2ee
E2 common input sha256 = d37cc850a1a367112678710197155008da97deb5483b8720e7e6ec4e15cb60aa
E2 common input digest = 9cb08277576c4e07d37f960afb68ab44196e2dd060f2e75b4b61c66b93a2a1ee
all-arm seal protocol sha256 = 7ff0bf49c2dcda340f09f5d69aba56f6e616dda2c0ce5891170d6de4f97fe4af
source manifest sha256 = dac1e1a84fb4b7410b874617f8c2abd4511ffd13ada38caa09ade147bc26bea5
source manifest canonical digest = 8284cdaabbeb2f1614364a61a80b5628cb946d4f37a8a4e2b5e415cbfbeacaad
stop contract sha256 = e5570f3f0ad36ff10c441982ea82c7de1aac11c9d067b0b8339aeb406ee3644d
```

机器验证事实：

```text
E1 exact configs / order                 11 / 11
E2 exact configs / order                  5 / 5
adjacent or full-minus-one contrasts      exact named component only
E1 common official channel-query identities 75
final K / verified Dense ceiling          8 / 30
E2 common range requirements / raw rows   2 / 973 (494 + 479)
T2 applicability                           pre-label NOT_APPLICABLE for both inputs
scorer filesystem/repository/Runtime imports 0 / 0 / 0
registry content loads / effect scores     0 / 0
official E1 replay / E2 transform          0 / 0
Reader/model/provider/controller calls     0
formal holdout / canonical mutation        0 / 0
candidate default                          OFF
synthetic stop gates                       positive shapes PASS; label/missing-seal negatives rejected
S2 source continuity                       13 / 13
targeted tests / strict mypy / Ruff         6 passed / PASS / PASS
expanded DG25 + Runtime regression          533 passed
architecture validate / release lock        PASS / PASS
```

readiness-001 因 scorer Runtime import 与 R1 proof/R2 optional-union 语义混淆被 owner 主动否决并保留；
没有覆盖旧 artifact。readiness-002 使用自包含 scorer hash，并把 active action role 显式区分为
`EVIDENCE_DISCOVERY` / `PROOF_CLOSURE`。R1 可组合 baseline discovery + required proof，只有第二个
discovery action 才由 R2 optional-union flag 控制。

readiness-002 后仍不得进入 S3A，必须先获得 fresh independent authorization。readiness receipt 只证明
preregistration 可审查，不证明任何 arm efficacy，也不产生 `final-minimal-policy.json`。

S2 后新增 8 条 append-only failure，failure index 当前累计 39 条：

| Failure family | Root cause | General repair |
| --- | --- | --- |
| readiness manifest inspection | 猜测了不存在的 manifest keys | 先枚举 top-level keys，再使用冻结的 `cost_ledger_fields` / `scorer_identities` |
| reviewer artifact stability | reviewer terminal 前读取了尚在写入的 review，随后 hash 改变 | 只在 reviewer 报告 terminal 后消费最终 artifact；瞬态版本未用于授权 |
| initial readiness Ruff | adjacent `zip` 与 import order 不符合 repository profile，且含一个 no-op loop | 使用 `pairwise`、确定性 import order，并删除无效循环，不改 arm/metric |
| initial readiness strict mypy | scorer/replay/JSON helper 的 collection 与 narrowing 隐式 | 添加显式集合类型和统一 fail-fast integer narrowing |
| artifact jq inspection | `.E1/.E2` 被 jq 解析为非法数字 token | 对大写 JSON key 使用 `.["E1"]` / `.["E2"]`；不重跑或修改已 PASS package |
| architecture external anchor | 从缩略状态手工补写 SHA-256，middle bytes 错误 | 从 S0 frozen artifact 读取完整 64 字符 anchor；bundle 与 release lock 均已 PASS |
| scorer isolation contradiction | readiness-001 scorer 导入 Runtime helper，但 contract 声称 Runtime import 0 | scorer 内置 canonical JSON SHA-256，并新增 Runtime/evals import source scan；reviewer 在授权前中止 |
| R1/R2 action-role conflation | replay API 把所有双通道都误当 optional union | 显式传入 action role；R1 required proof 不计为 optional discovery union，新增 synthetic contract test |

以上失败均在修复前封存 receipt；automatic retry 为 0。failure receipts 的新增不会改变 readiness-002
source manifest，readiness-002 之后未再修改其中 13 个 source files。

## Readiness-002 fresh review、五项整改与 readiness-004

readiness-002 的 fresh independent reviewer 已封存终态审查：

```text
artifact = var/dg25/reviews/dg25-s3-readiness-independent-review-20260830-002/review.json
sha256 = e0429920601adb4a7b8c6f4f009164a439bff9fb934bc1701a74fdee1b67469d
verdict = REQUIRE_EDITS
S3A E1 label-free all-arm generation = NOT AUTHORIZED
S4A / S4B / E3 = NOT AUTHORIZED / NOT AUTHORIZED / NOT AUTHORIZED
Reader/model/provider/controller calls = 0
```

该 review 的 `S3R-002-RE-01..05` 全部作为 blocking edit 接受，没有 waiver：

| ID | readiness-004 disposition |
| --- | --- |
| S3R-002-RE-01 | 冻结 11 arms × 15 query-requirement 的 165 个 exact action plans；action role 由 action kind 派生；R1 baseline+required proof、R2 仅在预算允许时增加 optional discovery；遗漏、错标、错 channel、预算逃逸负测 fail closed |
| S3R-002-RE-02 | 预封存实际 `s3a_generator.py`、`arm_sealing.py` 与 `run_dg25_s3a.py`；要求 exact 11-arm set/order、配置/输入/源码/授权绑定、R0/R0P 语义与成本等价、单一 E1 seal；既有输出目录拒绝 |
| S3R-002-RE-03 | generation/score stop gate 改为逐字段 exact equality；S3A runner 从实际工件派生 delta/protocol/source/config/pool/query/K/caps/source identities；错误但格式合法的 64-hex digest 负测被拒绝 |
| S3R-002-RE-04 | arm output、block seal、combined seal 与 self-contained scorer 绑定 block/config/delta/protocol/source/pool/common-input/K/caps/cost schema；重算自身 digest 后篡改 execution binding 仍被 scorer 拒绝 |
| S3R-002-RE-05 | fresh source manifest 覆盖 18 个文件，包括实际 S3A generator/sealer/runner 与 T0 predecessor `evals/dg24/scorer.py`；六个质量门的 stdout/stderr identity 与质量 receipt 被 hash-bound |

权威质量批次：

```text
run_id = dg25-s3-readiness-quality-20260830-001
receipt sha256 = a7d35177a4d992c27c236068fe2218c7dfb76fd2f72a08cf69870091ebef0739
status = PASS_DG25_READINESS_QUALITY
expanded pytest = 537 passed
strict mypy = 143 source files PASS
Ruff / compileall = PASS / PASS
architecture validate / release lock = PASS / PASS
source identities current after gates = 18 / 18
```

最终送审包不覆盖 readiness-001/002/003：

```text
run_id = dg25-s3-readiness-20260830-004
status = PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION
receipt sha256 = a5a8380f2b7a855aac03a6612b9d789991b80e49ac6015cf7d30e2ac08a44cb7
receipt size = 4429
hard gate / receipt checks = PASS / ALL TRUE
artifact identities current = 10 / 10
source identities current = 18 / 18
failure-index snapshot = 51 lines / b6d00f92c79fe77dee1a2e33572c31da39dade69465436d8be232b09f8b58d0a
```

关键 identity：

```text
execution delta sha256 / digest
  d63c7cec31dca149256a01d0923e6eb83255960647ee4c198ca9072e63fabcc6
  5751d8d7044001760afa539237baae48100887932ed622aa35c79173483889ee
E1 action manifest sha256 / digest
  24b39019074b4f653c0d400556a5005ec1954d679ab1767b05a060612ddf3037
  2ba2e8c001368538bd550a1fb1a56e2d48378a0aaf64c0f959f88dd780f176fa
all-arm protocol sha256 / digest
  905a2a7587408fe08495bb1525ae437b17e03e31baf277e56a4c81d0cab2a961
  9808ff807356f36547e9b1fcb4290bccf1d2d8be9325f88f02950495ad1b42b9
effect scorer sha256 / contract digest / source sha256
  757911b0e44f4f731b4068a465a8cb397847d9d7053f92a89912deb43f115c7f
  8d80e61ae494a031a3f0a2d272987e9f031b8382670c25125f5898ac5b624d42
  9a1e7fa8cba172b1d89b2dce9ee51e7d2d051a6d6cf1a75f55197ce4569218f0
E2 common input sha256 / digest
  a4f4fe3c63b486e0e822e0ea28142dc844af0994fd363d9a34ae611746caf9bc
  04f912dc48a0f1bb03aa7701d9568978484c793e848ab286f84a96e1150f32db
source manifest sha256 / digest
  ccbffba9065496f7db87ad30edc42e6e46bda76cc2aa82f33e04f118a5b348d0
  fbc81026661a198089cd813b30062e935a7fecfc61e030f8e1edcae076a92409
stop contract sha256 / bound digest
  988ed6b95e1228fe07b3adf5213ef848afa29fcade79050e8d8cb08e0c58a882
  dce11ee3ca5f19a5f0b0ec76cf1a169ccc5b6854c09a126694a9788f3f7d69fd
quality binding sha256 / digest
  d7655e4add4a66db56dc23fad558668bff1f1146ec9b577c99054e30356f8324
  a882f6ee95533c9287075230c679c693ef93bf24cd0a410d4e02f1bf0fd3b614
```

readiness-003 的十件技术工件与 004 相同且均有效，但其 receipt 在一次 post-seal 检查脚本失败入账后，
不再代表最新 append-only failure-index；因此保留历史、不覆盖，并以 004 作为唯一当前送审包。

从 39 条到 51 条的新增失败反思：

| Failure family | Root cause | General repair |
| --- | --- | --- |
| S2 trace inspection | 将 keyed trace object 猜成 `.records` | 先枚举真实 top-level keys，再按 R0/R0P 等键读取 |
| readiness validation patch | 大 patch 的函数签名上下文落后 | 检查当前函数体并拆成小 patch；原 patch 原子拒绝 |
| protocol/stop builder calls（2 条） | builder 合同收紧后，一处漏传配置、一处向不消费配置的 builder 多传参数 | 按每个 keyword-only signature 分别接线并 fresh rerun |
| R0/R0P synthetic equality | 把语义等价误写成包含 arm-bound plan digest 的整记录字节相等 | 比较语义投影与 action/cost 等价，同时要求不同 plan provenance；生成器内建同一检查 |
| equivalence/runner patch context（2 条） | 两个多文件 patch 使用了不精确返回体/条件分支锚点 | 原子拒绝后按已读取的精确行拆分小 patch |
| readiness strict mypy | Literal、aggregate annotation 与 Any→bool 边界未静态窄化 | 显式 Literal/container 类型与 `isinstance` 窄化；fresh gate PASS |
| readiness Ruff（2 条） | 异常类型、脚本 mode、无效 noqa、导入分组及成员顺序 | 最小修复并将两个 CLI 设为 executable；fresh gate PASS |
| S3A scorer-token isolation | runner 的十工件常量无意命名 scorer artifact | 不放宽禁令；runner 只具名六个实际消费的 label-free 工件，仍对 receipt 十工件通用 hash 校验 |
| readiness-003 inspection | 检查脚本猜测 quality binding 有 top-level `status` | 先枚举 binding keys，再重算全部 canonical digests；004 绑定更新后的台账 |

所有新增失败均先写 receipt/stdout/stderr 并追加 index，再修复或 fresh rerun；没有 automatic retry，
没有覆盖任一历史 run。到 readiness-004 为止，official E1 replay、E2 transformation、label/registry
内容读取、effect scoring、Reader/model/provider/controller call、formal holdout、canonical mutation 与 candidate
enablement 仍全部为 0。下一步只能是针对 receipt
`a5a8380f2b7a855aac03a6612b9d789991b80e49ac6015cf7d30e2ac08a44cb7` 的 fresh independent review；
该 review 已终态返回：

```text
artifact = var/dg25/reviews/dg25-s3-readiness-independent-review-20260830-003/review.json
sha256 = acd6c5ced54328cda0c98fc4d8070d8675d8e858529928d69f21c753fd6c441c
verdict = REQUIRE_EDITS
S3A authorization = false
```

旧 `S3R-002-RE-01/03/05` 已满足，RE-04 的 readiness static contract 已满足；review-003 新增两个
blocking edit：

1. `S3R-004-RE-01`：生成器不得按 case ID 字典序重排，必须保持 immutable
   `denominators.case_order`，其 digest
   `694e5584a791cfa42f4b2b7bbc59835bb4e2462cda333c2c69f2ea5124207c79`
   必须进入 action manifest、generation binding、arm execution binding、E1 seal、runner pre/post gate 与负测；
2. `S3R-004-RE-02`：唯一 official S3A path 的每次失败必须 zero-retry 地写 fresh immutable
   failure receipt/stdout/stderr 并恰好追加一条 failure index；必须覆盖既有输出目录与 post-generation
   gate failure 的 synthetic negatives。

两个 review blocker 已分别作为第 52、53 条失败写入 append-only ledger；在 fresh quality、readiness 与
独立复核明确授权前，不得运行 `scripts/run_dg25_s3a.py`。

### S3R-004-RE-01..02 本地整改（fresh seal 前）

两项 blocker 已完成源码与 synthetic contract 层整改，但尚未被写成授权：

- immutable 十 case 顺序及 canonical digest 已进入 action manifest、query-requirement order、
  execution delta、S3A exact bindings、每个 arm output、E1/combined seal、scorer contract 与 runner
  pre/post gate；每个 case 内 requirement ID 确定性排序，所有 arm 必须保持相同首见 case 顺序；
- self-consistent 但错误排序的 action manifest，以及 post-generation `case_order_exact=false`，均被
  fail-closed 负测拒绝；
- official S3A runner 由单一零重试 wrapper 覆盖 output-directory precheck、readiness/source/artifact/
  authorization/input precheck、generation/seal、post-generation gate 与 atomic write；异常时创建 fresh
  receipt/stdout/stderr，并以一次 append 写入 `var/dg25/failure-index.jsonl` 后重新抛出；
- synthetic negatives 已证明“既有输出目录”和“post-generation gate failure”各自只生成一份失败目录、
  一份 receipt 和一条 index 记录，`automatic_retries=0`。

fresh 定向门禁：

```text
tests/test_dg25_s3_readiness.py = 13 passed
strict mypy = 143 source files PASS
Ruff = PASS
frozen case order digest = 694e5584a791cfa42f4b2b7bbc59835bb4e2462cda333c2c69f2ea5124207c79
case / requirement / plan counts = 10 / 15 / 165
validation S3R-004-RE-01 / RE-02 = true / true
```

整改期间第 54—58 条失败均在修复或重新检查前 append-only 入账：source-scan nested key 读取错误、
两处 Ruff import order、synthetic fixture 将 15 requirements 误建成 15 cases、一次原子拒绝且零改动的
patch context mismatch，以及一次只读检查猜错 validation artifact key。通用修复分别是按真实 nested
schema 取值、规范导入、用 10 cases 聚合 15 requirements、按精确上下文拆小 patch、以及先从源码解析
artifact key。当前 failure index 为 58 条；这些失败没有导致 official replay、label/scoring、Reader/
model/provider/controller call、formal holdout、candidate enablement 或 canonical mutation。

下一合法动作仅为 fresh authoritative quality run；通过后必须生成新的 readiness run，并由独立 reviewer
对该新 receipt 做 fresh 审查。除非 review 明确给出绑定该 receipt 的
`AUTHORIZE_S3A_E1_LABEL_FREE_ALL_ARM_GENERATION`，S3A 仍不得执行。

### Authoritative quality-002 与 readiness-005

整改后的 fresh 权威批次与 readiness seal 已完成：

```text
quality run_id = dg25-s3-readiness-quality-20260830-002
quality status = PASS_DG25_READINESS_QUALITY
quality receipt sha256 / size = c4e07f1617dd77f5bfdf3f6f3cf8b248fdc81cb8f911bcf1ec5bd11ea7af4807 / 9263
expanded pytest = 540 passed
strict mypy = 143 source files PASS
Ruff / compileall = PASS / PASS
architecture validate / release lock = PASS / PASS
source identities current after gates = 18 / 18

readiness run_id = dg25-s3-readiness-20260830-005
readiness status = PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION
readiness receipt sha256 / size = edc2f76a7efc220fd54793340c44619844c3904e29b18f249bb844ceac42913d / 4429
hard gate / receipt checks = PASS / ALL TRUE
artifact identities current = 10 / 10
source identities current = 18 / 18
failure-index snapshot = 58 lines / 81d8b2092afe79c5bb12a35c8c8dc483968c551b29317ae1e1784b2e1ccbb5ce
automatic retries = 0
```

readiness-005 仍明确写出 `s3a_e1_official_replay=false`，它只证明可供审查，不自行授权执行。
当前唯一合法下一步是对 receipt
`edc2f76a7efc220fd54793340c44619844c3904e29b18f249bb844ceac42913d`
发起 fresh independent ablation-planner review；在其终态 verdict 返回前继续 fail closed。

### Independent review-004 与 S3R-005-RE-01

fresh independent review 已终态返回：

```text
artifact = var/dg25/reviews/dg25-s3-readiness-independent-review-20260830-004/review.json
sha256 / size = d28dcf925f4750086e0d0b0961c7e688cf9af8bdc9fa58a02305e6d326fc98b3 / 29097
verdict = REQUIRE_EDITS
S3A authorization = false
```

review 独立重算通过 10 个 readiness artifact identities、475 项 canonical digest、18/18 current
source identities、quality receipt 与 12 个 stdout/stderr identities，以及 58-line append-only failure
index；`S3R-004-RE-01` 的 10-case/15-requirement/165-plan exact order 已判 `SATISFIED`，旧 edits
无回归。唯一新 blocker 是 `S3R-005-RE-01`：

- runner 在 existing-output precheck 前只持有 config identity，source/input/snapshot 仍为空；
- readiness artifact/source whole-set validator 完成后才写入 context，所以第一个 missing/mismatch/unreadable
  identity 会丢失其余 expected/observed attempt envelope；
- 现有两个 wrapper helper 负测显式断言空 source/input identities，证明的是 exactly-one append，未证明
  official path 的完整可复现失败身份。

该 review blocker 已作为第 59 条 failure receipt 追加到 ledger；readiness-005 因而保留为历史包，不再是
最新 failure-index snapshot。整改必须在任何 covered precheck 前冻结 config、readiness/auth snapshot、十个
readiness artifact、十八个 source 与两个 predecessor input 的 expected/observed/missing/mismatch disposition，
并用完整 official-path existing-output 与 post-generation-gate synthetic negatives 验证 exactly-one complete
receipt/index append、zero retry 与 re-raise。完成后必须 fresh quality、readiness-006 和独立 review；此前
official S3A 与全部后续阶段继续禁止。

#### S3R-005-RE-01 本地整改结果（fresh seal 前）

official runner 现通过 `_build_s3a_failure_context` 在首个 hard precheck 前创建并 digest-freeze
`milai.dg25.s3a-attempt-identity-envelope.v0.1`：

```text
snapshot identities = 2 (readiness receipt + authorization review)
readiness artifact expected/current observations = 10
source expected/current observations = 18
predecessor input expected/current observations = 2
combined input identities = 12
each entry = category + key + path + expected_identity + observed_identity
             + MATCH/MISMATCH/MISSING/UNREADABLE/OUTSIDE/EXPECTED-INCOMPLETE disposition
frozen_before_covered_prechecks = true
complete_inventory_frozen = true
automatic_retries = 0
```

`_execute` 在 output-directory precheck 前重算 envelope digest、检查完整性并禁止 context drift；后续
artifact/source/input validation 只读同一身份，不得再追加或改写 envelope。failure receipt 同时保存 envelope、
其 digest，以及完全相同的 source/input/snapshot projections。

负测不再调用孤立 helper：两种情况都通过完整 `_execute` + 单一 failure wrapper。existing-output case 在
generation 前拒绝；post-generation case 使用空的内存 bundle stub 触发 frozen stop gate，不执行 official
replay。两者均验证一份 failure directory、receipt/stdout/stderr、恰好一条 JSONL append、re-raise、完整
2/18/12 identity envelope、stream hashes 与 `automatic_retries=0`。

整改期间第 60—64 条 fresh failure 均已先入账：初版 source-freshness/fixture precheck、Ruff 多余括号、
scorer metadata token 与 Ruff implicit-concatenation 冲突，以及 predecessor gate 的迟到 input mutation。
通用修复是将 scorer 静态禁令收紧为真实 import/call surface（身份 metadata 不等于 scorer 执行）、规范 path
表达式，并彻底删除冻结后的 context mutation。当前 failure index 为 64 条。

fresh 定向结果：

```text
tests/test_dg25_s3_readiness.py = 13 passed
strict mypy = 143 source files PASS
Ruff = PASS
readiness validation hard gate = PASS, false checks = 0
source manifest fresh = true, false source checks = 0
S3R-005-RE-01 static readiness check = true
```

这些结果仍不是执行授权。下一合法动作是 fresh authoritative quality-003、readiness-006 与新的独立
ablation-planner review；在精确 S3A authorization 返回前保持 fail closed。

#### Authoritative quality-003 与 readiness-006

```text
quality run_id = dg25-s3-readiness-quality-20260830-003
quality status = PASS_DG25_READINESS_QUALITY
quality receipt sha256 / size = 39250ddc186632c293e864a45b7b8b69a73468196b05bbb19ce6563e61b20197 / 9263
expanded pytest = 540 passed
strict mypy = 143 source files PASS
Ruff / compileall = PASS / PASS
architecture validate / release lock = PASS / PASS
source identities current after gates = 18 / 18

readiness run_id = dg25-s3-readiness-20260830-006
readiness status = PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION
readiness receipt sha256 / size = 9768ab4a793b2535b97996c0187e5dc2dbda2551e0eb9a20f186f244bb43ffa9 / 4429
hard gate / receipt checks = PASS / ALL TRUE
artifact identities current = 10 / 10
source identities current = 18 / 18
failure-index snapshot = 64 lines / bc09d6352dd16f713ee566a305191f11537276e8893150722e9b03a3400cf390
automatic retries = 0
```

readiness-006 仍明确设置 `s3a_e1_official_replay=false`。唯一下一步是 fresh independent review 对上述
receipt 与 complete-envelope official-path negatives 做独立重算；只有精确、receipt-bound 的
`AUTHORIZE_S3A_E1_LABEL_FREE_ALL_ARM_GENERATION` 才允许一次 S3A 执行。

### Independent review-005 与 S3R-006-RE-01..04

fresh independent review 已终态返回：

```text
artifact = var/dg25/reviews/dg25-s3-readiness-independent-review-20260830-005/review.json
sha256 / size = 8f31794f99e1a431a2aeff273560aa90bfc55273bb996b9b12a3e827921b7cab / 37739
verdict = REQUIRE_EDITS
S3A authorization = false
```

review 独立重算通过 10/10 readiness artifacts、18/18 source identities、quality receipt 与 12 条质量
stream identities、64-line failure snapshot，以及 635 项 canonical/self/cross-artifact digest；冻结的
10-case / 15-requirement / 165-plan exact order 与既有 edits 均无回归。但 reviewer 识别出四项新的
pre-authorization blocker：

| ID | 阻断事实 | 必须完成的通用整改 |
| --- | --- | --- |
| `S3R-006-RE-01` | attempt-envelope builder 在唯一 failure wrapper 外；invalid UTF-8 等首个 capture failure 可能没有正式证据 | 在任何 read 前预分配 2/10/18/2/12 固定槽位，把 capture 放入 exactly-once top-level boundary；所有 capture exception 映射为明确 disposition，冻结 envelope 后由首门失败并记录一次 receipt/index/re-raise |
| `S3R-006-RE-02` | 未认证 receipt path、dot-dot 与外部 symlink 可在 containment/authentication 前被读取；run ID 可把输出导向 S3A 根外 | run/readiness ID 只允许安全单组件；所有 output/review/receipt/10 artifact/18 source/2 predecessor 均先做 resolved exact provenance，再 hash/parse/write；只观察冻结固定路径集 |
| `S3R-006-RE-03` | synthetic valid fixture 的 20 个 symlink 实际解析到 synthetic root 外 | 使用 workspace-local copy/generated fixtures，并覆盖 invalid-content、absolute/traversal、path-set drift 与外部 symlink 的完整 top-level negatives；断言 generation/forbidden parse/outside write 前拒绝且 exactly-one failure evidence |
| `S3R-006-RE-04` | scorer/Reader/model/provider/controller surface 仅以字符串拼写扫描，alias、`importlib`、`__import__`、`eval`、`exec`、`getattr` 可绕过 | 使用 parsed AST import/call allowlist，加入 alias/dynamic indirection 负测，同时保留 10 个 readiness artifact（含 effect-scorer metadata contract）的纯身份 hash |

review blocker 已先作为第 65 条 failure receipt 写入：

```text
failure_id = dg25-readiness006-preauthorization-containment-review-20260830-001
first failing gate = DG25_S3A_PREAUTH_CAPTURE_AND_PATH_CONTAINMENT
receipt sha256 / size = 7dc9740e57e15ae2ca2d1cf53e200a4a282c64ad14d1bcf8fed379c1634f1528 / 3842
fresh rerun = dg25-s3-readiness-after-preauth-containment-20260830-007
```

随后一次只读时间戳检查使用了本机 GNU `date` 不支持的 `--iso-8601=microseconds`，也在修正命令前
作为第 66 条失败登记；通用修复是使用受支持的 `--iso-8601=ns` 或显式格式。该辅助失败没有执行
S3A、读取 label/registry、调用 Reader/model/provider/controller、触碰 formal holdout、启用 candidate 或
修改 canonical state。

因此 readiness-006 仅保留为历史技术通过包，其 64-line failure snapshot 已陈旧，不能授权 S3A。当前只允许
完成四项整改、fresh tests/quality、生成 readiness-007 并再次独立复核；在新的精确 receipt-bound
authorization 返回前，S3A 及全部下游阶段继续 fail closed。

#### S3R-006-RE-01..04 本地整改与 readiness-007

四项 edit 已在 fresh source seal 中落地：

- official entrypoint 先以无读取方式预分配 2 snapshot / 10 readiness artifact / 18 source / 2 predecessor /
  12 combined input 固定槽位，再进入唯一 exactly-once failure wrapper；UTF-8、JSON、permission、stat、hash、
  缺字段和其余 capture exception 均保留完整 inventory、explicit disposition、zero retry、一次 receipt/index
  append 与 re-raise；
- run/readiness ID 只允许安全单组件；output 必须是 `var/dg25/s3a` 的 resolved direct child；authorization、
  receipt、10 artifacts、18 sources 与 2 predecessors 在任何 hash/parse/write 前执行 exact lexical + resolved
  provenance，拒绝 absolute、dot-dot、path-set drift 和 symlink substitution；source/action manifest 只有在
  reviewed receipt binding 与 10/10 artifact identities 通过后才允许解析；
- synthetic official fixture 的 20 个外部 symlink 已全部替换为 synthetic workspace 内的真实副本；完整
  negative matrix 覆盖四类 JSON 的 invalid UTF-8 / invalid JSON / unreadable、missing/hash/stat、remaining
  capture exception、六类 absolute/traversal、authorization/receipt/readiness/output/artifact/source/predecessor
  symlink，以及 existing-output 和 post-generation gate；每个 attempt 均验证 exactly-one official evidence；
- runner/generator 改用 parsed AST import/call allowlist；拒绝 import alias、`importlib`、`__import__`、`eval`、
  `exec`、`getattr`、attribute scorer call 与 subscript dispatch，同时 effect-scorer contract 等 10 个 artifacts
  仍只做 metadata identity hashing，不进入 scorer/label/registry content。

整改中的第 67—69 条失败均先于修正 append-only 入账：一次原子拒绝且零改动的 large patch context mismatch、
Ruff 对 broad catch / exception type / mapping iteration 的三项拒绝，以及 strict mypy 对 test JSON `Any` return
的拒绝。通用修复分别为按精确边界拆小 patch、显式列举 capture/data exceptions 并保留最外层 wrapper 兜底、
使用正确类型异常与 `.items()`，以及在 JSON test boundary 显式窄化 object。当前 failure index 为 69 条；
没有失败被覆盖或自动重试。

fresh 权威证据：

```text
targeted official-path / AST tests = 18 passed
quality run_id = dg25-s3-readiness-quality-20260830-004
quality status = PASS_DG25_READINESS_QUALITY
quality receipt sha256 / size = 18ab81183f38bb7efac0a274ed30b8d8363f9acd9c5bdbc95b6d4b4e1368bfc5 / 9263
expanded pytest = 545 passed
strict mypy = 143 source files PASS
Ruff / compileall = PASS / PASS
architecture validate / release lock = PASS / PASS
source identities current after gates = 18 / 18

readiness run_id = dg25-s3-readiness-20260830-007
readiness status = PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION
readiness receipt sha256 / size = ae341ee2f6b5a0c6b27f0bf9b5a6f3a7e93be45f677cb628891f9e1ece2a3ff1 / 4429
hard gate / false checks = PASS / 0
artifact identities current = 10 / 10
source identities current = 18 / 18
AST findings runner / generator = 0 / 0
failure-index snapshot = 69 lines / 9ef75990ced81c2e466a00d3f390f25e8f3e0eb280f27fe5b9b1343e4c8c5288
automatic retries = 0
```

readiness-007 仍明确写出 `s3a_e1_official_replay=false`，未执行 E1 replay、E2、effect scoring、
Reader/model/provider/controller call、formal holdout、candidate enablement 或 canonical mutation。唯一合法下一步是
由独立 reviewer 对 receipt `ae341ee2f6b5a0c6b27f0bf9b5a6f3a7e93be45f677cb628891f9e1ece2a3ff1`
做 fresh 审查；只有精确 receipt-bound 的 `AUTHORIZE_S3A_E1_LABEL_FREE_ALL_ARM_GENERATION` 才允许一次 S3A。

### Independent review-006 与 S3R-007-RE-01..02

fresh independent review 已终态返回：

```text
artifact = var/dg25/reviews/dg25-s3-readiness-independent-review-20260830-006/review.json
sha256 / size = 9e1ca2fde0eb21f45e1e6e29f736440749cbb37376701e9e3ea94f1bf1af1bc8 / 34642
verdict = REQUIRE_EDITS
S3A authorization = false
```

除 AST call gate 外，reviewer 对 readiness-007 的 10/10 artifacts、18/18 sources、quality streams、69-line
failure snapshot、canonical/cross bindings、capture/path negative matrix 与旧 edits 均未发现新回归。唯一 blocker
是 `S3R-007-BF-01`：当前 parsed-AST 实现仍是 fail-open call blacklist，而非 closed-world、binding-aware
allowlist。独立 in-memory adversarial snippets 已证明以下调用可返回 CLEAN：

- unresolved callable `unknown()`；
- `fn = obj.score_all_arms; fn()`；
- `sys.modules[...].score_all_arms()`；
- `factory().score_all_arms()`；
- 先绑定再调用的 `getattr`、`__import__`、`eval`；
- 同类 Subscript-to-name alias（必须在新负测中显式冻结）。

required edits：

| ID | 必须完成的整改 |
| --- | --- |
| `S3R-007-RE-01` | 每个 `ast.Name` call 必须解析为显式允许的 local function、import symbol、constructor/builtin 或指定 call-site function parameter；unresolved name 一律失败。禁止 forbidden/unresolved callable assignment alias；Attribute root 为 Subscript/Call/Lambda/unresolved、`sys.modules`、`builtins`、`importlib` 一律失败；禁止 `__import__/getattr/eval/exec/compile/globals/locals/vars/setattr/delattr` 及其 alias。无法证明 exact allowed target 就产生 finding。 |
| `S3R-007-RE-02` | 把 reviewer 的 AST-BYPASS-01..07 与 Subscript-to-name alias 全部纳入 source-bound negatives；只允许精确冻结的 honest runner/generator call surface；之后 fresh quality、18-source seal、failure snapshot、readiness 与独立 review。 |

该 blocker 已在修正前作为第 70 条 failure receipt append-only 入账：

```text
failure_id = dg25-readiness007-ast-call-allowlist-review-20260830-001
first failing gate = DG25_S3A_AST_CALL_ALLOWLIST
receipt sha256 / size = 1e5def2c88c8d2e32dd99dafc92a93dfb3b89d5f1bae59336c073fc2945813c7 / 3428
fresh rerun = dg25-s3-readiness-after-binding-aware-ast-allowlist-20260830-008
```

readiness-007 的 69-line failure snapshot 因而已陈旧，仅保留为历史技术包。当前只允许完成上述两项 AST
整改并生成 fresh quality/readiness/review；S3A 与全部下游阶段继续禁止。

#### S3R-007-RE-01..02 整改与 readiness-008

两项 required edit 已在 fresh source seal 中落地：

- runner/generator 的所有诚实调用已等价改写为 `ast.Name` 或以已绑定 `ast.Name` 为根的 Attribute chain；
  runner 185 个、generator 105 个唯一调用目标逐项进入显式 closed-world allowlist，并在 source manifest 中同时
  封存 allowed/observed target list、count、exact-match 与 contract digest；缺少或新增任一目标均产生 finding；
- 每个 Name call 现在必须解析到显式允许且未被 shadow 的 top-level local function/class、精确 import、builtin /
  constructor，或仅限 `_execute_with_failure_ledger.execute` 的指定 parameter callsite；unresolved name 默认失败；
- assignment alias、Attribute root 与动态引用均做 binding-aware 检查：Subscript/Call/Lambda/未解析表达式根、
  `sys.modules`、`builtins`、`importlib`，以及 `__import__/getattr/eval/exec/compile/globals/locals/vars/setattr/delattr`
  本身或 alias 均 fail closed；
- source-bound negative tests 已逐项冻结 AST-BYPASS-01..07、`fn = dispatch['score']; fn()`、其余动态 builtin
  alias、dynamic module access、Lambda/Call root 与 unresolved Attribute root；精确诚实 runner/generator 仍为
  0 findings。

整改过程中的两项新失败均在修正前 append-only 入账：第 71 条是大块 checker patch 的 context mismatch，补丁
原子拒绝且未改变 checker implementation；第 72 条是拆分 `datetime.now().astimezone()` 后 Ruff DTZ005 暴露
无时区中间值，修复为显式 `datetime.now(UTC)` 后再转本地时区。两者 automatic retry 均为 0：

```text
failure 71 = dg25-readiness008-ast-checker-patch-context-20260830-001
receipt sha256 / size = e63cb8c1d6fb3b4b2da44c5a5f65f6df35dbefbbc329642fa46f1c005d436e1f / 2310
failure 72 = dg25-readiness008-ruff-dtz005-20260830-001
receipt sha256 / size = f5fcf4018a2d778a4278159534dde562561f600956448bf3bb895ab086e72861 / 2461
```

fresh 权威证据：

```text
targeted readiness / source-bound AST tests = 26 passed
quality run_id = dg25-s3-readiness-quality-20260830-005
quality status = PASS_DG25_READINESS_QUALITY
quality receipt sha256 / size = 0a93011593e5b1ef356cda6b77fc3edbcbaf525b4e93b86a8fd6f905fb51016e / 9264
expanded pytest = 553 passed
strict mypy / Ruff / compileall = PASS / PASS / PASS
architecture validate / release lock = PASS / PASS
quality source identities current = 18 / 18

readiness run_id = dg25-s3-readiness-20260830-008
readiness status = PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION
readiness receipt sha256 / size = 3219f1b1d83b83101438024053ec876254a125bcf7b0669e3b7e6e87e9a697c0 / 4430
hard gate / false checks = PASS / 0
artifact identities current = 10 / 10
source identities current = 18 / 18
AST findings runner / generator = 0 / 0
exact call targets runner / generator = 185 / 105
call-target contract digest runner = 6966eac3311b2d1948d9f08daf3f404e0cbbf4480c88c7f606563304144c40ed
call-target contract digest generator = 5a711813f4124c771113afa0aaba29a8dd0ac30ac5dd13091392a6ed700f4b49
failure-index snapshot = 72 lines / 160845f3c6b30d7139fa1e3cde2149af38f8d336da3f1246ffe5f9c6dc7c9595
automatic retries = 0
```

readiness-008 继续明确记录 E1 replay、E2、effect scoring、Reader/model/provider/controller、formal holdout、
candidate enablement 与 canonical mutation 均为 0 / false。唯一合法下一步是 fresh independent review；只有审查
对 receipt `3219f1b1d83b83101438024053ec876254a125bcf7b0669e3b7e6e87e9a697c0` 给出精确绑定的
`AUTHORIZE_S3A_E1_LABEL_FREE_ALL_ARM_GENERATION`，才允许执行一次 S3A。

### Independent review-007 与 S3R-008-RE-01..02

fresh independent review 已终态返回：

```text
artifact = var/dg25/reviews/dg25-s3-readiness-independent-review-20260830-007/review.json
sha256 / size = 7072f3b13783676dd60182f93b66a0d04dd7175083e886ed0948752f1ed4bfc3 / 31409
verdict = REQUIRE_EDITS
S3A authorization = false
```

reviewer 核验通过 readiness-008 的 10/10 artifacts、18/18 sources、12 quality streams、72-line ledger prefix、
canonical/cross bindings 与 S3A 未执行状态；新发现的唯一 failure family 是 callable provenance + reachability。
保持完整 runner 185-target set 和 contract digest `6966eac3...40ed` 的 whole-source 变异，可以把 wrapper 的
`execute` 来源替换成 argparse 注入的 `int`、`__builtins__.globals` 或 `args.score_all_arms`，同时把真实
`_capture_and_execute` 调用移入 `if False`，检查器仍返回 0 findings。由此证明“允许参数名被调用”不等于
“唯一 wrapper 可达且绑定到预注册 executor”。

required edits：

| ID | 必须完成的整改 |
| --- | --- |
| `S3R-008-RE-01` | 将唯一 failure wrapper 直接绑定到精确、可达的 `_capture_and_execute`；优先消除泛型 `Callable execute` 注入。若保留 callback，必须证明 exact body/args/callsite，并拒绝来自 argparse Namespace、parameters、locals、Attributes、Subscripts、conditionals 或未审 lambda 的 callable。静态存在但位于 `if False` 不得算通过。 |
| `S3R-008-RE-02` | 禁止 `__builtins__`，并把 scorer/Reader/model/provider/controller 等 forbidden Attribute segment 的检查扩展到作为数据运输的 Attribute，而非只检查 `Call.func`。新增保持完整 185/105 target set 的 whole-source mutation negatives，覆盖 `execute=args.x` + default `int`、default `__builtins__.globals`、`execute=args.score_all_arms`、required target 移入 `if False`，以及 generator 同类 transport；每项必须以 provenance/reachability/binding finding 失败，而不能依赖 target-set mismatch。之后 fresh quality/readiness/review。 |

该 review blocker 已在任何修正前作为第 73 条 append-only 入账：

```text
failure_id = dg25-readiness008-callback-binding-review-20260830-001
first failing gate = DG25_S3A_CALLBACK_BINDING_AND_REACHABILITY
receipt sha256 / size = 570b2d1df3004a114c2ca8d69000eec525299a25e74935a1678b31d98e6947e3 / 2861
fresh rerun = dg25-s3-readiness-after-exact-executor-binding-20260830-009
```

readiness-008 的 72-line failure snapshot 已陈旧，仅保留为历史技术包。S3A 与全部下游阶段继续禁止。

#### S3R-008-RE-01..02 整改与 readiness-009

callback provenance 与 reachability 已作为独立于 call-target set 的机器合同落地：

- runner 的 `_run_s3a_once` 与 `_execute_with_failure_ledger` 现在同时满足逐语句 normalized-AST 合同、exact
  parameter/body contract、`_capture_and_execute/_execute_with_failure_ledger/execute = 1/1/1` critical-call count，
  且唯一 lambda 必须精确为 `lambda: _capture_and_execute(args, context, root=root)`；任何 argparse/local/
  Attribute/Subscript/conditional replacement 均产生 `RUNNER_EXECUTOR_BINDING_CONTRACT_MISMATCH`；
- 所有 `if False`、`while False` 或常量条件不可达分支中的 call 均产生
  `STATICALLY_UNREACHABLE_CALL_FORBIDDEN`；因此把真实 executor 仅保留在 dead branch 不能满足合同；
- `__builtins__` 已加入 forbidden dynamic references；`score_all_arms/scorer/reader/provider/controller/repository/
  persistence/importlib` 等 Attribute segment 现在无论作为 `Call.func` 还是 callable data 都被拒绝；
- generator 仅允许两个精确 sort callback：`record_requirements.sort` 与 `required_requirements.sort` 的
  `lambda item: str(item['requirement_id'])`；额外 lambda、bound-method/Attribute callback transport 均失败；
- 7 个 full honest-source mutations 保持完整 185/105 target set 与原 call-target digest，分别覆盖 argparse
  default `int`、default `__builtins__.globals`、`args.score_all_arms`、required executor 移入 `if False`，以及
  generator 的 scorer Attribute、未审 bound method 与 builtins globals transport；全部以 provenance /
  reachability / forbidden-reference 专用 finding 失败，且明确断言无
  `CALL_TARGET_ALLOWLIST_EXACT_MISMATCH`。

fresh 权威证据：

```text
targeted readiness / whole-source mutation tests = 28 passed
quality run_id = dg25-s3-readiness-quality-20260830-006
quality status = PASS_DG25_READINESS_QUALITY
quality receipt sha256 / size = 0e7f81cb8198a91cf186d5f8025b4447442b218e773991e8e17da592df6bbdf2 / 9264
expanded pytest = 555 passed
strict mypy / Ruff / compileall = PASS / PASS / PASS
architecture validate / release lock = PASS / PASS
quality source identities current = 18 / 18

readiness run_id = dg25-s3-readiness-20260830-009
readiness status = PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION
readiness receipt sha256 / size = 6c5094be18a501970f83f9b778d739df64c19b1f5ba6246ad668a1e3a2ed3294 / 4430
hard gate / false checks = PASS / 0
artifact identities current = 10 / 10
source identities current = 18 / 18
call-target exact runner / generator = 185 / 105
call-target digests runner / generator = 6966eac3311b2d1948d9f08daf3f404e0cbbf4480c88c7f606563304144c40ed / 5a711813f4124c771113afa0aaba29a8dd0ac30ac5dd13091392a6ed700f4b49
callable provenance/reachability contract digest = ac30dd799666250176c83d46359e68cb0572a2d3b85c21d41e1941c79bf5bcb7
runner executor / generator callback findings = 0 / 0
failure-index snapshot = 73 lines / e9bb0d3b0fc52783d551313b7f9f2ab855e1a603205455e579264397643528c3
automatic retries = 0
```

readiness-009 仍明确记录 S3A/E1、E2、effect scoring、Reader/model/provider/controller、formal holdout、
candidate 与 canonical mutation 均未进入。唯一合法下一步是对 receipt
`6c5094be18a501970f83f9b778d739df64c19b1f5ba6246ad668a1e3a2ed3294` 做 fresh independent review。

#### Review orchestration interruption 与 readiness-010

第一次委派 review-008 时，平台在任何分析或 artifact 创建前将任务误判为 possible cybersecurity risk 并中止；
该事件不是技术 verdict，且没有修改受审源、quality、readiness 或 canonical state。它已在重新委派前作为第 74 条
failure 入账：

```text
failure_id = dg25-readiness009-independent-review-policy-interruption-20260830-001
first failing gate = DG25_S3_READINESS009_INDEPENDENT_REVIEW_ORCHESTRATION
receipt sha256 / size = 3699102068e15695c5d155b2f8f2e2688ed037475d429d7c230f5efe1ae6a760 / 2507
automatic retries = 0
```

由于 append-only snapshot 变化，readiness-009 立即历史化；18 个受审源未改变，quality-006 仍 current，因此以同一
quality evidence 重新封存新 snapshot：

```text
readiness run_id = dg25-s3-readiness-20260830-010
status = PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION
receipt sha256 / size = ffcd2d7aaae9ceb3b9026635e928e53e3028c6a76c57f25844d728338b4c9469 / 4430
failure-index snapshot = 74 lines / c28bd9e763869815399baca28507cab76964199f200fe9ee31a1a0a90b8e2b4d
quality receipt = 0e7f81cb8198a91cf186d5f8025b4447442b218e773991e8e17da592df6bbdf2
S3A / downstream execution = 0
```

fresh independent review 必须绑定 readiness-010，而不得继续引用已陈旧的 readiness-009。

第二次委派也在分析与 artifact 创建前被同一平台分类器中止，仍不构成技术 verdict。该失败作为第 75 条
append-only 入账，readiness-010 随 snapshot 变化而历史化：

```text
failure_id = dg25-readiness010-independent-review-policy-interruption-20260830-002
receipt sha256 / size = 4a82ea71b860fad62e5eb73c6dcaca05a611b396272c3dc4233672faaf9e71b6 / 2514
readiness run_id = dg25-s3-readiness-20260830-011
readiness receipt sha256 / size = d5628ffb571e82794344a059a50734467c6069b6614a84864ed8e77ef74e8ac8 / 4430
failure-index snapshot = 75 lines / e683eef2fc1384c421c2b28e4ab98918827a5043cf20a6cd69c223cfcbace3a1
technical source / quality change = 0
S3A / downstream execution = 0
```

下一次委派只引用 readiness-011 与仓库内已有审查合同，不在任务文本复述测试变换细节。

### Independent review-008 与 S3A official E1 all-arm seal

fresh reviewer 对 readiness-011 完成 472 项 canonical/cross-binding 核验与 9 个 target-set-preserving negatives，
关闭 `S3R-008-RE-01..02`，并签发一次性、零重试、严格 label-free S3A 授权：

```text
review artifact = var/dg25/reviews/dg25-s3-readiness-independent-review-20260830-008/review.json
review sha256 / size = ce3b330fe78a045b6c6b430cb17f6df22c2cbf24c65d0e433247e7bcb3f4776e / 33541
verdict = AUTHORIZE_S3A_E1_LABEL_FREE_ALL_ARM_GENERATION
authorization digest = 056fea828acc5a990a07b1f27221d806786dadb32fabbb31e31caa95df677cc0
reviewed readiness receipt = d5628ffb571e82794344a059a50734467c6069b6614a84864ed8e77ef74e8ac8
authorized attempts / automatic retries = 1 / 0
S4A / S4B / scoring / E3 / Reader / holdout / candidate = NOT AUTHORIZED
```

授权消费前，runner 独立验证 review schema、authorization/readiness-bindings digest、reviewed receipt、18 个源、
10 个 artifacts、75-line failure snapshot、路径 containment/symlink boundary 与 output absence。随后 official runner
恰好调用一次并成功：

```text
run_id = dg25-s3a-e1-label-free-20260830-001
status = PASS_DG25_S3A_E1_LABEL_FREE_ALL_ARM_SEALED
output = var/dg25/s3a/dg25-s3a-e1-label-free-20260830-001
e1-label-free-arm-outputs.json sha256 / size = 4f52a4837dc6b86edbd10e15a1fda80b3ad4e2e47485064981f0ad8a739d6e77 / 1691874
e1-all-arm-seal.json sha256 / size = 7e08857a33f1943dd3a84c6cd4f79dbc795533824efce592bb6709fbc02dfcf6 / 7801
E1 seal digest = 7333ef178ed0654df49f49cb2636f088f5d39618c87f5d98fe490d102441692a
arm outputs / records per arm = 11 / 10
labels / registry / scoring loaded = false / false / false
Reader-model-provider-controller calls = 0
formal holdout / canonical mutations / automatic retries = false / 0 / 0
```

post-write 独立重算已逐 arm 验证 label-free output digest、execution binding、cost-ledger schema、explicit
`arm_order`、11-arm exact set、output-set digest 与 all-arm seal digest。首次审计误把 `sort_keys=True` 后 JSON object
的字典序 key 当作 preregistered arm order，在任何 scorer/label 读取前 AssertionError；该审计错误已作为第 76 条
append-only 入账，S3A 没有重跑，随后改用 exact key set + seal 明示顺序通过：

```text
failure_id = dg25-s3a-postwrite-recompute-json-order-assumption-20260830-001
receipt sha256 / size = 95772411234e1913206b836aa307a325052f1e64a37e1f0f14727dabeba2341d / 2484
post-write recomputation = PASS
failure-index = 76 lines / d82f952ee69059761636688b98cb095406361d7f6b63827c29a3ba1ed606b5bf
```

S3A 的 single-use authorization 已消费，禁止再次调用。当前只允许进入 S4A 实现与独立的 label-free E2
generation/seal 门禁；S4B scoring 仍必须等待 immutable E1/E2 seals、combined seal 与 fresh scoring authorization。

### S4A implementation、quality 与 readiness 闭环

S4A 已实现为纯 label-free 的 `T0..T4` 生成链：`T2` 是严格 no-op；`T3` 按语义 occurrence identity
去重并保留 lineage；`T4` 依据 V02 sufficiency contract fail closed，证据不足时不得伪报 `COMPLETE`。同时修复
LongMem URI canonicalization，并把 combined seal 的 scorer-facing binding 固定为冻结 scorer contract 要求的
exact 16-field map，而不是复用 S4A generation authorization 的 27-field map。official run id 也冻结为
`dg25-s4a-e2-label-free-20260830-001`，runner 在加载 label-free input 前拒绝跨 run-id 重放授权。

实现期失败 77–101 均已在 append-only ledger 中逐项留痕并于 official execution 前关闭。主要类别为：输入/产物
schema 与路径假设、一次越界 fixture 搜索、T3 occurrence identity 与跨 evidence 去重、input manifest binding、
静态质量/可执行位/mypy，以及 immutable SHA 与 nested scorer-contract digest 的绑定错误。最终质量门如下：

```text
quality receipt = var/dg25/quality/dg25-s4a-quality-20260830-005/receipt.json
quality receipt sha256 / size = 5e4c17ef5ad390ad4f6c1a7b35219c2f5da2699a8d7d711aea148f21d69ad669 / 13010
quality gates = 7 / 7 PASS
targeted tests = 14 PASS
strict mypy source files = 141
source-set digest = bfbcb0747f7c23dd4483bc6a82d068ff14dd3456dcc98cb3c3788d91ad353575
protected user diffs = exact-match / unchanged
label / registry / Reader-model-provider-controller / holdout access = false / false / false / false
```

最终 readiness-006 把 quality、S3A E1 seal、frozen protocol/scorer contract、label-free input、product traces、
source/execution manifests、stop contract、109-line failure snapshot 与固定 official run id 绑定为一次性授权对象：

```text
readiness dir = var/dg25/s4a-readiness/dg25-s4a-readiness-20260830-006
receipt sha256 / size = f948a6167aa25d2420b2335d538600e2f769e47c90b9222a6990c11d81a7afe0 / 6160
authorization-bindings digest = 9251972b85da5e26b3f5a9070e64c5617d21fa7361923a409a3e5404285e9d5e
combined-seal 16-field bindings digest = 88d6bc602695320b4f511f2c93428dbafe51fb148411e9c07eb30d8bbbfc9c0e
source manifest sha256 = cf22dfbe…52c56
execution manifest sha256 = e82b2f7e…8a44d
validation report sha256 = d07561a5…884d2
stop contract sha256 = 024bc963…edb0
authorized attempts / automatic retries = 1 / 0
```

### S4A fresh independent review 的 blocker 与关闭

readiness-003 的独立审查发现 combined seal 错把 27-field generation authorization map 当作冻结的
16-field scorer-facing map；该真实 blocker 作为 failure 102 入账，随后通过独立 map、exact-key validator 与
兼容性测试关闭。readiness-004 的审查命令误用 system Python，failure 106 入账且该审查历史化；readiness-005
先因审查侧错误的 `jq` selector 失败并作为 failure 107 入账，随后又发现 authorization 可跨 run-id 重放，
failure 108 入账并通过冻结 official run id 与 pre-load rejection 关闭。最终 Ruff import order 修复作为
failure 109 入账后，readiness-006 获得 fresh reviewer 的明确授权：

```text
review artifact = var/dg25/reviews/dg25-s4a-independent-review-20260830-004/review.json
review sha256 / size = ba95c9adb2bf7e9188e3b104fa7579edbfd17f7d3a16988ec6e10498935c0858 / 6077
verdict = AUTHORIZE_S4A_E2_LABEL_FREE_ALL_ARM_AND_COMBINED_SEAL
authorization digest = 2276549019190326a1188366739d480539aebda34bb541f80457a851895fe63e
review digest = 7899fca2718121b8ae3da8a39be5b308f28f350783eda0dc0674332ca7e79f28
reviewed readiness = dg25-s4a-readiness-20260830-006
forbidden accesses = 0
```

### Official S4A E2 与 E1/E2 combined seal

single-use authorization 恰好消费一次，official runner 一次成功，未触发自动重试：

```text
run_id = dg25-s4a-e2-label-free-20260830-001
status = PASS_DG25_S4A_E2_LABEL_FREE_ALL_ARM_AND_COMBINED_SEALED
output = var/dg25/s4a/dg25-s4a-e2-label-free-20260830-001
e2-label-free-arm-outputs.json sha256 / size = 82ef53318d2571d8c9c2df250ae99bf5268c0c7a26e5402a0d41e6fbb1f385ce / 152285
e2-all-arm-seal.json sha256 / size = dd527f9bbee3c506d39e2f17d120c06a154dfc7f9943270b24d06cd05d21d736 / 5878
E2 seal digest = c2892d20c9ff0137acf11ce00d43248c44481e936dd2c210aa045c56bbc95eda
e1-e2-all-arm-seal.json sha256 / size = d2d03ab60e1a76798c60742311b17eef3907f9a24847b0e9340005c8a648bb30 / 6981
combined seal digest = c2a75955c7ba1a1bff93f341ccf81c1c46f0ddb3492595012ed435533d907b7f
generation-receipt.json sha256 / size = c72d945140fde2bd5736d7cbe1b651fad62d2928356bada4959d397f2802b779 / 1984
arms = 16
labels / registry / scoring loaded = false / false / false
Reader-model-provider-controller calls = 0
formal holdout / canonical mutations / automatic retries = false / 0 / 0
```

生成结果中，`T2` 的 records 与 ledger 均逐字节等于 `T1`；两个 opened-development case 的 `T3`
分别为 `selected/distinct/duplicates/unresolved/ambiguous = 6/4/1/2/0` 与 `8/5/0/2/4`；两者的
`T4` 均为 `PARTIAL`，没有把 V02 证据不足伪装成 `COMPLETE`。首次 post-write 只读审计误用不存在的
`ambiguous_event_count` key，在任何评分或 label/registry 读取前失败；failure 110 已 append-only 入账，
official runner 没有重跑。改正为冻结 schema 的 `ambiguous_time_count` 后，17/17 seal、binding、T2/T3/T4、
零调用与边界检查全部通过：

```text
failure_id = dg25-s4a-postwrite-audit-metric-key-assumption-20260830-001
failure receipt sha256 / size = 326dc61cf8b7b6673c9af52290dc3381fa0a0a871112d9947b344c9f334b1bcb / 2522
post-write audit = 17 / 17 PASS
failure-index = 110 lines / d090ad0c4035c64db1db042bafdd31495e9c0e103aa621175d551e8489ac5697 / 39707 bytes
```

S4A 的 single-use authorization 与固定 run id 均已消费，禁止再次调用。S4B 尚未授权；下一步只能先建立
绑定当前 combined seal、failure ledger、scorer source/contract 以及 labels/registry exact identities 的 fresh
scoring readiness，再由 fresh independent review 签发 scoring authorization。授权签发前不得打开 labels 或
scorer registry，也不得开始 scoring、Reader/model/provider/controller、holdout 或 candidate execution。

### S4B pre-label implementation 与 scorer-source amendment

S4B 前置枚举先后暴露两个无副作用的 owner 假设错误：把 S3 readiness namespace 写成不存在的
`var/dg25/s3-readiness`（failure 111），以及把 envelope 型 source/scorer/stop artifacts 当成扁平 schema
投影（failure 112）。两者都在读取 scorer-only 内容前停止并 append-only 入账，随后改为先枚举真实路径和
top-level keys 再读取已确认的嵌套字段。

随后 source-continuity gate 发现一个真实 blocker：combined seal 的 frozen 16-field map 沿用历史 scorer
source `ee8929… / 29966`，而 S4A readiness/review 已绑定 LongMem URI canonicalization 修复后的 source
`4b429b… / 30493`；二者的 scorer contract digest 同为 `58e1c1…`。该 split 作为 failure 113 入账。
不重跑 S3A/S4A、不修改任何 sealed output，而是在 label/registry 仍未打开时建立 exact compatibility
amendment：从当前源码删除唯一的 `urllib.parse.unquote` import、`_LONGMEM_SOURCE_REF` pattern 和
`_canonical_source_ref` LongMem branch 后，逐字重构出历史 SHA/size；排除该 allowlist 后 top-level AST
差异为 0。amendment 同时绑定 base combined seal、S4A authorization/review、旧/新 source identity 与不变的
metric contract，仍要求 fresh independent scoring authorization。

S4B 实现保持小而分层：pure report projector 只把 joint score 投影为 routing、full-minus-one、synonym
leave-one-out、temporal 与 final-minimal-policy；readiness builder 在授权前对 registry 只执行 `lstat`/size，
不计算 SHA、不解析 JSON；official runner 固定 `dg25-s4b-joint-score-20260830-001`，必须依次通过 fresh
authorization、pre-score gate，才允许 exact identity + JSON open，并静态恰好调用一次 `score_all_arms`。
Reader/model/provider/controller、E3、candidate 与 holdout 均不在本授权范围。

初始静态门的 4 个 Ruff finding 与 2 个 Literal typing finding 分别作为 failures 114–115 入账并做最小修复；
readiness-001 又发现 aggregate evaluator 错把正确的关闭态 `labels_or_registry_content_loaded=false` 与
`effect_scoring_executed=false` 当成必须为 true，failure 116 入账后改为分别验证 true/false/zero 三类。
源码变化使 quality-001/readiness-001 历史化；fresh quality-002 与 readiness-002 如下：

```text
targeted S4B tests = 8 / 8 PASS
quality run = dg25-s4b-quality-20260830-002
quality receipt sha256 / size = fd7941c81e956b526005e9131589ba8276d5df2597adedd7c32ff44f3180248f / 8414
quality gates = 7 / 7 PASS
source-set digest = 1e55dd17a3c4e3ac003b6ec917c0a507815354854f180a4ed8c12341baeae25f

readiness run = dg25-s4b-readiness-20260830-002
readiness receipt sha256 / size = 24cc00d1c419f59e2eeacc6c626550b6aaa184227c846b83785d96ae80f3f55c / 6492
execution manifest sha256 / size = 53b4e0e3ded5e0727b457ab7e76598e7e5703f3bbe62a1bd3a52fcb9d394bfeb / 10017
validation report sha256 / size = ff899f683e53c8336c09753081a5683b7a0cd6b6cf3b54d3960d4e87a02a2bc6 / 1576
amendment artifact sha256 / size = 69b647cafac0d88922686155756bf6c95b0fe2bc32a5b854e4c9d1143020fa33 / 2146
amendment canonical digest = 45d491b837256ff62d836d38bddc99a69facfa30f597966dd1e8a2cae22d7aa2
source manifest sha256 / size = 6e18ab253fd4b33b889609702ce0af9cd097b8d35c2263aa4c6c4e1018290c86 / 1893
source manifest canonical digest = 8d767107322a88e6330b744cd9af4e9a95ecf79357bbbe42037d169d209998c0
stop contract sha256 / size = ff4997ba257091bbba65cb6dde59d88c8ebaa0b97c61dc1b1ea2aaf7c6ce7e97 / 3766
authorization request digest = 076ccdb0ff5f06904dd0d00c4f6749d384fb974f2f05a8d10c45a12a30209d4c
authorization bindings digest = e4a9cde93bf2e2172152a214d2a00317c651b26b5863b926df00cada57fe62a1
failure snapshot = 116 lines / 85f74adde87f1812edc4b65107559b1bc0867af62825b5209f01a461a89f7017 / 41904 bytes
```

readiness-002 中两个 registry path 都是 regular file 且 size 与 frozen identity 相同，但明确记录
`content_opened=false`、`sha256_computed=false`。首次动态文档插入因一行遗漏 patch `+` 前缀被原子拒绝，
文档没有部分修改；failure 117 入账后 readiness-002 历史化，正在进行的 independent review 已立即停止且
未写 authorization、未访问 registry 内容、未运行 scoring/runner/test。复用仍与当前 source 完全一致的
quality-002 后，fresh readiness-003 绑定 117-line ledger 并通过全部 pre-label 门禁：

```text
readiness run = dg25-s4b-readiness-20260830-003
readiness receipt sha256 / size = 56154aba328cf030d0924c6a100ed3a3088fb4a59185c551734797c2aef07fb1 / 6492
execution manifest sha256 / size = 9355460e98e9cb20750aad205223377be8aac33692320eb419c532b7b0be26ff / 10017
validation report sha256 / size = f7e30ea0cd0cf0f562ebc3d8584ae40769c66ba7f67ddea59727ae90732af65f / 1576
authorization request digest = 148d09c9e8ba0e966e941b2d204cc090f13e892067a8a62c6a29386e43638501
authorization bindings digest = c52293a90998dec349a8476c699b4defc9d370d742d83e029b08856c97ffcde1
failure snapshot = 117 lines / fe81c685c01df6b0e6cd2f27a30ffe97aa9b62f660ef7dd49622e4398be2aa4f / 42258 bytes
registry content opened / SHA computed = false / false
```

### S4B fresh independent authorization 与 one-shot score 终态

fresh reviewer 只读验证 readiness-003、quality-002、combined seal、scorer-source amendment、runner control
flow 与受保护 diff，未打开、解析或哈希 scorer-only registry，签发恰好一次的联合评分授权：

```text
review artifact = var/dg25/reviews/dg25-s4b-independent-review-20260830-001/review.json
review sha256 / size = 3c53eb15e4384b003fe6e75f130ac0739374775e8fd6492aa98b5dee858a4311 / 6508
verdict = AUTHORIZE_S4B_JOINT_E1_E2_POST_SEAL_SCORE
authorization digest = 19ec1adca3fe2215cf51f45df2657678d168221066dc6fd337a51b46c374cc68
review digest = e90662a2827cbf4f916e004dad9c5a156dda4412be05583899ad22faff20a720
forbidden access / scoring / official runner calls = 0 / 0 / 0
```

授权、117-line failure snapshot 与 output absence 再次精确核验后，official S4B runner 只执行一次。pre-score
gate 全部通过后才首次按授权打开两个 registry；联合分数和全部 diagnostic reports 已原子封存。post-score gate
按预注册规则得到 `STOP`，runner 随后以非零退出登记 failure 118；该退出发生在输出封存之后，不是可重试的
执行故障：

```text
run_id = dg25-s4b-joint-score-20260830-001
status = STOP_DG25_S4B_POST_SCORE_GATE
output = var/dg25/s4b/dg25-s4b-joint-score-20260830-001
receipt sha256 / size = 7af5760d0da3fd578f54037383a86e1abed9c49c8368ea4834a370b93d65d4c4 / 4173
joint-score sha256 / size = 32a06fd33ef12aa6b5d0330834e0862bf398f19b72edc850527a0d0922da8c0c / 24914
score digest = 480a59a44fe0690f64e2c36ce068836e039d1b6785bde7a1de79b102e74484b7
pre-score gate = PASS; all binding/schedule/amendment checks PASS
post-score failed rules = STOP_PRECISION + STOP_WRONG_COMPLETE
minimum AcceptedBindingPrecision = 0.6666666666666666, required 1.0
WrongComplete sum across 16 diagnostic arms = 16, required 0
arms with WrongComplete = 8; temporal-arm WrongComplete sum = 0
score executions / registry opens / automatic retries = 1 / 2 / 0
Reader-model-provider-controller calls / holdout / canonical mutations = 0 / false / 0
candidate default / post-score adaptation = false / false
failure receipt = var/dg25/failures/dg25-s4b-official-run-20260830-095731/receipt.json
failure receipt sha256 / size = 884cb6b54ab6f2d5ae166abe5dfa0f5d8d8e8eb1f777f80300e374feeadc48ea / 1363
```

`final-minimal-policy.json` 只保留为 score-bound diagnostic projection，`candidate_default=false`，不发布、不采用。
按 HG-11 与第 0.3/15.4 节，S4B 的合法一次性 STOP 立即禁止 S5–S9；不得运行 E3、Reader、answer、latency、
PostgreSQL release quality 或 formal holdout，也不得重跑 S3A/S4A/S4B 等待偶然 PASS。DG-25 各 lane 固定为：

```text
overall = FAIL_SAFETY_OR_REGRESSION
retrieval = FAIL_BINDING_PRECISION_OR_GOVERNANCE
temporal = PARKED_EVENT_TIME_OR_DEDUP_UNRESOLVED
answer = NOT_ENTERED_C1_FAILED
efficiency = NOT_ENTERED_CORRECTNESS_UNSEALED
quality = NOT_ENTERED_S9_DUE_S4B_STOP
```

S10 终态构建器只重算 sealed S4B 与非 scorer-only identities，不重新打开 registry；首轮 Ruff 发现 runner
缺 executable bit 和无效 `noqa`，作为 failure 119 入账后做最小修复。当前 terminal targeted + S4B regression
为 11/11 PASS，Ruff、strict mypy 与 compileall 均 PASS；failure ledger 为
`119 lines / 157f961a227178e1562cb064ccc08722dc173bb3bff31d8580cb9d5020e1da38 / 42914 bytes`。
DG-25 现按上述机器终态收口，固定 terminal run id 与权威位置为：

```text
run_id = dg25-s10-terminal-20260830-001
terminal root = var/dg25/terminal/dg25-s10-terminal-20260830-001
S5 / S6 / S7 / S8 / S9 = NOT_ENTERED_S4B_STOP
formal holdout = untouched
candidate default = OFF
Schema / public MCP / architecture v1 changes = 0 / 0 / 0
```

---

# 0. Goal 决定

DG-25 是 DG-24 的修复型 successor，不再继续猜测“可能是 Dense、Top-k、Prompt 或 Reader budget”。它只修复 DG-24 已经机器化定位的损失，并把 DG-23 的 Reader 回归放在检索与 Operator 已闭合之后处理。

DG-24 已证明当前 23 个 opened-development evidence equivalence groups 的终态分布为：

```text
TERMINAL_SURVIVAL                  13
CHANNEL_ELIGIBLE_NOT_INVOKED        6
CHANNEL_CUTOFF_DROP                 1
NO_CHANNEL_RETRIEVED_GOLD           3
──────────────────────────────────────
TOTAL                              23
```

另有 37 个 proof obligations：

```text
SATISFIED                          35
AMBIGUOUS_EVENT_TIME                2
──────────────────────────────────────
TOTAL                              37
```

10 个 evidence first-loss 全部集中在三类对象：

```text
2e6d26dc / MATCHING_EVENTS_IN_RANGE
  5 × CHANNEL_ELIGIBLE_NOT_INVOKED

88432d0a / MATCHING_EVENTS_IN_RANGE
  1 × CHANNEL_ELIGIBLE_NOT_INVOKED
  3 × NO_CHANNEL_RETRIEVED_GOLD

a82c026e / LOOKUP_ANSWER
  1 × CHANNEL_CUTOFF_DROP
```

2 个 proof failure 正好位于两个 `COUNT_DISTINCT + ALL_MATCHES_IN_RANGE` requirements：

```text
2e6d26dc / EVENT_TIME_RESOLUTION / AMBIGUOUS_EVENT_TIME
88432d0a / EVENT_TIME_RESOLUTION / AMBIGUOUS_EVENT_TIME
```

因此，DG-25 不把全部问题混成一个“提高 Recall”指标，而是在一个行政 Goal 中维护三条独立、按顺序 seal 的 lane：

```text
Lane R — Retrieval / Selection
  解决合法 action 未组合执行和 rank/cutoff 丢失

Lane T — Temporal / Completeness
  解决 interval-valued event time、event identity、dedup 和 proof closure

Lane A — Answer / Consumption
  让 deterministic OperatorResult 成为答案值权威，阻止 Reader 覆盖正确值
```

三条 lane 可以共享 Runtime source revision 和最终质量门，但不得共享效果归因。只有 Lane R/T 先获得 seal，Lane A 才能进入 matched Reader/answer execution。

## 0.1 当前真正需要修复的架构冲突

当前源码不是缺少又一个检索器，而是存在以下组合冲突：

```text
AccuracyActionBundle
  只能表达一个 channel

compile_accuracy_action_decision
  将 ALL_MATCHES_IN_RANGE requirement 排除为 SKIP_PROOF_CHANNEL_REQUIRED

CapabilityConstrainedRecoveryService
  先选择一个 deterministic action
  再允许 accuracy action supersede 原 execution selection

EvidenceAcquisitionExecutor.execute
  一次只接收一个 FeasibleAcquisitionAction

结果：
  evidence discovery action
  与
  proof-closing temporal action
  不能在同一个 fresh state 中组合
```

这导致系统在 COUNT requirement 上出现错误二选一：

```text
要么执行 lexical/dense evidence discovery
要么执行 temporal proof action
```

正确设计应为：

```text
Fresh RequirementState(epoch=N)
  ↓
Runtime enumerates FeasibleAcquisitionActions
  ↓
Runtime compiles one bounded RequirementAcquisitionPlan
  ├─ evidence discovery actions
  ├─ proof-closing actions
  └─ optional local expansion actions
  ↓
Official AcquisitionService executes the authorized batch
  ↓
one Gate / Binding / RequirementState / Sufficiency recomputation
```

“一次 extra pass”表示一次 state transition 和一次完整重算，不等于只允许一个 repository probe；但全部 probe 必须在 plan 中预先声明、逐个 capability 校验，并满足总成本上限。

## 0.2 两个 Primary Claims

按照实验设计约束，本 Goal 只保留两个 primary claims。

这 10 个 case 是 opened-development，且 DG-24 已使用其 labels 定位损失并启发组件。
“product-before-score seal”只阻止同一运行的评分适配，不会把它们变成无偏 validation set。
23 个 evidence groups 和 37 个 proof obligations 聚类于 10 个 case，不是独立样本；
2 个 temporal COUNT 也只支持确定性开发闭环，不支持统计显著性或人群泛化。

| ID | Primary Claim | 可证伪验收 |
| --- | --- | --- |
| C1 | 基于 fresh RequirementState 的统一 acquisition plan、requirement-preserving selection、interval event normalization 与 `BoundedRangeScanProofV02`，能在 official product path 中关闭 DG-24 的 10 个 evidence first-loss 和 2 个 proof failure | 23/23 evidence groups terminal survival；37/37 proof obligations satisfied；Accepted Binding precision = 1.0；OperatorReady = 10/10；Wrong COMPLETE = 0 |
| C2 | 当 deterministic Operator 已形成 typed result 时，由 Runtime 保持 answer-value authority、Reader 仅负责受约束表达，能关闭 DG-23 的两个 temporal COUNT 正确病例回归而不损害其他病例 | 两个 temporal COUNT 在全部预注册 replicate 中正确；Candidate EM ≥ 6/10；normalized F1 ≥ 0.633715799；correct-case regression = 0；wrong COMPLETE = 0 |

Supporting claims 仅包括：

```text
S-COST
  覆盖提升不是由增加 retry、扩大未验证 Top-k 或无界 hydration 获得

S-GENERALITY
  新路径不含 case ID、gold span、答案、opened-dev 专用分支

S-MINIMALITY
  若 proof-first 单通道计划已关闭问题，多通道 union 不进入最终策略
```

## 0.3 Success 与 Failure 的解释

若 C1 PASS、C2 PASS：

```text
结论：
MiLA 可以在不放松 Governance、Binding、Sufficiency 和 Canonical 边界的条件下，
通过 requirement/proof-aware deterministic execution 完成当前 opened-dev 的检索、
temporal COUNT 和 typed answer closure。
```

若 C1 FAIL：

```text
不能进入 Reader 调试。
先按 residual first-loss 重新分解：
  discovery
  interpretation
  event-time
  dedup
  proof
```

若 C1 PASS、C2 FAIL：

```text
检索与 proof 终态单独保持 PASS；
Overall 不得宣称 Full PASS；
终态进入 PARKED_READER_EVIDENCE_CONSUMPTION_NONCONFORMANCE。
```

若仅靠扩大 Top-k、改变 seed、增加 retry 或使用 gold-aware rule 才 PASS：

```text
结果作废，终态 FAIL_PROTOCOL_VIOLATION。
```

## 0.4 Anti-Claims

本 Goal 即使 Full PASS，也不支持以下表述：

```text
MiLA 已在 formal holdout 泛化
MiLA 已达到 Production ready
vLLM state-aware ranking 已被证明有效
LLM action ranking 已被证明必要
ReFind-style active search 已被实现
Dense 优于 lexical
多通道 union 对所有 query 都更好
Graph retrieval 有必要
Schema 已冻结
```

## 0.5 为什么本 Goal 暂不使用模型

DG-24 的全部已知损失均已有确定性的首损位置：

```text
channel invocation / action composition
channel cutoff
event-time proof validation
```

没有任何一个当前 first-loss 被定位为：

```text
fixed governed pool 内 semantic reranking failure
grounded interpretation not produced
residual expression proposal missing
associative evidence unreachable
```

因此本 Goal 的 Planner、Controller、ResidualCue、reranker 和 temporal judge model calls 固定为 0。只有 DG-25 终态仍留下机器可定位的 semantic mediator gap，才允许 successor 建立 `StateView + vLLM` 实验。

---

# 1. 权威事实基线

## 1.1 规范优先级

发生冲突时按以下顺序解释：

1. `architecture/v1.0/` frozen bundle；
2. `MiLAi_Logical_Architecture_v1_设计文档.md` 中的 frozen MUST；
3. `MiLAi_Lean_V1_实施合同.md`；
4. executable Runtime、真实 PostgreSQL integration/security tests；
5. DG-24 S8-003/S7/S6/S3/S0 authoritative artifacts；
6. DG-23 authoritative terminal、context 与 Reader artifacts；
7. 本 Goal；
8. runbook、README、注释和自然语言总结。

必须保持：

```text
EvidenceRecord != ClaimVersion
candidate != accepted evidence
retrieval score != RequirementBinding
event point != completeness proof
source observed time != event occurrence time
model output != canonical truth
Reader output != OperatorResult authority
projection/search/context cannot raise authority
unknown permission/retention/revocation fails closed
```

## 1.2 绑定输入与 SHA-256

| Artifact | SHA-256 | 用途 |
| --- | --- | --- |
| `architecture/v1.0/architecture_manifest.json` | `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e` | frozen architecture identity |
| `MiLAi_Lean_V1_实施合同.md` | `395a443da282f69a56ae5ea29f0dac07a65da12a697534e5c650c9893f8ae3ba` | implementation contract |
| `MiLAi_DG-24_检索首损点审计与候选生命周期归因_GOALS.md` | `ba3b136c3e510f7829d50af7d50c7aef5de86b04c31e82507c6f647db5347d27` | predecessor Goal |
| `var/dg24/s8/dg24-s8-terminal-20260829-003/receipt.json` | `fff0f5ce8ab7b230c49923308f37c080d1eab58776d298a075cda513790a6aa0` | authoritative DG-24 terminal |
| `var/dg24/s6/dg24-s6-scoring-20260829-003/first-loss-distribution.json` | `a782ff232707cc909db679bf1bd68135b547bcb1d997cc0f3c3ac0ca07d4d128` | 23-group first-loss denominator |
| `var/dg24/s6/dg24-s6-scoring-20260829-003/requirement-loss-attributions.json` | `d62448bc7ca22034a117abdf881fee56b7f2c5eeee34a19a7bfbb2b1fb1d40eb` | per-group causal starting point |
| `var/dg24/s6/dg24-s6-scoring-20260829-003/proof-obligation-traces.json` | `83fed146a0f0cb4963fb184a1c7cc7c538f89396135d5c7fadeb2c7efa72575c` | 37 proof obligations |
| `var/dg24/s6/dg24-s6-scoring-20260829-003/channel-availability-report.json` | `83785ff4a25194eabc1f32edfb50cfe7bb07e8490d58621035904ec80defa529` | official channel availability ceilings |
| `var/dg24/s6/dg24-s6-scoring-20260829-003/successor-routing-report.json` | `543685a2ae072a786ceac70b92a9f2b5f1915cd928e8f8473cff7458a0f8d2d5` | successor route preregistration |
| `var/dg24/s6/dg24-s6-scoring-20260829-003/rule-feature-attribution-report.json` | `d88381767e832d503d546618411ad537a799ef6cc7a4badff44fd54b5c3c2e53` | benchmark-shaped rule inventory；causal effect 尚未估计 |
| `var/dg24/s0/dg24-s0-freeze-20260829-008/stage-implementation-registry-v0.1.json` | `d8b51869b657ff4dc3bcdbb70fe9e35aaf110dc39c7ff25df6c09e146817a934` | current real pipeline stages |
| `var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/gold-equivalence-registry-v0.1.json` | `c13789936296695027191f3c625c99e49e5725db189fd53791d207879226493a` | post-seal scoring registry |
| `var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/proof-obligation-registry-v0.1.json` | `a2e40b175c33ebc453253e1596f680285c33e13e6b8141cd6a0d5be6158ba26a` | post-seal proof registry |
| `var/dg24/s3/dg24-s3-product-trace-20260829-002/sealed-product-traces.json` | `463e1dae44e8f9239f037f9e5525fc168a4b7f161fe3c54125de49e4266f300d` | frozen product baseline trace |
| `var/dg24/s3/dg24-s3-product-trace-20260829-002/sealed-official-probe-traces.json` | `b10805d13cb7ace90a035050b4a32d17842a818e8dbc14e157055e572c2100e0` | official read-only channel probe |
| `var/dg23/s9/dg23-s9-terminal-20260829-001/receipt.json` | `fa1a71b1c724c0632ca3edea04a6a331821a554cd8bb0e79f41e863e002020f2` | Reader predecessor terminal |
| `var/dg23/s6/dg23-s6-opened-dev-context-20260829-020/context-score.json` | `ba641d024c81a9e502c3b3ab7a13b6719bf5b2bb1fe891e6700ec6808d290ee0` | current candidate mediator/cost baseline |
| `var/dg23/s7/dg23-s7-matched-reader-20260829-002/answer-score.json` | `9e4a42b072dea1133f9714ead53987bf7c9156da549efae41161f9e2305835d4` | current Reader regression baseline |
| `evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json` | `4a88cb030e67cce456b1dfe159fce177a5ace4b972f11af2a6674639c52dc876` | opened-dev scorer-only labels |
| `var/dg11/paper/freeze/longmemeval-full-inputs.json` | `7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412` | frozen opened-dev label-free input |

以上 artifacts 只读。DG-25 必须创建全新的 `var/dg25/`、run IDs、failure index、source manifest、artifact manifest 和 terminal receipt。

## 1.3 当前 source baseline

| Source | SHA-256 | 当前职责/冲突 |
| --- | --- | --- |
| `runtime/src/milai/application/accuracy_acquisition.py` | `ddd6a05ae168c62f1e309c4e1de684c063f30514e66ec4d9eeaeed755932947e` | single-channel bundle、fixed channel order、benchmark-shaped lexical rules |
| `runtime/src/milai/application/deterministic_recovery.py` | `9b62d078d30eb1ff08e0c7ccd24e1f525d4584c7530395d4c80d88a815bdf334` | single selected action；accuracy candidate 可 supersede legacy execution selection |
| `runtime/src/milai/application/acquisition_capability.py` | `3cccfec3f3d4877cadf6859ef0d6a0794ed4d2101013b884555f66bb0a563568` | capability set、feasible action 与全局成本上界 |
| `runtime/src/milai/application/acquisition_execution_policy.py` | `c3708f0777925c2175e7c3505159e90c2b1ab7244e92043e9557ea495cae08db` | current execution selection policy |
| `runtime/src/milai/application/evidence_acquisition.py` | `6909326e1bf2f0236127fddf43484d75b1ccca77c52498b4263b1e6a6cca5b6a` | official executor、one action、`BoundedRangeScanProof` v0.1 |
| `runtime/src/milai/application/acquisition.py` | `b01d2729f6f19032a6077ab5a552058ba2c729e6933e515c0c11e1744f5bd19d` | local rank、fusion 和 fixed priority |
| `runtime/src/milai/application/memory_query.py` | `8307d22e830bf9bfffcb1db51fe51d8e13b2a2898ee7192bbf97e814286135ba` | query interval / requirement compilation |
| `runtime/src/milai/application/query_planner.py` | `1f4abb484ae0012a7648eec0d9699ed233f863ad989b787e7a7a656cad7a28a6` | QueryPlan boundary |
| `runtime/src/milai/application/appointment_composition.py` | `3e57c2b528dff2da9c5ee25ae3d884d2e7987c75fc4e2b3a6122b02a2638d323` | bounded count composition |
| `runtime/src/milai/application/evidence_semantics.py` | `888bfa3f161f455930909f0ddb2c489655f4b08bb5106f8a4cba56665a4d2cef` | span、interpretation、Binding |
| `runtime/src/milai/application/requirement_state.py` | `de7c5ae47c1d28b0f3f978f1e0897237c3e73009a91997e09b59bd1b4d75fe1a` | fresh RequirementState |
| `runtime/src/milai/application/sufficiency.py` | `fc8d54a76e2c9303a8c7cc09a57095c01732ca632fefc2d8fe9ddaedcc115dda` | typed completion authority |
| `runtime/src/milai/application/query_operators.py` | `592fac4614aa906f760ce372caec99697571a37ebb0ad80df9107469ffd60ba4` | deterministic operator |
| `runtime/src/milai/application/retrieval.py` | `ae9baf98a46e67d56f5f7d13a8cec3eeaed041e89ef88e586c2989a7d925218a` | EvidenceSet selection/context boundary |
| `runtime/src/milai/persistence/retrieval_repository.py` | `9c158681ea5ac06e7101b276dbe6467ccba2edc141332ae74af2340445c8575a` | official repository cutoffs |

执行 S0 时必须重新计算这些 identity；如果 source 已被其他用户工作修改，先记录 drift，不能用本表覆盖当前工作树。

## 1.4 当前 worktree 保护

起草时发现以下已有用户修改，DG-25 必须保留：

```text
scripts/dg13u_u1_review.py
tests/test_dg13u_u1_review.py
```

仓库还有大量既有 untracked assets。DG-25 只能编辑自身明确列入 source manifest 的文件，不得清理、reset、checkout 或批量格式化无关路径。

## 1.5 DG-24 channel 机器事实

官方 audit 的重点不是“Dense 一定更好”，而是已证明不同 channels 的可达性不同：

```text
Raw FTS recall:
  @8   15/23
  @16  16/23
  @32  17/23
  @64  17/23

Enriched FTS recall:
  @8    4/23
  @16   5/23
  @32   6/23
  @64   6/23

Dense recall:
  @8   10/23
  @16  11/23
  official verified cap = 30
  @32/@64 = UNAVAILABLE，分母必须为 0

Union oracle recall:
  @8   15/23
  @16  17/23
  @32  19/23
  @64  19/23
```

这些是 diagnostic availability，不是 product treatment result。DG-25 禁止将 official audit probe 的宽池直接注入产品 Binding。

## 1.6 DG-23 当前强基线

DG-25 不只与 DG-24 candidate-OFF product trace 比较，还必须不回归 DG-23 已有 candidate 结果：

```text
Required evidence coverage @ REFERENCE_B_REF  22/23
Accepted Binding precision                      1.0
Additional acquisition calls                      4
Candidates hydrated                              18
UsefulCandidateRate                              1.0
Wrong COMPLETE                                    0

Reader candidate @ REFERENCE_B_REF:
  EM per replicate                              4,4,4
  F1 per replicate          0.474263765 / 0.470909091 / 0.478605605

历史强 answer gate：
  EM                                             >= 6/10
  normalized F1                                 >= 0.633715799
```

DG-25 的 retrieval/proof 目标是从 22/23 到 23/23，并关闭 proof；不是以牺牲 precision 或成本换取宽池表面 recall。

## 1.7 `NO_CHANNEL_RETRIEVED_GOLD` 的正确解释

DG-24 的 3 个 `NO_CHANNEL_RETRIEVED_GOLD` 均来自 `88432d0a`。DG-23 sealed candidate context 已经包含该病例的四个 baking source refs，但 requirement 仍为 `PARTIAL`、OperatorReady 仍为 false。

因此这 3 个 reason code 表示：

```text
DG-24 分别探测的 lexical/dense/event audit occurrence 中没有该 gold，
并不表示 frozen snapshot 中没有 evidence，
也不表示必须新增 synonym 或扩大 Top-k。
```

正确 successor 诊断是：

```text
bounded temporal/raw scan 已能接触相关 source rows
→ query-time event normalization / identity / Binding 未形成完整闭环
→ proof 仍因 AMBIGUOUS_EVENT_TIME 失败
```

DG-25 必须让 official range-scan result 获得完整 candidate lifecycle、event interpretation、Binding 与 proof lineage；不得为这三个对象另写 eval-owned retriever。

---

# 2. 授权、范围与禁止项

## 2.1 允许范围

DG-25 允许修改：

```text
Runtime internal typed acquisition contracts
deterministic recovery plan compilation
official acquisition batch execution
requirement-aware rank/cutoff/selection
query-time event-time interval interpretation
event identity and dedup
BoundedRangeScanProof V01 → V02 internal upgrade
typed OperatorResult → answer conformance boundary
candidate-only feature flags and rollback
DG-25 eval harness、scorer、scripts、tests、runbook、receipts
```

## 2.2 默认禁止

```text
public MCP schema change
PostgreSQL DDL / migration
architecture/v1.0 change
canonical write or authority change
formal holdout access
candidate default enable
case ID / answer / gold span runtime branch
Prompt-owned channel/action selection
vLLM planner/reranker/judge
ReFind-style free search loop
Graphiti/Zep/OpenViking production route
new external dependency
unverified Dense @32/@64 claim
Top-k sweep to pass
seed switching
automatic retry
eval-owned BM25 / vector / temporal implementation
Reader before mediator seal
```

## 2.3 Schema lane

本 Goal 设计为不需要 PostgreSQL migration。`BoundedRangeScanProofV02`、event identity 和 typed answer decision 均是 Runtime / trace contract。

如果执行中发现必须新增持久列、索引或 migration：

```text
当前 lane 立即停止
生成 schema impact report
终态 = NOT_ENTERED_SCHEMA_AUTH_REQUIRED
```

不得把临时 JSON、旁路表或 eval-owned store 当作 schema 绕过。

## 2.4 数据与标签边界

执行必须分成：

```text
Product Plane
  只读取 label-free query/snapshot
  不加载 gold registry
  先 seal product trace

Scoring Plane
  seal 后加载 opened-dev gold registry
  只做归因与评分
  不能改变 product artifacts
```

Runtime source scan 必须确认不存在：

```text
10 个 case IDs
gold atom IDs
expected answers
gold source refs
opened-dev 人名/食品名作为控制分支
```

一般语言词汇可以存在于通用 parser/normalizer，但必须有 domain contract、独立 synthetic coverage 和非 case 特化来源。

## 2.5 Formal holdout

```text
formal holdout case count = 0
formal holdout label load = 0
formal holdout Reader call = 0
```

任何 holdout access 均使本 Goal `FAIL_PROTOCOL_VIOLATION`。

---

# 3. 冻结后的目标控制流

## 3.1 总流程

```text
MemoryQueryIR
    ↓
Official baseline acquisition
    ↓
Governance Gate
    ↓
Span / Interpretation / Binding
    ↓
Fresh RequirementState(epoch=N)
    ↓
Runtime enumerates FeasibleAcquisitionActions
    ↓
RequirementAcquisitionPlanCompiler
    ├─ evidence discovery obligations
    ├─ proof obligations
    └─ local expansion obligations
    ↓
Runtime validates every action + aggregate budget
    ↓
Official EvidenceAcquisitionExecutor.execute_plan(...)
    ↓
per-channel ranked pools
    ↓
rank-based union + dedup lineage
    ↓
Governance Gate
    ↓
Requirement-aware EvidenceSet selection
    ↓
fresh Span / Interpretation / Binding
    ↓
fresh RequirementState(epoch=N+1)
    ↓
BoundedRangeScanProofV02 validation
    ↓
fresh Sufficiency / OperatorResult
    ↓
TypedAnswerDecision
    ├─ deterministic safe formatter
    └─ constrained Reader verbalization when semantically necessary
```

## 3.2 Hard State 与一次 pass

所有 actions 必须引用同一个：

```text
query_ir_digest
requirement_state_digest
requirement_state_epoch
acquisition_capability_digest
policy_digest
snapshot_identity
access_snapshot_identity
```

任一 identity 在执行前变化：

```text
reject whole plan as STALE_ACQUISITION_PLAN
automatic retry = 0
```

一次 pass 的定义：

```text
0 or more predeclared official repository probes
→ one candidate union
→ one full semantics recomputation
→ one RequirementState epoch increment
```

禁止：

```text
probe 1 后偷偷重新规划 probe 2
失败后换 channel
未声明的 fallback
重复 action digest
第二次 Provider call
```

---

# 4. 新增与升级的内部合同

## 4.1 `RequirementAcquisitionPlanV01`

建议内部合同：

```yaml
RequirementAcquisitionPlanV01:
  schema_version: requirement-acquisition-plan-v0.1
  plan_digest:

  lineage:
    query_ir_digest:
    requirement_state_digest:
    requirement_state_epoch:
    acquisition_capability_digest:
    policy_digest:
    snapshot_identity:
    access_snapshot_identity:

  target_requirements:
    - requirement_id:
      status:
      missing_evidence_roles: []
      proof_obligations: []

  actions:
    - action_digest:
      target_requirement_id:
      action_role:
        EVIDENCE_DISCOVERY
        PROOF_CLOSURE
        LOCAL_EXPANSION
      channel:
      candidate_cap:
      reason_code:

  aggregate_budget:
    extra_state_passes: 1
    max_repository_calls:
    max_hydrated_candidates:
    model_calls: 0
    automatic_retries: 0

  execution_contract:
    one_full_recompute: true
    product_official_executor_only: true
    canonical_mutation: false
```

Validation 必须保证：

```text
每个 action 都是当前 FeasibleAcquisitionAction 的精确成员
action digest 唯一
target requirement 当前未满足
proof action 只用于适用的 proof obligation
aggregate cost 不超过 policy
optional channel 不削减 baseline channel quota
所有 action 使用同一 epoch/snapshot/policy
```

## 4.2 与 `AccuracyActionBundleV01` 的兼容

`AccuracyActionBundleV01` 已存在于历史 artifacts，不得删除解析能力。DG-25 可以：

```text
保留 V01 reader
新增 plan V01 writer
将 legacy single-channel bundle 映射成单 action plan
```

禁止修改旧 receipt 或让新 writer 伪装成 V01。

## 4.3 `EventTimeIntervalV02`

```yaml
EventTimeIntervalV02:
  schema_version:
  interval_start:
  interval_end_exclusive:
  timezone:
  precision:
    INSTANT
    DAY
    WEEKEND
    WEEK
    MONTH
    RELATIVE_RANGE
  basis:
    EXPLICIT_CALENDAR
    SOURCE_RELATIVE
    UNIQUE_ANCHOR_RELATIVE
    SOURCE_OBSERVED_PROXY
  anchor_evidence_ids: []
  grounded_span_ids: []
  ambiguity_reasons: []
```

`SOURCE_OBSERVED_PROXY` 不能自动用于 COMPLETE。它只能成为候选解释，并由 proof validator 判断是否足以对当前 query range 作出确定的 in/out 分类。

## 4.4 `EventIdentityV01`

```yaml
EventIdentityV01:
  event_identity_digest:
  event_type:
  actor_identity:
  object_or_participant_identity:
  occurrence_interval_digest:
  source_evidence_ids: []
  identity_policy_version:
  disposition:
    DISTINCT
    DUPLICATE_OF
    UNRESOLVED
```

要求：

```text
同一 baking event 的重复叙述必须合并
同一 evidence span 中的 twins 必须形成两个 participant event identities
不同 event type 或不重叠 interval 不得因文本相似合并
无法确定时保持 UNRESOLVED，不得任意计数
```

## 4.5 `BoundedRangeScanProofV02`

直接升级现有 `BoundedRangeScanProof`，不创建平行的 CompletenessCertificate。

```yaml
BoundedRangeScanProofV02:
  schema_version: bounded-range-scan-proof-v0.2
  status:
    COMPLETE
    PARTIAL
    UNAVAILABLE

  query_closure:
    query_ir_digest:
    requirement_state_digest:
    event_time_interval:
    timezone:
    boundary_convention: CLOSED_OPEN

  snapshot_closure:
    transaction_snapshot_identity:
    source_partition_snapshot_identity:
    access_snapshot_identity:
    revocation_snapshot_identity:
    snapshot_stable:

  scan_closure:
    scan_axis: EVENT_OCCURRENCE_TIME
    source_partition_closed:
    range_scan_complete:
    max_items:
    max_items_hit:
    unreadable_source_count:

  projection_closure:
    projection_version:
    temporal_normalizer_version:
    target_watermark:
    projection_watermark:
    projection_watermark_covered:
    dead_letter_gap:
    unprojected_source_count:
    raw_fallback_closed:

  event_set_closure:
    candidate_event_count:
    in_range_event_count:
    out_of_range_event_count:
    ambiguous_time_count:
    unresolved_event_count:
    event_identity_policy_version:

  dedup_closure:
    dedup_policy_version:
    duplicate_group_count:
    unresolved_duplicate_group_count:
    distinct_event_count:
    dedup_complete:

  access_closure:
    policy_digest:
    unreadable_evidence_count:
    access_snapshot_valid:
```

`COMPLETE` 的唯一合法条件：

```text
snapshot_stable
AND source_partition_closed
AND range_scan_complete
AND max_items_hit == false
AND unreadable_source_count == 0
AND dead_letter_gap == false
AND projection_watermark_covered
AND (
      unprojected_source_count == 0
      OR raw_fallback_closed
    )
AND ambiguous_time_count == 0
AND unresolved_event_count == 0
AND unresolved_duplicate_group_count == 0
AND dedup_complete
AND access_snapshot_valid
```

任一条件不成立：

```text
RequirementState.status = COMPLETENESS_PROOF_MISSING
Sufficiency != COMPLETE
OperatorReady = false
```

## 4.6 `TypedAnswerDecisionV01`

```yaml
TypedAnswerDecisionV01:
  schema_version:
  decision_digest:

  lineage:
    query_ir_digest:
    requirement_state_digest:
    sufficiency_decision_digest:
    operator_result_digest:
    proof_digest:
    evidence_set_digest:

  answer_contract:
    answer_type:
    normalized_value:
    unit:
    allowed_surface_variants: []

  rendering_route:
    DETERMINISTIC_FORMATTER
    CONSTRAINED_READER
    ABSTAIN

  reader_constraints:
    value_must_echo_operator: true
    may_change_value: false
    may_change_unit: false
```

Reader 输出通过 conformance validator 后才能返回。Reader 改变 typed value、unit、time order 或 count：

```text
READER_OPERATOR_VALUE_MISMATCH
```

处理顺序：

```text
若 answer type 可确定性格式化：使用 deterministic formatter
否则：abstain
```

不允许 retry-to-pass。

---

# 5. Requirement 定向 acquisition policy

## 5.1 总原则

```text
Runtime chooses obligations and actions.
Official services execute.
Binding accepts evidence.
Proof validates completeness.
```

最终 policy 不能以一个固定优先级对所有 query 使用同一路径。

## 5.2 Requirement / proof routing

| Requirement / obligation | 必需 action policy |
| --- | --- |
| exact current state | Canonical exact；不进入本 candidate |
| single-value LOOKUP | 保留 baseline official acquisition；对 required role 预留一席 |
| multi-operand operator | 每个 required operand 独立 reservation |
| `ALL_MATCHES_IN_RANGE` | mandatory `TEMPORAL_EVENT` bounded scan if executable；lexical/dense 不能证明 completeness |
| event-time unresolved | interval normalizer / unique-anchor resolver；不是 synonym retry |
| event identity unresolved | deterministic event identity + dedup validation |
| provenance | exact source/provenance action |
| no feasible proof action | fail closed / `COMPLETENESS_PROOF_MISSING` |

## 5.3 Baseline preservation invariant

DG-22 已发现可选 Dense channel 不应隐式削减既有 FTS budget。本 Goal 冻结：

```text
添加 optional action
不得改变已授权 baseline action 的：
  query
  scope
  candidate cap
  cutoff
  channel-local rank
```

如果总预算不足以同时执行：

```text
优先保留 correctness-required proof action
再保留冻结 baseline action
optional action 返回 BUDGET_NOT_AUTHORIZED
```

不能静默缩小每个 action 的 cap。

## 5.4 Multi-channel union 不是默认结论

DG-24 显示 channel opportunity，但没有证明 multi-channel product union 必要。必须消融：

```text
R0 current single-action behavior
R1 unified proof-first plan，仍保持最小 channel set
R2 R1 + per-channel quota union
```

决策规则：

```text
若 R1 与 R2 的 Binding/proof/OperatorReady 相同，
且 R2 增加 calls、hydration、noise 或 latency，
最终产品 policy 必须选择 R1。
```

## 5.5 Per-channel quota 与 fusion

如 R2 被证明必要：

```text
FTS_RAW       使用冻结 product cap
FTS_ENRICHED  使用冻结 product cap
EVIDENCE_DENSE 使用冻结 product cap；不得请求未验证 @32/@64
TEMPORAL_EVENT 使用 bounded range contract，不使用 Top-k 证明 completeness
```

不同 channel raw score 不可直接比较。使用 rank lineage 和可解释的 rank-based fusion；必须保留：

```text
channel
raw rank
raw score
score direction
query digest
index identity
```

同一 Evidence 被多个 channel 发现时只 hydrate 一次，但保留全部 discovery lineage。

## 5.6 Requirement-preserving cutoff

`a82c026e` 的 gold 在 official Raw FTS rank 1，但产品在 S15 `CHANNEL_CUTOFF_DROP`。修复不能是全局扩大 K，而应建立：

```text
fixed candidate pool P
fixed final K
每个 unsatisfied required evidence role
  至少保留其最高合法 candidate 一个位置
剩余位置按全局 rank/fusion 填充
```

reservation 只基于 Runtime requirement identity 和 candidate semantics，不使用 gold。

Single-value requirement 最多预留一个；multi-operand 按 role 预留；exhaustive set 不依赖 context K 完成计算，其完整 event set 在 operator working set 中保持，Reader 只消费 typed result 和必要 provenance。

## 5.7 Hard filter 分类

以下仍是 hard gate：

```text
tenant/scope/access
revocation/retention
source role required by typed contract
event-time definitely outside interval
value type incompatibility
```

以下不得在 pre-Binding 阶段作为无审计 hard drop：

```text
lexical overlap absence
entity surface alias absence
regex query-class guess
query wording mismatch
```

它们可以作为 ranking feature。任何 hard drop 必须有 reason code 和 candidate lifecycle trace。

## 5.8 Benchmark-shaped rule discipline

DG-24 只建立了 association inventory，没有运行 leave-one-rule-out。DG-25 允许在 sealed opened-dev treatment 中执行：

```text
candidate policy with legacy _SYNONYMS
candidate policy without legacy _SYNONYMS

candidate policy with lexical hard filters
candidate policy with lexical filters as soft rank features
```

规则：

```text
若移除规则不降低 mediator，candidate path 必须停止依赖该规则
若移除规则降低 mediator，保留 legacy path 但不能宣称 generality closure
若新正确性仅依赖 opened-dev lexical literal，Full PASS 禁止
```

---

# 6. Temporal event normalization 与 COUNT closure

## 6.1 三种时间必须分离

```text
source_observed_time
  对话/证据何时被观察

event_occurrence_interval
  事件何时发生

system_time
  系统何时持久化/处理
```

禁止用 source time 直接覆盖 event time。

## 6.2 解释优先级

事件时间解析按以下顺序执行：

1. 明确日期/时间；
2. 相对 evidence 自身 `source_observed_time` 的 deictic expression；
3. coarse calendar interval，如 month/weekend/week；
4. 同一 authorized event set 中唯一且已绑定 anchor 的相对关系；
5. 无法唯一确定则 `UNRESOLVED`。

示例能力类型，不是 case rule：

```text
today / yesterday / last Thursday
Tuesday relative to source observation
last weekend
in March / in April
a few weeks ago
a few weeks after <unique event anchor>
```

所有 parser 必须使用独立 synthetic matrix 覆盖跨月、跨年、DST、timezone 和 query-boundary 情况。

## 6.3 Interval containment

令 event interval 为 E，query interval 为 Q：

```text
E 完全包含于 Q     → IN_RANGE
E 与 Q 不相交      → OUT_OF_RANGE
E 与 Q 部分相交    → AMBIGUOUS_RANGE_MEMBERSHIP
E 未解析            → EVENT_TIME_UNRESOLVED
```

只有 `IN_RANGE` 可以进入 distinct count。`AMBIGUOUS` 不能按概率或 source time 猜入集合。

## 6.4 Relative anchor resolution

跨 evidence 的相对时间只允许使用：

```text
同 tenant/scope/access snapshot
同 query-local event set
唯一 subject/entity/event anchor
已形成合法 Binding
关系 span 已 grounded
```

若存在多个可能 anchors：

```text
ANCHOR_RELATION_AMBIGUOUS
```

不得选择最相似 anchor。

## 6.5 Query-time raw fallback

现有 temporal scan 已能报告 source partition、projection watermark 和 raw fallback closure。DG-25 必须复用正式 repository scan，不创建 eval-only scan。

raw fallback 只用于：

```text
投影覆盖不全
event projection 无 resolved occurrence interval
需要从 bounded raw source partition 重建 event candidates
```

它必须：

```text
使用 query interval / snapshot / scope
记录 scanned rows
不把全部 rows hydrate 给 Reader
在 `max_items_hit` 时返回 PARTIAL
```

## 6.6 Event identity 与 dedup

distinct count 的 identity 不能等于 evidence row 数量。

```text
同一事件多次提及
  → one event identity

同一 span 中明确两个参与者/对象
  → two event identities

只有主题相似、时间不同
  → distinct

identity 不可决定
  → proof incomplete
```

event identity policy version 必须进入 proof digest。

---

# 7. Typed answer conformance

## 7.1 Operator authority

当以下链条已成立：

```text
Governed EvidenceSet
→ valid Binding
→ RequirementState satisfied
→ proof complete when required
→ deterministic OperatorResult
```

Reader 不能重新计算或覆盖：

```text
count
date difference
temporal order
numeric divide/subtract result
unit
boolean
```

## 7.2 Rendering route

第一阶段：

| Answer type | Route |
| --- | --- |
| INTEGER / NUMBER / BOOLEAN | deterministic formatter |
| DATE / DURATION / TEMPORAL_ORDER | deterministic formatter with typed unit |
| exact STATE value | deterministic formatter when value is normalized and contract allows |
| EXPLANATION / preference rationale | constrained Reader |
| incomplete / contested | abstention template |

## 7.3 Reader 输入

Reader 输入必须包含：

```text
original question
TypedAnswerDecision
minimal answer-bearing evidence
proof summary when relevant
trace pointers
```

不再以 512 或 2048 作为 treatment 变量。预算权威继续使用 DG-23 已建立的真实 chat-template token delta 和 `REFERENCE_B_REF / ADAPTIVE_RUNTIME`。

512/2048 只可作为历史回归标签，不得通过选择其中一个来让新结果过关。

## 7.4 Reader calls

```text
typed deterministic route
  Reader calls = 0

constrained Reader route
  每个 exact request identity 最多 1 call
  automatic retry = 0
  checkpoint by exact identity
```

已封存的 baseline answers 复用，不重复调用 Provider。

## 7.5 Conformance failure

```text
invalid JSON
typed value mismatch
unit mismatch
evidence citation outside allowed set
answer asserts COMPLETE while Runtime is not COMPLETE
```

均不得自动 retry。确定性可渲染时降级为 formatter；不可渲染时 abstain。

---

# 8. 通用配置合同

建议新增 candidate-only internal policy：

```yaml
RequirementCompleteRetrievalPolicyV01:
  schema_version:
  policy_digest:
  default_enabled: false

  max_extra_state_passes_per_query: 1
  max_actions_per_plan: 3
  max_additional_repository_calls_per_query: 2
  max_target_requirements: 3
  max_candidate_pool_per_query: 64
  max_hydrated_candidates_per_query: 120
  max_reader_evidence_items: 8

  preserve_baseline_action_budget: true
  allow_unverified_dense_cutoff: false
  allow_case_id: false
  allow_gold_inputs: false
  allow_time_axis_substitution: false

  require_proof_action_for_all_matches: true
  require_role_reservation: true
  use_rank_based_cross_channel_fusion: true
  compare_raw_scores_across_channels: false

  range_scan_max_items: 2000
  local_anchor_radius: 2
  model_calls: 0
  automatic_retries: 0
```

其中数值不是调参 sweep：

```text
64 / 120
  继承当前 AcquisitionCapabilityPolicy 的 candidate / hydration 上界；
  它们是 fail-closed ceiling，不是效果目标

8 / 2000 / radius 2
  分别继承当前 post-Binding context、official bounded scan 和 local expansion 边界

Dense verified official audit cap = 30
  继续由 capability registry 提供，不写死进 Prompt
```

最终实际 policy 必须以 Runtime capability 和 S0 freeze 为准；若当前 source 已变化，重新 seal，不得为了本表强行回退。

Full PASS 的跨 10-case 成本目标继续使用更强 DG-23 实测点：

```text
additional acquisition calls <= 4
candidates hydrated          <= 18
```

若正确性只能在旧 hard ceiling 内完成：

```text
calls <= 6
hydrated <= 26
```

可以封存为 `PASS_CORRECTNESS_PARKED_EFFICIENCY_REGRESSION`，但不得获得总体 Full PASS。

注意：

```text
range rows scanned != candidates hydrated
```

两者必须分别报告。

---

# 9. Work Packages

## WP25-00 — Baseline、denominator 与 review freeze

交付：

```text
DG24 terminal identity verification
DG23 candidate mediator/answer baseline verification
10-case order freeze
23 evidence-group denominator freeze
37 proof-obligation denominator freeze
source/config/index/snapshot identities
pre-existing worktree changes receipt
ablation independent review or Owner waiver receipt
```

硬门：

```text
formal holdout 0
architecture manifest matches
all predecessor hashes match
no treatment executed
```

## WP25-01 — Typed contracts and synthetic matrix

实现：

```text
RequirementAcquisitionPlanV01
plan validator
EventTimeIntervalV02
EventIdentityV01
BoundedRangeScanProofV02
TypedAnswerDecisionV01
canonical serialization and digest
```

Synthetic matrix 至少覆盖：

```text
stale state/epoch/action rejection
aggregate budget overflow
duplicate action digest
proof action required
optional action cannot shrink baseline cap
per-role reservation
cross-channel raw-score non-comparability

explicit date
source-relative weekday
last weekend
month interval
cross-year relative date
DST/timezone
unique relational anchor
ambiguous relational anchor
interval fully inside/outside/overlap
twins / multiple entities in one span
repeated same event across turns
unresolved event identity

proof max_items hit
projection gap with/without raw fallback
dead-letter gap
access snapshot invalid
unreadable source
Reader value/unit mismatch
```

本 WP 不加载 opened-dev labels。

## WP25-02 — Unified acquisition plan and official execution

实现：

```text
compile one plan from fresh RequirementState + feasible action set
compose evidence-discovery and proof actions
validate aggregate budget
execute through official AcquisitionService only
preserve per-action lineage
one fresh full recomputation
```

移除 candidate path 中：

```text
accuracy action silently supersedes deterministic action
ALL_MATCHES_IN_RANGE is globally excluded from acquisition planning
```

legacy path 保留，candidate 默认 OFF。

## WP25-03 — Ranking, cutoff and EvidenceSet selection

实现并分开测试：

```text
proof-first minimal plan
optional per-channel quota union
rank-based fusion
dedup with all channel lineage
per-requirement/evidence-role reservation
fixed final K
hard-filter taxonomy
```

必须提供组件级消融，决定哪些组件进入最终 policy。

## WP25-04 — Temporal interval and proof closure

实现：

```text
source-relative interval parser
coarse interval representation
unique-anchor relative relation
query-range membership validation
event identity / dedup
BoundedRangeScanProofV02 builder and validator
full RequirementState/Sufficiency integration
```

禁止使用模型或 gold event times。

## WP25-05 — Product-faithful mediator run

流程：

```text
label-free product execution
→ seal
→ scorer loads 23/37 registries
→ exact first-loss and proof scoring
```

对照：

```text
DG24 product baseline
DG23 candidate strong baseline
DG25 final minimal candidate
```

## WP25-06 — Typed answer boundary

实现：

```text
OperatorResult digest
TypedAnswerDecision compiler
deterministic formatter
constrained Reader validation
fail-closed mismatch behavior
trace linkage
```

## WP25-07 — Matched answer execution

仅在 WP25-05 C1 seal 后运行。

固定：

```text
10-case order
Reader model/revision
tokenizer/chat template
prompt
request identity
three preregistered replicate identities
runtime B_ref
Reader evidence plan
```

baseline 复用 sealed DG-23 outputs；只调用 DG-25 treatment 必需的 Reader requests。

## WP25-08 — Efficiency, quality, PostgreSQL and security

```text
correctness seal 后再做 five-repeat latency
unit / contract / targeted / predecessor regression
strict mypy
Ruff
real PostgreSQL integration/security
temporary DB cleanup
architecture validate / release lock
secret/privacy scan
```

## WP25-09 — Terminal, runbook and rollback

```text
lane dispositions
overall disposition
failure index
source/artifact manifests
terminal receipt
rollback instructions
candidate default confirmation
formal holdout confirmation
```

---

# 10. Stage 执行顺序

```text
S0  Baseline / denominator / source / independent-review freeze
 ↓
S1  Contracts + synthetic matrix
 ↓
S2  Unified plan compiler + validator + official batch execution
 ↓
S3A Ranking/cutoff/selection label-free all-arm generation and seal
 ↓ labels/scoring forbidden
S4A Event interval / identity / BoundedRangeScanProofV02 implementation
    + temporal label-free all-arm generation and seal
 ↓ both block seals + combined seal
Fresh independent scoring authorization bound to combined seal
 ↓
S4B Joint E1/E2 post-seal scoring and final-minimal-policy disposition
 ↓
S5  Product-faithful mediator run and C1 seal
 ↓ only if C1 PASS
S6  TypedAnswerDecision and formatter/conformance tests
 ↓
S7  Matched answer execution and C2 seal
 ↓ only after correctness seal
S8  Five-repeat latency/cost characterization
 ↓
S9  Full quality/PostgreSQL/security/architecture gates
 ↓
S10 Terminal audit / manifests / runbook / rollback
```

禁止跳过：

```text
S3A/S4A 不得加载 opened-dev labels 或执行 scoring
S4B 前必须同时存在 E1/E2 immutable all-arm seals、combined seal 与 fresh independent authorization
S5 前不得调用 Reader
S7 correctness seal 前不得做 latency repeats
S9 未通过不得写 Full PASS terminal
```

---

# 11. Claim-driven Experiment Blocks

本节遵守最多五个实验 block。以下方案由本地起草，状态为 `[pending independent review]`。

## E0 — Contract and synthetic falsification

**支持 Claim：** C1/C2 的可执行性前提。  
**输入：** synthetic, label-free。  
**处理：** 新 typed contracts、validator、event-time/dedup/proof/answer negative matrix。  
**主要指标：** invalid contract rejection、Wrong COMPLETE、stale acceptance、budget overflow acceptance。  

成功解释：

```text
所有非法/stale/不完整输入 fail closed；合法输入可重放。
```

失败解释：

```text
不能进入 opened-dev effect；先修合同或缩小 claim。
```

## E1 — Acquisition plan / channel / cutoff component ablation

**支持 Claim：** C1 的 retrieval/selection 部分。  
**输入：** DG-24 frozen label-free snapshots；每个 arm 使用相同 official per-channel pool 与固定 final K。  

E1 是 post-seal、只读的 matched replay：official channel-local results 先冻结，各 arm 只改变“哪些已存在的合法 occurrences 被 plan 选择并进入固定 K”。它不把宽 audit pool 注入产品；真实 invocation/cost 由 E3 product-faithful run 确认。

Arms：

| Arm | Component |
| --- | --- |
| R0 | current single-action / single-channel behavior |
| R0P | 将 R0 的同一 action 放入 one-action `RequirementAcquisitionPlanV01`；必须与 R0 完全等价 |
| R1 | unified proof-first acquisition plan；无 optional multi-channel union |
| R2 | R1 + per-channel quota union |
| R3 | R2 + requirement/evidence-role reservation |
| R4 | R3 + lexical hard filters converted to soft rank features |
| R5 | R4 - synonym normalization；若无 paired loss，synonym table 不得进入最终 candidate |

累计比较 `R0P→R1→R2→R3→R4` 只估计该顺序下的 conditional increment，
不得声称 order-independent unique effect。便宜 screen 完成后，对每个可移除的拟保留组件
执行预注册的 final-policy full-minus-one replay；所有可能 drop arm 在 pre-treatment manifest 中先行枚举，
不根据分数临时新增。

固定：

```text
snapshot
QueryIR
RequirementState input
capability set
channel-local queries/caps
Gate
final K
Binding/Sufficiency
no model
```

主要指标：

```text
TargetRequirementCandidateRecall@K
RequiredEvidenceCoverage@K
TargetRequirementBindingGain
AcceptedBindingPrecision
first-loss count by stage
calls / hydrated / noise
```

组件保留规则：

```text
组件必须产生唯一 mediator gain，且不降低 precision/safety；
无唯一 gain 的组件从最终 policy 移除。
```

## E2 — Temporal normalization / identity / proof ablation

**支持 Claim：** C1 的 temporal/proof 部分。  
**输入：** 两个 COUNT requirements 的同一组 label-free bounded-scan raw rows；gold 只在 seal 后评分。  

Arms：

| Arm | Component |
| --- | --- |
| T0 | current point-only event time + proof V01 |
| T1 | interval-valued direct/source-relative normalization |
| T2 | T1 + unique-anchor relative resolution |
| T3 | T2 + event identity/dedup V01 |
| T4 | T3 + BoundedRangeScanProofV02 full validation |

主要指标：

```text
event time resolved / ambiguous / unresolved
range membership accuracy
distinct event identity accuracy
proof obligations satisfied
Wrong COMPLETE
```

预期若组件有效：

```text
T1 关闭 source-relative date gaps；
T2 只对预声明且 grounded unique-anchor relations 提供额外 closure；无该 relation 时记为 NOT_APPLICABLE；
T3 消除 duplicate rows 且保留 multi-entity events；
T4 只在全部 closure 成立时允许 COMPLETE。
```

若 T1/T2/T3 无唯一 efficacy 作用，不应因架构美观而保留；但 event identity/dedup
和 Proof V02 的 fail-closed validator 可以由 synthetic counterexample 证明 safety necessity，不因两个 COUNT case
无 recall delta 而删除。T4 的 estimand 是 false COMPLETE prevention，不是 recall gain。

## E3 — One-pass product-faithful mediator confirmation

**支持 Claim：** C1。  
**输入：** 固定 10 opened-dev cases、23 evidence groups、37 proof obligations。  
**执行：** 先运行当前 source revision 的 fresh Candidate OFF，再运行 Candidate ON treatment；
两者使用相同 product repository、index、scope、snapshot、Gate、Binding、Sufficiency。DG-24 sealed output
只作历史参照，不代替 fresh OFF control。  

Primary endpoint：

```text
23/23 terminal evidence survival
37/37 proof obligations satisfied
10/10 OperatorReady
Accepted Binding precision = 1.0
Wrong COMPLETE = 0
```

失败解释按 residual first-loss 分类，禁止立即改 seed/Top-k/Prompt。

## E4 — Typed answer conformance matched confirmation

**支持 Claim：** C2。  
**输入：** E3 sealed EvidenceSet / OperatorResult；DG-23 baseline outputs 只读复用。  

Arms：

| Arm | Description |
| --- | --- |
| A0 | DG-23 frozen Reader answer baseline |
| A1 | same evidence + current unconstrained Reader boundary |
| A2 | TypedAnswerDecision + deterministic formatter where supported |
| A3 | TypedAnswerDecision + constrained Reader for non-deterministic rendering |

A1 是因果诊断 arm，用于区分“新 evidence 本身”与“typed answer boundary”的贡献；其 Reader calls 必须单独记入 evaluation cost，不能计入最终 product candidate 的 Reader-call 指标。A0 复用旧 sealed output，不重复调用。

在加载 labels 前冻结 answer-type routing 与 case membership。A2/A3 是互斥的最终 routing strata，
不是在不同 case 上比较的 alternatives：只在 deterministic-format-capable 的同一批 case 上比较
A1–A2，只在 non-deterministic 的同一批 case 上比较 A1–A3。A0 是历史 comparator，
不是 matched causal control。如 non-deterministic stratum 为空，A3 = NOT_APPLICABLE，不发起调用。
本 independent review 对 E4 的调用授权仍为 0；必须在 C1 seal 后另行冻结 exact requests/replicates/call budget
并取得非零调用授权。

固定：

```text
Reader identity
tokenizer
chat template
prompt
replicate identities
runtime B_ref
no retry
```

Primary endpoint：

```text
temporal COUNT correct in every replicate
correct-case regression = 0
Candidate EM >= 6/10 in every replicate
Candidate F1 >= 0.633715799 in every replicate
Wrong COMPLETE = 0
```

---

# 12. Metrics

## 12.1 Evidence lifecycle

```text
EvidenceGroupTerminalSurvival
FirstLossCountByStage
ChannelEligibleNotInvokedCount
ChannelCutoffDropCount
NoChannelRetrievedGoldCount
DedupWrongRepresentativeCount
```

Full target：

```text
EvidenceGroupTerminalSurvival = 23/23
所有非治理授权缺失 first-loss = 0
```

## 12.2 Binding and coverage

\[
RequiredEvidenceCoverage =
\frac{\#\text{covered acceptable evidence groups}}
{23}
\]

\[
AcceptedBindingPrecision =
\frac{\#\text{accepted bindings matching an acceptable role}}
{\#\text{all accepted bindings}}
\]

目标：

```text
RequiredEvidenceCoverage = 1.0
AcceptedBindingPrecision = 1.0
```

## 12.3 Temporal proof

```text
EventTimeResolvedRate
AmbiguousEventTimeCount
UnresolvedEventCount
EventIdentityResolvedRate
UnresolvedDuplicateGroupCount
BoundedRangeScanProofCompleteRate
ProofObligationSatisfactionRate
```

目标：

```text
AmbiguousEventTimeCount = 0 for the two registered requirements
UnresolvedEventCount = 0
UnresolvedDuplicateGroupCount = 0
Proof obligations = 37/37
```

## 12.4 Operator and answer

```text
OperatorReadyRate
TypedOperatorValueAccuracy
ReaderOperatorMismatchRate
Candidate EM
Candidate normalized F1
CorrectCaseRegressionCount
Wrong COMPLETE
Abstention correctness
```

## 12.5 Candidate efficiency

\[
UsefulCandidateRate =
\frac{\#\text{hydrated candidates contributing a valid Binding}}
{\#\text{all hydrated candidates}}
\]

\[
NoisePerUsefulCandidate =
\frac{\#\text{hydrated candidates not contributing a Binding}}
{\max(1,\#\text{useful candidates})}
\]

分别报告：

```text
logical selected actions
physical repository calls
replayed repository calls
returned rows
range rows scanned
candidates returned
candidates hydrated
candidates bound
candidates shown to Reader
state passes
Reader calls
latency
```

E1 matched replay 的新增 physical repository calls 固定为 0，但 live latency 记为 `NOT_MEASURED`，
不得把 replay 误写成零成本产品证据。最终 policy 的实际 calls/hydration 只由 E3 fresh execution 确认。

## 12.6 Cost and latency

```text
additional acquisition calls
additional state passes
range rows scanned
hydration count
Reader calls
product-candidate Reader calls
matched-diagnostic Reader calls
Planner/Controller calls
tokens
acquisition latency
semantics latency
proof latency
answer latency
end-to-end latency
```

correctness seal 后进行 5 次固定顺序 repeats，报告 median、p90、p95、max；不删除 cold run。

---

# 13. Hard Gates

## HG-00 — Identity and denominator

```text
DG24 authoritative receipt hash matches
DG23 authoritative artifacts match
10 cases fixed
23 evidence groups fixed
37 proof obligations fixed
formal holdout untouched
```

## HG-01 — Architecture and governance

```text
architecture manifest = ac16f3...55d0e
public MCP schema unchanged
PostgreSQL schema unchanged
canonical mutations = 0
wrong scope = 0
authority violation = 0
revoked/unreadable accepted evidence = 0
```

## HG-02 — Plan integrity

```text
stale plan accepted = 0
infeasible action accepted = 0
unregistered action executed = 0
aggregate budget overflow = 0
duplicate action executed = 0
automatic retries = 0
Planner/Controller/Residual Provider calls = 0
```

## HG-03 — Retrieval

```text
EvidenceGroupTerminalSurvival = 23/23
RequiredEvidenceCoverage = 23/23
AcceptedBindingPrecision = 1.0
correct-case evidence retention = 100%
non-authorized first-loss = 0
```

## HG-04 — Temporal proof

```text
37/37 proof obligations SATISFIED
AMBIGUOUS_EVENT_TIME = 0
EVENT_TIME_UNRESOLVED = 0
unresolved duplicate groups = 0
both COUNT requirements proof status = COMPLETE
top_k_used_as_completeness = false
```

## HG-05 — Operator and safety

```text
OperatorReady = 10/10
Wrong COMPLETE = 0/10
wrong operator value = 0
wrong unit = 0
```

## HG-06 — Answer

```text
temporal COUNT correct = 2/2 in every replicate
Candidate EM >= 6/10 in every replicate
Candidate normalized F1 >= 0.633715799 in every replicate
correct-case regression = 0
ReaderOperatorMismatch escaping validator = 0
invalid JSON escaping validator = 0
```

## HG-07 — Efficiency

Full PASS target：

```text
additional acquisition calls <= 4 across 10 cases
candidates hydrated <= 18 across 10 cases
additional state passes <= 1 per eligible query
Reader calls = 0 for deterministic typed answers
matched-diagnostic Reader calls are isolated and reported separately
exact identity duplicate Reader calls = 0
automatic retries = 0
```

若只满足：

```text
calls <= 6
hydrated <= 26
```

则 correctness 可单独 PASS，Overall 必须 PARK efficiency。

## HG-08 — Generality

```text
case-ID runtime branches = 0
gold/answer runtime inputs = 0
new opened-dev literal rules = 0
unverified Dense cutoff use = 0
eval-owned retrieval = 0
final policy components all have unique mediator gain or correctness necessity
```

## HG-09 — Quality

```text
all selected unit/contract/targeted/predecessor tests pass
strict mypy pass
Ruff pass
real PostgreSQL integration/security pass
temporary databases cleaned
architecture validator pass
release lock pass
secret/privacy scan pass
```

## HG-10 — Release boundary

```text
candidate default OFF
formal holdout untouched
no release enablement
no Production-ready claim
Schema remains 0.1.x EXPERIMENTAL / NO-GO FOR FREEZE
```

## HG-11 — Preregistered execution discipline

每个 block receipt 必须逐项机器化求值：

```text
identity/source/snapshot/access/K/cap/scorer/arm-order drift = 0
label loaded before immutable product seal = 0
unmatched pool or final K = 0
stale/infeasible/unregistered plan = 0
budget overflow = 0
AcceptedBindingPrecision < 1.0 = false
Wrong COMPLETE > 0 = false
schema/public MCP/architecture drift = 0
retry/model/provider/controller calls = 0
post-score treatment adaptation = 0
```

任一项失败立即停止当前及下游 effect block，写 append-only failure receipt，不自动重跑：

```text
E3 C1 FAIL  → E4 NOT ENTERED
correctness 未 seal → latency repeats NOT ENTERED
需要 schema/public MCP/architecture 变更 → NOT_ENTERED_SCHEMA_AUTH_REQUIRED
Reader mismatch/invalidity → deterministic fallback or abstain；不得 retry-to-pass
```

---

# 14. Test Plan

## 14.1 Unit

### Plan and capability

```text
fresh plan accepted
stale state/epoch/capability/policy rejected
unknown action rejected
duplicate action rejected
aggregate call/hydration budget rejected
proof action required for ALL_MATCHES_IN_RANGE
optional action cannot shrink baseline action cap
one state epoch increment
```

### Ranking and selection

```text
same fixed pool and fixed K
each required role reserves legal best candidate
single-valued requirement reserves at most one
cross-channel raw score never directly compared
dedup retains all channel lineage
wrong dedup representative rejected
lexical soft feature cannot bypass Gate
```

### Temporal

```text
explicit point
day/week/weekend/month interval
source-relative weekday
relative phrase crossing month/year
timezone/DST
unique vs ambiguous relational anchor
closed-open boundaries
full containment / disjoint / partial overlap
same event repeated
multiple events in one span
event identity unresolved
```

### Proof

```text
complete proof
max_items hit
snapshot drift
partition open
projection watermark behind
dead-letter gap
raw fallback closes/does not close gap
unreadable source
access snapshot invalid
ambiguous event time
dedup incomplete
```

### Answer

```text
integer/date/duration/boolean formatter
unit preservation
Reader exact echo
Reader changes value
Reader changes unit
Reader claims COMPLETE on partial state
deterministic fallback
abstention when no safe formatter
```

## 14.2 Contract

```text
legacy AccuracyActionBundleV01 remains readable
RequirementAcquisitionPlanV01 digest stable
BoundedRangeScanProofV01 historic artifact remains readable
V02 writer never emits V01 schema version
TypedAnswerDecision identity stable
public MCP response schema unchanged
feature flags default false
```

## 14.3 Product-faithful integration

```text
official RetrievalRepository only
official AcquisitionService only
real index identities
Gate/Binding/Sufficiency full recompute
no eval-owned retrieval
no gold loaded before seal
```

## 14.4 PostgreSQL and security

使用独立临时测试库和真实 login roles：

```text
tenant/scope isolation
revoked evidence rejected after stale index hit
permission/retention unreadable fail closed
event range scan snapshot identity
watermark/dead-letter behavior
statement timeout
transaction snapshot stability
connection context reset
cleanup
```

不修改 migration 时仍必须运行当前 integration/security suite。

## 14.5 Regression

至少运行：

```text
runtime tests/unit
runtime tests/contract
retrieval/temporal/semantics/sufficiency/operator targeted tests
DG20–DG24 behavioral regression
DG25 targeted evaluation tests
strict mypy for Runtime and DG25 harness
Ruff for Runtime and DG25 files
architecture validate_bundle
architecture verify_lock release mode
real PostgreSQL integration/security
```

测试数以 fresh logs 为准；本文不预先编造 passed count。

## 14.6 Negative fixtures

必须包含：

```text
gold at rank 1 but cutoff drops it
optional channel returns only noise
all channels repeat same region
Dense unavailable above verified cap
temporal scan returns all rows but one event time overlaps query boundary
one unreadable row in bounded partition
twins in one span
same baking event repeated in two sessions
relative anchor has two candidates
Reader returns correct prose with wrong number
Reader returns malformed JSON
```

---

# 15. Failure Discipline

## 15.1 Append-only evidence

每次失败必须：

```text
创建新的 failure receipt
append var/dg25/failure-index.jsonl
保存 command/argv/cwd/config/source/snapshot identity
保存 stdout/stderr digest
记录 first failing gate
记录 root cause
记录 general fix
新 run ID fresh rerun
```

旧失败不得覆盖、删除或改写。

## 15.2 禁止的修复方式

```text
换 seed
加 retry
扩大 Top-k 直到 gold 出现
改变 case order
删除失败 replicate
只重跑失败 case 并当作 full run
把 source time 当 event time
按 case ID/答案/gold source ref 分支
将 proof PARTIAL 改名 COMPLETE
降低 Binding precision
让 Reader 自己决定 count
使用 simplified shadow retriever
```

## 15.3 失败后的合法动作

| Failure | 合法处理 |
| --- | --- |
| channel still not invoked | 检查 plan compiler / capability validation / aggregate budget |
| candidate still cut | 检查 fixed-pool reservation，不扩大 K |
| no channel discovers evidence | 检查 bounded temporal/raw fallback 或另开 semantic/associative successor |
| event time unresolved | 检查 grounded interval/anchor；不能猜 |
| proof partial | 保持 `COMPLETENESS_PROOF_MISSING` |
| Binding precision drops | 回滚 treatment，保留 first-loss |
| Reader mismatch | typed gate fallback/abstain，不 retry |
| cost regression | 移除无 unique gain 的 channel/component |
| schema needed | `NOT_ENTERED_SCHEMA_AUTH_REQUIRED` |

## 15.4 Three-strike 不适用说明

本 Goal 的 terminal PARK 是实验终态，不是持久 Goal 系统的 `blocked` 状态。一次合法、完整、预注册的 effect run 已可产生 PARK；不得通过连续重复相同失败来等待偶然 PASS。

---

# 16. Terminal Dispositions

## 16.1 Lane dispositions

### Retrieval

```text
PASS_REQUIREMENT_COMPLETE_RETRIEVAL
PARKED_RETRIEVAL_FIRST_LOSS_REMAINS
FAIL_BINDING_PRECISION_OR_GOVERNANCE
```

### Temporal

```text
PASS_BOUNDED_RANGE_SCAN_PROOF_V02
PARKED_EVENT_TIME_OR_DEDUP_UNRESOLVED
FAIL_WRONG_TEMPORAL_COMPLETE
```

### Answer

```text
PASS_TYPED_ANSWER_CONFORMANCE
PARKED_READER_EVIDENCE_CONSUMPTION_NONCONFORMANCE
FAIL_CORRECT_CASE_REGRESSION
```

### Efficiency

```text
PASS_DG23_COST_NONREGRESSION
PASS_CORRECTNESS_PARKED_EFFICIENCY_REGRESSION
```

## 16.2 Overall terminal

只有全部 Full gates 成立：

```text
PASS_REQUIREMENT_COMPLETE_ACQUISITION_TEMPORAL_ANSWER_CLOSURE
```

其他合法终态：

```text
PARKED_RETRIEVAL_FIRST_LOSS_REMAINS
PARKED_TEMPORAL_PROOF_UNRESOLVED
PARKED_READER_EVIDENCE_CONSUMPTION_NONCONFORMANCE
PARKED_EFFICIENCY_REGRESSION
PARKED_INDEPENDENT_ABLATION_REVIEW_REQUIRED
NOT_ENTERED_SCHEMA_AUTH_REQUIRED
FAIL_SAFETY_OR_REGRESSION
FAIL_PROTOCOL_VIOLATION
```

Overall receipt 必须同时写出每条 lane disposition，不能用一个总体字符串覆盖局部成功或失败。

## 16.3 Full PASS receipt 最低字段

```yaml
DG25TerminalReceiptV01:
  overall_disposition:
  retrieval_disposition:
  temporal_disposition:
  answer_disposition:
  efficiency_disposition:
  safety_disposition:
  quality_disposition:

  denominators:
    cases: 10
    evidence_groups: 23
    proof_obligations: 37
    reader_replicates: 3

  metrics:
    terminal_evidence_groups:
    proof_obligations_satisfied:
    required_evidence_coverage:
    accepted_binding_precision:
    operator_ready:
    wrong_complete:
    answer_em_by_replicate: []
    answer_f1_by_replicate: []
    correct_case_regressions:
    additional_acquisition_calls:
    candidates_hydrated:
    range_rows_scanned:
    product_candidate_reader_calls:
    matched_diagnostic_reader_calls:
    controller_calls:
    automatic_retries:

  safety:
    candidate_default:
    formal_holdout_consumed:
    canonical_mutations:
    public_mcp_schema_changed:
    postgresql_schema_changed:
    architecture_v1_changed:
```

---

# 17. Deliverables

## S0

1. `baseline-freeze.json`  
2. `denominator-freeze.json`  
3. `source-config-index-snapshot-manifest.json`  
4. `preexisting-worktree-receipt.json`  
5. `ablation-independent-review.json` 或 `owner-review-waiver.json`  
6. `receipt.json`

## S1

7. `contract-schema-bundle.json`  
8. `synthetic-matrix.json`  
9. `negative-contract-report.json`  
10. `receipt.json`

## S2

11. `requirement-acquisition-plan-traces.json`  
12. `plan-validation-report.json`  
13. `official-execution-equivalence-report.json`  
14. `receipt.json`

## S3 readiness / S3A

readiness 前置产物：`execution-delta-manifest.json`、`e2-common-input.json`、
`effect-scorer-contract.json`、`all-arm-seal-protocol.json`、`source-manifest.json`、
`stop-evaluation-contract.json`、`readiness-validation-report.json`、`receipt.json`。

S3A 产物：`e1-label-free-arm-outputs.json` 与 `e1-all-arm-seal.json`。

## S3/S4B scored reports

S3A 先生成 `e1-all-arm-seal.json`；以下 15–19 只有在 S4A 的 E2 all-arm seal、combined seal、
fresh independent scoring authorization 和 S4B joint score 全部通过后才能发布：

15. `routing-selection-ablation-report.json`  
16. `component-unique-contribution-report.json`  
17. `rule-leave-one-out-report.json`  
18. `final-minimal-policy.json`  
19. `receipt.json`

## S4

20. `event-time-interval-traces.json`  
21. `event-identity-dedup-traces.json`  
22. `bounded-range-scan-proof-v02-collection.json`  
23. `temporal-ablation-report.json`  
24. `receipt.json`

## S5

25. `sealed-product-treatment.json`  
26. `sealed-product-treatment-sha256.txt`  
27. `mediator-score.json`  
28. `first-loss-post-treatment.json`  
29. `proof-obligation-post-treatment.json`  
30. `cost-trace.json`  
31. `receipt.json`

## S6/S7

32. `typed-answer-decision-collection.json`  
33. `answer-conformance-negative-report.json`  
34. `sealed-reader-treatment.json`  
35. `answer-score.json`  
36. `reader-call-ledger.json`  
37. `receipt.json`

## S8/S9

38. `latency-repeat-report.json`  
39. `quality-gate-receipt.json`  
40. `postgresql-integration-security-receipt.json`  
41. `temporary-database-cleanup.json`  
42. `privacy-secret-scan.json`  
43. `architecture-lock-verification.json`

## S10

44. `terminal/receipt.json`  
45. `terminal/deliverable-index.json`  
46. `terminal/source-artifact-manifest.json`  
47. `terminal/failure-index.json` 或对 append-only index 的 digest-bound pointer  
48. `docs/runbooks/dg25-requirement-complete-acquisition.md`  
49. `terminal/rollback-report.json`

所有 receipt 内嵌 source/artifact identity 必须在终态后独立重算。

---

# 18. Rollback、兼容与发布边界

## 18.1 Feature flags

至少分离：

```text
requirement-complete acquisition candidate
typed-answer conformance candidate
```

两者默认均为 OFF。关闭后必须恢复 DG-24/DG-23 当前默认行为，不要求数据库回滚。

## 18.2 Contract compatibility

```text
historic V01 artifacts remain readable
new V02 proof uses new schema version
no in-place rewriting of old receipts
no public MCP response change
no DB row migration
```

## 18.3 Rollback triggers

任一情况立即关闭 candidate：

```text
Wrong COMPLETE > 0
Accepted Binding precision < 1.0
correct-case regression > 0
cross-tenant/scope/access violation
unbounded range scan
Reader mismatch escapes validator
automatic retry > 0
architecture/schema drift
```

## 18.4 Release

DG-25 Full PASS 仍只代表：

```text
opened-development candidate correctness closure
```

不自动授权：

```text
default ON
formal holdout
Production release
Schema freeze
public benchmark claim
paper claim
```

这些需要独立 Goal 和 Owner 授权。

---

# 19. 执行检查表

## 开始前

- [x] 重新读取 `AGENTS.md` 与实施合同  
- [x] 验证 DG-24 S8-003 authoritative identity  
- [x] 验证 DG-23 mediator/Reader identities  
- [x] 冻结 10/23/37 denominators  
- [x] 记录用户已有 worktree 修改  
- [x] 完成 independent ablation review 或 Owner waiver  
- [x] 确认 holdout 0  
- [x] 确认 candidate default OFF

## Contracts

- [x] Plan V01  
- [x] EventTimeInterval V02  
- [x] EventIdentity V01  
- [x] BoundedRangeScanProof V02  
- [x] TypedAnswerDecision V01  
- [x] stale/negative synthetic tests  
- [x] legacy readers preserved

## Retrieval

- [ ] unified plan replaces supersession in candidate path  
- [x] proof and discovery actions compose  
- [x] aggregate budget validated  
- [x] official executor only  
- [x] fixed K  
- [ ] requirement reservation  
- [x] channel lineage retained  
- [ ] component ablation determines minimal final policy  
- [ ] no unverified Dense cap

## Temporal

- [ ] source/event/system time separated  
- [ ] direct/source-relative intervals  
- [ ] unique-anchor relation  
- [ ] interval membership  
- [ ] event identity  
- [ ] duplicate/multi-entity behavior  
- [ ] proof V02 closures  
- [ ] Wrong COMPLETE 0

## Mediator

- [ ] product trace sealed before labels  
- [ ] 23/23 evidence groups  
- [ ] 37/37 proof obligations  
- [ ] Binding precision 1.0  
- [ ] OperatorReady 10/10  
- [ ] cost targets met

## Answer

- [ ] typed result authority  
- [ ] deterministic formatter  
- [ ] constrained Reader validation  
- [ ] baseline calls not repeated  
- [ ] three treatment replicate identities fixed  
- [ ] temporal counts 2/2 all replicates  
- [ ] EM/F1 floors met  
- [ ] correct-case regression 0

## Quality and terminal

- [ ] correctness sealed before latency repeats  
- [ ] all quality gates pass  
- [ ] real PostgreSQL/security pass  
- [ ] temp DB cleanup  
- [ ] architecture lock pass  
- [ ] failure index complete  
- [ ] manifests independently verified  
- [ ] candidate remains OFF  
- [ ] formal holdout untouched  
- [ ] truthful lane + overall terminal written

---

# 20. DG-25 之后的路由（历史预注册，已被后验结果取代）

本节原表保留为 pre-score 设计历史，不再是当前执行入口。DG-25、DG-26 的后验结果已经证明：固定池重排和层层硬验证都不是主要修复路径。当前 successor 以 [DG-26～DG-30 自适应检索轻量开发基线](./MiLAi_DG-26-DG-30_轻量执行与审查基线.md) 为准：

```text
DG-27  ProvisionalBinding + 集中 DecisionBoundary
DG-28  Capability Sandbox 内一轮宽 multi-channel retrieval
DG-29  条件式 observation-driven refinding
DG-30  集中验证与集成
```

只有 DG-25 完成后，才按实际 residual first-loss 选择 successor：

| DG-25 结果 | Successor |
| --- | --- |
| deterministic Full PASS | 不调用模型；另开 release/holdout authorization Goal |
| fixed governed pool 存在 gold，但排序仍丢失 | StateView-aware reranker matched experiment |
| action 已选定但 expression gap 仍存在 | `ResidualCueV02` SHADOW → one-pass official acquisition |
| 多个 feasible actions 有稳定选择歧义 | model action ranking within feasible set |
| grounded interpretation 缺失 | bounded `EvidenceInterpretationProposal` experiment |
| 任何现有 channel/temporal/raw fallback 均不可达且存在 anchor | bounded associative retrieval / cue graph |
| Reader 仍覆盖 typed value | Reader boundary 单独 PARK；不得继续改 retrieval |

长期架构仍保持：

```text
Model-understood, Runtime-governed
```

但当前开发顺序必须服从机器事实：

```text
先修 action composition
→ cutoff preservation
→ temporal interval and proof
→ typed answer authority
→ 再判断模型是否真的有 residual mediator space
```

---

# 21. 最终原则

DG-25 的目标不是把更多文本塞给 Reader，而是让每个 required evidence role 和 proof obligation 都有一条可验证、可审计、成本受界的完成路径。

最关键的工程原则：

> **COUNT 的正确性来自受界 event-time 枚举、event identity、dedup 和 proof closure，不来自 Top-k；答案的数值来自 deterministic OperatorResult，不来自 Reader 猜测。**

最关键的实验原则：

> **先证明 unified proof-first plan 是否已经足够；只有具有独立 mediator gain 的 multi-channel、rule、ranking 或模型组件才允许进入最终 policy。**

最关键的安全原则：

> **中间候选只执行权限、来源和动作边界 admission；语义解释允许 provisional/ambiguous。只有最终 AcceptedBinding、Sufficiency、OperatorResult 和 Canonical 边界执行集中严格验证；Candidate 仍默认关闭。**
