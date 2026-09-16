---
goal_id: MILA-V02-24
version: "0.3"
date: "2026-09-13"
title: Gate A Closure to Valid Persistent Note Comparison
kind: CONSOLIDATED_MASTER_RESEARCH_AND_DEVELOPMENT_GOAL
document_status: UPDATED_PLAN_NOT_EXECUTION_AUTHORIZATION
programme_status: IN_PROGRESS_UNFINISHED
current_gate: A_R04_LOCAL_CALIBRATION_HEADROOM_MET_AUDIT_PENDING
gate_a: NOT_PASSED
gate_b_to_e: NOT_ADMITTED
memory_status: MEMORY_NOT_ADMITTED
memory_valid_denominator: 0
next_single_gate: A0_EXISTING_CALIBRATION_INDEPENDENT_CLOSURE
new_model_allocation: 0
new_provider_http_allocation: 0
new_confirmation_allocation: 0
new_experiment_execution_allocation: 0
cumulative_raw_token_cap: null
e_matrix_selection: NOT_SELECTED
active_execution_contract_changed: false
---

# V0224 v0.3：收口 Gate A，恢复有效执行，再判断普通持久记忆的行为影响

## 1. 本版目标、效力与成功定义

本版是新的 A–E **规划入口**：整合最新可核验证据、v0.1 的执行路线与已经采纳的 v0.2.1 研究差异。
不覆盖旧 Goal、不修改正在使用或已结束的实际合同，不重启旧实例，不新增实验配额。
“生成最新 Goal”不等于本轮启动实验；今后执行仍须绑定实际子合同、有效前置证书与明确范围。

最终目标是完成首批可解释的 **N0 / ordinary persistent Note N1 / ordinary review R1** 比较：

> 当旧 Note 曾有依据、真实提交、经新 Host 公开冷读，且旧 Note 与当前证据都实际呈现，
> 行动合同可执行、世界行为真值可靠时，这份记忆是否改变后续行为？普通复核是否已经足够？

有效的无差异、普通方案足够、局部帮助或局部风险，都可以完成研究；不要求必须发现复杂机制。
仅完成工程修复、部分矩阵或失败报告，不能宣称 A–E 主研究已完成。

### 1.1 文档分工与冲突处理

| 文件 | 地位 |
| --- | --- |
| [v0.1 主 Goal](MILA_V0224_Gate_A至E执行有效性与持久记忆研究_总GOAL_20260913.md) | 保留制定时快照；其中 NOT_STARTED 不是最新运行状态 |
| [v0.2 提案](MILA_V0224_RESEARCH_REFINEMENT_PROPOSAL_20260913.md) | 提案历史，不整体替换既有执行设计 |
| [v0.2.1 采纳差异](MILA_V0224_RESEARCH_ADOPTION_DELTA_20260913.md) | 同调用 review、前瞻 E 矩阵、D2 世界覆盖、分母与成本规则的来源 |
| 本版 v0.3 | 后续工作与验收的整合入口；不追溯改变已冻结实例 |
| [R03 authority 合同](MILA_V0224_GATE_A_REVISION_03_BUNDLE_AUTHORITY_20260913.md)、[R04 去重合同](MILA_V0224_GATE_A_REVISION_04_SCOPE_DIGEST_REUSE_20260913.md)及实际 run contract | 当前 A 工作点的技术保证、差异、资源和真实执行范围 |
| [执行记录](MILA_V0224_EXECUTION_STATE_20260913.md)与原始 terminal/review | 执行证据；摘要落后时，以绑定相同版本的可核验终态为准，不靠较新文件名判 PASS |

历史 V0222、R02/R03/R04 各次失败和未运行位置保留。新合同只能接替后续工作，不能续填旧失败为 PASS。
原始轨迹留在 Git 外；Goal 写判据，执行状态写当前下一步，报告写结果，不再向 Goal 追加执行流水账。

## 2. 当前起点：局部计时达标，不是 Gate A PASS

以下是本版制定时的只读证据快照。旧执行记录仍写“R04 V2 准备完成、待校准”，
但原始六位置校准 terminal 已完成；**完整独立结果验收和 K3 尚不能据此签发**。

| 项目 | 已核验证据 | 严格解释 |
| --- | --- | --- |
| R04 V2 准备 | 外层 214.74 秒，退出 0 | 准备完成；不是参考矩阵或 Gate A 通过 |
| 六位置 U1/S1/S2/U2/U3/S3 | 父与六子进程退出 0，清理完成；外层 179.63 秒 | 该有界校准完成；不是六个独立任务根 |
| S 三次完整 runtime 并集 | 15.775482363 / 15.725068708 / 15.764869123 秒 | 已测七次校验路径均 ≤18 秒，最小余量约 2.22 秒 |
| 严格 U 的整个 worker | 30.363849588 / 29.224506841 / 29.217148055 秒 | 以整个 worker 上界保守证明内部 Session ≤60 秒 |
| S/U 配对比值中位数 | 1.004835179，门为 ≤1.10 | 此测量方式局部合格；不是候选加速比或生产 SLA |
| 逐例业务效果检查 | 六位置均 PASS | 三轮、单动作 reference 路径；不等于完整独立审计 |
| 独立综合语义/SQL审计 | terminal 仍为 `REQUIRED` | 本版不预填通过；需有绑定当前 raw 的终态 |
| 模型、Provider HTTP、设备 | 该校准均为 0 | CPU Reference / INTENT_ORACLE，不是自然模型行为 |
| 长路径、完整 K3、B–E | 当前证据不足以签发 | Memory 合格分母仍为 0 |

本次状态核对复算了三组原始时间区间，并核对 terminal 绑定的 16 个文件摘要一致。
这项小范围核对**不替代**完整语义、动态 SQL、历史账务、世界效果和生命周期独立验收。

关键证据：

- [实际校准合同](/cra/memory/mx_memory/evidence/v0224/20260913-a-scope-digest-v2/calibration-contract-draft-v1/contract.json)，SHA256 `cf2a2f86492f15209a8e4d2bd880afdafb8b2d684b39e20d9ac0954687117160`。
- [校准原始终态](/cra/memory/mx_memory/evidence/v0224/20260913-a-scope-digest-v2/calibration-contract-draft-v1/calibration-external-terminal.json)，SHA256 `717948dd78b2dd34abdcf98f3e5fbaa800253caddf5b4e717097a08e94fdef45`。
- [四轮 reference 后续计划](/cra/memory/mx_memory/evidence/v0224/20260913-a-scope-digest-v2/four-turn-reference-slice-plan.json)，当前是 `PLAN_ONLY_NOT_IMPLEMENTATION_OR_EXECUTION`，不作为执行许可或成绩。

### 2.1 保证变化必须诚实列出

R03 将明确分类的历史纯静态原字节迁入冻结 bundle authority，复用封存时的静态语义验证。
旧静态路径单独漂移、而新 authority 与所有 fresh 边界未变时，其接受行为可能不同于 R02；这是**有意修改保证**。
R04 在 R03 上只复用同一 scope、同一不可变 bytes 已验证的整包摘要，删除解析末尾重复哈希。
其重复调用/资源异常不再原样发生，不能宣称所有调用计数与异常路径完全等价。

每 scope 的首次与关闭实际读取/整包哈希、每 blob 校验、完整解析，以及当前授权、stop、owner、
CAS/head、operation/receipt、历史账本、动态 SQL、实际执行源码/环境、期限检查仍按合同保留。
没有跨 scope PASS 缓存，不把旧 bundle 中的动态值当成当前 authority。
未来通过只能写“在绑定的 R03+R04 保证下 Gate A PASS”，不能追认原 R02 全保证已恢复。

## 3. 总路线与不可变边界

```text
A：既有校准独立收口 → 长路径 → 完整 CPU/cold/余量与工程终态
 ↓
B：新正式 P3，16/16 完整意图保真
 ↓
C：P4，24/24 已知正确意图执行
 ↓
D：去 Oracle；恢复校准 + 无旧 Note 的自然任务能力
 ↓
E：自然 Note → 公开冷读与双呈现 → N0/N1/R1 有效比较
 ↓
保持简单 / 分层诊断 / 有依据的开放探索 → 另立独立确认合同
```

全程遵守：

1. A 零模型、零 Provider/实验 HTTP、零设备调用。后续只用明确范围内的 vLLM HTTP，不操作 GPU、驱动或共享模型服务。
2. 业务副作用只发生在绑定的隔离世界；Product 仅经已 pin 的公开 API/testkit，不写 canonical 私表，不用私有 clone/helper。
3. principal、tenant、scope、权限由可信 Host/Runtime 绑定；模型、Note、外部来源不能扩权。State 不成为信息过滤权威。
4. 完整 Schema、CAS、操作幂等、回执与独立 world readback 保留。Note 写成功、文字 DONE、accepted 都不替代业务完成。
5. A0 默认、Product 行为、公开部署与 Schema NO-GO 不变；不消费 candidate 57、保护 reserve 或确认池。
6. 累计 raw-token 上限仍不设置，但每批请求、并发、输出容量、时限、停止和用量结算必须有界。
7. 本地协议工程回归与 A 实验网络范围分账；任何工程例外不传递成 vLLM/外部 HTTP 权限。
8. 测试床、研究原型、公开 Product 行为分别标明 `ExperimentArmKind`；模拟世界效果不冒称线上产品收益。

## 4. Gate A：只收口已有工作点，不重新开启泛化成本工程

### A0 — 既有六位置校准的独立收口：当前唯一下一步

不重跑六位置，不修改原 terminal。独立审阅者核对：

- 原始合同、所有实际执行源码/环境 pin、输入与 authority 的绑定，以及生命周期 start/exit/cleanup。
- 七次完整 runtime 区间、setup 与 session 边界，inclusive/union 不重复相加；严格 U 未引入内部观察器。
- 原始动作、完整 intent、首提接受、CAS/operation/receipt、独立 world effect；无隐藏副作用、未知提交或协议拒绝。
- local ledger、四份历史 coordinator、当前 SQL/控制面、动态负控与所有规定的 fresh 检查。
- 全部资源上界、父收口、遗留用量与本次账务；无模型/实验 HTTP/设备调用。

输出紧凑的独立结果与 blocking findings，绑定 raw hash。预执行 freeze/readiness 审阅不能代替事后结果审阅；代理审阅也不能标为人工审阅。
PASS 只记 `R04_SEVEN_RUNTIME_CALIBRATION_ACCEPTED`，仍不是 Gate A PASS。
若发现可补核对的缺证据，先只读补验；若原始执行、保证或计量不成立，保留失败，转最小修订，不补写假证据或重复取快值。

### A1 — 四轮、九次 runtime 的长路径验证

仅在 A0 验收成立并有明确子合同后，落实既有四轮计划；不是再造一个 profiler/cache/adapter。
冻结一个原目录内、确实包含两动作的 reference case、输入/顺序/源码与新冷身份，不打开新研究根或 C。
选择依据是需要覆盖的**执行形状**，不是此前输出好坏；最长声明轮数不等于已证明最坏耗时。

子合同沿用六位置 U1/S1/S2/U2/U3/S3、并发 1、零模型/HTTP/设备；完整四轮含九次 runtime 校验，两个 setup 回调另计。
逐 S 的九次并集 ≤18 秒；严格 U 整个 worker ≤60 秒，或提供另行冻结且完整可信的 Session 外层证明。
六位置 parent ≤600 秒、worker 外层保护 ≤300 秒、准备 ≤300 秒；worker 保护不是把 Session 60 秒延长。
父子完整退出、效果、SQL与动态边界同样需独立验收，不能将旧七次校准的比例、时间或三轮效果转借给九次路径。

这一步若需选择器等最小接线，先声明差异、局部反例与依赖失效范围，再冻结新实例；不在旧实例内 patch。
通过只补长路径可行性，不把六位置校准当成完整 24 P4 或 40 冷进程。

### A2 — 当前版本完整 K3 与正式 Gate A

前述诊断成立后，才组织一个新的、完整冻结的 CPU 验收实例，复用有效证据但不借旧位置凑数。

| 必须完成 | 通过条件 |
| --- | --- |
| 实际规模与 authority | 覆盖历史 55-scope 前缀、57 local ledgers、4个历史 SQL 根及完整5k+闭包；复算实际 paths/bytes/rows，逻辑覆盖与物理读取分报 |
| 保证与负控 | R03/R04 有意差异逐项披露；其余内容/权限/账务/效果保证保持，无未声明的新差异；动态校验持续新鲜 |
| 参考与业务效果 | 完整 16+80 reference rows、24效果链，准确覆盖 single/double/complex 与合法 finish |
| 冷执行及父收口 | 实际16+24独立冷进程、父 finish/gate、回执和独立 readback；不是一个热进程循环40次 |
| 工程终态 | 全检查实际 exit 与结果绑定当前执行 revision，非 collected、历史测试数或未完成进程 |

资源判据不改变：

| 对象 | 原硬期限 | 所需余量 |
| --- | ---: | ---: |
| 完整参考 Session | 60秒 | 全部 runtime admission 并集≤18秒 |
| 单正式链 CPU replay | 300秒 | 该链及归属父准入合计≤90秒 |
| CPU P3阶段 | 1800秒 | 整阶段≤900秒 |
| CPU P4阶段 | 7200秒 | 整阶段≤3600秒 |
| K3 seal/init、完整参考准备 | 300秒、3600秒 | 创建包、静态验证、审阅与报告计入各自实际生命周期 |

完整阶段包括调度、父子准入、finish/gate、写报告与退出。预计算不能从成本中消失；重复引用不重复计费。
冷 Host/进程不宣称清空 OS 页缓存；小样本逐项判门，不报总体 P95/SLA；CPU 通过不保证真实 HTTP 通过。

只有 A0/A1 的适用证据、A2 全矩阵、保证/负控、资源与当前工程终态全部有效，才签发：
`GATE_A_PASS_UNDER_R03_R04 / LIVE_NOT_ADMITTED / MEMORY_NOT_ADMITTED`。
另一个更长路径再次超限时，先定位具体重复成本或提出删减保证的 testbed 简化合同；不自动加时或继续堆审计层。

## 5. Gate B：新的正式 P3，16/16 full intent fidelity

进入条件：A证书有效，唯一新 concrete live scope 与 Provider 请求范围明确；当前输入容量、身份、完整 Schema/wire/presentation 绑定完成。
初始沿用 B1+D11：D11 只改变生成约束，完整后验业务校验保留；不把删除约束等同于放宽意图标准。

- 矩阵：原四个已暴露 roots × full/finish × 两冷遍 =16位置，每位置一次真实请求、无业务 dispatcher。
- 首遍8/8才进入次遍；完整16/16才通过。旧12 PASS、诊断8/8不能计入新矩阵。
- 验收顺序：HTTP/用量结算 → strict JSON → 完整 Schema → 授权目标及全部值/顺序或合法 finish → 适用 CAS/envelope → 原始证据与期限内父接受。
- 合法但错误目标仍 FAIL；不 trim、改值、删除合法对象或用 gold enum/const 帮模型选答案。
- 非预期意图、格式、基础设施失败即关闭本正式实例；未知用量立即停发且不自动重试。C不启动。

可回已开放 DEV 区诊断具体 wire/呈现差异，提出新版本后重验完整16位置；不只补错题、不换 seed 抽签过关。
计划上界16生成、P3阶段1800秒、每HTTP≤60秒、并发1；辅助 identity/tokenize 请求须另冻次数与到期。

## 6. Gate C：P4，24/24 known-intent execution

在同一合格栈上，四 roots × 单写/双写/复杂文本 × 两冷遍 =24链，每链≤4生成，最多96生成。
80 reference rows 是合法参考路径数，不是实际请求上限；参考替身成功不计真实模型成绩。

给定完整授权意图以隔离执行能力，但不由 evaluator 每轮填下一动作、CAS或正确回读。
模型依据公开版本、回执和轨迹编码动作；身份仅由 Host 绑定。

逐链验收：原始 intent → action encoding → 完整验证 → 合法 dispatch → CAS/幂等 → receipt → 独立 World readback → 合法 finish。
目标、全部值、顺序、版本演进、操作记录及世界效果全部一致，无重复副作用、隐藏纠正或未知提交，24/24才通过。
计划每链≤300秒、P4阶段≤7200秒、每HTTP≤60秒、并发1。计划内无主动新故障；恢复另在D1测试。
未知提交先冻结写入，仅经公开 operation/status 查证，不能依据当前 head 猜测“未成功”后重写。
结果只证明已知意图可执行，不证明自然任务能力或 Memory 效果。

## 7. Gate D：先证明无旧 Note 时能自然做对

### D0 — 明确移除 Oracle，并核对 E0 的公共依赖

移除 evaluator 授权答案、gold next_action/正确值及参考输出；保留正常用户任务、合法资料、工具与授权范围。
checker 私有真值只用于离线评分，不能作为 Runtime 业务路由或重试提示。
合法但业务上错误的动作应在隔离世界中形成可评分错误，不能被隐藏答案门替模型纠正。

在耗费 B–D 大批模型预算前，可以只读核对 E0 所需公共能力是否存在；不要与 A 计时并发运行新负载。
现有 save/read/status 有文档，但**同源Note与各臂新写入的隔离组合尚未准入**；历史0.1.15文档不替代当前执行 pin。
只读存在性审阅不是 E0 PASS。新增工具/Schema/Provider、复制或连接绑定需要独立的有界机械与兼容校准，增量预算单列。

### D1 — 可恢复错误校准

每个候选根两事件 × 两冷遍，最多4根/16链，每链≤5生成，总上界80。

1. CAS变化但业务前提未变：真实拒绝且无副作用 → 公开读取当前版本 → 合法提交/回读。
2. CAS与适用条件一起变化：不能只递增版本；应依据新证据改动作、撤回或保持未决/澄清。

预期错误未实际触发记 `NOT_EXERCISED`；错误后至多三次生成用于必要恢复，其余用于合法收尾。
每根四链均正确恢复或按任务真值正确停止，才具备该根D1证据；已知初始意图的恢复校准不充当D2。
未知提交、权限或用量异常不是“预期CAS负控”，仍按系统性失败停止。

### D2 — root × world 的自然能力覆盖

两政策均无继承 A Note：N0-exec普通任务；R0-exec同调用普通复核。相同当前事实、模型、来源、工具和资源。
冻结公共预取或自主读取方式，证明所需当前证据实际呈现，不把 acquisition 漏洞算作记忆问题。

使用既有[D2覆盖表](MILA_V0224_D2_WORLD_COVERAGE_20260913.csv)，只维护：
`root × Stable/Changed × policy × cold repeat × world/version × existing terminal evidence`。
现表32行是潜在需求，非已运行、非32次分配；当前世界绑定和证书需逐行完成。

- E会使用的每个世界，均须两政策各两次独立冷运行正确，且无未恢复协议/身份/提交问题；D1证据也须适用。
- m根双世界完整需求为 `m×2×2×2=8m episodes`，每个≤16生成，即最多128m生成。
- 两根双世界=16 episodes/256生成；四根双世界=32/512。原四根单世界16/256不能不加说明覆盖双世界。
- 已有证据只有在任务、世界、事件、呈现、策略、checker和执行版本等价时可复用；同一轨迹不能冒充两次冷运行。
- 只分配缺失的最小位置；不默认原16个已覆盖，也不默认必然追加16个。覆盖和增量在首个自然A前冻结。

至少2 roots / 2 families具备拟用世界的稳定局部能力，才形成 `G_TASK_READY`；每个E根须自己合格。
当前已开放目录是4根、family分布2+1+1，不是2+2，也不是D证书；不为凑数量改名、造新接口或打开C。
D失败按取得/呈现/解释/意图/编码/执行/真值分层。相同未恢复协议错误连续两次收口该episode，错误签名预先冻结，不耗尽16轮才承认无进展。

## 8. Gate E：第一批可解释的普通 Note 消费比较

### E0 — 公共冷读、隔离与实际呈现

首轮是 **controlled consumption**，不是自主召回或 Memory Store 比赛。
受信 Host 根据公开提交ID/version和正常来源绑定取得自然Note，不用gold挑证据，不复制旧assistant轨迹或隐藏缓存。
公开读回正文与引用的各分页后，绑定组装请求、实际wire、响应与内容hash；“API返回过”不等于“模型看到了”。

N1/R1必须使用同一自然A内容与版本，各臂世界和新增写入隔离；N0正常历史可查，但不能读到处理用A Note。
优先同一原commit只读、新写入另scope；如仅公开派生副本可行，先审定estimand并标 `DERIVED_NOTE_COPY`，记录原commit→副本与正文/metadata等价，不冒称同一原ID。
不能通过tags/filter冒充授权隔离、删除引用绕权限或调用私有数据库clone。当前撤销/删除/来源权限优先于历史版本pin。
组合不成立则E0未通过；不要等B–D耗尽后才发现公共原语无法组合。

### E1 — 在首个自然 A 输出前选择唯一矩阵

| 模式 | 前置条件 | 冷恢复B矩阵 | 结论边界 |
| --- | --- | --- | --- |
| `PAIR_REPEAT`（优先可行路线） | 至少2根/2family的实际D资格；可冻结最多4个D合格候选 | 2根×2世界×3臂×2冷遍=24 | 独立lineage仅2，可看同根重复 |
| `FOUR_ROOT_DIVERSITY`（有条件选择） | 已有4个实际D合格根、两family各2根，无需扩建任务/接口 | 4根×2世界×3臂×1遍=24 | 独立lineage4，无同根重复 |

模式、候选全集/顺序、family约束、世界版本、波次与停止规则均在A输出前冻结。
选择只能依据此前D资格、资源和隔离可行性，不能依据Note质量、N1输赢或R1效果。
四根不足时不能A后改成两根模式追认完成；下载过但未审阅的任务也不自动成为可用确认池。

### E2 — 自然 A 与机会失败

每根至多一个A会话，≤16生成；A从正常任务和证据形成经验，自主决定是否保存普通自由Note。
允许统一收尾提示，不指定结论、认知字段或未来变化。A的业务成功、Note写入和提交分别验收。
evaluator离线核对相关命题在t0的依据与确定程度；真实未决记录不等于其猜想已被证实。

PAIR模式按冻结队列接纳首个合格根及首个不同family合格根，最多4A，所有机会选择在B开始前结束。
这是既定候选顺序的资格接纳，不是事后扩池；FOUR_ROOT模式固定四根，无补根。
不重生成、不手工修Note、不删除错误句后当作自然产物；相关命题t0已错或混错影响不可分者不进入“曾正确记忆”分母。

| 事件 | 停止与继续规则 |
| --- | --- |
| NO_WRITE、相关命题t0错误/无法裁定 | 该根曾正确Note比较不运行；可继续其他预定根，PAIR仅按原队列递进 |
| 可证明只影响一根的读取/来源资格失败 | 该根相关位置NOT_RUN；其他隔离根可按冻结规则继续 |
| scope污染、用量未知、共享执行/证据合同失守 | 停受影响批；范围不明时停当前波，不能继续累积效果分数 |
| B普通业务失败但输入、执行和真值链有效 | 保留配对及结果；不因N0答错、N1无旧方向错误而删题 |

部分合格根可以按预授权规则形成局部比较，但报告 `PARTIAL_MATRIX / MEMORY_OPPORTUNITY_INSUFFICIENT`，
不能冒充完成全部24B或Gate E。NO_WRITE与无双呈现不是“固着率0%”，分母为0时记N/A。

### E3 — 固定三臂、两个世界与公平呈现

| 臂 | 唯一预定义处理 |
| --- | --- |
| N0 | 不提供A Note；相同当前任务、证据、A业务历史和合法来源仍可访问 |
| N1 | 公开冷读并实际呈现固定A Note，使用普通执行政策 |
| R1 | 同一Note与当前证据，增加领域无关普通review；默认在同一次正常决策调用内完成 |

冻结共同任务、证据、工具的区块hash、角色、相对顺序及Note/review槽；不顺带给R1更强角色、重排资料或缩短干扰内容。
新增文字的长度/绝对位置变化照实记录；识别的是“提供Note/复核政策”的整体效应，不把每个新增错误直接命名为惯性。
R1不强制第二Agent或额外生成，不透露对象答案，不规定新证据总是正确或旧记忆一律丢弃。

Stable中旧信息仍适用；Changed中t0原本合理的内容被外生变化取代或暂不适用，当前公开证据足够支持正确动作/澄清。
两世界都有可靠、允许多解的世界postcondition；不能问了澄清却保留错误confirmed或继续提交。
Helpful、等长无关Note、A→B→A、额外Recovery不临时插入首轮；有需要另冻增量。

PAIR首波12B有效后，无论谁赢谁输，按预冻结平衡/反序完整冷复验12B，共用同一A，不只重复阳性。
FOUR_ROOT可预冻两波、每波两family各一根的12B；局部机会失败不自动阻断其他预定根，系统性失败则停止。
每B≤16生成；24B是会话上界，不是24次模型请求。

### E4 — 有效分母、指标与结论

全链逐项可追溯：

```text
t0真实经验 → 自写Note → 提交/版本 → 新Host公开冷读
→ Note实际呈现 + 当前证据实际呈现
→ 自主意图 → 合法编码 → 世界效果 → 独立真值
```

公布候选/D资格/A尝试/自选写入/提交/t0资格/冷读/双呈现/各臂分配与未运行/有效配对/全部业务结果。
资格不按当次N0成败或N1是否旧方向错误重选；条件切片可附报，但不替代全配对与全尝试。
旧Note双呈现不等于受到注意，更不等于影响了行为；只结合可观察动作方向和对照解释，不索取隐藏推理。

主指标分别报告：首次相关行动、完整世界成功、旧方向错误、重复工作、Stable无谓推翻、Changed修正速度、成本。
条件重激活是适用条件A→B→A，可全程不犯错；错误Recovery必须先有错误偏离及合法纠正机会，二者分母独立。
首轮Stable/Changed不声称验证重激活、完整Memory生命周期或总体因果效应。

| 观察 | 有界结论 |
| --- | --- |
| N0/N1/R1都正确或相近 | 本范围普通方案足够/未见差异；不强造新机制 |
| N0正确，N1重复旧方向错误，R1正确 | 局部可纠正Note消费信号；普通review优先，不证明复杂State必要 |
| N1帮助连续性且不损害适应 | 普通Note局部价值；保持简单 |
| 各臂共错，或执行/真值链失效 | 回到最早可证实失败层，不直接归因Memory |
| 跨独立根反复出现，强简单政策仍不足 | 允许提出机制候选，不等于机制已经确认 |

## 9. 完整资源账与停止边界

所有以下数字是规划包络，**当前新增执行/模型/HTTP/C allocation仍为0**；不是余额、已消费或必须耗尽的次数。

| 阶段 | 模型生成计划上界 | 时限/说明 |
| --- | ---: | --- |
| A | 0 | 按§4冻结；校准、准备、审计、K3与工程成本全部单列 |
| B | 16 | P3 1800秒；每HTTP≤60秒；并发1 |
| C | 96 | 24链×≤4；每链300秒、P4 7200秒 |
| D1 | ≤80 | ≤4根×2事件×2遍×5；建议每链≤300秒，具体阶段需冻结 |
| D2 | ≤128m | m根双世界；2根256、4根512；按覆盖表只执行未覆盖位置 |
| E自然A | ≤64 | 最多4根×16；只有两候选时下调，不能虚增机会 |
| E冷恢复B | ≤384 | 最多24会话×16；两种模式不能相加 |
| 新Note校准/诊断/外部基线/机制/Judge | 0新增 | 必须单列差异、次数、时限与范围，不能藏入已有包络 |

既有16-episode D2包络下总上界为 `16+96+80+256+448=896`；
若确需四根完整双世界D2，则为 `16+96+80+512+448=1152`。
原D2数量不证明世界覆盖；实际新分配由所选候选全集、已有有效证据与最小增量重算，不默认两个包络都要跑满。
E前B–D分别占448或704生成；不能把这条路线描述成只花“24次请求”。

D2/E建议episode≤900秒，但阶段时限、辅助HTTP/tokenize/identity次数、输出预约、模型配置和到期必须在实际合同中补齐；
未补齐即NOT_ADMITTED。建议期限不延长旧60/300秒参考合同，新增HTTP参数检查也不是免费模型机会。
同一未恢复协议错误、未知用量、授权或证据失败遵循冻结停止策略；普通业务错误在E有效比较中是结果，不自动全批停。

两种成本账分开：

- **实际实验账单**：每个A/B/失败/准备/审计/工具事件按唯一ID记一次；共享A不因臂或世界分叉重复收费。
- **策略生命周期账**：经验获取、写入、维护、读取、复核、行动分别归属；注明实际/假定复用次数k及摊销敏感性。N0是不给该Note的消费对照，不是独立跑过完整无记忆生命周期；反事实未测成本记UNMEASURED而非0。

模型输入/输出/raw、辅助HTTP、CPU/IO/墙钟、服务生命周期与代理平台用量分账；失败和未知保留。
累计raw不限不等于运行无界；历史未知预留不是实际消费，新未知立即停该批发送，不自动重试或擅自清债。

## 10. 开发灵活性：允许反思修订，不允许结果追认

探索固定证据边界、不预选认知策略；正式准入与确认冻结策略、矩阵、判据和预算。
停止一次实验实例不等于整个方向失败；局部可修复失败应先缩到最小问题，不默认回到A重做全部历史。

每次非预期失败或完成有界wave，记录一个紧凑决定：
`Observation → earliest proven layer → alternative explanations → smallest discriminating check → delta → invalidation → next bound`。
连续两轮未增加可区分证据，触发设计复审、简化或暂停，不无限增设adapter、不无限重抽模型。

| 改动 | 最小重验范围 |
| --- | --- |
| 文档/导航 | 链接、矩阵算术、状态与旧hash；不修改已冻结执行凭据 |
| admission、计量、历史账、父子编排 | A受影响保证/计量/生命周期；若破坏下游绑定则B–E失效 |
| 模型/wire/presentation/动作Schema、权限/CAS/receipt | 相应A负载/语义、B/C及受影响D/E |
| 自然任务/来源/review/checker | 新任务与暴露记录、D/E；影响编码/容量时回B/C |
| Note公共接口/pin/冷隔离 | E0及新增工具校准；共用执行栈变化再回溯C/D |
| Memory候选策略 | 新探索臂、同信息强简单对照；未受影响A–D可有据复用 |

同一有效授权内的一般实现修复可留痕继续；新期限、服务、预算、authority保证、保护池或产品范围必须明确新合同/方向。
改变旧判据不得静默更正为PASS；保留旧raw、说明修正和敏感性分析，另开新实例。
有未覆盖依赖变化时标 `STALE_FOR_CURRENT_REVISION`；复用要说明适用性，不能只引用旧测试总数。

## 11. 创新保持开放，但晚于有效性

长期对象仍是 **Host-owned、可错、可修正的认知状态如何调节长期记忆的行为影响**。
人类记忆/ADHD执行支持仅为功能启发，不作临床外推，不模拟分心；Runtime不做隐藏语义推理。

association regulation、conditional reactivation、stability–plasticity、memory–world consistency、meta-memory
都是候选维度，不是必须实现的模块或固定优先级。允许在已打开discovery上组合、拆解、放弃或新增假设。
有用的bundle先标bundle信号，之后做消融；不把多改几个字段当作已验证机制。

研究门分开：

1. **发现Memory-use现象**：有效对照与旧方向行为反复出现；R1能修复不使现象消失。
2. **证明额外机制必要/值得**：强简单review或相关公开使用政策仍不足，或实际生命周期成本有可重复改善；不能给R1人为增加额外Agent制造成本优势。

后继外部策略优先参考[公开基线审计](MILA_V0224_PUBLIC_BASELINE_AUDIT_20260913.md)与[制品摘要清单](MILA_V0224_PUBLIC_BASELINE_SOURCE_AUDIT_20260913.json)。
AdaptiveMem只是待验使用政策对照；CUPMem/TEPA等用于近邻差异核查，不因论文/代码存在就授予本地效果准入。
届时重新核验许可、版本、实际prompt与输入公平性；本版不新增查新结论，不同时接入多个Memory Store。

候选必须面对同信息普通Note/review消融，兼顾Changed、Stable、后续条件重激活与错误Recovery的不同真值。
选择同时看行为收益、跨任务重复、简单性、新颖性、完整成本与失败安全；普通方案打平就KEEP_SIMPLE。
独立确认需另冻未打开lineage、模型、强基线、最小有用收益、指标和资源；当前reserve不等于合格C，本版不消费确认额度。

## 12. 交付、状态与下一单步

每门只复用现有五类资产：冻结合同；原始轨迹/低开销计时；逐位置结果/分母/成本；反思差异；简短执行状态/综合报告。
不创建新的业务State schema或第六层审计框架。最新执行状态应同时列证据时间、当前revision、已通过/待验/停止门、下一步与分配，不能把PLANNED视为实时状态。

实现变更后的正式工程验收仍按仓库规定：

```bash
uv run milai-lab-check-boundary
uv run pytest
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

记录实际源码绑定、start/log/exit；本机协议工程测试另按已审定范围隔离和计数，不污染A的零HTTP声明，不与正式计时争抢资源。
文档检查或本轮工程终态都不能代替R04/K3的有效证书；历史全回归数字不转填为本版Gate成绩。
本版交付检查另见[文档校验与工程检查终态](MILA_V0224_GOAL_V03_DOCUMENT_CHECK_20260913.md)；其中Ruff有一项报警，全仓pytest主动中断，不宣称工程全绿。

| 最终/中间状态 | 含义 |
| --- | --- |
| `R04_LOCAL_CALIBRATION_HEADROOM_MET` | 当前已测七次路径有余量；独立收口、长路径与全门仍待验 |
| `GATE_A_PASS_UNDER_R03_R04` | 当前声明保证下完整离线准入通过；不直接授权HTTP |
| `GATE_B_PASS / GATE_C_PASS / G_TASK_READY` | 各自范围准入；均非Memory研究完成 |
| `MEMORY_OPPORTUNITY_INSUFFICIENT / PARTIAL_MATRIX` | 可以有局部证据，但预定完整比较尚未完成 |
| `E_VALID_COMPARISON_COMPLETE` | 已选矩阵及其应触发冷复验完成，链/分母/成本可复算，允许无差异 |
| `COMPLETE_WITH_BOUNDED_RESEARCH_CONCLUSION` | 有效A–E证书及E结论/反思全部交付，本合同无必做剩余工作 |
| `REVISION_REQUIRED / BLOCKED_UNFINISHED` | 需修订、补边界或明确新方向；报告完成不等于主目标完成 |

**下一单步：对既有R04六位置校准做独立完整结果收口；不重跑、不扩缓存、不启动模型。**
之后依次：既定九次长路径 → 完整K3/当前工程/余量 → 新P3 → P4 → D世界覆盖 → E0隔离与A前矩阵冻结 → 自然A及N0/N1/R1。
如独立终态在本版之后更新，执行状态按新证据前移，不改写本版的历史快照，不把更新文档当作新增执行授权。
