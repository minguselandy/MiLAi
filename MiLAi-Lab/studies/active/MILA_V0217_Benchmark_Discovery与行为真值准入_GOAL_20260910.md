---
document_id: MILA-V02-17
version: "0.3"
date: "2026-09-10"
status: VALIDITY_GAPS_RECORDED
experiment_arm_kind: BENCHMARK_ADMISSION_ONLY
research_focus: BENCHMARK_DISCOVERY_AND_BEHAVIORAL_GROUND_TRUTH_ADMISSION
research_mode: CAPABILITY_AND_VALIDITY_AUDIT_BEFORE_MECHANISM_DISCOVERY
engineering_role: THIN_LAB_ADAPTER_AND_OBSERVABILITY_ONLY
mechanism_development_authorized: false
product_default: A0_UNCHANGED
context_projection_enabled: false
new_runtime_schema: false
local_vllm_use_approved: true
local_provider_preflight: MODELS_ENDPOINT_ONLY
new_local_model_requests_allocated: 0
new_paid_model_requests_authorized: 0
new_judge_requests_allocated: 0
cumulative_raw_token_cap: null
execution_authorized_by_this_document: false
execution_authorized_by_user: true
bounded_b0_b4_audit_completed: true
p_lane_admitted: 0
public_deployment_authorized: false
schema_status: 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE
---

# MILA-V02-17：Benchmark Discovery & Behavioral Ground Truth Admission

## 1. 目标与本次转向

**先确定哪个公开实验对象能测正确的长期行为，再研究 Memory 调控；不预设新的 State、
打分器、关系绑定、检查点或注意力机制。**

需要找到可核验的链：

Experience → Memory → Later Retrieval → Presented → World Change → Decision → Recovery/Revision。

[V02-16 执行](MILA_V0216_EXECUTION_20260910.md)与[失败图谱](MILA_V0216_FAILURE_MAP_20260910.md)
仍为 FAILURE_MAP_RECORDED / KEEP_SIMPLE：低压 12/12、高压 5/12、回退 11/12；
36 阶段来自两个合成根，8 次失败都在取得/覆盖层，自选 Note 写入 0。
没有可裁定的“旧持久笔记与新证据均呈现后误用”样本；惯性分母是 0，不是固着率 0%。
混合压力也不能给出通用长度阈值。

本版本替代[未执行的 v0.1 研究合同](MILA_V0217_持久记忆使用与稳定性可塑性探索_GOAL_20260910.md)。
其 Track A / N0–N1 不再是当前首批必跑实验；可作为以后获准的适配/诊断参考。
既有准备脚本、原型及用户改动保留，不因有脚本就宣称本合同已实施。
V02-11 阻塞、V02-15 零候选、V02-16 完成等历史终态不改写，旧额度不滚存。

v0.2 预审产物为 Goal、[公开制品预审](MILA_V0217_BENCHMARK_PREFLIGHT_20260910.md)和索引。
“预审完成了若干检查”不等于“benchmark 全面准入完成”，更不等于机制有效。

v0.3 执行注记：用户另行授权执行后，已完成本合同 B0–B4 的有界审查，见
[准入终态报告](MILA_V0217_BENCHMARK_ADMISSION_20260910.md)与
[制品/hash 清单](../../data/manifests/v0217-admission-20260910.json)。
40 项局部原生检查发现 11 项语义反例；66 项数据边界/模拟事件后置条件通过。
P 准入 0，终态 VALIDITY_GAPS_RECORDED；无 Agent benchmark 运行或模型能力成绩。
v0.2 原文已保存在外部证据目录，原始预审及旧 V0216 报告不改写。

## 2. 候选次序及已经核实的修正

保留用户提出的研究优先级，**不按这个次序预判可运行性或要求第一候选成功后才看下一项**。

| 候选 | 当前核查结论 | 下一准入问题 |
| --- | --- | --- |
| The Compliance Trap 的 MemTrapBench | 论文描述 browser E-P-R；匹配该论文的公开制品尚未定位 | 确认原作者代码、任务、事件与评分器，不能拿同名仓库替代 |
| WorldMemArena | 公开 pipeline 可逐 session 摄取并做 checkpoint QA；有记忆/update/evidence 标签 | 生命周期诊断可行性与动作/恢复真值分别检查；先隔离 gold 与隐式 Judge |
| Supersede | 自维护有界 notes、事实替代与最终 QA；原生会截断 notes、不重供历史 | 仅作为有界 supersession probe 候选；先校准 matcher，不冒充正常全来源产品 |
| ClawMark | 公开多 stage 环境操作/checker 接线；当前 orchestrator 重用同一 session ID | 动作真值、外生更新、真实冷边界与 Memory 因果分别准入 |

这些是预审结论，不是四套已通过的系统。来源、commit、许可证与代码证据见
[预审 §§2–5](MILA_V0217_BENCHMARK_PREFLIGHT_20260910.md)。

特别区分：

- 七月 arXiv 2607.10608 的 MemTrapBench，与 zjunlp 的八月 arXiv 2608.20202 同名项目不是同一制品。
- 反复注入 memory 不等于持久存储；多 stage 不等于真实冷 session。
- QA/奖励字符串不等于真实工具动作；有 deterministic checker 也不自动意味着判据正确。
- WorldMemArena 的 CLI 标注 all=461/small=150，不是本地重算的数据量或合格题数。
- 缺少付费 API key 不再作为不可运行理由：可用本地 vLLM，但不能借此放过 gold fallback、
  模态缺失、无效评分或对原 benchmark 条件的改变。

## 3. Research-fit matrix：逐能力取证，不给笼统星级

每项能力记录“证据级别 + 制品定位 + 剩余缺口”，不把空白填成否，也不把论文描述填成 PASS。

证据级别为 PAPER_DESCRIBED、CODE_INSPECTED、FIXTURE_CHECKED、RUNTIME_VERIFIED；
另标 NOT_NATIVE、ADAPTER_REQUIRED、UNVERIFIED。读过代码不提升为运行验证。

| 维度 | 准入时必须能够核验的事实 |
| --- | --- |
| Self-authored memory | 是否允许 Host 自选内容；原生是自写、逐轮强制改写、harness 导入还是实验者注入，分别标明 |
| Persistent boundary | 提交/版本/内容 hash 可核验；新 Host 不继承旧消息与内存，允许的文件和缓存逐项声明 |
| Exogenous update | 旧判断当时是否合理；更新有时间/版本及对象范围，不能看模型答案后制造“真相” |
| Definitely presented | 旧 memory 与当前必要 observation 的内容确实进入实际发送请求，不只返回 ID、路径或 retrieval HIT |
| Counterfactual/conflict | 可构造合法同源对照并排除 memory 副本串臂；从开始就错与后来过时分别记录 |
| Action-level ground truth | 参数/环境状态/动作约束可评分，有必要前置条件，允许多种正确策略和合理澄清 |
| Recovery opportunity | 错误后确有合法纠正材料、可恢复环境及剩余行动机会，而非任务已经终止 |
| Stage attribution | 能区分获取、呈现、记忆使用、环境动作、判分器和基础设施失败 |

**任务“具备写入机会”与本次 Agent“确实选择保存”是两件事。**
零模型准入只验证前者及接线；自选写入、实际采信和恢复只能由之后的真实行为记录证明。
原生注入可用于 consumption probe，不能把“通过 MiLAi 保存再读出同一注入文本”改称自主记忆形成。

## 4. 按研究主张分 Lane，完整链的门不降低

| Lane | 最小研究对象 | 准入后仍不能声称 |
| --- | --- | --- |
| C：Memory consumption | 已知 memory 暴露、环境证据、可评分决策/纠正机会；外部注入须明示 | 自主写入、真实持久化或完整产品收益 |
| L：Memory lifecycle diagnostic | 摄取/维护/读取/呈现及阶段标签可核验；QA 允许单列 | 动作成功、恢复能力或 Memory 行为因果 |
| A：Action-world validation | 外生环境更新、动作/状态 checker、可复位轨迹 | 仅凭任务成功就认定 memory 必要或有效 |
| P：Persistent-memory regulation | §3 全链可验证，且运行中旧 memory、新 observation 均实际呈现 | 一次暴露差异自动等于稳定机制优势 |

每个候选先列 lane-specific gap。局部适用可为 PROBE_ONLY，不能混入 P 的机制分母；
**只有 P 的完整条件满足，才能进入所主张的持久记忆调控探索。**
不要求单一 benchmark 包办所有层，也不通过把几套互不相连的结果拼起来伪造一条完整因果链。
适配改变边界时另命名 MILAI_ADAPTED_PROFILE，保存 native 与 adapted 差异，不沿用官方分数。

## 5. Behavioral ground truth 与统一观测合同

以下是 **Lab 观测记录**，不是 Runtime/Note 必填业务 schema，也不要求输出隐藏推理。

每条轨迹关联：benchmark/revision/root、事件版本、合法主体/任务、原始经验、
memory 来源类别与提交版本、读取回执、实际请求内容/hash、当前 observation、
工具请求/真实环境结果、checker 版本/输出、错误与成本。
敏感凭据不落账；gold、checker 实现和未来事件脚本只供离线评价。

| 观察 | 判定边界 |
| --- | --- |
| Exposure / presentation | 明确哪些 bytes/图像进入哪次实际模型输入；不是“已理解” |
| Memory Entry | 首次相关动作与 memory 一致只是行为相容；要称“被 memory 改变”需合法匹配对照/干预依据 |
| Evidence conflict | 当前已呈现证据足以挑战旧判断的对象、范围与时间；无关新近事实不能自动推翻旧记忆 |
| Adaptation | 首次符合当前环境的行为，报告从纠正证据呈现起的步骤、耗时与成本 |
| Propagation | 记录偏离后的后续错误；另一个独立错误不自动算 memory 传播 |
| Recovery | 在已偏离且有纠正机会的条件下能否恢复；未偏离、无机会、预算结束分别列示 |
| Stability | 旧记忆仍适用时有无正确利用、无必要重开；不能只测“推翻旧结论” |
| Full outcome | checker 的动作/状态判分、最终交付、合理澄清与完整成本独立保留 |

Memory Entry 的因果判断不能靠模型自述，也不能只看一次 N1 错而 N0 对。
旧笔记本身错误、提示权威感、位置/长度、随机性与正常来源重建都是替代解释。
工具调用文本是 ACTION_INTENT；只有隔离环境中实际执行并检查结果，才记 ACTION_EXECUTED。

分母至少包括：candidate / screened / eligible / attempted / memory-written /
durably-recovered / memory-presented / new-support-presented / conflict-opportunity /
diverged-with-recovery-opportunity。零机会报 N/A；不因无保存、未取得、超时或不可裁定而删除总流程记录。

## 6. 配对条件：验证基准能支持，不立即开四臂模型实验

| 条件 | Memory 与环境关系 | 合理行为 |
| --- | --- | --- |
| Stable | 旧记忆仍正确，关键环境不变 | 保留有效约束，不无端重开 |
| Helpful | 有效旧经验对后续任务有用 | 利用并减少重复；不要求只能靠 memory 解题 |
| Superseded | 旧记忆原本合理，后有外生变化 | 按新证据修订适用判断 |
| Conflicting | 记忆已与当前环境冲突，有明确核验材料 | 拒绝或纠正，不授予记忆额外权威 |

Stable/Helpful 可以重叠，不是四个正交因素；不得把它们当四个独立根样本。
Recovery 是偏离后的后续机会，不是天然第五独立 arm。
同源条件、多 stage 和重复启动均以 root/task family 聚类；只有实际满足机会的项才计对应指标。

先查官方任务是否原生有这些关系。需要改变事件或 memory 才能形成对照时，列出适配 diff、
事件时点、环境复位、正常来源及 memory 副本隔离；不得看到输出后临时改世界状态。
保留普通 Note/简单提醒/正常来源强基线；不能只为了放大处理差异隐藏 N0 的正常来源。
有界 notes-only 等原生限制单列 native profile，不暗中写入 MiLAi A0。

## 7. Evaluator 必须先验收

B1/B2 在任何 benchmark 答案生成前冻结 evaluation_contract：
可评分行为、有效前提、允许结果集合、判分代码/hash、正例、负例、部分完成、必要澄清、
stale/current 共现、否定/引用旧值、争议规则、后续恢复机会及评价调用路径。

- 脚本模拟正确与错误动作，确认 checker 区分对象、范围、版本和阶段；只验证接线，不算 Agent 成绩。
- 确定性匹配器也要测试“否定正确值”“同时提新旧值”“引用旧值但已纠正”等反例。
- Judge 若必需，可将本地 vLLM 作为独立评价角色；仍须校准、分账、声明与官方模型的差异。
  同一个模型兼任被试和 Judge 有相关偏差，不能把本地 Judge 当独立真值。
- 不调用模型的替代评分若不是官方同义协议，标 NONSTANDARD_LOCAL_DIAGNOSTIC；
  无可靠自动判据则保留人工语义审阅/争议，不能把 substring 命中写成动作成功。
- 未来事件、gold memory points、gold answer 不进在线 Host；业务工具回传只用白名单公共字段。
  观察协议的 trace 不能泄露未来状态或 grader 私有内容。

已知必须防护的路径见[预审](MILA_V0217_BENCHMARK_PREFLIGHT_20260910.md)：
WorldMemArena 默认答案分支的缺 key→gold 回退、带 gold 的 question 对象跨边界；
Supersede matcher 的否定/引用混淆。**填本地 key 能解决配置条件，不能替代失败关闭和 gold 隔离测试。**

## 8. Thin Benchmark Adapter：只接线，不建新平台

适配器归 MiLAi-Lab，Product 继续用 MiLAi 自己的代码与公开协议。
不接入四套第三方 Memory 后端，不复制其自动认知策略，不新增 Product MCP tool 或业务 schema。

拟定职责只有：

1. 固定版本的任务/来源映射、事件推进与隔离环境复位。
2. 在线 Host 可见材料与离线 evaluator 数据分离；模态及 source provenance 不丢失。
3. 普通保存、精确读取和恢复通过公开 MiLAi 接口；绑定可信 scope、版本和幂等操作。
4. 记录实际送入模型的 memory/observation 与真实动作/checker 结果。
5. provider/Judge/embedding/视觉加工的调用与成本全部显式化。

外部设定的 memory 经 harness 写入须记 HARNESS_SEED，与 AGENT_NOTE_MUTATION 分账；
不能自动 approve 为 Canonical。强制逐轮重写属于 benchmark policy，不冒充 Agent 自选保存。
图片路径/官方 caption/真实图像分别标识；不得偷偷 OCR、生成 caption 或裁去关键模态。
只选 text-capable 子集需先验证关键判断确实不依赖缺失模态，并公开改名与覆盖范围。

冻结任务脚本前先审查代码；ClawMark task loader 会执行 Python 模块，不能把“加载配置”
当成无副作用读文件。容器、外网服务、账号、邮件/日历写入只能在专用测试域，不能用用户真实业务系统。
完整原始制品与大型下载放 Git 外；仓库只留小型 manifest、观测摘要与重放入口。

## 9. 本地 vLLM 与 API key 接入合同

用户已同意使用本地 vLLM。沿用本地 provider，不要求购买云端 key：
[现有 Provider](../../tools/v0213_provider.py) 使用 127.0.0.1:7860；
本次 GET /v1/models 返回 Qwen3.6-35B-A3B-FP8、max_model_len=65536。
无凭据及兼容占位 Bearer 的目录请求均成功；仅验证目录，不证明生成或鉴权功能通过。

建议的 **Lab 配置字段**如下，尚不是已安装的第三方配置文件：

~~~yaml
provider_kind: local_vllm
base_url: http://127.0.0.1:7860/v1
model: Qwen3.6-35B-A3B-FP8
api_key_env: MILAI_LOCAL_VLLM_API_KEY
allow_remote_fallback: false
allow_gold_fallback: false
~~~

第三方 wrapper 必须显式映射 base_url/model/key，不能假定设置一个通用环境变量就覆盖所有子客户端。
现有原始 HTTP Provider 的 base 是不带 /v1 的 origin，调用路径再加 /v1；
OpenAI-compatible 客户端一般使用上例带 /v1 的 base，防止拼成 /v1/v1。
若使用容器，127.0.0.1 是容器自身；连接宿主模型需显式受限路由，不能改成任意公网出口。

隔离、未启用服务端鉴权的本地兼容路径可使用非空占位 key；占位不是秘密，不是安全控制。
若服务配置真实 key，客户端须从环境/秘密存储注入匹配值，不写入 Git、命令回执或 trace。
vLLM 支持服务端 API key，但该选项不保护所有服务路径，应保持本地/受限网络边界；
本文不重启共享模型、不改变鉴权、不开放公网端口。
[官方 vLLM 说明](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)

未来接线验收：模型身份/端点固定 → 错配置明确失败 → 无 gold/远程回退 → 小型真实生成
及 usage 核对 → benchmark 专属能力（工具、图像、输出格式）核验。
真实生成/本地 Judge 可以另开低量 preflight，不能用目录成功或非空 key 直接跳过这些步骤。

## 10. 发现、抽样与封存

当前为 admission discovery，不为计算无偏效应量；可比较任务家族、公开开发样例与接线，
逐项保留否决理由。不得只因“看来容易显出惯性”接纳，不能以 A0 是否答错决定资格。
读过正文、gold、checker 或有答案提示的任务家族标 EXPOSED_FOR_ADMISSION，不再叫 untouched。

拟运行 pool 在生成前固定 revision/hash、候选 universe、非结果 eligibility、
cluster key、排序 seed 和停止规则；按 frozen-pool sequential acceptance 接纳，
不再先赌死几个题号后因为不合格而禁止访问整个候选池。
可观察性、许可、模态、来源/判分器可用性是资格条件；“该机制会赢”不是。
未获得完整数据时只保留 proposed pool，不编造数据 hash 或 accepted count。

Horizon 55 个确认 cluster、原 Mem2Act 确认池和其他既有保护集不因此解封。
确认阶段另建未打开 cluster 合同；本次预审样本、纯函数反例和适配修复均只属开发材料。

## 11. 阶段、交付与停止规则

| 阶段 | 必须交付 | 本次状态 |
| --- | --- | --- |
| B0 身份/制品 | 论文↔仓库↔数据的身份、版本、许可证、下载与依赖清单 | BOUNDED_AUDIT_COMPLETE；WMA 数据 pin/NC 许可与一个样本已核；MemTrap locator HOLD |
| B1 静态合同 | research-fit matrix、在线/evaluator 边界、事件/评分器/模态审查 | COMPLETE_FOR_AUDITED_SCOPE；八维矩阵与具体缺口，不是原生 runtime 验证 |
| B2 零模型验收 | 可重放正负 fixture、事件/reset、gold 污染与越界调用探针 | COMPLETE；40 检查/11 反例，66 数据边界/模拟事件后置条件通过；原生完整任务未跑 |
| B3 最小接线计划 | 每个候选的 native/adapter 差异、公共 MiLAi/provider 路径、资源需求 | PLAN_COMPLETE；薄边界 helper 已测，完整 adapter/model batch 未实施 |
| B4 准入结论 | lane-specific ADMIT/PROBE_ONLY/HOLD/REJECT 及下一最小执行合同 | VALIDITY_GAPS_RECORDED；ADMIT=0，P=0；局部 PROBE_ONLY 与 native HOLD 分列 |

ADMIT 只用于指定 lane 的合同与 fixture 已合格；不代表被试能力通过。
制品未定位/数据未核验/许可或依赖未解决用 HOLD，不把它记为语义失败；
本次已检查的原生接口可先列 PROBE_CANDIDATE，但不能混作完整链 ADMIT。
若完成有界审查后没有合适对象，允许 VALIDITY_GAPS_RECORDED / NO_FIT_IN_AUDITED_POOL，
不强求胜出者、不立刻补造整套新 benchmark，也不推导所有 Memory 机制无效。

B0–B4 不是“先赢 benchmark 再做研究”；它们是研究对象与评分可信性的门。
MemTrap 制品待定位不阻止继续核查其他候选；某 lane 缺动作真值只限制该 lane 主张。
未来有行为探索时仍保持 Discovery / Confirmation 两套合同，开放策略但不开放证据真实性。

## 12. 资源与本次交付边界

本次新增实验模型请求 0、本地/付费 Judge 0；v0.2 两次模型目录 GET 与纯函数检查不算生成。
本地 vLLM 路径已获用户同意，不因无付费 key 停工；v0.3 执行了公开制品/零模型夹具审查，
仍未分配 Agent benchmark batch，也未把目录成功或 mock 回执算作真实呈现。
后续低量探针在发送前记录目的、请求数、时间、输出上限、并发和未知用量停发规则。
累计 raw-token cap 继续 null，质量/功能优先；不继承 V02-16 剩余 74 次。
被试、Judge、embedding/视觉处理、工具/存储、环境维护和代理劳动分别计量。

不启动大型下载、训练、公开部署、业务写入或未经范围确认的外部账户环境。
共享模型未重启，MiLAi A0、公开 OAuth、Canonical、权限、Schema NO-GO 不变；
无 Product 实现、迁移或部署回滚事项。已完成的历史报告与失败账本保持原样。

v0.2 离线回归曾为 766 passed / 1 optional SDK-wheel skipped。
v0.3 回归为 Lab boundary、ruff、mypy（39 文件）、build 通过；
pytest 777 passed / 1 optional SDK-wheel skipped。不安装可选 wheel，因此不改写 V02-16 的 767。
没有 Product 实现改动，未重跑 Product 包、数据库和公网验收。
这些检查只证明现有工程回归，不是 benchmark、适配器或记忆机制准入通过。
