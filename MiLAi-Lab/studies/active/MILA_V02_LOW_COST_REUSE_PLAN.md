---
document_id: MILA-V02-03-EXPERIMENT-PLAN
version: "0.1"
date: "2026-09-06"
status: COMPLETED_KEEP_BASELINE
baseline: FULL_A0_WITH_REAL_TASK_FILES
candidate: S_EXACT_NOTE_CONDITIONAL
experiment_scope: OPENED_DEVELOPMENT_AND_LME_DERIVED_CONTINUATION
max_model_allocations: 28
formal_500_scoring: false
product_effect_claim: NOT_EVALUATED
---

# MILA-V02-03：可信诊断与增量保存成本实验合同

对应 [开发 Goal](../../../MiLAi-Product/docs/goals/MILA_V02_03_可信诊断与低成本记忆续做_开发实验_GOAL_20260906.md)。2026-09-06 已获授权执行；本文是规范合同，实际分配与阶段进度另存执行记录，不冒充已完成证据。

原先因输入空白归一化收尾的工程判断已更正；通用 payload 保真修复后，原定 N4 实际对照
通过，N5一条确认历史通过，另一条因累计token启动闸门缺少后续对照。见
[修复与续做报告](MILA_V02_PAYLOAD_FIDELITY_CORRECTION_20260906.md)。
[旧交付](MILA_V02_LOW_COST_REUSE.md) 保留修复前事实；本文假设、候选、成本阈值和预算不变。

## 1. 假设、对照和禁止外推

| 问题 | 可证伪假设 | 主要对照 | 结论上限 |
|---|---|---|---|
| trace 拒绝 | 局部运行身份导致响应摘要不同，但实际取证行为未变 | 同一就绪来源下 normal/baseline/traced + 人为实质变化负控 | testkit 观测正确性，不是检索效果 |
| 计数歧义 | 标签与合理题意/事件去重口径不完全一致 | 原始题面、完整允许来源、原参考、明确写出的不同解释 | 开发评价状态；不重写官方 gold |
| 额外保存 | 已有相同任务文件时，一次原样 State 复制能在两个后续中收回增量成本 | F：A0+文件；S：相同 A0+文件+实际复制后的 State | 条件递送/复用价值，不是语义修复或自然维护 |

真实 Host 通过锁定公开接口记 `PRODUCT_BLACK_BOX`；公开 testkit 诊断记 `PRODUCT_TESTKIT`。人工构造的反例、改写问题或 oracle 证据重放分别标注，不能混入原生 LME 或自然使用分母。

本轮不重跑 v02-02 的 4 组 U/V 来修改旧终态。新估计对象是“共同笔记已经产生之后的边际维护成本”；前轮将整次生成会话计入的保守结果继续有效。

## 2. 数据、来源与历史暴露

优先使用前轮已经修复的 Git 外 `artifacts/v02-lme-incremental/data-20260905b/`，由其中 manifest 核验各 source hash；`data-20260905a/` 只保留失败证据，不再在线使用。复用 [原 D/V 清单](MILA_V02_LME_INCREMENTAL_SELECTION.json) 中 12 个已开放案例，不重新读取 500 corpus。

新阶段划分：

- 诊断锚点：计数 `0a995998`，另一个普通控制和一个明确更新/组合案例；具体后两例在读候选结果前固定。
- R：2 条有普通任务笔记需求、来源条款明确的历史，作为 N4 开发探针。
- C：若进入保存确认，另 2 条历史，与 R 不重叠且未用于本轮候选设计。
- QA：若选问答修复分支，在现有 opened 范围内预定 4 个开发和 2 个复核案例；不得因保存分支结果临时重挑其历史。

历史数量不足时报告不足，不改用新 Formal 案例。过去已被阅读/评分、这轮未参与调参、这轮尚未运行分别标注；C 与 QA 复核都不是严格盲留出。

### 2.1 在线包必须通过的检查

1. 原会话 ID 全部为中性 `session-{ordinal}`；保留角色、内容、日期、顺序、重复实例和干扰，不能删掉正文里正常出现的“answer”等词来伪装隔离。
2. Host 只看到自己的 workspace、允许 source 文件、实际任务、当前 State 和正常工具；无 labels、评分脚本、其他 case、旧 artifact 或完整 corpus 挂载。
3. 衍生任务的历史截止点、当前问题、未来问题单独管理。原 source-only JSON 的顶层 `question/question_date` 也属于任务信息：共同任务 G 的在线历史包不得因此夹带原题或未来续问；必要时生成只含当时 session 的派生包，保留原包 hash 与变换记录。
4. 时间变化实验在分配前固定 t0/t1；G 只见 t0 以前已出现的材料，后续 F/S 同时收到同一 t1 更新。未来标签/问题不能出现在文件名、目录名、环境配置或提示中。
5. 所有来源固定为允许的去标识开发材料、隔离项目；不研究动态撤销传播。当前引用资格仍须有效，State warning 不是披露许可。

源码与单测验证泄露字段拒绝、源正文不变、派生时间截止、未来问题缺席。先做无模型容器检查，再允许真实 Host 分配。

## 3. N1 行为中性诊断合同

### 3.1 已知线索与待验证点

前轮首次 testkit 拒绝同时有 repository watermark/snapshot 等差异；第二次在无导入重叠时 `observer_equal/repository_equal=true`、`response_equal=false`。Product 当前响应比较对 `continuation` 做整块复制，而 continuation 含 root/context 局部身份。这是源码支持的候选解释，不是已经观察到具体响应差异的根因证明。

先在 Product testkit 侧提供受控字段级差异，Lab 仅接收公开错误/报告。报告至多包含预定数量的 JSON paths、值类型/基数/摘要与截断标志；不输出来源正文、凭据或跨 scope 数据。原响应仅在已有授权的隔离调试 artifact 中按原边界保存。

### 3.2 最小非模型矩阵

| 检查 | 固定条件/有意变化 | 期待 |
|---|---|---|
| T1 基础中性 | D1 OFF，来源 READY，三次同请求 | 语义一致；已有比较能力不退化 |
| T2 局部身份 | D1 ON、首轮有合法 frontier；三次正常独立 receipt/root | 若仅 ID 不同，能证明绑定关系并准确诊断；修复后语义一致 |
| T3 无后续机会 | D1 ON、无 frontier 或无 Evidence | 空/耗尽/不可用语义保持；不能统一抹成“相同” |
| T4 实质变化负控 | 单测注入 Evidence ID、顺序、正文摘要、available/reason/generation 或计数之一变化 | 必须拒绝；输出最早差异路径 |
| T5 身份绑定负控 | 单测错误 root/receipt 对应，PG 中错误 query/scope/predecessor | 比较/公共 API 按各自合同拒绝，不能被规范化掩盖 |
| T6 环境变化 | 隔离实例通过公开捕获新增相关来源或让 READY 身份变化 | 拒绝中性归因或显式标 snapshot 不同；不删除真实变化字段 |

T4/T5 的响应变体由 Product 定向测试构造，不向真实用户数据注入错误。PG 只用新实验范围的公开接口/正常迁移；不直接改 canonical 表。公开 resolve 自身正常产生的 receipt/continuation 记录如实保留，不把“Canonical 不变”说成“数据库零写入”。

### 3.3 允许的最小修复

若证实只是局部 ID，定义有限的同次身份对应关系并验证 root/receipt/query/scope，保留原始 ID 及新比较摘要。Evidence/turn 身份、顺序、内容摘要、frontier 状态/数量、generation、失效、重放、降级与权限相关信息不忽略。

不允许：删除 continuation 整块、去掉 repository/observer 门、只比最终答案、自动排序所有有序列表、放宽到“差不多相同”、绕过拒绝读取 Product 私有 candidate pool。

若摘要口径改变，Product 发布新的语义版本/兼容说明并记录 pin；历史 Product-10/X1 的摘要与终态不重新计分。修复后在一个复杂已开放案例和一个普通控制上确认，再看是否足以重新定位 first-loss；不把恢复内部观测当成 B1 问答效果。

N1 可在真实行为漂移已定位时以 `REAL_DRIFT_REJECTED` 交付；无法定位则记录 `UNRESOLVED`，不写成通过，也不阻止无需该 trace 的 F/S 公开路径实验。

## 4. N2：小型评价审计

离线记录最小字段：题目身份/日期、原参考、来源引用、对象或事件描述、同一事件重复叙述的依据、时间/商店/状态条件、计数单位、包含/排除理由、替代解释、审阅者和不确定性。

`0a995998` 至少审阅购买与换码是否同一事件、商店限定、借用/待领取的资格，以及“一双/单只/一类衣物”是否由题面明确。不得因为参考是 3 就补造第三项，也不得因为 A0 答 2 就把 2 定为新 gold。

评分状态在候选分配前固定：

- `SCORABLE`：题面、来源和所用评价规则足以判定。
- `AMBIGUOUS`：有无法由现有来源消除的合理解释分歧；保留原参考匹配分，但不用于候选二值胜负。
- `INSUFFICIENT_SOURCE`：无法充分确认；保留原案例，不自动补事实或当作候选错误。

明确化问题另记 `LME_DERIVED_CLARIFIED_TASK`，有父 case/hash 和新增条件记录；评价该衍生任务，不回填原生分数。审阅方式默认执行者源文核对，单独 Judge 若调用计入模型额度；没有人类/独立复核就明示未做，不把多模型一致当 gold。

## 5. N3：确定性 checkpoint 的输入、输出和测试

唯一候选 `S_EXACT_NOTE` 在正常共同任务结束后，由 Lab 显式调用一次。Host 不收到额外 A1/H1 提示，不要求每轮自检或保存。

输入是预先约定的相对路径笔记、当前真实完整 State、该任务实际来源映射、expected version 和 operation ID。采用现有 JSON payload 与引用合同，不新建领域 schema。实验管理的字段位置及合并规则在 N4 前固定，必须保留其他旧字段和引用。

管理字段固定为 `milai_lab_exact_note_v1`，值包含 `owner="MILA-V02-03"`、`path`、原样 `text`、`content_sha256` 与 `evidence_refs`。已有同名未知结构拒绝覆盖。普通文本中的引用须与来源映射及受检 `evidence_refs` 集合核对，不能用 `evidence_ids` 或空提取冒充资格校验。自然语言支持另行离线审阅。

GET 仅接受完整 `ACTIVE` 或 `ABSENT`：已有版本使用实际 `state_id` 和 version，ABSENT 使用 null/0；`EXPIRED`、`TRUNCATED`、缺字段或 warning 均拒绝合并，不经数据库私有路径补取。按完整旧 payload 合并后再检验完整 bootstrap 大小，不以 4,096 字节笔记上限代替装配上限。

执行发现（N4 前）：公开 Runtime 输入递归 strip 字符串首尾空白，PG 回读确认末尾换行丢失。封装器曾在提交前拒绝 `text != text.strip()` 的文件；该临时拒绝在通用 Product 保真修复后已移除，不再是候选前置条件。原失败回执保留，原文件不改。

规则：

1. 文件确实由共同任务产生、非 symlink、在允许 workspace 内；默认正文 ≤4,096 UTF-8 字节，精确计算 bytes，不按字符数冒充。
2. 文本保持原样。JSON escaping、分支 source ID/相对路径映射只做机械处理，有可逆对应记录；不能顺便改写含义。
3. 来源支持审阅在未来 F/S 执行前完成，回执验证权限/引用资格；资格验证与自然语言真实支持分别记录。
4. 相同内容/必要元数据已有则 no-op；既有自然保存同样保留。未变化不创建新 version，不加入动态时间戳制造 hash 变化。
5. 超长、缺文件、来源无资格、State 字段归属不清、bootstrap 总量超限时跳过/拒绝，记录原因；不自动让模型压缩、不增大上限。
6. 精确 CAS；冲突/未知结果按已有公开合同记录和确认，不盲写、不切换 operation ID 试运气。

| 测试组 | 必须覆盖 |
|---|---|
| 正常 | ABSENT→ACTIVE、已有其他字段保留、UTF-8/换行/引号/相对路径稳定、合法引用映射 |
| no-op | 同样内容、自然已保存、二次调用不增加版本/模型调用 |
| 资源/来源 | 超限不截断、文件逃逸/symlink、未知字段归属、跨项目引用与无效来源 |
| 写入失败 | stale version、operation conflict、明确失败、结果未知后确认仍未知 |
| 模型边界 | checkpoint 内没有模型 dispatch；无隐式摘要/Reader/重试生成 |
| PostgreSQL | 真实版本、旧字段/旧引用、幂等/拒绝与公开 GET 结果核对 |

实现通过仅表示条件保存路径可用；是否保留为用户能力由 N4/N5 决定。

## 6. N4：F/S 配对合同

### 6.1 共同起点与两个任务

在 R 的两条历史中，各预先固定 G 当前任务、指定的短笔记产物、历史截止、两个不同后续问题与评价条款。G 是普通实际工作请求，不要求额外 State 检查/保存；保留完整 A0 全部 13 工具、prefetch/revalidation、文件/搜索和自然保存能力。

G 只运行一次形成共同 artifact 和真实 State H。两个反事实都保留 G 的全部真实文件，不只复制对候选有利的那个笔记。若 G 自然已写入等价 State，记 `NO_OP_NATURAL_SAVE`，不清空 H；该链没有新增复制机会。

两个后续优先为：一个同一事实的不同使用任务，一个不同关注点或 t1 新变化的任务。不能只是同一问答改写以测试答案缓存；若没有自然 t1 变化，不编造“原生更新”，按不同用途探针记录。

F 使用 H，S 使用 N3 从 H 实际保存所得 H'。两个未来任务分别从同一完成点独立分叉，任务一的新文件/State 不进入任务二。本轮不估计完整纵向自动维护或经过无限续做后的回本。

### 6.2 配对必须相同的条件

- 同问题、任务日期、来源 cutoff/新增来源、全部任务文件与历史文件；来源和文件哈希按已声明分支映射核对。
- 同 Host/模型/推理配置、完整工具目录、预算、安装 artifact/pin、权限；同样允许模型再次查源或保存。
- 各自独立 home/会话/project/task，合法来源映射；F 不接受 S 的 State/临时对话，S 不拿未来答案。
- 唯一预定差异是 checkpoint 后 State 内容及其正常装配成本；checkpoint 本身的成本另计一次。
- 执行前平衡 F/S 顺序，记录缓存 input 子集与实际时间。不清全局缓存或停共享服务来创造条件；小样本顺序/缓存影响作为限制。

未来模型自己产生的新 State/文件属于真实该臂行为，不能禁止或从成本中删除。每个后续独立分叉，防止它改变另一组起点。

### 6.3 资格与分母

全部 G 分配及其成功、失败、无笔记、过长、自然保存、无来源、no-op 都入总账。资格在未来结果出现前判定；F/S 有效比较是“产生了合格共同笔记且确实增加 State 内容”的条件子集，不是所有任务自然可用率。

固定 R 不能因为某条不合格就暗换为容易保存/节省的历史。不足两条时局部报告或 `NOT_EVALUABLE`，不达完整 N4 门槛；非模型拒绝/no-op 测试仍单独交付。

## 7. 成本、质量与效果判据

### 7.1 成本分账

| 成本类别 | 归属 |
|---|---|
| G 的正常任务、笔记和自然保存 | 两个反事实相同；比较抵消，实际总账计一次，不说免费 |
| Delta_save：额外读取 head、读取笔记、封装、提交、确认与失败处理 | S 的新增成本；即使没有模型也记录 API/CPU/墙钟与动作 |
| F/S 后续的 bootstrap、模型、工具、再保存、输出 | 各自全计；不能扣掉候选增加的输入或合理来源复查 |
| case 捕获/READY、分支快照/引用映射、独立观察 GET、testkit 和本地测试 | 研究准备/测量开销单列进入实际总账；不伪装为用户每次需做的工作 |
| 重试、无效分配、取消与失败 | 不删除；实际发生的成本计入其阶段，不用成功会话覆盖 |

每条历史分别报告 token、在线墙钟、工具/API 次数；不合成为没有单位依据的总分。cache 是 input 子集，未知不填零。确定性 checkpoint 确认无模型调用时其模型 token 可据实际为 0，但 API/墙钟成本不为 0。

墙钟固定三项：`operational_online_seconds` 保留 launcher/prefetch、正常 bootstrap、模型与工具；`instrumentation_seconds` 单列独立 `debug prompt-input` 导出、observer GET 和观测处理；`delta_save_seconds` 包含保存所必需的 head GET、提交及确认。若从原始计时扣除实际观测时段，保留原始时长和测量边界；watchdog 仍按原始时长限制，旧实验结果不重算。

```text
F_future = C(F_task_1) + C(F_task_2)
S_future = C(S_task_1) + C(S_task_2) + Delta_save
Net_gain_2 = F_future - S_future
Cost_ratio_2 = S_future / F_future
```

除上述边际比较，还报告包含共同 G 的两条完整路径总量和本研究实际花费。任何额外模型压缩/摘要都计入 Delta_save，且退出本次唯一无模型候选；不通过事后归类把它当共同成本。

因输入未逐请求直接观测，禁止按工具调用前后比例切分一个模型会话的 token 来冒充精确维护成本。先前实验的整次生成扣费与本轮实测 checkpoint 是不同估计对象，分别保留。

### 7.2 语义与行为

离线核对首次外显实质判断、最终产物、来源归属、时间适用、未确定条件、原正确内容、更新后错误依赖及后续完成情况。原始回答/字段片段与评价依据可追踪；只用字符串 EM、State version 递增、工具调用减少均不够。

仍用 `later_model_inputs=UNOBSERVED`；返回/文件工具输出有关键片段不等于知道所有后续模型请求都呈现了该片段。不收集私有思维链。

### 7.3 N4/N5 保存候选门槛

对两条历史分别满足以下条件，不能用一条的大收益抵另一条损失：

- F/S 均完成任务，S 无新增关键错误、来源误归属、错误适用、正确内容丢失或权限问题。
- 真实额外保存和恢复可验证；Delta_save 和决定性 usage 不未知。
- 两次后续含 Delta_save 的 token 比 ≤0.90，在线墙钟净节省 >0。
- 非模型普通/no-op/过长控制行为正确，不新增模型调用或不必要写入。

每例、每条历史、最大 S/F 成本比和失败均报告，不能只报中位数。门槛通过仅进入冻结后确认，不是统计显著。若 token 降而时间升、仅质量改善或收益小于门槛，分别记录事实但不宣称已通过双成本门。

N5 保存确认采用另两条历史、完全相同候选/阈值。R/C 均通过才可保留有限范围的显式 checkpoint；仍不自动启用、不主张优于所有笔记格式/自动语义维护。

## 8. N5 可选 QA 分支

仅当 N4 未通过且 N1/N2 找到可靠的一般性任务缺口，才在首次分配前选择该分支；若 N4 通过，优先保存确认，QA 移到后续 Goal。本 Goal 不同时执行两分支。

先固定一个小修复 B、4 个开发配对案例（目标复杂失败与普通控制均覆盖）和 2 个不参与本轮调参的复核案例。A0 保留合法文件、搜索与自然保存，不以旧 MCP-only 受限配置代替。检索、Host 提示与 State 候选不能同时变化；D2 不接入公开 frontier，不增加 top-k 或 case/gold 词路由。

开发门：4 对至少 1 个净任务胜例、任务损失 0；中位 input+output 与在线墙钟比均 ≤1.25，普通控制两种比均 ≤1.10。复核门：2 对再次至少 1 个胜例且无损失、成本约束同样满足；不能针对这 2 对调参。胜例为 A0 错误/未完成而 B 正确完成，反向为损失；歧义/部分结果另列。

复核只支持这个有限 opened-development 切片；不采用“1/2 通过”推断广泛可靠性。没有可靠缺口就不进入，工程诊断仍可作为完整交付。

## 9. 分配预算、软停线和配置冻结

| 分配池 | 上限 | 固定用途 |
|---|---:|---|
| N0–N2 | 4 | 必要 Host 诊断/smoke/单独评分，不为凑数启动 |
| N3–N4 | 12 | 2 个 G + 8 个后续 + 2 个失败预留 |
| N5 | 12 | 保存确认的 2+8+2，或 QA 的 8+4；共用且互斥 |

合计最多 28 个实验模型分配；取消与未启动模型的分配仍占额度。阶段未用预算不自动转移。执行者离线源文审阅不另造 Judge；若实际增加独立模型评分/生成/压缩，必须占上述额度并记录 usage。默认不调度子 Agent。

默认 300 秒/会话、24 次工具动作；每批 ≤4 分配且累计在线 ≤1,200 秒；case capture/readiness ≤300 秒，采用既有单 worker/persistent client/journal OFF。下一会话额度受本批剩余预算约束。

已观测累计 input+output 达 2,400,000 时禁止下一模型启动；正在执行请求可能超出，如实记录。该闸门与120k软提醒都不宣称硬 API token 限制。模型启动而 usage 不明时不按零推进；先查证或以证据不足收尾。本文不虚构价格或账单金额。

N1 最多两批、每批 6 次 testkit 调用（每次含三次官方读取）、120 秒/调用；单测与构建另计。无新增定位信息即停止重复探针。每批需有候选/对照/数据 hash、代码与实际安装 pin、scope/snapshot/READY、顺序、预算、评价口径；任一变化生成新批次版本，保留旧结果。

## 10. 运行记录与验收

本轮研究配置与 pin、诊断/资格清单、批次分配和紧凑结果已创建，文件前缀为
`v02-low-cost-reuse` / `MILA_V02_LOW_COST_REUSE`；实际证据索引见交付报告。

最小记录字段：`allocation_id, phase, kind, arm, case_cluster, task_id, source_hash, cutoff, task_files_hash, initial_state_ref, actual_update_ref, product_pin, host_config_hash, order, validity, eligibility, save_status, first_judgment, final_quality, usage, cache_subset, delta_save, preparation_cost, online_seconds, stop_reason, evaluator, later_model_inputs`。它们属于 Lab 日志，不进入用户任务或 Product schema。

复用 runner/来源/分支复制与汇总代码，在相邻测试补新行为；既有固定旧结果汇总不得直接改为新计费口径。保留前轮中性来源、persistent capture、失败预算与分支映射测试。Lab active `src/milai_lab` 不导入 Product 私有模块或 `milai_client`；外部公开 hooks/SDK worker 继续使用其锁定安装环境。

执行阶段检查：Lab boundary、Ruff、mypy、pytest、build；Product 受影响包的相应 gates；真实 PG 的中性/负控、公共 State 保存和拒绝。只声称实际运行范围，不拿前轮 133 项充数。本次文档交付仅检查文档链接、格式与计划自洽，不提前运行这些实验。

全部分配有终态后，按开发 Goal 的三个终态规则报告：工程可用、可靠任务缺口、条件保存收益分别给结论。保留未知/歧义/未进入，不只展示胜例；只停止本次身份可验证的自建服务，数据和旧失败默认保留，清理临时认证副本但不删除用户数据。

始终保留完整 A0、D2 SHADOW、Product-11 旧封存、Formal 未正式评分、公网不变与 Schema NO-GO。本计划不授权自动维护上线或下一轮无限扩样。
