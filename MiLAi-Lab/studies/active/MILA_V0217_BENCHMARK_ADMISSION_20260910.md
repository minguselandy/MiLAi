---
document_id: MILA-V0217-BENCHMARK-ADMISSION
version: "1.0"
date: "2026-09-10"
status: VALIDITY_GAPS_RECORDED
scope: BOUNDED_B0_B4_ADMISSION_NOT_AGENT_BENCHMARK
experiment_arm_kind: BENCHMARK_ADMISSION_ONLY
fixture_arm_kind: SIMULATION
native_benchmark_runtime_verified: 0
p_lane_admitted: 0
model_requests: 0
judge_requests: 0
paid_requests: 0
raw_token_cap: null
product_default: A0_UNCHANGED
---

# V0217：有界准入完成，完整持久记忆调控链仍未准入

本次完成 [Goal](MILA_V0217_Benchmark_Discovery与行为真值准入_GOAL_20260910.md)
要求的 B0–B4 有界审查；终态为 **VALIDITY_GAPS_RECORDED**，不是“模型未通过”。
四个候选中，WMA 可继续生命周期/QA 接线，Supersede 可作有界 notes probe，
ClawMark 可继续局部动作判据与环境接线；没有一个候选在本次范围内满足 P 的全链要求。
MemTrap 的对应制品仍待定位，未以同名项目替换。

实际执行：40 项原生函数/文件夹具检查，11 项与先定语义预期不一致；
66 项真实数据边界及模拟事件后置条件检查通过；11 项新边界单测通过。
这些数字不相加为独立样本数，也不是 Agent 正确率。模型、Judge、embedding、视觉加工均 0 次。
未执行旧 v0.1 配对原型，未改 Product、A0、业务数据、权限、公共部署或受保护样本池。

## 1. B0：身份、版本、许可、制品与依赖

完整原始证据位于 Git 外：
`/cra/memory/mx_memory/evidence/v0217-admission/20260910`（下称 `E/`）。
[小型 hash 清单](../../data/manifests/v0217-admission-20260910.json)
封存 78 个原始文件，核对了 50 个成功下载的实际 bytes/hash；不把语料正文、凭据或图片复制入 Git。
[范围合同](../../configs/v0217-admission-scope.json)在夹具执行前确定候选与停止规则。

| 候选身份 | 固定制品 | 本次许可与可取得性 |
| --- | --- | --- |
| The Compliance Trap / MemTrapBench，Chen / Bai / Yuille，arXiv 2607.10608v1 | 论文 HTML 可读；匹配原作者的代码、任务、checker 未定位 | 论文页面标 CC BY 4.0；不能据此推定任务/代码许可。代码/data hash、依赖锁均未知，HOLD |
| UCSB-AI/WorldMemArena；仓库关联 arXiv 2605.29341 | code `15ea25b723d9c4fb35e8062037aec6a5601e4442`；HF data `e2148757921fc7e2d66d8ed899823b763227c341` | code MIT；HF 数据卡 **CC BY-NC 4.0**，gated=false；仅下载一个 JSON，不宣称全量可运行 |
| Vrin-cloud/supersede；仓库关联 arXiv 2606.27472 | code `677993d3713c265329ac935262d3c08cbfa4cd63` | Apache-2.0 代码；未取外部 LongMemEval 数据，不推定其数据许可/资格；官方合成生成器与原生 rollout 可独立检查 |
| evolvent-ai/ClawMark；仓库关联 arXiv 2604.23781 | code/tasks tree `d1b641b3171e584e69a3763c269069f32a13b574` | 仓库 CC BY-NC 4.0；代码/任务树可读，所选任务完整资产和原生服务环境未下载/验证 |

身份与许可依据：[Compliance Trap 论文](https://arxiv.org/html/2607.10608v1)、
[WMA 固定 README](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/README.md)、
[WMA code LICENSE](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/LICENSE)、
[固定 HF 数据卡](https://huggingface.co/datasets/LCZZZZ/WorldMemArena/blob/e2148757921fc7e2d66d8ed899823b763227c341/README.md)、
[Supersede README](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/README.md)、
[Supersede LICENSE](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/LICENSE)、
[ClawMark README](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/README.md)、
[ClawMark LICENSE](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/LICENSE)。
NC 制品的后续商业使用/再分发仍需单独核清适用许可；本报告没有授予或认定商业使用权限。

MemTrap 的负面检索结论限于本次确切标题、arXiv、作者/GitHub 组合及论文链接检查，
不是“作者从未发布”。论文描述受控浏览器任务与外部编写 memory 的 E-P-R，
不等于本次已有可重放任务。zjunlp 的 arXiv 2608.20202 同名项目明确排除。
定位账本为 `E/memtrap/locator-audit.json`；本地 HTML 下载 TLS 失败，未编造论文文件 hash。

| 依赖层 | 已检查的原生要求 | 本次实际执行 |
| --- | --- | --- |
| WMA | requirements 含 OpenAI/Anthropic 客户端、向量库、torch/transformers、图像处理及多种第三方 memory 后端 | 不安装全依赖；仅标准库结构/AST 检查与 Lab 单测；不接四套后端 |
| Supersede | Python≥3.11；核心 pydantic/typing-extensions；env extra 为 verifiers/datasets，Judge 可选 | 仅审阅过的 reward/rollout 标准库模块；未启动 RL、verifiers 或训练 |
| ClawMark | Python≥3.11、httpx/playwright、Google API/calDAV 等；原生 Docker/OpenClaw、邮件/日历及任务服务 | 仅抽取审阅过的函数，真实临时文件 + 本地服务替身；没有 task loader、Docker 或真实账号调用 |
| MemTrap | 官方运行制品未定位，不能冻结依赖 | 无执行 |

依赖依据：固定制品中的 `wma/requirements.txt`、`supersede/pyproject.toml`、
`clawmark/pyproject.toml`、`clawmark/docker/docker-compose.yaml`，均在 hash 清单。
ClawMark loader 会执行模块，且把运行 timeout 固定为 7200 秒，不能用 metadata 的 600/900 秒
冒充实际上限；其 OpenClaw 配置声明的上下文大小也不是本地模型已验证能力。
[loader](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/src/clawmark/task_loader.py)

## 2. 抽样、覆盖范围与分母

ClawMark 从固定 tree 得到 100 个 `task.py` 路径，按 `sha256('217:' + path)` 排序，
先冻结 12 个静态检查位置；11 个下载并做安全字段 AST 检查，1 个 TLS 失败仍保留。
按顺序选前两个不同 family 的可隔离函数夹具：`executive_assistant/task2`、`insurance/task3`。
其余成功下载项只做 metadata/资产后缀清点，不声称完整语义审查。
两个入选任务均标 L4、多服务；资产树分别有 49/11 个非 task.py 文件，未下载。
原生完整任务资格已证实为 0，意思是“未验证合格”，不是否定全部 100 项。
见 `E/clawmark/frozen-pool.json`、`static-inventory.json`。

WMA 只冻结 HF `lifelong/personal` 下 20 个 JSON 的同种 hash 顺序，
按非结果条件（目录、JSON、≤4 MB）取首项 `personal_18.json`，只尝试一个样本。
实际 802,911 bytes，SHA256 `d91be0d6c908d62c850cab1a30798196b8b111010a3c5f37e4456c251c9fd51f`；
30 sessions、5 checkpoints、55 questions、89 个附件引用；图片下载 0。
这不是全量 WMA 的抽样覆盖证明；官方 461/150 计数仍是发布者声明，不是本地重算。

所有 12 个 ClawMark 位置保守标为 EXPOSED_FOR_ADMISSION（含失败位置），
WMA 已打开样本和 Supersede 纯函数材料也只属开发审查，不能称 untouched confirmation。
多 stage、重复回放和多个问题按 task/root 聚类；此次没有效应量或独立确认估计。

| 分母 | 本次值及含义 |
| --- | --- |
| candidate / screened | 4 / 4 个 benchmark-level 候选；子池覆盖如上，不混用单位 |
| eligible | P=0；完整原生任务已验证合格=0；隔离 ClawMark fixture families=2，非 Agent 资格 |
| attempted | 原生 benchmark Agent 任务=0；原生函数/文件 fixture=40；真实结构/后置条件检查=66 |
| memory-written | AGENT_NOTE_MUTATION=0；HARNESS_SEED 写入 Product=0；脚本 rollout 字符串不算 Agent 写入 |
| durably-recovered | 0 |
| memory-presented / new-support-presented | 0 / 0；mock transport 回执不计 |
| conflict-opportunity | 实际 Agent 双方材料已呈现机会=0，指标 N/A |
| diverged-with-recovery-opportunity | 0，恢复率 N/A，不报告 0% |

## 3. B1：八维 research-fit matrix

PD=PAPER_DESCRIBED；CI=CODE_INSPECTED；FC=FIXTURE_CHECKED；U=UNVERIFIED；
NN=NOT_NATIVE；AR=ADAPTER_REQUIRED。FC 必须结合对象读：本地函数/替身，不是原生服务。
**本次没有任何 RUNTIME_VERIFIED 的完整 benchmark。**

| 维度 | Compliance Trap | WMA | Supersede | ClawMark（所选两 family） |
| --- | --- | --- | --- | --- |
| Self-authored memory | PD：外部编写/注入，非自主形成 | CI：harness ingest + backend 维护；Host 自选保存 U | FC：强制逐轮改写 notes，非自愿策略 | CI：工作文件可修改；专门 memory 写入 U |
| Persistent boundary | 持久化/冷边界 U，反复注入不能替代 | CI：end_session 不等于新进程；AR | FC：进程内 rollout 字段；持久提交 NN | CI：同一 session ID 跨 stage；冷边界 AR |
| Exogenous update | PD：任务冲突结构；旧值曾合理 U | CI：按 session 推进与 update/gold 标签；非执行中的动作世界 | CI：会话事实替代；FC 只测 notes 推进 | FC：固定时点 email/CRM 更新替身；完整旧前提合法性 U |
| Definitely presented | PD：注入协议；本次实际请求 U | FC：白名单与前缀；实际发送 U | FC：notes/current prompt 组装；实际发送 U | CI/FC：notification 与隐藏状态分离；Agent 是否读取 U |
| Counterfactual/conflict | PD：匹配干预；本次制品 U | 配对世界/隔离副本 AR；QA 不能自动作动作对照 | CI：更新任务；匹配持久副本/正常来源对照 AR | CI：有变化/冲突材料；同源合法配对与复位 AR |
| Action-level truth | PD：浏览器/E-P-R；checker 制品 U | CI：QA/Judge/检索指标，动作真值 NN | FC：QA matcher 语义反例；真实动作 NN | FC：真实文件由脚本写入后检查；局部判据反例，完整动作链 U |
| Recovery opportunity | PD：E-P-R；当前可运行机会 U | CI：QA 后没有已验证纠错行动窗口；AR | FC：最终 answer 后 DONE，无恢复回合 | CI：后续 stage 存在；未自动发送 checker 反馈；偏离后可恢复性 U |
| Stage attribution | PD：E-P-R 分解；本地 trace U | CI：session/delta/retrieval/QA；FC：隔离，实际 provider trace U | FC：notes/answer phase；获取/采信因果仍 U | CI：event→Agent→snapshot→checker；FC：局部输出；infra 与语义仍需拆分 |

主要代码定位：WMA 的
[runner](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/pipeline/runner.py)、
[QA runner](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/pipeline/qa_runner.py)、
[adapter 接口](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/memory_adapters/base.py)；
Supersede 的 [rollout](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/src/supersede/rollout.py)、
[env](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/src/supersede/env.py)；
ClawMark 的 [orchestrator](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/src/clawmark/orchestrator.py)。

## 4. B2：先定评价合同、原生反例与隔离验收

评价合同由 [scope](../../configs/v0217-admission-scope.json)、
[预设 fixture cases](../../tools/check_v0217_admission.py) 与本节共同定位。
scope SHA256 `3f318ea085075a0f0887fb0b9f9c70afac31d2dc43721ed4c1350e9d676b9fb3`；
40 项 fixture runner SHA256 `6ed5cc02d4f396030de71405e3ec4ebab285ae471e869c0d5e50987a2c52cabe`。
原生函数返回值与研究者预定语义分别保存，禁止为得到绿灯改写 native 输出。
反例预期在该轮函数调用前写入；后续真实数据接线修正另行记账，无模型答案参与选择。

评价规则：正确值须作为当前、对应对象/版本的有效断言；明确否定、未经采信的引用、
未解决的新旧并列不算完成。部分字段命中不等于完整任务；合理澄清单独记 CLARIFICATION，
不是自动正确或 stale-use。引用旧值后明确纠正不应被当作采信旧值。
复杂回答保留人工语义审阅/UNSCORABLE，不用本地 substring 替代动作真值。
本轮是非盲研究者校准材料，不宣称独立人工 gold 或已校准的语义 Judge。

| 对象 / 原生调用范围 | 检查与实得 | 准入影响 |
| --- | --- | --- |
| Supersede：8 种文本 × answer/stale 两函数，另 4 项 rollout | 20 项；5 个反例。否定当前值、未定新旧值、仅引用当前词可命中 answer；已纠正旧值仍触发 stale；未定并列也被当作 stale assertion | matcher 原始输出可留作诊断，不能直接用其分数声称语义适应 |
| WMA：仅抽取默认 answer factory，配置解析为本地 stub | 1 项；缺 key 时返回 PRIVATE_GOLD_CANARY 已复现 | 默认分支未经隔离不得接在线模型；非空 key 不是隔离证明 |
| ClawMark executive：真实 CSV 文件 + 选定 checker | 7 项；6 项符合预期，缺 C04 开始时间仍通过该 checker | 必需字段/时间前提须另外验收；尚未运行完整 rubric |
| ClawMark insurance：真实 JSON 文件 + 选定 checker | 10 项；否定 22:47、其他 claim 对象、缺 amount、否定 operational 四项仍命中局部 checker | 保留 native 局部分；不能把字段/词存在当作有效完整决策 |
| 两个 ClawMark family 的固定 stage 事件各回放两遍 | 2 项一致性检查；另在补充检查中验证 4 项事件时间、邮件数及状态后置条件 | 仅 SIMULATED_STUB_NOT_NATIVE_SERVICES；并未证明原生邮件/Notion/reset |

合计 40 项，29 项符合预设语义、11 项反例。后置检查不加入此 40 的分母。
Supersede 的默认 env rubric 实际只挂 `answered_current`；stale helper 的反例
**不等于默认总分已经包含 stale penalty**，可选 Judge 路径也未运行。
[reward.py](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/src/supersede/reward.py)

ClawMark 反例是 checker-local，不据此推断完整 rubric 会判整题正确。
例如 claim 对象可能由其他前置判据约束，必须联检；实际 Agent 行动也可能有多种正确顺序，
不得为了匹配单一文件示例而拒绝其他合法策略。
固定源码：[executive task2](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/tasks/executive_assistant/task2/task.py)、
[insurance task3](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/tasks/insurance/task3/task.py)。

### 数据、未来事件和 provider 边界

[薄边界实现](../../tools/v0217_admission_contract.py)只保留允许的会话字段和 question 文本，
丢弃离线 gold/memory_points/evidence/category 与私有 trace；不执行 native CLI。
在线会话必须为合法时间前缀；WMA `covered_sessions` 可以是局部窗口，
须按官方 runner 的最新 covered session 确定累计摄取边界，不能在每个 QA 窗口重置历史。
首次误把 coverage 当 prefix 的失败已保存在 `E/data-boundary-attempt1-failure.json`，
通用映射修复后未改题目、gold、checker 或样本顺序。

真实样本的 5 个前缀/私有字段检查、55 个 question 白名单检查、1 个缺图失败关闭、
1 个 label/future canary，加 4 个模拟事件后置条件，共 **66/66**。
附件只可在显式 `official_caption_diagnostic` 中保留发布者已有 caption；
该 profile 标 `native_multimodal_equivalence=false`、`images_presented=false`，不是原生图像任务。
这些测试不证明所有潜在嵌套文本都无泄漏，也不替代上线后的实际序列化/运输审计。

11 项单测覆盖错误 endpoint、双 `/v1`、错误模型、缺 key 映射、gold/remote fallback、
未来/私有 canary、模态缺失、coverage-window 与发送回执边界。
配置只允许既定本地 provider；无调用行为，未宣称 native WMA/Judge 的所有客户端已被修好。
payload hash + mock ack 仅测试观测语义，不能计 definitely-presented，更不证明理解/采信。

原始结果 `E/fixtures-v1/result.json` 的 SHA256：
`9b4e4b8e66918a36f54afef81d77b193d9bac4cfca05cfa361ae1b599e45416c`；
`E/data-boundary-result.json`：
`7c51cbb360d03710fcdc1d92cab7f2001b3466755e7a85c7985929ad3d20818e`。

### 后续真实轨迹的统一观察合同

Lab 记录 benchmark/revision/root、事件版本/对象/scope、合法来源、memory_origin、
commit/version/content hash、读取回执、实际发送的 memory/observation bytes 或图像 hash，
以及 action request、执行结果、环境快照、checker hash/output、错误、elapsed/usage。
凭据、未来事件代码与 evaluator labels 不进在线 Host；不是要求 Product 新业务 schema。

Exposure 只证明传输；Entry 先记“行为相容”，合法匹配干预后才能讨论因果；
Evidence conflict 要求同一对象/适用时间且双方材料已呈现；Adaptation 从纠正材料呈现起计步/时间；
Propagation 不能把独立后续错误串成传播；Recovery 只在已偏离且尚有行动机会时计分；
Stability 单列仍有效旧约束的保留；Full outcome、合理澄清及完整费用保留独立结果。
ACTION_INTENT 与真实环境 ACTION_EXECUTED 分开；本次文件变更属于 SCRIPTED_FIXTURE_MUTATION。
本次这些 Agent 行为字段全部未测，不用模型自述或“一个臂错、另一个对”自动补出因果链。

## 5. B3：每个候选的最小接线与资源计划

以下是下一合同，不是本轮新增模型授权。本轮 allocation 仍为 0。
共同入口：固定 `http://127.0.0.1:7860/v1` 与 `Qwen3.6-35B-A3B-FP8`，
显式环境 key 映射、禁止远程/gold fallback；目录成功只沿用历史 preflight，未冒充生成通过。
下次可先单独申请 2 个≤192 输出 tokens 的通用生成/格式探针，单并发、45 秒/请求，
usage 缺失或端点漂移立即停发；这不是 benchmark 成绩或自动滚存额度。
容器需受限宿主路由，不能把容器的 127.0.0.1 当成宿主；不重启共享模型或公开端口。

| 候选 | Native 与最小 adapted diff | 下一最小执行合同 / 资源与停止条件 |
| --- | --- | --- |
| MemTrap | Native 代码/任务/判据未知；不以“把注入文本写入 MiLAi”冒充自主形成 | 先得到可核验官方 locator、许可和一个公开开发任务；审查事件/reset/checker/正常来源。此前模型 0、无新浏览器 benchmark 构造；locator 不足则继续 HOLD |
| WMA | Native 是 ingest/end_session/snapshot/delta/retrieve/checkpoint QA。改为 `MILAI_ADAPTED_WMA_LIFECYCLE_V1` 时剥离 gold/category，显式 provider/evaluator，记录摄取与来源读取；不导入四套后端 | 先在已打开 sample 的 QA00 冻结一个问题，验完整所需模态、摄取前缀与离线语义判据，再另配小量请求。缺关键图像则 native HOLD；caption-only 必须另名，QA 不升级 A/P。Judge 另校准/分账；不能用 F1 或 substring 代替 |
| Supersede | 保留 native 的逐轮强制 notes、默认 300 字符截断和不重供旧会话；公共 MiLAi 持久化若接入须另名 `MILAI_ADAPTED_SUPERSEDE_NOTES_V1`，不改 A0 | 先对官方合成生成器冻结一条开发 timeline/seed 和合法答案集合，不访问既有保护 LME；语义校准后才分配 session 数+1 的请求。不得训练或把强制改写解释为自然保存。结束即 DONE，不报告恢复率 |
| ClawMark | Native 同一 OpenClaw session、多模态、多服务、分 stage checker。冷 Host 或以本地服务替身替代真实服务均另名 `MILAI_ADAPTED_CLAWMARK_ACTION_V1` | 先对已选 family 补全所需资产清单、完整 rubric 前提/澄清判据及一次真实隔离环境 reset；本次不批准资产全集/镜像/账号。未完成则仅继续局部无模型 checker 审查，不启动 native Agent；原生 dry-run 的 no-op exec 不算执行 |

WMA 的 [实际 loader](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/datasets/worldmemarena.py)
同时构造离线 gold 状态与 checkpoint；
[默认 answer factory](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/cli.py)
有回退风险；[QA evaluator](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/evaluators/qa.py)
有答案与检索证据 Judge 路径，必须独立配置和计量，不能假设通用 key 覆盖全部客户端。

公共 MiLAi 计划只用已发布的 `capture_evidence`、`browse_evidence/get_evidence_content`、
`write_note/get_note/get_note_operation` 等接口，先重新验证 product lock 与能力回执。
HARNESS_SOURCE_INGEST / HARNESS_SEED / AGENT_NOTE_MUTATION 分账；Note 不自动变 Canonical。
scope 与 operation ID 由可信 Host 绑定，冷恢复须新进程且声明允许文件/缓存，不继承旧消息；
提交版本、内容 hash、实际读取/发送均留证。
本次只是读过公开 SDK 的接口计划，没有 Product-backed effect run、SDK 安装或 pin 更新。

Stable/Helpful/Superseded/Conflicting 下一步必须在同 root 的合法环境关系中预先定义；
不能将四种标签当四个独立样本，也不能看到错误才改事件。Matched arms 的普通来源同样可用，
保留普通 Note、简单提醒、无 memory 的正常来源强基线；memory 副本、环境/缓存逐臂隔离。
这四套 benchmark 的局部检查不拼接成一条 P 链。

## 6. B4：分 Lane 准入终态

PROBE_ONLY 表示已找到明确但不完整的接线/诊断对象，**不是允许立即发布官方分数**。
HOLD 是缺制品、必要前提、模态、判据或 runtime 证据；不是被试语义失败。

| 候选 | C consumption | L lifecycle | A action-world | P persistent regulation |
| --- | --- | --- | --- | --- |
| Compliance Trap | HOLD：原作者任务/checker 待定位 | HOLD：自主写入/持久边界未取得 | HOLD：仅论文描述 | HOLD：全链制品与证据缺失 |
| WMA | PROBE_ONLY：QA/retrieval 消费，缺纠错动作窗口 | PROBE_ONLY：真实结构/标签边界已验；语义评分、模态/实际存储发送未验 | HOLD：本次接口为 QA，无动作环境真值 | HOLD：冷持久、自选保存、双呈现、动作恢复未验 |
| Supersede | PROBE_ONLY：有界 notes→QA；matcher 不准入语义主张 | PROBE_ONLY：强制重写过程，不是自主持久生命周期 | HOLD：原生没有动作世界/恢复窗口 | HOLD：持久/动作/恢复不满足 |
| ClawMark | HOLD：memory 来源与实际暴露未核验 | HOLD：同 session，持久恢复未核验 | PROBE_ONLY：两 family 的局部文件判据/模拟事件；完整 native runtime HOLD | HOLD：自写、冷恢复、双呈现与 memory 因果未验 |

ADMIT=0；P-LANE_ADMITTED=0。完成条件是“本次范围内的资格缺口有可复核结论”，
不是强行选出胜出者；不能外推为所有公开基准不适用、所有 Memory 机制无效。
后续最有价值的窄路径是 WMA 的 L 接线或 ClawMark 的完整判据/环境前提核验，
但都还不能直接开启所主张的持久记忆调控效果比较。

## 7. 重放、工程回归、失败与成本

重放入口（输出目录必须为新路径，保留旧证据）：

```bash
uv run python tools/check_v0217_admission.py --root <E> --output <fresh-fixtures-dir>
uv run pytest tests/unit/test_v0217_admission.py -q
```

`check_v0217_data_boundary.py` 使用 `E/fixtures-v1/event-replays.json` 与已冻结样本，
写 `data-boundary-result.json` 时拒绝覆盖；完整重放应复制输入到独立新证据目录。
`inventory_v0217_admission.py` 在样本下载前冻结 pool，输出同样拒绝覆盖；
不应在看过结果后重跑改池。原生源码未被修改，AST 提取不执行 task.py 模块顶层。
这些工具是 Lab 薄接线/可观察性，不是新增记忆机制或 Runtime schema。

工程回归：boundary PASS；pytest **777 passed / 1 optional SDK-wheel skipped**；
ruff `src tests tools` PASS；mypy 39 文件 PASS；build wheel/sdist PASS。
可选 SDK wheel 未安装，不能将此回归数改写到 V0216 的历史 767-test 记录。
工程绿灯不消除本报告记录的 evaluator 语义反例，也不是 benchmark 准入绿灯。

下载账本 54 次尝试、50 成功、4 个 TLS 失败；成功落盘 **2,279,406 bytes**，小于 24 MB 范围。
另一次完整 HF metadata curl 在 25 秒超时，部分传输 1,698,957 bytes、没有完整 JSON/hash，
保留单独失败记录；随后 limited metadata 成功。网络总字节（含浏览器检索和失败开销）未知，
不把落盘量冒充总网络费用。一次 QA evaluator 下载失败后成功，旧失败没有删除。
ClawMark journalist/task5 与论文 HTML 未取到，不按语义失败或不可用全集计数。

实验模型请求/输入输出 tokens、Judge、embedding、OCR/图像生成、业务写入、Product 存储调用均 0；
无新增付费调用，无 token cap。代理劳动与公共元数据 HTTP 不是实验模型 token 分母，
未伪造其精确费用。共享模型未重启，无自建服务需关闭，所有失败与开发材料保留在 Git 外。
[原始预审](MILA_V0217_BENCHMARK_PREFLIGHT_20260910.md)和 V0216 结果保持历史原文。

| Goal 阶段 | 本次交付 | 完成判定 |
| --- | --- | --- |
| B0 | §1 身份/制品/许可/依赖、hash manifest、受限下载及失败账本 | 有界审查完成，未知项保持 HOLD |
| B1 | §3 八维矩阵；§4 在线/evaluator/模态与观察合同 | 完成，不冒充 runtime |
| B2 | 40 项原生局部结果、11 反例、66 后置/隔离检查、11 单测与首失败修复记录 | 完成校准；非所有 evaluator 合格 |
| B3 | §5 四候选 native/adapted、公共接口/provider/资源最小计划 | 完成计划，完整 adapter 和模型 batch 未实施 |
| B4 | §6 分 Lane 结论与下一最小合同 | VALIDITY_GAPS_RECORDED，P=0 |
