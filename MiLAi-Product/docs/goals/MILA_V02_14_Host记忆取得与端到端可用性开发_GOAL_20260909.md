---
document_id: MILA-V02-14
version: "0.3"
date: "2026-09-09"
updated_date: "2026-09-10"
status: COMPLETED_LOCAL_OPT_IN_CLIENT_HELPER_DELIVERED
document_update_scope: STATUS_BOUNDARIES_AND_ACCOUNTING_ONLY
document_update_new_experiment_requests: 0
document_update_new_experiment_raw_tokens: 0
execution_scope: LOCAL_D0_D7_NO_PUBLIC_DEPLOYMENT
execution_authority: USER_EXPLICIT_FULL_GOAL_EXECUTION_AND_UNCAPPED_CUMULATIVE_TOKENS
execution_model_requests: 133
execution_raw_tokens: 877655
execution_cumulative_raw_limit: null
execution_accounting_scope: V0214_EXPERIMENT_PROVIDER_ONLY_ALL_SEVEN_ALLOCATIONS
execution_report: ../../../MiLAi-Lab/studies/active/MILA_V0214_HOST_RESULTS_20260909.md
candidate_client_version: "0.1.4"
candidate_client_scope: LOCAL_UNRELEASED_OPT_IN_MECHANICAL_HELPER
candidate_client_published: false
candidate_client_deployed: false
default_policy_changed: false
client_helper_runbook: ../runbooks/host-source-acquisition.md
predecessor: MILA-V02-13-v0.2
predecessor_status: HOST_COLD_RECHECK_VERIFIED_KEEP_A0
priority: PRODUCT_USABILITY_BOUNDED_SOURCE_ACQUISITION_AND_END_TO_END_RESUME
primary_goal: GENERIC_HOST_ACQUISITION_DELIVERY_AND_COLD_RESUME
secondary_goal: EFFICIENT_SELECTIVE_ACQUISITION_AFTER_CORRECTNESS
research_state: KEEP_A0_NO_NEW_MEMORY_MECHANISM
baseline_mcp_version: "0.1.15"
baseline_client_version: "0.1.3"
baseline_runtime_version: "0.1.4"
baseline_version_scope: FROZEN_EXPERIMENT_PIN_NOT_LATEST_PUBLIC_DEPLOYMENT
recorded_public_pin_date: "2026-09-09"
recorded_public_mcp_version: "0.1.15"
recorded_public_client_version: "0.1.3"
recorded_public_runtime_version: "0.1.5"
baseline_catalog: compact-memory-v1
baseline_registered_tools: 8
baseline_policy: A0
host_candidate_origin: V0213_H1_V2
host_candidate_status: INDEPENDENT_SYNTHETIC_CONFIRMATION_PASS_OPT_IN_CLIENT_ONLY
context_projection_enabled: false
state_mechanism_enabled: false
structured_binding_enabled: false
automatic_maintenance_enabled: false
new_memory_backend_authorized: false
new_product_schema_authorized: false
public_deployment_authorized_by_this_document: false
public_business_mutations_authorized_by_this_document: false
external_business_action_execution_authorized: false
model_transport_enabled: false
new_local_model_requests_authorized: 0
new_paid_model_requests_authorized: 0
new_judge_model_requests_authorized: 0
new_raw_tokens_authorized: 0
protected_horizon_confirmation_clusters: 55
protected_horizon_confirmation_queries: 712
protected_mem2act_clusters_opening_authorized: false
schema_status: 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE
---

# MiLAi V02-14：Host 记忆取得、可靠交付与端到端可用性开发 Goal

## 当前收口：本地可选 Client 集成完成（2026-09-10 对齐）

**D0–D7 已在授权本地范围完成；保留 A0 默认和 Schema NO-GO。Client 0.1.4 仅为未发布、未部署的可选机械 helper。**
本次 v0.3 只更新状态、验证边界、成本分账及索引，不重新执行实验或改写已封存的准入、模型输入与结果。
完整证据见[实验报告](../../../MiLAi-Lab/studies/active/MILA_V0214_HOST_RESULTS_20260909.md)，
接入和回退见[使用说明](../runbooks/host-source-acquisition.md)。

下方 2026-09-09 注记及 §0–§15 按历史原样保留；其中“当前只制定规划”“待实现”等不再表示当前执行状态。
顶层 `execution_*` 是已执行范围和实际消耗；`model_transport_enabled: false` 与新增授权为 0
表示当前没有新运行分配，不否认此前执行，也不恢复已取消的累计 raw-token 硬上限。
继续遵循**功能实现优先、token 最后优化**；实际模型上下文、输出预约、调用/并发与时限边界仍分别有效。

### A. 验收结论及正确分母

| 范围 | 已取得证据 | 结论限制 |
| --- | --- | --- |
| D0–D4 工程 | 作用域/版本、分页覆盖、资格复核、取得/呈现分账、并发与最终交付预约；D0 实际 517 次公开调用 | 旧预算回放不证明答案改善；不把 Host 排队控制当服务端饱和拒绝或 SQL 并行证明 |
| D5 开发回归 | H 最终 16/16 阶段通过：15 次正确交付、1 次正确澄清；覆盖保存、冷恢复、新观察与并发 | 16 个阶段来自 8 条开发 lineage，不是 16 个独立新任务；全部失败迭代保留 |
| D6 合成确认 | 四个独立合成 clusters 全部保留：H 任务成功 4/4，A0 1/4 | H 包含 1 次正确澄清；可评分调用参数分别 H 3/3、A0 1/1，不把弃答或格式失败记成参数错误 |
| D6 长历史 LX | 两题均正确；H/LX 的已声明支持实际呈现 6/6，A0 0/6 | 固定 lexical＋普通原文读取的本地诊断，不是线上 BGE/Product retrieval 或外部泛化证明 |
| D7 Client 集成 | 本地 Client 0.1.4 可选模块、兼容测试和构建通过 | 仅交付机械 helper；没有发布、改变默认流程或完成新 wheel 在真实外部 Host 的行为验收 |

D5 的“尚未读取就澄清”“文字澄清却提交业务调用”“重复业务调用”失败及 v2/v3 未通过记录全部保留。
v4 使用公开 readiness assessment 先于交付，并检查 assessment/action、请求操作数量的一致性；
模型仍决定是否缺输入，Host 不从 gold、默认值或 provenance 猜业务参数。
自洽但语义错误的 assessment 仍可能失败，不能把交付一致性校验解释成事实正确性保证。

D5 中一次明确请求的 Note 已通过公开接口保存，新进程无原文件、无操作者传递 saved ID，
经正常 Note inventory/read 恢复；其余阶段保持 NO_CHANGE。该成功不证明自动维护或普遍保存净收益。
冷启动指 Host/MCP 进程和任务作用域隔离，不指共享模型权重重载或清除推理缓存。

两条确认长历史约 0.86/0.95 MB，H 分别读取 4/3 个选中范围，保留 PARTIAL，无需读到全文 EOF。
这是固定合成任务上的支持覆盖证据；选中范围到 EOF 不代表完整历史已覆盖，命中字符串也不自动等于语义蕴含。
业务输出仍为 `ACTION_INTENT_ONLY`，没有执行真实业务服务。

### B. 已进入 Client 与仍在 Host 的能力

[Client 模块](../../integrations/python-client/src/milai_client/host_acquisition.py)
通过显式 `milai_client.host_acquisition` 导入，使用调用者提供的可信 `SourceBackend`；
不新增包根默认导出、模型调用、Note 自动摄取、默认 Agent-loop 接线或运行时依赖。

| 能力 | 当前归属 |
| --- | --- |
| Binding、SourceRef/SourcePage、Coverage、Acquisition；资格/版本/请求关联校验、有界读并发及分页 | Client 0.1.4 的 opt-in 机械 helper |
| 是否需要历史、lexical 排名、查什么、readiness/澄清提示与 typed-delivery 策略 | Lab/Host，未整体迁入 Client 或 Runtime |
| 模型额度、最终交付预约、未知 usage 保留与停发、传输回执确认 | 周边 Host/transport；helper 不隐式接管模型预算 |
| 权限、CAS、撤销、Canonical、Note/Working State 持久化 | 既有 Product 公开合同，未改变语义或数据结构 |

`presentation()` 负责发送前资格复核，不标记已经发送；`record_presentation()` 记录 Host 确认实际传输后的回执，
并校验所呈现页与取得内容一致。仅构建 payload、选择片段或排入队列不能当作 presented；
可信身份与 source eligibility 必须来自认证绑定和合法适配器，不能由模型自报。
已发送内容不能撤回，后续发送需重新检查，不能从其他未复核 transcript 通道带回旧正文。

### C. 实验版本、候选版本与公网版本分开

| 口径 | 版本/状态 |
| --- | --- |
| D5/D6 冻结实验 pin | MCP 0.1.15 / Client 0.1.3 / Runtime 0.1.4，隔离 hash backend |
| D7 本地候选 | Client 0.1.4 机械 helper，未发布、未部署；不替换 A0 |
| 报告于 2026-09-09 核实的公网安装快照 | MCP 0.1.15 / Client 0.1.3 / Runtime 0.1.5；本次文档更新未重新探测公网 |

D5/D6 的模型效果属于冻结实验与 Lab H 策略，不能把它们当作新 Client 0.1.4 全链路或线上 Runtime 0.1.5/BGE 的验收。
新 Client 已通过其机械接口与包兼容检查；后续真实 opt-in Host 接线仍需独立验证。
本候选不改 HTTP/MCP 工具、Runtime、API/权限/Canonical 或 State schema，无数据库迁移。
回退可取消显式 helper 接入并恢复原 Client 0.1.3 pin，不需要转换 Notes/State 数据。

### D. 完整成本与功能优先决策

| 本 Goal 实验阶段 | 生成请求 | raw tokens |
| --- | ---: | ---: |
| D5 六批，含全部失败、smoke 与完整回归 | 119 | 770,002 |
| D6 一批，A0/H/LX | 14 | 107,653 |
| V02-14 七批合计 | **133** | **877,655** |

D6 内部为 A0 34,520、H 54,991、LX 18,142 raw；这些已包含在总额，不能再次相加。
H/A0 为 **1.5930×**，各任务延迟也增加但满足冻结的工程容忍；这是正确性取舍，不是成本或延迟优势。
D0 的 517 次公开调用与 D5/D6 的 448 次公开调用单列，不冒充 965 次模型生成；
V02-13 及更早消费不并入本 Goal。所有实验 usage 已结清，unknown/violation 为零。

用户提供的 Goal 追踪器累计 **1,373,706 tokens、约 1 小时 40 分钟**单独保留为代理统计，
不与 Provider 的 877,655 raw 合并，也不当作产品单次成本或本次文档更新的用量。
审查劳动、货币、GPU、全量网络/磁盘等未完整计量的项目仍为未知，不填成零。
累计 raw cap 继续为 null；没有因收口或文档整理重新启用 20k、80k 等旧额度。

### E. 验证、收尾与未验证事项

已报告检查：Lab **748 passed**；Client **209 passed**（19 个新 helper tests）；
MCP **385 passed / 7 optional skips**；hooks 52、OpenWorker 176、LangGraph 5、AutoGen 6 passed。
相应静态检查、边界检查和构建通过；这是执行报告的验收，不是本次文档更新重跑的测试。
七项 MCP 跳过不等于新 wheel 的真实 PG 验证；D0 的 PG/CAS/撤销证据仍属于旧冻结 pin。

本地 helper 性能在预注册工程容忍内，但 8 KiB 串行读 P95 为 0.443→2.407 ms（5.43×），不能写成性能提升。
服务端饱和拒绝、SQL 级并行、大租户容量、远程/对抗性 source adapter、冷缓存规模、外部任务泛化、
新 Client 真实 Host 接入及线上 BGE 效果仍未验证。四个合成确认场景不支持默认策略切换或统计显著性主张。

自有 API/PG 按报告全部停止，卷、失败和原始证据保留；共享模型及公网服务未由本 Goal 重启。
本 Goal 的四个新合成确认场景已运行；旧 Horizon 55 个保护分组/712 题、16 道未跑题及 Mem2Act 保护池仍不动，
不能将两类确认池混称全部未打开。没有新增 State、attention、Hint、绑定机制或自动维护。
后续发布/部署、真实 opt-in 接入或外部确认需独立明确范围；本次更新不授予新运行或变更 A0 默认的权限。
这些未验证事项是后续范围，不回写为本次成功，也不把已完成 D0–D7 重新标成待执行。

## 历史执行注记与原规划

以下执行注记及 §0–§15 保留原文；“当前”“下一阶段”“待实现”等均按当时语境读取，当前结论以上文为准。

> **2026-09-09 执行收尾**：用户后续明确授权完整执行并取消累计 token 上限；D0–D7
> 已在本地授权范围完成。最终开发 H16/16 阶段通过，独立合成确认 H4/4、A0 1/4，
> 长历史 LX2/2。含全部失败迭代共 133 请求 / 877,655 raw tokens，未知用量零。
> 已交付本地 Client0.1.4 显式 opt-in 机械 helper；未发布、部署或改变 A0 默认。
> 完整结果与 10 项回答见 `MiLAi-Lab/studies/active/MILA_V0214_HOST_RESULTS_20260909.md`，
> 使用与回退见 `docs/runbooks/host-source-acquisition.md`。下文保留原规划及默认关门条件；
> 顶部模型默认关闭/初始额度 0 不代表已完成授权分配的实际用量，也不授权新的自动实验。
> 实验 pin 为 Runtime0.1.4；只读核实的线上 Runtime 已为0.1.5，未声称验证线上 BGE 效果。
> Schema 继续 `NO-GO FOR SCHEMA FREEZE`。

## 0. 决策摘要

**下一阶段不继续增加 State、attention、Hint、绑定字段或新的 Memory backend。**
V02-13 已经提供了更直接的开发信号：在原两题、两轮真正冷 Host 中，H1 v2 的
“完整公开分页取源 + typed delivery”得到 4/4 完整调用意图正确；但该结果来自两个重复任务，
而且所有历史都能在有限页数和模型上下文内完整取得，因此不能直接作为 Product 默认策略。

本 Goal 将该 Lab 候选抽象为一个**通用 Host-side memory acquisition and delivery capability**，
优先完成真实可用性：

```text
可信任务绑定
→ 识别可用来源与当前输入是否足够
→ 必要时通过公开来源接口取得材料
→ 明确 COMPLETE / PARTIAL / WITHHELD / UNKNOWN
→ 缺少业务输入时澄清，不猜值
→ 满足业务输出/工具调用合同后交付
→ 有延续价值时按既有公开 Memory 能力保存
→ 进程结束
→ 新进程恢复并继续
```

首版首先保证**正确、可追踪、可恢复和多任务并发**；随后才优化“是不是每次都要读到 EOF”。
完整读源是正确性参考和回归能力，不是产品永久默认。

本 Goal 是开发与验收合同。当前只制定规划，**不自动执行代码修改、模型调用、数据集解封、
公网部署、真实业务动作或 Schema 变更**。新的模型额度和实际运行范围均需后续明确授权。

---

## 1. 当前依据、接受结论与不扩大主张

### 1.1 从 V02-13 接受的当前事实

当前基线继续为 MCP 0.1.15 / Client 0.1.3 / Runtime 0.1.4 / compact 8 tools / A0。
V02-13 当前终态为 `HOST_COLD_RECHECK_VERIFIED_KEEP_A0`，累计实验模型 46 次、421,485 raw tokens；
Product、Schema、权限与 Canonical 未改变。

接受以下边界：

| 已有证据 | 本 Goal 的使用方式 | 不能据此声称 |
| --- | --- | --- |
| H1 v2 原两题 × 两轮，4/4 完整调用意图正确 | 作为正确性回归种子和 Host 候选来源 | 已跨独立任务泛化；H1 应成为默认产品策略 |
| H1 通过普通公开 source_read、固定顺序分页，7/8 页读到完整原文 | 证明公开来源路径可支撑完整获取 | 所有任务都应该读到 EOF；已经证明选择性检索最优 |
| H1 delivery 使用已知业务工具定义，要求必填参数和正确类型 | 抽象为通用 typed-delivery gate | 工具选择已验证；业务动作真实执行成功 |
| A0 在同轮冷对照中完整交付 2/4，可评分参数 2/2 正确 | 保留 A0 为默认与对照 | A0 失败率稳定；H1 单项改动有独立因果收益 |
| H1 v1 3/4，v2 才 4/4 | 保留失败和修订轨迹 | 可以删除 v1 或把 v2 视为第一次就成功 |
| 685 tests/gates 为 Host 阶段已有结果 | 后续开发以此为历史回归基线 | 本 Goal 已重跑或当前安装包天然包含未来修改 |

### 1.2 当前真正未完成的产品问题

V02-13 已明确留下以下问题，本 Goal 以其为开发范围：

1. **长历史超过页数或模型 context 时如何取得**，不能永久使用“全读到 EOF”。
2. **任务缺少必要输入或主体身份歧义时如何澄清**，不能用 Memory 猜出业务 ID。
3. **选择性检索和完整读源怎样组合**，需先保证正确性再降本。
4. **Host 多轮工具取得怎样保留最终交付预算**，避免有调用次数却无法完成最终请求。
5. **独立任务和不同历史长度下是否仍可正确使用来源**，原两题不能承担泛化证明。
6. **Product-backed memory/search 是否有实际净价值**，当前 H1 主要使用普通 source path。
7. **冷恢复后的 Host 使用能力如何产品化接入**，当前仍是 Lab 候选。
8. **多用户/多任务并发与作用域隔离**不能因 Host 取得逻辑增加全局串行瓶颈。

### 1.3 明确不进入本 Goal 的问题

本 Goal 不自动恢复以下研究线：

- Control State / S1 / S2；
- target / trigger / closure_basis 结构化绑定；
- context projection / pruning；
- ASSOCIATE / PARK / RESUME / CONVERGE 提示策略；
- automatic memory maintenance；
- Hint/path learning；
- graph memory；
- embedding/dense retrieval 平台扩建；
- hidden Reader / Reviewer / Judge；
- 新 Memory database 或 Schema freeze。

只有在独立任务中反复出现“充分支持已呈现仍然错误使用”的明确 failure，才另立研究 Goal；
不能由本 Goal 的普通 acquisition/clarification failure 反向推导 State 机制必要。

---

## 2. 产品目标与成功定义

### 2.1 首版用户可用路径

对一个明确支持的 Host/客户端组合，必须能够完成：

```text
用户/任务开始
→ 可信 principal / project / task 绑定
→ Host 得到当前任务和普通初始材料
→ 判断是否需要历史来源
→ 有界取得或直接读取合法来源
→ 必要输入齐全：形成 typed answer / action intent
  或
  必要输入仍缺：明确澄清 / 不足，不猜值
→ 正常产物完成
→ 可选保存有延续价值的 Memory
→ 结束 Host 进程与临时上下文
→ 新进程恢复合法 Memory / 来源入口
→ 正确继续下一步
```

用户不应被要求：

- 重新粘贴全部旧历史；
- 手工填写 source ID / page cursor；
- 先知道应该使用哪个 Memory 工具；
- 在后台修正 Working State；
- 为了让 Agent 不超预算，手工提醒“现在请给最终答案”。

### 2.2 结果必须拆成三项

| 维度 | 最低通过条件 | 不代表 |
| --- | --- | --- |
| **Acquisition correctness** | 必要时能取得支持，或明确知道仍是 partial / unavailable | 已正确理解材料 |
| **Delivery correctness** | 必填字段、类型、业务合同完整；缺输入时不编造 | 真实外部动作已执行 |
| **Cold resume usability** | 新进程能从可信任务绑定和公开来源/记忆入口继续正确工作 | 自主保存策略、长期净收益已证明 |

正式 Product 默认策略的发布必须同时满足对应正确性、安全、并发与成本门；
Lab 单例成功不能直接改变 A0。

---

## 3. 架构边界：Host 负责语义，Runtime 保持机械正确

### 3.1 责任划分

| 层 | 负责 | 不负责 |
| --- | --- | --- |
| **Host** | 当前任务是否缺信息、查什么、何时澄清、如何使用材料、何时交付 | 权限、CAS、版本真实性、Canonical 治理 |
| **Host acquisition helper / adapter** | 公开来源调用、分页/游标、预算计量、结果关联、可观察 coverage | 判断业务事实真伪、生成隐藏摘要、猜正确参数 |
| **MiLA Runtime/MCP** | identity/scope、eligibility、版本、CAS、idempotency、公开 Memory/来源操作 | 第二套语义 Planner/Reader |
| **Canonical governance** | 正式长期状态与治理 | 当前任务临时工作判断 |

首版优先在 Host SDK/Lab 适配层实现；只有发现公开 Product 接口缺陷时才修改 Runtime/MCP。

### 3.2 不新增业务 Memory schema

允许 Host 继续使用自由 Markdown/JSON/现有 Working State。开发中可以使用机械记录结构，例如：

```text
AcquisitionCall
- request_id
- source_id / version
- cursor / offset
- bytes / tokens
- result_status
- coverage_status

DeliveryCheck
- required argument present?
- type valid?
- unresolved required input?
- final response emitted?
```

这些是执行与观测结构，不是用户业务 Memory Schema，也不能进入 Canonical 语义。

---

## 4. 核心开发能力

### 4.1 Source Inventory：先知道可查什么

Host 不应在每个任务中猜测“历史是否存在于 Product memory、普通文件或 Working State”。
首版建立一个可信的、机械的 source binding view：

```text
source_binding_manifest
- task scope
- source kind
- source identity / version
- eligibility
- readable entrypoint
- pagination / search capability
- approximate size if available
- Product store populated? yes/no/unknown
```

要求：

1. 只使用可信任务绑定和当前权限。
2. 明确区分 SOURCE_FILES、PRODUCT_NOTES、WORKING_STATE、EVIDENCE 等实际载体。
3. 空 Product store 的 MISS 不能覆盖普通文件历史的存在性。
4. manifest 不能包含 gold、future answer 或题目专用正确路径。
5. manifest 内容发生版本/资格变化时，以当前观察为准，不从旧缓存扩大披露。

### 4.2 Acquisition Modes：正确性优先的多级取得

首版允许四条简单路径，Host 可直接跳过中间层：

```text
EXACT_READ
→ 已知来源/路径/版本时直接读取

BOUNDED_SCAN
→ 来源较短或需确认完整覆盖时顺序分页

LEXICAL_SEARCH
→ 长历史下使用固定、可回放的词面检索取得候选

CONTINUE
→ 对同一来源/查询继续分页或扩大已知边界
```

默认原则：

- 已知精确来源不先跑 search；
- 历史能安全完整读取且成本合理时，完整读取是正确性基准；
- 长历史不允许永久依赖 EOF 全读；
- 词面检索首版不引入 embedding/LLM query rewrite；
- source search 失败不等于历史不存在；
- Host 能直接读 L3 原始来源，不要求 L1→L2→L3 顺序。

### 4.3 Coverage Contract：取得状态必须可解释

每次来源取得返回或在 Host 侧记录：

| 状态 | 含义 |
| --- | --- |
| `COMPLETE` | 按该来源/固定范围的机械定义已读到终点 |
| `PARTIAL` | 已获得一部分，存在明确未读范围或 cursor |
| `WITHHELD` | 来源存在但当前主体不可披露正文 |
| `UNAVAILABLE` | 当前接口/资源不可用；不等于内容不存在 |
| `UNKNOWN` | 无足够机械证据判断覆盖 |

关键要求：

- COMPLETE 只能由公开 cursor/EOF/可证明边界得到，不由模型自述“看完了”得到。
- 搜索 top-k 返回不能标 COMPLETE_HISTORY；最多是 QUERY_RESULT_COMPLETE / SOURCE_PARTIAL 等局部状态。
- 取得过 ≠ presented；必须另记录实际模型输入。
- 已进入旧上下文的内容不能通过后续资格变化自动“忘记”；下一次发送仍执行当前资格。

### 4.4 Task Readiness 与 Clarification

V02-13 已暴露主体身份歧义、业务 ID 缺失等 Oracle 不充分场景。
产品路径必须区分：

```text
READY
→ 当前任务和取得材料足以形成合法交付

NEEDS_SOURCE
→ 合法历史中可能补足，继续有界取得

NEEDS_CLARIFICATION
→ 当前来源仍无法唯一补足必要业务输入，向用户澄清

BLOCKED
→ 权限/协议/资源不允许继续
```

这是 Host 可见的执行决策，不是 Runtime 领域语义状态机。

禁止：

- 为通过 benchmark 补造 booking ID、主体身份、地址或 account value；
- 将 optional 参数缺失当 required；
- 将“有一个合理默认值”当作用户已经给出；
- 因 Memory 中出现旧值就忽略当前用户新输入。

### 4.5 Typed Delivery Gate

H1 v2 的 typed delivery 应抽象为通用交付合同：

1. 业务工具/输出 schema 来自当前任务合法接口，而非 evaluator gold。
2. 检查合法工具名、必填参数、参数类型和可判定的格式。
3. 必要值缺失时允许 clarification/abstain，不能填假值追求完整 JSON。
4. 结构合法与语义正确分别记录。
5. `ACTION_INTENT_ONLY` 与真实外部执行严格分开。
6. 多步任务分别记录首个业务动作意图、完整计划与最终交付。

### 4.6 Final Delivery Reserve

Host 在多轮 acquisition 中必须避免“还有请求次数但已经没有足够预算交付”。

设计一个**机械预算保留规则**，不恢复旧 20k 全局上限：

```text
remaining_budget
>=
next_step_upper_bound + final_delivery_reserve
```

其中 final_delivery_reserve 由当前 Host/模型/输出 schema 在运行开始时冻结，可配置而非硬编码。

规则：

- 非必要 acquisition 会侵蚀 final reserve 时，Host 必须在“交付当前受限结果 / 澄清 / 停止”之间选择；
- 必要工具结果若已取得但未送入模型，不能算 presented；
- reservation 只解决预算安全，不判断该继续查还是答；
- 未知 usage 保留预约，不通过重启/换目录清零；
- 本地模型资源成本与 raw token 账本分开。

### 4.7 Cold Resume

冷恢复定义为：

- 原 Host/客户端进程结束；
- 新 Host/MCP 会话；
- 可信 principal/project/task 重新绑定；
- 临时 messages、未授权日志、另一 arm 产物不继承；
- 允许共享模型权重和底层推理缓存，但必须明确不称“模型冷加载”。

恢复后 Host 应能取得：

- 当前允许的 Working State（如存在）；
- source binding / 正常来源入口；
- 与当前任务相关的公开 Memory；
- warning / withheld / stale 状态。

不要求所有任务自动生成新 Working State；不存在 State 时正常来源路径仍可工作。

---

## 5. 并发与高效性设计

### 5.1 并发模型

产品不采用“整个 Memory/Host 一次一个请求”的串行设计。

允许：

- 不同用户、项目、任务并发；
- 同一任务中互不依赖的只读来源请求有界并发；
- 多个来源读取结果按 request/source/version 关联回 Host；
- 读与无关写并发；
- 同一 State 的竞争写继续使用 CAS。

实验中的“单模型请求在途”只用于预算控制，**不得转成服务全局锁**。

### 5.2 资源池

至少区分：

1. source read/search；
2. Product DB/MCP connections；
3. model generation；
4. optional background indexing（若未来存在，本 Goal 不新增）。

Host acquisition helper 应有可配置的 `max_parallel_source_reads`，但首版不冻结生产常数；
D0/性能阶段根据实际硬件测量后确定测试档位。

### 5.3 性能目标的冻结方式

本 Goal 不凭历史数字虚构新的生产 SLO。D0 先测同版基线，再冻结：

- read/search P50/P95/P99；
- throughput；
- queue wait；
- DB connection wait；
- cross-tenant isolation；
- first-useful-evidence latency；
- end-to-end delivery latency；
- write/commit confirmation latency；
- cold resume latency。

新 Host helper 不得造成同条件读路径 P95 的无解释大幅回退；具体允许比例在基线测量后写入执行配置。

### 5.4 高效取得的演进顺序

只允许按以下顺序优化：

```text
1. 避免无效/错误工具分支
2. 精确来源直接读
3. 有界 continuation
4. 固定 lexical retrieval
5. 必要时再研究 semantic/dense
```

只有出现“lexical 在多个独立长历史中反复取不到，但 oracle 能答对”的证据，
才另立 semantic retrieval 研究；不能因为外部系统常用 embedding 就预先引入。

---

## 6. 代码与模块设计

### 6.1 实现原则

- 先在 Lab/Host adapter 验证通用行为；
- 不复制 Product Runtime 的权限/版本逻辑；
- 不从 Lab 导入 Product 私有实现；
- 若要产品化，优先放在 Host SDK/Client helper，而不是 Runtime 认知逻辑；
- Product API 缺陷才修改 MCP/Runtime；
- 所有语义行为变化要有明确 failure 对应。

### 6.2 建议模块

文件名是建议，不要求一概拆分；已有相邻模块满足职责时直接扩展。

```text
MiLAi-Lab/
  tools/
    v0214_source_binding.py
    v0214_acquisition.py
    v0214_delivery.py
    v0214_budget.py
    run_v0214_e2e.py
    check_v0214_live.py
    summarize_v0214.py
  configs/
    v0214-dev.json
    v0214-holdout.json
  tests/
    ... adjacent tests ...
```

后续如产品化到 Client SDK，候选结构：

```text
MiLAi-Client/
  acquisition/
    source_binding
    pagination/continuation
    result/coverage types
    budget hooks
```

Client 只提供机械 helper；`query`、`need clarification`、`ready to deliver` 仍由 Host 决定。

### 6.3 内部接口建议

不是新 MCP schema，只是 Host-side interface：

```text
resolve_sources(task_binding) -> SourceBindingView
read_source(source_ref, cursor?, limit?) -> SourcePage
search_sources(query, scope, budget) -> SearchResult
continue_source(source_ref, cursor, budget) -> SourcePage
observe_coverage(acquisition_trace) -> CoverageObservation
check_delivery(candidate, delivery_contract) -> DeliveryCheck
reserve_final_delivery(budget_state, contract) -> BudgetDecision
```

所有返回必须包含 request correlation、source/version、资格状态和实际消耗；
不得返回 evaluator label 或业务正确答案。

---

## 7. 分阶段开发计划

## D0：当前基线与开发边界冻结

### 目标

将 V02-13 的终态变成新的开发起点，避免历史规划快照继续作为当前约束被误读。

### 工作

1. 核对 Product/Lab/Client 实际 revision、安装 wheel hash、AGENTS/合同。
2. 核对 H1 v2 实际源码、配置、4 个成功请求和 v1 失败，不重新打分。
3. 建立 `v0214-baseline-manifest.json`：
   - Product/Client/MCP pin；
   - Host/model/template；
   - 当前 8 tools；
   - source interfaces；
   - 当前 A0；
   - H1 v2 candidate identity；
   - protected datasets/cluster lists；
   - current permissions and deployment scope。
4. 重新测非模型并发/读取基线，冻结后续性能比较条件。
5. 核对 V02-13 中旧预算已取消的部分，不恢复 20k；本 Goal 使用独立可配置预算合同。
6. 默认模型发送关闭。

### 出口

`D0_BASELINE_FROZEN`：实际当前能力、历史证据、未完成项和新开发边界一一对应。

---

## D1：抽取通用 Source Binding 与 Coverage

### 目标

让 Host 在任何任务中机械知道“当前合法来源在哪里、能怎样读、读到了多少”，不依赖 case-specific 路径。

### 工作

1. 从 H1 v2 提取公开 source_read 分页调用，不携带题目专用业务逻辑。
2. 实现/复用 `source_binding_manifest`。
3. 建立 COMPLETE/PARTIAL/WITHHELD/UNAVAILABLE/UNKNOWN 机械状态。
4. 支持新 observation/版本变化后重新读取当前资格。
5. 记录 acquired vs presented。
6. 多来源只读有界并发；结果归属不能串 task/source。
7. 不增加新 Product Memory Store，不将普通文件内容自动写成 Note/State。

### 必测

- 0 页、1 页、超过 16 页；
- exact EOF；
- cursor 丢失/重复；
- source version 变化；
- revoked/withheld；
- 两个 task 相同文件名；
- 多来源并发乱序完成；
- timeout/partial response；
- new process recovery。

### 出口

`D1_SOURCE_ACQUISITION_MECHANICS_READY`。

---

## D2：Task Readiness、Clarification 与 Typed Delivery

### 目标

解决“历史可以读到，但任务仍缺业务必要输入”这一产品问题。

### 工作

1. 将 H1 v2 typed delivery 抽象为通用 delivery contract checker。
2. Host 侧支持 READY / NEEDS_SOURCE / NEEDS_CLARIFICATION / BLOCKED。
3. 对 known-tool 场景验证 required/optional/type/default 边界。
4. 多工具场景只验证机械候选目录，不按 gold 筛正确工具。
5. 缺失 required value 时形成用户澄清，不补造。
6. 澄清后新用户输入具有最高当前性，旧 Memory 不覆盖。
7. 输出结构合法和语义正确分账。

### 必测

- required ID 缺失；
- 主体身份歧义；
- 时间/地址/坐标缺失；
- optional 缺失；
- Memory 中存在旧值但用户给新值；
- wrong type；
- unknown enum；
- clarification 后恢复；
- explicit abstain。

### 出口

`D2_DELIVERY_AND_CLARIFICATION_READY`。

---

## D3：预算与最终交付保护

### 目标

避免多轮 acquisition 把预算消耗到无法交付，同时不通过删除合法能力制造低成本。

### 工作

1. 离线复用 V02-12/V02-13 请求，分解 fixed tools、history、tool results、message replay、output reserve。
2. 实现 Host-side configurable `final_delivery_reserve`。
3. 每次额外 generation/tool action 前检查剩余可负担边界。
4. 工具调用无模型 token 时仍计 latency/CPU/network。
5. unknown model usage 保留预约。
6. 不自动 retry、不自动换模型、不静默降低输出 contract。
7. 允许 Host 在剩余预算不足时选择受限交付/澄清/停止。

### 关键实验

用零生成 replay 回答：若 V02-12 两个 budget-stop 在每一步保留 final reserve，何时会提前停止 acquisition；
不能假定最终一定会答对。

### 出口

`D3_DELIVERY_BUDGET_READY`。

---

## D4：选择性取得策略——先 lexical，再考虑更复杂检索

### 目标

在不损失 H1 完整读源正确性边界的前提下，使长历史能够低成本取得必要材料。

### 第一版策略

```text
if precise source known:
    exact read
elif history fits bounded complete-read budget:
    bounded scan
else:
    lexical search -> selected source reads -> optional continuation
```

### 工作

1. 冻结机械 lexical baseline（BM25 或现有实现中明确名称的词面检索）。
2. query 仅来源于当前问题、明确实体/标识符、当前业务 schema 名称；不使用 gold。
3. 记录 A0 自产 query 与 lexical backend 的 zero-generation replay。
4. 记录 lexical query 在 A0 原合法 backend 的 cross replay。
5. 建立参数/必要事实级 support coverage：available / acquired / presented。
6. top-k、chunk、overlap、证据 budget 先在开发集冻结；不看答案调整。
7. lexical 失败不自动启用 embedding；先归因。

### 停止条件

- 如果 bounded complete read 在目标长度下已经稳定且成本可接受，不必强推 lexical。
- 如果 lexical 在多个独立长历史中 coverage 不足、Oracle/完整读源能成功，才提出下一 retrieval Goal。

### 出口

`D4_BOUNDED_SELECTIVE_ACQUISITION_READY` 或 `D4_KEEP_COMPLETE_READ_FOR_SUPPORTED_RANGE`。

---

## D5：真实冷 Host 端到端开发链

### 目标

将 D1–D4 合在一个真实 Host 使用路径中，验证不依赖旧两题。

### 开发任务类型

至少包含：

1. 短历史、无需检索；
2. 短历史、需要完整读；
3. 长历史、选择性取得；
4. 缺 required input，需要 clarification；
5. 新 observation 推翻旧历史值；
6. 冷恢复后继续；
7. 两个并发独立任务。

任务首先使用明确标注的开发/开放材料，不消耗保护 confirmation 集。

### 每条链记录

```text
start binding
→ source inventory
→ acquisition decisions/calls
→ acquired/presented evidence
→ readiness decision
→ delivery/clarification
→ optional save
→ process end
→ cold resume
→ first relevant action
→ final result
→ total cost
```

### 成功条件

- 用户不重贴历史；
- 不由操作者提供 gold source ID；
- 关键来源真正 presented；
- 缺输入时不编造；
- 交付 contract 正确；
- 新进程恢复后不依赖旧临时 messages；
- 无跨 task/principal 泄漏；
- cost/latency 可复算。

### 出口

`D5_REAL_HOST_E2E_DEV_PASS`，仅为开发范围，不代表外部泛化。

---

## D6：独立任务确认与产品化门

### 目标

验证通用 Host policy 是否超出原两题，并决定是否值得产品化。

### 数据与分区

- 不打开 Horizon 55 个保护 confirmation clusters，除非另有明确 Goal/授权；
- 不自动打开 V02-13 已封存的 Mem2Act clusters；
- 先冻结新的 dev/confirmation split 与 eligibility；
- cluster-first，不能把同一 lineage 的多题当独立样本；
- accepted task 运行失败不补题。

### 建议第一确认批

在明确允许的**未参与 D1–D5 调试**的池中，至少覆盖 4 个独立 task clusters：

- 2 个短/中历史；
- 2 个长历史或需要选择性取得；
- 至少 1 个 clarification/ambiguity 负控；
- 至少 1 个 no-memory-needed 负控。

具体 N 是产品确认覆盖，不用于统计显著性主张；正式论文确认另立。

### 比较

至少保留：

- A0 当前默认；
- H1-derived generic Host candidate；
- 对长历史适用时的固定 lexical retrieval diagnostic。

不要求所有任务都查 Memory；正确不查是允许结果。

### 产品化门

只有同时满足：

1. 候选在独立任务上不降低必要正确性；
2. clarification/abstention 不被破坏；
3. 长历史下没有依赖“读到无限 EOF”；
4. 多任务并发无串 scope；
5. 总成本/延迟在冻结边界内；
6. 失败可解释，未出现安全/权限回退；

才进入 `PRODUCT_INTEGRATION_CANDIDATE`。

---

## D7：产品集成（条件阶段，不自动进入）

如果 D6 通过，再决定实际落点：

### 优先方案

将机械 acquisition helper 产品化到 Client/Host integration，而不是 Runtime 语义层。

Product change 只包括必要的：

- 公共类型/SDK helper；
- request correlation；
- coverage/cursor handling；
- budget hooks；
- observability。

不在 Runtime 中实现：

- “什么时候应该搜索”的语义模型；
- 业务参数推断；
- 状态正确性判断；
- 自动维护 State。

### 发布要求

- semver / compatibility decision；
- SDK/MCP contract tests；
- real PG for state/permission-related changes；
- upgrade/rollback instructions；
- current deployment pin；
- no schema freeze unless separately approved。

---

## 8. 非模型工程验收矩阵

以下是新 Goal 的待实现/复用检查，不代表已通过：

| ID | 场景 | 核心断言 |
| --- | --- | --- |
| T01 | source binding | task/principal/project 作用域准确 |
| T02 | exact read | 已知来源直接读，不先无意义 search |
| T03 | short complete scan | EOF 后才 COMPLETE |
| T04 | long > page limit | PARTIAL + cursor，不伪装完整 |
| T05 | source version change | 老 cursor/版本不静默指向新正文 |
| T06 | revoked/withheld | 正文不返回，状态可观察 |
| T07 | no source | 没有合法历史与服务不可用分开 |
| T08 | concurrent reads | 结果归属正确，不串 task |
| T09 | duplicate/late result | 不覆盖当前新版本/错误来源 |
| T10 | required value missing | NEEDS_CLARIFICATION，不猜值 |
| T11 | optional value missing | 不错误阻塞交付 |
| T12 | stale memory vs new user input | 当前用户新值优先 |
| T13 | type/enum validation | typed delivery 明确失败原因 |
| T14 | action intent | 不执行外部业务动作 |
| T15 | final reserve | 预算不足前可预测停止，未发请求不计消费 |
| T16 | unknown usage | 保留预约并停发 |
| T17 | lexical query determinism | 无 gold、可复算、无 case branch |
| T18 | cross-backend replay | query 与 backend 影响可拆分 |
| T19 | support coverage | available/acquired/presented 分开 |
| T20 | no-memory-needed | 不强制检索/保存 |
| T21 | cold process | 临时 context 不继承 |
| T22 | state absent | 普通 source 路径仍可工作 |
| T23 | save optional | 合理 NO_CHANGE 不当失败 |
| T24 | two writers | CAS，不覆盖 |
| T25 | multi-user load | 不跨用户；服务端无全局锁 |
| T26 | overload | 容量外有界拒绝，不无限排队 |
| T27 | logging | 无 auth secret；正文按权限保存 |
| T28 | artifact accounting | 每次请求/工具/预算/版本可追踪 |

D1–D4 的纯逻辑可以单元测试；权限、CAS、撤销、真实持久化必须使用实际 Product/PG 路径。

---

## 9. 模型行为与端到端验收

### 9.1 过程指标

每条任务至少记录：

| 环节 | 指标 |
| --- | --- |
| Availability | source 是否存在、可读、版本/资格 |
| Activation | Host 是否决定取源；无调用不自动算错 |
| Acquisition | exact/search/read/continue 的实际调用与 coverage |
| Presented | 实际模型输入中的 source/span/version |
| Readiness | READY / NEEDS_SOURCE / NEEDS_CLARIFICATION / BLOCKED |
| Use | 支持是否正确映射到参数/判断 |
| Delivery | required args/type/完整计划/最终回答 |
| Resume | 新进程首次相关动作 |
| Cost | raw token、输出、工具、CPU/磁盘/网络、latency、人工审查 |

### 9.2 结果分类

- `SUCCESS_WITH_DEMONSTRATED_MEMORY_USE`
- `SUCCESS_WITHOUT_DEMONSTRATED_MEMORY_USE`
- `SOURCE_NOT_ACQUIRED`
- `SOURCE_ACQUIRED_NOT_PRESENTED`
- `PRESENTED_SUPPORT_WRONG`
- `NEEDS_CLARIFICATION_CORRECT`
- `UNSUPPORTED_GUESS`
- `HOST_BUDGET_STOP`
- `PERMISSION_WITHHELD`
- `UNSCORABLE / DISPUTED`

任务成功与 Memory-use 证据分开；Agent 猜对不能自动记成 Memory 成功。

### 9.3 强对照与 Oracle 的位置

外部诊断仍可使用：

- A0 autonomous；
- fixed lexical retrieval；
- evidence oracle。

但它们是**诊断工具**，不是 Product 三种默认模式。
Oracle 只用于回答“证据充分后是否仍会用错”，不能给在线 Agent gold label。

---

## 10. 成本与预算合同

### 10.1 不恢复已取消的历史硬上限

本 Goal 不重新启用 V02-13 旧规划里的 20k 累计 cap。
后续每次执行应在 D0/D3 按实际模型、context window、输出合同和任务类型冻结：

- 单请求最大输入；
- 输出预约；
- 单任务 generation 上限；
- source call 上限；
- wall-clock；
- batch total；
- final delivery reserve。

数值属于具体运行配置，不写成长期 Product 常量。

### 10.2 完整成本

分别记录：

```text
ingest / source preparation
+ Host acquisition calls
+ model input/output
+ repeated context
+ delivery
+ save/commit
+ cold resume
+ optional maintenance
```

货币、raw tokens、cache、GPU、CPU、磁盘、网络、延迟和人工审查不强行合成单一分数。

### 10.3 失败也计成本

- timeout；
- rejected request；
- invalid arguments；
- partial source；
- unknown usage；
- clarification；
- no-op save；

全部进入分母与账本，不能只统计成功路径。

---

## 11. 代码质量、审查与合并规则

### 11.1 每个增量的最小 Review Card

```text
Observed problem:
Hypothesis:
Changed layer:
Behavioral difference:
Mechanical invariants:
Regression/negative controls:
Evidence:
Cost:
Decision: MERGE / KEEP_LAB / REVERT / STOP
```

不为每个 helper 增加架构审批；真正改变 Product 权限、事务、Schema、治理语义才需要 ADR。

### 11.2 建议 PR 序列

| PR | 内容 | 依赖 |
| --- | --- | --- |
| PR-01 | baseline manifest + current H1/A0 replay harness | D0 |
| PR-02 | source binding + coverage types | PR-01 |
| PR-03 | generic pagination/continuation + concurrency-safe correlation | PR-02 |
| PR-04 | task readiness + typed delivery checker | PR-02 |
| PR-05 | final delivery reserve + accounting | PR-03/04 |
| PR-06 | lexical acquisition diagnostic + cross-replay | PR-03 |
| PR-07 | real cold Host dev E2E runner | PR-04/05/06 |
| PR-08 | independent confirmation runner + summarizer | PR-07 |
| PR-09 | conditional Client/Product integration | D6 pass only |

### 11.3 检查

依仓库实际 AGENTS/合同执行，至少包括适用的：

```bash
uv run milai-lab-check-boundary
uv run pytest
uv run ruff check ...
uv run mypy ...
uv build
```

Product/Client 修改则增加对应 SDK/MCP/Runtime 测试；权限/状态/事务变更必须真实 PG。
不能引用历史 685 tests 代替新代码验证。

---

## 12. 产物与证据布局

原始证据继续放 Git 外，建议：

```text
artifacts/v0214/<run-id>/
  manifest.json
  source-binding.json
  allocations.jsonl
  acquisition-calls.jsonl
  requests/<request-id>/
  delivery-checks.jsonl
  budget-ledger.jsonl
  cold-resume.json
  evaluations/
  cleanup.json
```

Git 中只提交：

- Goal；
- 小型配置/manifest；
- 代码；
- 紧凑结果和证据索引；
- 不含敏感正文/密钥的报告。

每个结果必须能追溯到 Product/Host/model/config/source versions。

---

## 13. 阶段门与终态

| 终态 | 含义 |
| --- | --- |
| `D0_BASELINE_FROZEN` | 当前版本和边界可复算，无新产品/模型效果主张 |
| `HOST_ACQUISITION_MECHANICS_READY` | 来源绑定、分页、coverage、并发机械行为通过 |
| `HOST_DELIVERY_READY` | clarification、typed delivery、final reserve 通过工程门 |
| `REAL_HOST_E2E_DEV_PASS` | 开发任务真实冷链正确，未证明外部泛化 |
| `PRODUCT_INTEGRATION_CANDIDATE` | 独立任务确认、性能和安全门通过，值得产品化 |
| `KEEP_A0_HOST_CANDIDATE_REJECTED` | 候选无净价值或出现负迁移，继续 A0 |
| `ROUTE_TO_RETRIEVAL_RESEARCH` | 长历史失败主要由 acquisition/search coverage 导致 |
| `ROUTE_TO_USE_RESEARCH` | 多独立任务在充分 presented support 下仍错误使用，另立 State/attention 研究 |
| `BLOCKED_PROTOCOL_OR_DATA` | 接口/来源/样本/评价不能形成有效验证 |
| `STOPPED_SAFETY_OR_BUDGET` | 权限、泄漏、未知费用或硬预算阻断，保留全部事实 |

Schema 始终保持 NO-GO，除非后续有独立证据与发布决定。

---

## 14. 创新研究的保留入口

本 Goal 不否定“受人类记忆/ADHD 执行功能方法启发的 State 记忆调控”方向，
但明确把它放在**充分材料仍反复用错**之后。

只有出现：

```text
support available
→ acquired
→ presented
→ independent tasks repeatedly wrong in relation/applicability/next-action use
```

且普通 clarification、typed delivery、简单复核不能解释时，才允许提出新的最小机制。

届时优先顺序仍是：

```text
simple prompt / free State
→ relation-preserving free State
→ only if still necessary, minimal structure
```

不因为 V02-10/v0.5 的 controlled case 或 V02-13 H1 回归成功直接恢复 State schema 研究。

---

## 15. 最终交付要求

下一轮开发报告必须明确回答：

1. H1 v2 中哪些行为被抽象成通用能力，哪些被删除为 case-specific？
2. Host 怎样区分完整/部分/无权限/未知来源覆盖？
3. 长历史不读到 EOF 时，关键支持如何取得？
4. 什么时候需要 clarification，而不是继续查或猜值？
5. final delivery reserve 是否减少 budget-stop，代价是什么？
6. independent task 上正确率、Memory-use 证据、负迁移和成本分别如何？
7. 多用户/多任务并发是否保持作用域与性能？
8. 当前候选是否值得成为 Product 默认；如果不值得，失败在哪一层？
9. 是否出现足以重新启动 State/attention 研究的 presented-but-wrong 重复 failure？
10. 哪些范围仍未验证？

**本 Goal 的产品成功标准不是“多做了一套记忆策略”，而是：真实 Host 能在不要求用户重述历史的情况下，
以可解释、可恢复、可并发、成本有界的方式取得需要的长期材料；缺资料时知道该澄清，资料充分时能够正确交付。**
