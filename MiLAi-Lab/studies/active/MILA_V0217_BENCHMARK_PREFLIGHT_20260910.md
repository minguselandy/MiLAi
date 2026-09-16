---
document_id: MILA-V0217-BENCHMARK-PREFLIGHT-20260910
version: "0.1"
date: "2026-09-10"
status: PARTIAL_READONLY_PREFLIGHT_RECORDED
goal_version: "MILA-V02-17 v0.2"
mechanism_lane_admitted: 0
benchmark_task_runs: 0
new_model_generation_requests: 0
new_judge_requests: 0
local_provider_check: MODELS_ENDPOINT_ONLY
product_default: A0_UNCHANGED
schema_status: NO-GO FOR SCHEMA FREEZE
---

# V02-17：候选 Benchmark 公开制品预审

## 1. 结论与证据范围

**支持先审 benchmark validity；但目前不能直接把四个名称变成四套已就绪的行为基准。**
本次核对论文、官方仓库身份、若干关键源文件与许可证；复现两个纯函数判分反例，
并只读检查现有本地 vLLM 模型目录。未执行完整任务、未生成被试/Judge 答案，
未下载完整数据、拉容器、启用新服务或改 Product。不是独立重复论文实验。

执行入口是[V02-17 Goal v0.2](MILA_V0217_Benchmark_Discovery与行为真值准入_GOAL_20260910.md)；
旧 v0.1 N0/N1 计划停止作为当前任务，历史保留。最终 lane 准入仍待 fixture 和完整制品核验。

最需要防止的四个混淆：

1. 同名 MemTrapBench 对应不同论文，不能替换后仍沿用 231 browser tasks/E-P-R 的描述。
2. WorldMemArena 有 lifecycle 标签，但已检查的主 pipeline 产物是 session 记录和 checkpoint QA；
   不能直接当作 live action/recovery checker。
3. Supersede 的 notes 是强制有界重写；matcher 确定性不代表否定、纠正和引用语义正确。
4. ClawMark 多 stage 中复用同一 agent session，不自动证明真实跨冷会话记忆。

## 2. 身份、版本与可取得性

以下为 2026-09-10 通过 GitHub commit API 核对的代码 pin，不是数据集 hash。
数据与依赖未完整取得，所以不填“dataset verified”或 eligible 数量。

| 项目身份 | 本次代码 pin / 制品情况 | 许可及未决项 |
| --- | --- | --- |
| The Compliance Trap / arXiv 2607.10608v1，Yixiong Chen 等 | 本次有界检索尚未定位匹配的官方任务/runner；不是断言永久未公开 | 任务与代码许可未核实 |
| WorldMemArena / UCSB-AI | 15ea25b723d9c4fb35e8062037aec6a5601e4442 | 仓库 MIT；HF 数据许可/版本/完整清单仍待独立核验 |
| Supersede / Vrin-cloud | 677993d3713c265329ac935262d3c08cbfa4cd63 | 仓库 Apache-2.0；外接 LME/HF 数据的适用许可分开核验 |
| ClawMark / evolvent-ai | d1b641b3171e584e69a3763c269069f32a13b574 | 仓库 CC BY-NC 4.0；资产与实际研究/发布用途需核对 |
| 同名排歧：zjunlp/MemTrapBench / arXiv 2608.20202 | 02fc32a2b5ffecce893e353b29fcd49242ea71cf | 不是本次 2607.10608 候选，不自动纳入或继承许可 |

代码依据：[WMA commit](https://github.com/UCSB-AI/WorldMemArena/commit/15ea25b723d9c4fb35e8062037aec6a5601e4442)、
[Supersede commit](https://github.com/Vrin-cloud/supersede/commit/677993d3713c265329ac935262d3c08cbfa4cd63)、
[ClawMark commit](https://github.com/evolvent-ai/ClawMark/commit/d1b641b3171e584e69a3763c269069f32a13b574)、
[同名仓库 README](https://github.com/zjunlp/MemTrapBench/blob/02fc32a2b5ffecce893e353b29fcd49242ea71cf/README.md)。
许可分别见 [WMA LICENSE](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/LICENSE)、
[Supersede LICENSE](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/LICENSE)、
[ClawMark LICENSE](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/LICENSE)。

## 3. 候选逐项审阅

### 3.1 The Compliance Trap：消费机制贴近，但先解决制品身份

论文确实研究 Entry–Propagation–Recovery，描述 231 个长程 browser tasks、
DECOY/UPTAKE/GROUNDING/OVERRIDE 诊断族。Memory 为实验设置的外部文本，
按不同时间/重复呈现策略注入；这里的 persistent exposure 不能直接解释为冷会话持久存储。
其 compliance 评分包含 LLM Judge，也不能把全部 E-P-R 都称为零模型 deterministic scoring。
[论文正文与实验方法](https://arxiv.org/html/2607.10608v1)

检索论文题名、arXiv ID、MemTrapBench 与作者/项目链接后，未定位匹配的官方可执行包。
公开 zjunlp 同名仓库的 README 却指向 **2608.20202**，描述 1,050 个会话/最终问题实例，
与七月 browser benchmark 不同；不能据此填写原项目“代码已发布”。
[八月同名论文](https://arxiv.org/abs/2608.20202)、
[对应 README](https://github.com/zjunlp/MemTrapBench/blob/02fc32a2b5ffecce893e353b29fcd49242ea71cf/README.md)

当前为 ARTIFACT_IDENTITY_HOLD。下一步需要原作者匹配制品、任务模板、环境/reset、
评分/Judge 契约；如果只能依据论文复现，必须叫 THIRD_PARTY_RECONSTRUCTION，
不能冒称官方 benchmark，也不是本次已授权的自建任务工程。

### 3.2 WorldMemArena：生命周期诊断候选，不预判动作真值

论文描述 400 个多 session 多模态任务；本次检查的 CLI 帮助标 all=461/small=150。
这只是论文与 runner 的两种制品声明，完整数据未在本机枚举；不据此断言增长原因或合格题数。
[论文](https://arxiv.org/abs/2605.29341)、
[固定版本 CLI](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/cli.py)

pipeline 逐 turn ingest，end_session 后导出 snapshot/delta，覆盖 checkpoint 时 retrieve 再回答 QA。
session boundary 在这里是数据/adapter 边界，代码本身未证明独立 Host 进程冷恢复。
这可作为 L lane 的强候选，但未提供本次 P lane 所需的实际行动与偏离后恢复验证。
[runner](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/pipeline/runner.py)

两处必须进入适配防护：

- 默认非 harness 答题分支在 target.api_key 为空时返回 q.gold_answer。离线跑出“正确答案”
  可能只是该 fallback；当前不能用这种路径计算正确率。本次只做源码检查，未执行此分支。
- answer_fn 接收的 question 对象带 gold；retrieve 还收到 question_type_abbrev。
  在线 MiLAi 映射须白名单剥离 gold；类别路由如保留也需披露，不能暗加到普通 A0。

依据：[默认 answer_fn](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/cli.py)、
[QA runner](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/pipeline/qa_runner.py)。

QA evaluator 分别用模型 Judge 判断答案与检索覆盖，另算 lexical/ranking 指标；
harness 的 answer-only 也仍有答案 Judge。不能把 F1/ID 命中直接替换语义正确或动作真值。
[QA evaluator](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/evaluators/qa.py)

数据模型含 gold answer/evidence 和 memory/update 信息；loader 会把官方 attachment caption
并入文本，并尝试解析图像路径。caption 支持的文本结果不等于图像已呈现，也不能自动证明
text-only 等同 native multimodal。
[bundle loader](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/eval_framework/datasets/wma_bundle.py)

README 指向 HF 数据并说明约 10 GB 下载，本次未下载。HF metadata 大响应读取超时，
因此不声称已核实数据 sha、license 或全量文件。下一步先取得小型 manifest/许可和明确
开发样例，再决定是否值得准备环境，不直接调用 quickstart 全量运行。
[官方 README](https://github.com/UCSB-AI/WorldMemArena/blob/15ea25b723d9c4fb35e8062037aec6a5601e4442/README.md)

### 3.3 Supersede：可复用 supersession probe，但原生合同不是 A0

MemoryRollout 逐 session 要求模型完整重写 notes，按字符上限截断；后续只给 notes 和当前
session，最终仅给 notes 与问题。notes 保存在 rollout 对象里，不能直接叫 durable Note。
这能研究受限记忆中的事实替代，但改变了保存政策和原始来源访问条件，不能静默成为 MiLAi 默认。
[rollout](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/src/supersede/rollout.py)

env 默认以 answered_current 评分，Judge 可选；虽然另有 stale penalty 函数，
不能仅凭函数存在就称默认 rubric 已惩罚 stale use。
[environment](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/src/supersede/env.py)

本次读取固定版本 reward.py 后，在本地 Python3 隔离模式仅调用其纯函数，得到：

| 函数/输入（开发反例，不是 benchmark 样本） | 实际返回 | 局限 |
| --- | --- | --- |
| answer_matches("I do not live in Boston. I still live in Seattle.", "Boston") | true | 仅提到被否定的正确值也能命中 |
| stale_use_penalty("I used to live in Seattle, but now I live in Boston.", ["Seattle"]) | 1.0 | 引用并纠正旧值仍被计 stale |

这是两项**判分函数反例**，不是模型失败或 Supersede 总体无效。
第一次使用 python 命令因本机无该别名失败；改用 python3 后退出码 0，模型请求 0。
原函数使用 substring/token overlap 或旧值出现检测，语义适用范围必须由 evaluator contract 限定。
[固定 reward.py](https://github.com/Vrin-cloud/supersede/blob/677993d3713c265329ac935262d3c08cbfa4cd63/src/supersede/reward.py)

当前为 QA_PROBE_CANDIDATE / EVALUATOR_CALIBRATION_REQUIRED。最小下一步是正负 fixture
与 native/modified 合同，不训练模型、不先把它扩成完整行动/恢复 benchmark。

### 3.4 ClawMark：动作环境候选，但冷边界、反馈与资源要实查

README 描述多日环境变更、任务级 Python checker 和 Docker/服务接线；
同时提供的某些 Notion/Sheets 流程需要配置凭据，不能假定全部后端天然本地无账号。
[固定 README](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/README.md)

实际 orchestrator 顺序执行 stage_fn → Agent → workspace snapshot → stage checker，
最后再执行 final checker；同一 Orchestrator 的各 stage 使用同一 session_id。
stage checker 结果进入评分记录，不等于已向 Agent 提供纠正证据；
recovery opportunity 必须在任务的实际后续事件中另查。
[orchestrator](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/src/clawmark/orchestrator.py)

loader 动态执行 task.py，再读取 stage/RUBRIC；不能以“零模型”推定导入和 dry-run 无副作用。
本次未加载官方任务模块、未执行其 checker；论文 1,537 checker 数亦未本地复算。
[task loader](https://github.com/evolvent-ai/ClawMark/blob/d1b641b3171e584e69a3763c269069f32a13b574/src/clawmark/task_loader.py)、
[论文](https://arxiv.org/abs/2604.23781)

当前为 ACTION_WORLD_CANDIDATE。下一步选择已披露的开发家族验证事件/reset/checker，
查真实用户数据隔离、外部服务和许可证，最后才考虑改变 session 生命周期的 adapted profile。
不能把跨 stage 成功直接计作跨冷会话持久记忆收益。

## 4. 初始 research-fit matrix

P=论文描述；C=已查关键代码；F=本地纯函数检查；?=未证实；A=需要适配。
下表不是布尔功能承诺，所有 runtime 级完整行为链仍未验证。

| 维度 | Compliance Trap | WorldMemArena | Supersede | ClawMark |
| --- | --- | --- | --- | --- |
| Host 自选记忆内容 | 外部注入 P | adapter 摄取 C，自选写待查 | 自产但强制重写 C | 是否自然保存待查 |
| durable / 冷 session | ? | end_session C，冷/持久 A | 内存对象 C，持久 A | 同 session C，冷 A |
| 外生变化 | OVERRIDE P | session/update 标签 C | 时间线更新 C | stage 接口 C，逐题语义待查 |
| memory 实际呈现 | 注入调度 P | answer 输入接线 C，实际发送待验 | notes prompt C，实际发送待验 | ?，需 trace 接线 |
| 反事实/冲突 | P | A | stale/current C，配对 A | A |
| 动作真值 | browser 设计 P | 已查主线为 QA | 已查主线为 QA | checker 调用 C，正负 fixture 待验 |
| 偏离后恢复机会 | P | ? | 原生 QA 结束，A | 逐题后续机会待查 |
| 阶段归因 | E-P-R P | session/QA records C | reward 反例 F | snapshot/checker C |
| 当前限制 | 匹配制品待定位 | gold/Judge/模态、无已验动作链 | bounded 政策与 matcher | session、环境、评分与许可 |

完整 P lane 已准入 **0**。这不是“0 个可用 benchmark”的结论，而是本次尚未完成运行级准入。
可以并行推进不同候选的已知缺口；不把第一项的制品缺口变成全项目等待。

## 5. 本地 vLLM：可用的配置路径，不是缺云端 key 的阻塞

现有 [Lab Provider](../../tools/v0213_provider.py) 固定到 127.0.0.1:7860。
本次用进程级不走代理的 GET /v1/models 检查：

- 不带 Authorization：成功返回 Qwen3.6-35B-A3B-FP8，max_model_len=65536。
- 带非秘密兼容占位 Bearer：返回相同模型目录。
- 未 POST chat/completions，未调用 Judge，未修改或重启服务。
  目录可达不是模型工具调用、图像、生成用量或真实 API key 鉴权验收。

用户已同意使用本地 vLLM，Goal 采用显式 base_url/model/api_key_env 映射。
非空占位只用于无鉴权隔离服务的客户端兼容；真实鉴权用服务端匹配的秘密 key。
官方说明 vLLM 可配置 API key，但并非所有端点受保护，仍需受限网络边界。
[官方接口与 API key 边界](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)

对 WMA 不能只“填个 key”了事：必须验证确实走本地模型，错误配置失败关闭，不返回 gold，
不回退远程供应商；Judge/嵌入/视觉子客户端也要逐一显式接线和计量。
若以后用本地 Judge，结果需说明不是官方 evaluator 条件，且不把模型判分当无误真值。

## 6. 本次保留与下一步

本次改动仅文档/索引；未运行任何候选 benchmark、未编写新的 State 或适配器实现。
已有用户代码、原始轨迹和失败不改写；读取制品/协议算开发暴露，不称 untouched confirmation。
未打开旧 Horizon/Mem2Act 保护池，未购买 API、未下载整包或访问真实业务账户。

下一步优先完成可阻止假阳性的零模型工作：

1. 七月 MemTrap 制品身份；找不到就保留 HOLD，不换成同名项目。
2. WMA gold/类别/模态边界及 fail-closed 计划，明确只到 lifecycle/QA 的原生主张。
3. Supersede 正负判分 fixture 与原生 notes-only 限制。
4. ClawMark 小型开发家族的 checker/reset/外生事件/恢复机会及隔离资源评估。
5. 在具体 candidate/lane 合同合格后再分配本地小型生成探针，而非直接开始算法比较。

Lab 离线检查：boundary、ruff、mypy（39 文件）、build 均通过；
pytest **766 passed / 1 optional SDK-wheel skipped**。未装可选 wheel，不改写旧 767 记录。
这些检查不是四套 benchmark 的测试结果。无 Product 实现/权限/Schema/Canonical 改动，
故未重跑 Product 包、PG 和公网验收；无迁移/部署回滚。本次新增模型生成与 Judge 均为 0。

