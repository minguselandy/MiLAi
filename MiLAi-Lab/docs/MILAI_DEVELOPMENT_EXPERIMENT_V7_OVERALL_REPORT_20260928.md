# MiLAi v7 总体开发与实验报告

**首批 P0/P1/E1 已执行完毕。**现有 JSON 路径 J 完成 12 条预定微轨迹、26 条公开消息，
92/92 条任务义务通过；native N 的 12 条轨迹因现有服务未启用自动工具解析而未运行。
因此本轮协议比较为 **INCONCLUSIVE / N: BLOCKED_ENVIRONMENT**，不能宣布 native 改善或选择新默认协议。
工程接线已完成，当前 JSON 在这批有限诊断中可用；整体记忆方法的稳定 unseen 收益仍未建立，Product **NO-GO**。

本报告依据[原 v7 计划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_20260928_v7.0.md)、
[架构复盘](MILAI_MEMORY_ARCHITECTURE_REVIEW_20260928.md)和[执行记录](MILAI_DEVELOPMENT_EXPERIMENT_EXECUTION_V7_20260928.md)。
原设计文档字节、v6 失败及全部旧账本保留。本轮实际授权先开放 P0/P1/E1，未自动扩展到后续条件分支。

## 1. 身份、环境与冻结

| 项目 | 已核实身份 |
| --- | --- |
| 基底 | `c6f335fef7cf00c86fa3dbe201a60c802439ca12`，v6 完整报告提交 |
| 源码 A | `37d48577bdff582f74faf2f5e663b359885350ec` |
| 输入／实际运行提交 B | `2f30c14c5e7ea82db2b0a962d3636e14de5f2391` |
| 发布 | [draft PR #71](https://github.com/minguselandy/MiLAi/pull/71)，依赖仍未合并的 v6 PR #70；main 未改 |
| 执行 freeze SHA256 | `d46e343951e22d83f5691986bf38ac99bdeff29a1dd113408281db2cd9c0b467` |
| Host | Qwen3.6-35B-A3B-FP8，vLLM 0.27.1，7860，65536 容量 |
| 请求 | temperature=0，max_tokens=4096，enable_thinking=false，无 seed 改动，HTTP 并发 1，每消息最多 12 次生成 |
| Embedding | bge-m3，7861，1024 维 |
| 配方 | B0 / strict / retained / current_request / compact_v6 / host_direct / 原始业务接口 |
| 依赖 | Python 3.11.13、LangChain Core 1.6.5、LangGraph 1.1.10、LangMem 0.0.30；锁文件及完整版本见检查清单 |

部署 config、tokenizer.json、tokenizer_config.json、chat_template.jinja 与计数资产的四项 hash 一致。
完整权重 revision 未独立取得，不能把模型名说成完整权重校验。
[能力清单](../data/diagnostics/development-experiment-v7-p0/protocol_capabilities.json)保存服务 flags、安装源码与资产 hash。
实际服务无 `--enable-auto-tool-choice` / `--tool-call-parser`，安装代码也不会在该配置下输出自动解析的 `tool_calls`。
没有用无效生成试探、重启共享服务、改 parser/template、下载权重或部署新模型；也没有发明第三种客户端协议。
模型模板支持工具、parser 已安装，不代表部署已启用。

两协议保留相同合法内容、权限、工具名称／能力和执行校验；允许目录表示、模板标记、envelope、调用 ID 和 tokens 不同。
JSON 的解码 `answer` 与 native 的最终自然文本使用同一用户义务。N 未实际运行，不能声称两组真实行为等价。
所有 24 个身份在已发布 B 上零模型 prepare 后冻结；N 的环境阻断已事前登记，J 沿既定顺序各执行一次。
每 job 独立 run_id、owner namespace、Store、checkpoint 和业务数据库，全空开始；没有 operator memory 或世界预填。
原用户文字、当前 owner、交付 ID，以及所有后续使用中的正确记录正文均已核对到实际 HTTP。
评分说明仅由 Root 离线使用，未进入 runtime，没有在线 Judge、自动补写或最终答案改写。

## 2. 开发结果与验证

首个实际工程断点是 native 绕过 request_view.project、fit_final_request 和 delivery，且 runner 原来只接受 JSON。
竞争解释一是局部协议接线缺失；解释二是模板目录、容量、解析和执行调度也存在独立契约，单改 tool_mode 不足以比较。
最小修复复用 RequestContext/Renderer：共同合法投影 → 协议编码 → 含 native tools 的真实容量核算 → 同一同步 ToolNode → 实际回执／交付。
只改发出请求的副本，原 checkpoint、历史和工具 JSON 不变；不增加新 runtime、持久状态层、writer 或 selector。

P1 为 5 个源码文件、3 个既有测试文件、2 个配方。56 个去重窄测通过（Core 20、Foundation 36），
131 个历史请求分别在 full/compact 回放，86 项审计和 checkpoint hash 保持。
回放比较有序实际请求在锁定 HTTPX 下的编码与 MockTransport 字节，没有原始 socket 抓包；不重复计作新模型实验。
覆盖无工具、单／多工具、拒绝与续接、同 ID 更新、删除后读、owner、partial、坏参数／截断／重复 ID，
以及实际 tokenizer/tools 容量、同步调度和旧 query/Attention/C 邻接路径。Ruff、Mypy、矩阵与依赖边界均通过。
详见[工程报告](MILAI_V7_P0_P1_ENGINEERING_REPORT_20260928.md)及[P1 检查清单](../data/manifests/development-experiment-v7-p1-checks-20260928.json)。

P0/P1 本地检查未使用真实 Host/embedding/Postgres；实际 ToolNode 使用本地 SQLite 和模拟 provider，不能冒充真实 native 语义成绩。
初次两项测试 harness、19 项 lint 和两项 typing 问题已保留并局部修复；不为发布重复完整回放。

**发布后的 CI 缺口：**B 的 Fast `36422762879` 中 foundation 模块为 36 passed / 1 failed，
失败是新增真实 tokenizer 测试在 GitHub runner 缺少 `/cra/qwen36-35B`，不是 Host 推理失败。
这是本地资产测试未正确登记／缺失时未明确跳过的接线问题。Sol 仅补 `local_artifacts` 标记、缺目录时的明确 skip
和矩阵归属；现有目录仍校验原 hash／模板，不隐藏资产损坏。实际资产下目标测试 1 passed，
缺资产分支、矩阵、Ruff 和 diff 检查均通过；没有重跑 56 测试、131 回放或 E1。
修复提交 C 为 `a1c6c683a39e8d0bf87e75afec32061fae46dfd4`，见[独立检查回执](../data/manifests/development-experiment-v7-ci-repair-checks-20260928.json)。
实验 B、其输入和 runtime 源码继续冻结。C 的 Fast `36425412512` 状态待最终发布核对；Full `36425412508` 按工作流跳过。

## 3. E1 完整结果

六种合成意图结构、两个预定重复、两个计划协议，共 24 条轨迹／52 消息。
实际 J 为 12 条／26 消息／22 session；N 为相同数量未运行，不能算失败，也不能从计划分母消失。
六种结构是任务单位；重复、同链消息和义务不是新的独立样本。新实例继承已暴露的意图结构，不称自然用户或稳定 unseen 证据。

| 结构 | 重复 1 任务 | 重复 2 任务 | 生成 tokens：R1 / R2 | 核心实际证据 |
| --- | ---: | ---: | ---: | --- |
| 保存计划，不执行业务 | 6/6 | 6/6 | 3,828 / 3,813 | 实际 CREATE；新 session 得到完整计划 |
| 修改原事项、保留其他条件 | 13/13 | 13/13 | 7,237 / 7,204 | 两独立事项形成；原计划同 ID 更新；其他内容保持 |
| 查询业务当前状态 | 7/7 | 7/7 | 5,153 / 5,139 | 一次预约／标签，随后真实 exact-key lookup，实际 ID 匹配 |
| 普通只读问答 | 3/3 | 3/3 | 1,092 / 1,086 | 正确纯数字答案，零工具／零写入 |
| 被拒绝的命令式引文 | 6/6 | 6/6 | 2,321 / 2,313 | 引文未采纳，无记忆／业务副作用，后续任务正确 |
| 临时格式＋恢复长期偏好 | 11/11 | 11/11 | 5,127 / 5,143 | 长期格式真实保存；临时段落不写入；随后恢复两条 bullet |
| 合计 | **46/46** | **46/46** | **24,758 / 24,698** | J 共 12/12 条轨迹通过 |

四层义务分别为：current_explicit **52/52**、later_use **8/8**、persistent **32/32**，
另记录 **26 条非任务失败诊断**，未观察到额外不必要读取。显式当前＋后续合计 60/60，任务总计 92/92。
离线复用既有 `obligation_trace.compose_obligation_trace` 合并人工结果，两次各 46/46，全部可见依据校验通过。
首次直接组合报 `INVALID_OBLIGATION_LAYER`：冻结文件使用 `diagnostic_obligations`，既有组合器名称为
`diagnostic_completeness`。仅在报告端内存副本映射这一非任务层名；原文件、义务、依据和人工分数均不改。
这项汇总格式修正及输出 hash 记入[需求审计](../data/manifests/development-experiment-v7-requirement-audit-20260928.json)，无新增语义评分或模型调用。
18 条不写记忆消息均无 mutation attempt 或内容改变。没有假保存／假更新、越权效果、失败后替换题目或重试挑选。
不同重复的输出文字和 tokens 有少量差异；运行时 IDs／历史也不同，不能据此归因于某个服务非确定性原因。

逐义务分数、provider IDs、真实工具参数／回执、记录和交付 IDs、world、成本及 trace hash 见
[完整精简结果](../data/manifests/development-experiment-v7-e1-results-20260928.json)。原始 HTTP／轨迹、数据库与 DSN 保持 ignored。

## 4. 七层结果与条件化分母

| 层 | 观察与限制 |
| --- | --- |
| 意图／动作选择 | 12/12 个需要操作的消息出现所需动作；合法不写入情形通过。没有强制 required |
| 参数 | 14/14 个实际必要工具调用的 ID、完整 key、数量、范围和内容正确；其中形成两事项的消息各发两次 CREATE |
| 执行 | 正确参数下 14/14 实际执行符合合同：8 CREATE、2 UPDATE、2 reserve_and_label、2 get_reservation |
| 持久记忆 | 32/32 义务；形成 8 个不同真实 ID；两次更新保持原 ID，无冲突副本或独立事项丢失；E1 无删除任务 |
| 当前回答 | 52/52；保存／更新确认与真实提交一致；格式、引文和实时世界陈述正确 |
| 后续任务 | 正确内容已持久化且实际交付时 8/8 后续义务通过，分布于 6 个后续消息；真实业务查询另列 2/2 |
| 资源 | 38 generation、10 embedding；所有失败／unknown／观察成本按实际保留，无新 selector 或纠错入口 |

这些比例不是可相乘的独立概率。14 个调用不等于 14 个独立任务；同一正确记录可能承担多个后续义务。
E1 的同 ID 更新为 2/2，实时 exact-key 查询为 2/2；真正的部分副作用、未知外部结果恢复和跨 owner 攻击
未在 E1 自然激活，只保留 P1 工程检查，不能声称真实 Host 已具备这些能力。
38 次 delivery 均走 all，最大普通记忆规模很小，没有触发新的查询／容量瓶颈或独立 Attention 比较。

## 5. 全部实验成本与效益边界

| 阶段 | generation calls | 输入 tokens | 输出 tokens | generation 合计 | embedding calls / tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| formation | 12 | 16,072 | 586 | 16,658 | 8 / 238 |
| maintenance | 4 | 5,588 | 241 | 5,829 | 2 / 56 |
| business（初次执行） | 4 | 4,949 | 219 | 5,168 | 0 / 0 |
| use（含后续 live lookup） | 18 | 21,222 | 579 | 21,801 | 0 / 0 |
| **总计** | **38** | **47,831** | **1,625** | **49,456** | **10 / 294** |

实际 HTTP wall 合计 **19.03s**；12 个运行器子进程 wall 合计 **65.45s**，包含加载等本地工作。
这是运行过程测量，不含 Root 离线核查、开发、CI 和等候，不称为完整产品用户时延。
观测到 76 次 ordinary-memory 读取（9004 logical bytes）、36 次 namespace guard 读取、26 次 checkpoint 读取
（45723 logical bytes）；operation audit 额外 checkpoint reads 为 0。客户端读／审计 CPU 和 wall 细项在结果清单。
这些不能替代数据库写入 CPU、物理 IO、GPU 小时或货币费用，未独立计量的项为 unknown。
此 ordinary-memory 路径的 LocalStateBank stats 为空，不代表存储工作为 0。

本轮 HTTP error、未知 generation/embedding usage、截断、容量拒绝、额外重试均为 0。
服务未独立返回 reasoning token 数，记 **UNKNOWN_NOT_SEPARATELY_REPORTED**，不填 0，不重复加到 completion。
N 为事前阻断，generation/embedding calls 为 0；这表示未运行，不能说更便宜。
P0/P1、CI 修复和离线评分无真实模型调用。开发代理 token 与本表分开。

连续账本从 **3263 / 4,155,747 / 23,276** 增至 **3301 generation calls / 4,205,203 generation tokens /
23,570 embedding tokens**；delta 与 38 个独立 provider IDs 及全部 trace usage 完全一致。
末账本 SHA256：`f9efa35e1a83f4c4300f03f28394a584868f8955b320e960dc3f8bb7a4ce1592`。
所有嵌套历史账本原样保留，无清零或重算旧失败。

投入在事前 J 的 26–90 calls、约 40k–150k tokens 估算内。当前成本覆盖整条任务和后续使用，而非只选成功片段。
因 N 缺席且 v6 任务不同，**没有可估的协议成本效益差或相对压缩收益**。历史编码回放保留的 6870 token 差额
不是新 v7 实验节省，不能再次累加。通过的 J 只是可用诊断基线，不是本次算法收益。

## 6. 反例、首断点与方法反思

本批新 E1 未出现任务失败；以下 v6 反例完整保留在[P0 失败链](../data/diagnostics/development-experiment-v7-p0/failure_chain.json)，
小批通过不能将旧反例注销。

| 反例 / Expected | 实际链与首断点 | 两个竞争解释 | 混杂、最小下一步与决定 |
| --- | --- | --- | --- |
| 明确保存应持久化 | H/I 首响应声称已保存，零 CREATE、空 Store，后续无计划；首断点为动作选择 | 自定义表达／compact 视图使终答更易；Host 没正确履行保存意图 | 本轮 J 可保存不排除旧失败；缺 N 对照，协议原因未定。未来先解决协议环境，当前 slice Stop |
| 完整 key 应原样使用 | H 实际预约把复数改为单数并提交；首断点为参数生成 | Host 习惯性词形规范化；字符串引用接口加重选择负担 | E1 两次 exact-key 成功不足以排除偶发失败。对象适配 E3 留作单独接口比较，不自动开发 |
| 实时查询应读业务 | H 明确查真实状态却只发两次 memory search；首断点为工具选择 | 上游缺计划使 Host 提前停止；混淆 memory 与 live world | 本轮不依赖 formation 的业务链 2/2 通过，旧混杂仍在。保留独立查询分层，不据此宣布解决 |
| 部分副作用应真实激活再评价 | I 漏存后无法预约，partial 未激活；末次 lookup 正确 not_found | 上游形成断裂；执行器与 Host 的 partial 能力是不同问题 | 原缺席分支评分修正及前序失败保留；E1/P1 不能替代 E5 真正恢复链。Not run，不算失败能力通过 |

工程中另观察到两个真实断点：native 未走共用投影已修；服务无自动解析以环境阻断保留。
CI 的 tokenizer 缺目录属于测试资产归属，不应归因为模型或材料质量。
这些分层避免把协议、对象、写入责任和工作视图合并成一个失败解释。

H1“协议表达是主要原因”仍未识别；H2“Host/工作视图/接口负担也会致错”未被本次简单任务推翻。
当前没有证据要求新增同步 writer、对象平台或 selector。实际额外调用应看完整生命周期收益，不能先验认定有益或有害。
State–Attention 的研究方向保留，但协议／工程通过不算 Attention 效果；不降低预算制造触发。

## 7. 全部需求与后续状态

| 计划要求 | 本轮状态／证据 |
| --- | --- |
| P0 完整计划／复盘、能力、四首断点、连续成本 | COMPLETE；原文 hash、能力／失败清单，无新增 P0 模型调用 |
| P1 共用材料、旧 JSON 兼容、真实目录容量、执行语义 | COMPLETE_ENGINEERING；56 窄测、131 双视图回放／86 审计，旧扩展边界显式 |
| E1 冻结范围／重复／顺序／权限与真实链 | COMPLETE_FOR_RUNNABLE_J；12/12，92/92；N12 BLOCKED_ENVIRONMENT，协议 INCONCLUSIVE |
| P5 七层／四层／条件分母、完整成本、反例、复现与审计 | COMPLETE_REPORT；本报告＋[逐项需求清单](../data/manifests/development-experiment-v7-requirement-audit-20260928.json)，无选成功轨迹或运行时 gold |
| E2 推理模式 | NOT_RUN；首批范围外，未改变 thinking 或输出容量 |
| P2/E3 对象引用 | NOT_RUN；未把接口改动掺入协议实验 |
| P3/E4 同步写入子任务 | NOT_RUN；本批无漏存，旧反例仍在；未引入第二 writer 或关键词保存 |
| P4/E5 连续任务／真实 partial/unknown 恢复 | NOT_RUN；短诊断不代替综合验收 |
| E6 State–Attention | NOT_TRIGGERED_THIS_SLICE；未构造密度压力，未进行选择器比较 |
| 第二模型家族 | NOT_RUN；未部署／下载，当前仍单一模型家族证据 |
| 长期研究目标、稳定 unseen、Product | NOT_ACHIEVED / 未建立 / NO-GO |

按计划 §14.4、§15.3，本 slice 可以在明确环境限制下结案：至少一个合法完整投影和真实执行路径已验证，
保存／no-write、记忆／业务、参数／执行分别评价，未运行项与方法未定清楚。
**停止本 slice 的进一步实验，不自动开启 N、E2–E6、旧 v19/v27 或新服务。**
如以后选择完成 native 比较，需先明确隔离的服务差异，再用新 run/config 身份冻结；既有 E1 样本已暴露，不能重新称 unseen。
这不等于总开发目标完成，也不撤销 v6 对其 compact 候选的失败结论。

## 8. 复现与发布边界

复现此次实际实验应检出 **B `2f30c14c`**，不是把后来的报告提交当成运行身份。
使用其 `uv.lock` 的 baseline-langmem 环境、[E1 协议](MILAI_V7_E1_PROTOCOL_20260928.md)、两配置、六输入、
[顺序](../data/diagnostics/development-experiment-v7-e1/execution-order.json)及冻结义务／guide。
现有 `tools/run_persistent_memory.py prepare` 和 `run-phase` 已能逐 job 执行，Root 编排只调用该入口。
例如使用 order 中的 json-action config、save_plan-inputs、B0、phase0，指定新的 run 和 runtime-root，
在已具备相同模型／模板／embedding 的环境下注入自己的 `MILAI_LANGMEM_POSTGRES_DSN`。
每 job 新 namespace/Store/checkpoint/world，不能覆盖本次 attempted 目录或复用已污染状态。
本机账本继续追加；外部复现需使用自己的明确新身份账本，不能伪称接续或重置本次权威账本。

ignored `artifacts/development-experiment-v7/e1/` 保存24份 prepare、完整 freeze、12份 N 阻断记录、
12次 J 运行及 Root 逐义务 review、前后账本、原始 trace/world/checkpoint 和成本核对。
公开结果列出源码／输入／工具合同／检查／原始证据 hash。全文义务在 Git 中可审阅，运行时不可读它们。

仅公开源码、配置、合成输入／评分、精简证据和文档；DSN、原始私密 HTTP、数据库、环境、资产、构建产物继续排除。
Root 负责文档／输入／串行实际调用／离线评分，Sol xhigh 负责源码和局部 CI 修复，Luna high 负责提交推送。
原 v7 文献表的12处 Markdown 硬换行尾空格按原文例外保留，original/current/staged 字节核对一致；没有为 lint 改原计划 hash。
最终发布和远端检查记录于执行文件；PR71 保持 draft，未合并 main，旧树和 v27 草稿保留。
