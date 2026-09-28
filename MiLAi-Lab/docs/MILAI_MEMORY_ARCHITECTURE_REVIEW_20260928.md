---
title: MiLAi 记忆架构复盘与可实施设计
version: architecture-review-1.0
date: 2026-09-28
status: RESEARCH_AND_DESIGN_ONLY
basis_commit: c6f335fef7cf00c86fa3dbe201a60c802439ca12
scope: MiLAi-Lab
code_modified: false
experiments_started: false
product_status: NO_GO
---

# MiLAi 记忆架构复盘与可实施设计

> 结论：保留已经完成的 Store、来源、Request Assembly、隔离和执行回执；先校准模型—工具接口，再使明确的记忆工作能够在真实执行后结束。State–Attention 继续存在，但不承担补救漏调用、修正业务标识或认证事实的全部职责。

本文件根据截至 2026-09-28 取得的 MiLAi 冻结报告、选定源码、论文全文和官方项目资料编写。它是设计与诊断建议，不是已经实现的系统、实测改进或实验启动授权。未修改 GitHub、未运行模型、未改变旧 Goal 状态。

## 1. 证据范围

### 1.1 本轮直接读取的 MiLAi 内容

- 固定提交 `c6f335fef7cf00c86fa3dbe201a60c802439ca12` 的 S4 独立任务报告。
- 同提交的 `src/milai_lab/providers/langmem_chat.py`，包括 `_action_schema`、`_action_prompt`、`_json_action_history` 和实际请求生成路径。
- v6 总体报告的阶段、失败、成本与冻结边界，结合当前对话中已取得的原文。

原始私密 HTTP traces、数据库与完整执行环境没有在本轮重新取得或运行。报告列出的精简轨迹支持定位，但不能替代原始服务审计。

### 1.2 实际读取的外部源码

| 仓库 | 文件 | 本次读取返回的 blob SHA |
| --- | --- | --- |
| langchain-ai/langmem | `src/langmem/knowledge/tools.py` | `769325d953db392b60006fbbce318824e8b6c4c4` |
| mem0ai/mem0 | `mem0/memory/main.py` 的 add 与形成路径 | `e750edbf19b4ed20b12d11118f2831ce6d700f6c` |
| QwenLM/Qwen-Agent | `qwen_agent/agents/assistant.py` | `a1ab161eb32b61a6d49caff40bdce9e231e4681d` |
| QwenLM/Qwen-Agent | `qwen_agent/agents/fncall_agent.py` | `0135a6f230128d1af336c01e6b4e3ea31c6316b3` |

这些是选定代码路径，不是完整项目审计。上游 main 会改变；真正接入前应再次固定 commit、依赖和许可。SimpleMem 本轮核验到论文全文，所尝试的 GitHub `core` 目录未取得内容，不能声称已经复现或审计其当前源码。

## 2. 当前事实和不能推出的结论

S4 为 10/12 脚本、166/193 任务义务通过。两次首次保存请求没有发生 CREATE，却返回保存确认。后续还出现完整业务 key 被单数化、明确状态查询未调用业务查询工具。第一次漏存发生在 Store 和执行器介入之前。[M1]

四次首响应诊断得到 full 2/2 合法 CREATE 提案、compact 1/2；其中相同 compact 前缀产生两种动作。没有执行这些提案工具。因此：

- 不能把合法提案计为持久化成功。
- 不能宣布 compact 是唯一原因。
- 不能宣布 full 已经恢复完整生命周期。
- 不能把同一次形成失败造成的多项后续失败当作多个独立根因。
- 实际部分副作用没有发生，该能力仍是 NOT_ACTIVATED，而非通过或已证明失败。

当前稳妥结论是：来源和存储的基础功能有证据；开放自然语言请求到正确动作的策略仍不可靠；额外材料处理的收益尚未从模型接口与任务复杂性中分离。

## 3. 对此前设计判断的修正

### 3.1 少调用不等于可用

零额外控制调用不是必须坚持的科学原则。一次有明确用途、能够提高端到端成功率的调用可能值得；无依据的循环反思则不值得。应比较完成同一任务所需的总成本，而不是先限制算法只能用几次调用。

### 3.2 单一 Host 不等于必须在一个无状态选择中完成全部职责

同一模型可以在一个 ReAct 循环中执行不同子任务。不可取的是两个独立维护者无协调地改写同一事项，不是任何阶段性处理都被禁止。

### 3.3 State 可以包含有依据的工作事实

“State 绝不保存事实副本”过于绝对。工作状态可以缓存正在使用的计划、工具结果和解释，但要附来源、观察时点或记录版本，并有失效规则。问题是独立写入责任与过期使用，不是出现了第二份显示文本。

### 3.4 动态业务状态可以进入记忆

已发生动作、结果、失败经验和最后观察都具有长期价值。必须区别“某次观察为真”“当前仍然如此”“计划希望如此”。不能通过全面禁止记录动态结果来回避执行后维护。

### 3.5 语义可靠性不能由类型系统代替

JSON 合法、UUID 存在、工具成功都不证明目标选择和正文正确。另一方面，模型也不应该重复计算程序已知的执行身份和状态。

### 3.6 完成一轮诊断与停止研究方向不是同一决定

保留已经冻结的 Stop/Pivot，不重开旧结果。未来有明确授权时，仍可以针对同一假设做有上限、可区分解释的修复。程序错误、模型使用问题、随机性、任务评分和机制无收益应分别判断，不再“一失败就换方法”。

## 4. 论文与项目带来的设计依据

| 工作 | 实际机制 | 对 MiLAi 的启发 | 不应照搬或宣称 |
| --- | --- | --- | --- |
| MemGPT，2023 [R1] | 分层上下文，模型调用记忆操作，系统事件和控制流配合 | 记忆不只是一个向量库，需要与实际执行循环衔接 | 有分层和中断不代表自由文本保存意图已可靠 |
| LangMem 官方文档与代码 [R2,G1] | 工具式主动记忆与独立形成流程分别支持；Store 与语义变换分离 | 写入责任可以有明确边界，不应全靠临终自报结果 | 暴露工具不等于模型掌握调用策略；上游宽合同不能冒充严格更新 |
| Mem0，2025 [R3,G2] | 论文采用抽取与更新，依据新对话和相关旧记忆选择操作 | 以“新材料＋相关旧记录”限定写入问题，不让写入器重写全库 | 本轮所读 main 默认是 additive extraction；不能当作原论文完整更新复现 |
| SimpleMem，2026 [R4] | 结构化压缩、会话内综合、意图相关检索 | 独立可读条目、形成与取材分别优化 | 名称中的 lossless 不是任意事实无损证明，也不能保证 Host 执行业务正确 |
| A-MEM，2025 [R5] | 结构化笔记、链接形成、记忆演化 | 多事项联系可以保留，当前不需完整图数据库 | 图链接不解决零 CREATE 或错误业务 key |
| AgeMem，2026 [R6] | 将长期与短期操作放入策略，通过分阶段 RL 学习 | “工具会执行”和“模型会选工具”是两类能力 | 不应据此立即开始大规模 RL，也不能把免训练自动等同更先进 |
| MemR³，2025 [R7] | evidence–gap 状态和检索／反思／回答控制 | State 应对应真实缺口，逐步取得材料 | 它主要解决取材，不是漏写和副作用执行的万能修复 |
| LeanMem，2026 预印本 [R8] | 按资料性质区分 profile/event/source-grounded record，选择性维护 | 不同内容可采用不同维护强度与保真要求 | 不同数据集上的作者成绩不能预测 MiLAi 业务效果 |

本表是机制研究，不是性能排名。Qwen-Agent 作为模型工具调用的校准参照，不冒充完整长期 Agent Memory 系统。[G3]

## 5. 首先修模型—工具接口，不先改 Memory Store

### 5.1 当前实际接口

MiLAi 当前要求模型输出：

```json
{"answer":"..."}
```

或：

```json
{"calls":[{"name":"manage_memory","arguments":{}}]}
```

`_generate()` 调用 `_action_schema(..., generation_only=True)`。此时工具名称受约束，但 `arguments` 仅为一般 object；具体参数在后续执行入口校验。协议完整写在 system catalog 中。[M2]

这不等于已经发现一个必然导致失败的 bug。它意味着应检验：自定义 JSON 分支与模型原生工具协议之间是否存在使用成本和动作选择差异。

### 5.2 正确的校准对象

Qwen3.6 官方模型卡推荐 Qwen-Agent，并给出 vLLM 原生工具调用、thinking 与 non-thinking 用法。该模型不应直接沿用别的 Qwen 版本的软开关假设。[R9]

vLLM 官方文档明确：结构化调用保证可解析，不保证高质量或正确调用意图。[R10]

下一轮如获授权，先做三个有限条件，不改变记忆算法：

1. 当前 custom JSON-action + 当前 non-thinking 配置，作为历史参照。
2. 同模型、同工具、同来源下，经版本验证的原生工具协议；优先保持其他设置不变。
3. 条件2下的 thinking 模式诊断；单列推理 token 和容量差异，不能将额外计算隐去。

若原生协议要求另一种模板或服务 parser，这不是纯 mode 单变量，必须记录为协议组合比较。不得为检查自动重启共享服务或下载新权重。

### 5.3 需要观察什么

同时包含明确保存、只读、引用、不记住、精确业务查询等案例。记录工具选择、合法参数、实际 Store/world 和最终答复。必要的固定重复用于估计行为变化，不把重复当独立场景，也不挑最好一次。

不能只用 `tool_choice=required` 强迫工具调用后宣称自主策略变好。只有应用已经明确指定为某类操作时，限制该操作流程才是正常应用合同；开放自然语言条件必须保留“不调用”的合法选择。

## 6. 推荐架构：一个记忆服务、一个工作状态、一个执行循环

```text
实际用户／工具事件
        │
        ▼
来源与会话存储 ───────────────┐
        │                    │
        ▼                    ▼
唯一 MemoryService       TaskState
来源保留／当前理解        当前目标、活动事项、
CREATE/READ/UPDATE/DELETE  依据、未完成动作与真实结果
        │                    │
        └───────┬────────────┘
                ▼
已有 RequestContext / Renderer
当前适用内容＋必要历史＋实际工具观察
                │
                ▼
同一 ReAct Host
读／写记忆、调用业务、询问、结束
                │
                ▼
已有工具执行器与结果日志
身份／权限／参数检查，实际执行，真实回执
                │
                └──────────→ 新观察与状态更新
```

这是逻辑职责图，不新增数据库、分布式事件平台或后台 Agent。现有 LangGraph、Store、checkpointer、Request Assembly 和原生工具继续使用。

## 7. 数据合同：只增加当前问题确实需要的区分

### 7.1 SourceEvent

保留原始角色、正文、真实事件身份、取得时间和已知业务对象身份。事件内容表示“实际收到了什么”，不自动证明为真。

来源进入审计不等于获得跨会话可检索权限。Retained 条件下，未被合法保留的历史不得通过 audit 或 checkpoint 旁路流入下一任务。

### 7.2 MemoryRecord

首版沿用现有 ordinary record，必要信息为：

```text
id
content
scope / subject（材料明确时）
provenance（程序记录实际触发背景）
known object references（取得过的外部身份）
observed/valid time（有依据时，未知不猜）
```

无需给每句话建立本体。相互独立变化的事项宜分开；同一计划中必须联合理解的字段可以共存。不要为减少卡数将无关事项合并，也不要为追求原子化无限拆卡。

业务 key、订单 ID、文件路径等身份不应只出现在模型生成的 title 中。有明确上游结构字段时原样保留；只有自然语言名称时，不假装已有经过业务核验的实体身份。

### 7.3 TaskState

```text
goal / 原请求引用
当前约束与活动子任务
正在使用的记忆引用及版本／内容签名
带依据的临时事实或假设
已提出但未完成的操作
真实执行结果
```

State 可以有多个局部项，可以缓存当前数值；缓存须说明它来自哪项记录或观察。不要由 State writer 和 ordinary writer 分别长期修改同一事实而缺少单一提交规则。

修改后引用失效不等于自动采用新结论。应重新解析内容，并在含义可能改变时由 Host 重核。

### 7.4 OperationResult

由程序生成：实际操作、目标身份、成功／失败／部分／未知、返回内容与关联调用。它不由最终答案中的 `saved=true` 生成。

成功写入仅证明写入发生，不证明所有用户要求均已满足；成功调用业务也不证明参数符合用户意图。

## 8. 写入架构：将明确保存变成可执行工作，不依赖结束时的自证

### 8.1 完整操作空间保持

- CREATE：新事项或新的独立观察。
- READ：取得当前所需材料。
- UPDATE：同一事项的内容、范围或状态变化。
- RETRACT/DELETE：撤回错误理解、退出当前视图或按授权实际清理，三者不能混为一谈。
- NO_CHANGE：没有必要改变持久记忆。

### 8.2 唯一提交入口

无论由 Host 主动工具调用，还是明确的应用记忆命令进入，都通过同一个 MemoryService 提交。

不维护两套 independently writable 当前事实；不让外围“修复器”直接写库而 Host 毫不知情。

### 8.3 明确记忆工作与机会性学习分开

| 输入性质 | 建议处理 |
| --- | --- |
| 应用明确提供的保存／修改／删除命令 | 同步完成该记忆子任务；返回实际结果；不把持久化排到已确认成功的答案之后 |
| 普通对话中的自然语言记忆意图 | 由同一 Host 识别并执行，保持可观察的未完成状态；该识别仍可能漏掉 |
| 仅本轮要求 | 当前 TaskState，不默认永久化 |
| 引文、假设、未采纳建议 | 保存时保留身份，不转换为用户偏好 |
| 被动发现的可能长期信息 | 允许不保存；需要机会性整理时单独评估，不默认每轮运行维护器 |

不能从 rubric、题号或事后正确答案生成“明确应用命令”。开放自然语言和显式 API 模式必须分别评测。

### 8.4 可以保证与不能保证的完成边界

对已经登记且实际提出的写入，程序能保证：未成功提交就不能将该操作记为 completed，恢复时只续接未完成操作。

程序不能仅凭是否发生了一次 CREATE，认证这条 CREATE 正确覆盖整项用户请求；也不能在模型完全漏识别保存意图时，凭空知道还有未登记义务。

因此应同时评价两个能力：

```text
意图识别／动作选择
实际执行／持久提交
```

不恢复 C 的最终自证字段，不用一份新的 checklist 自报覆盖来代替语义验收。

### 8.5 原生调用校准后若仍稳定漏存

可以进一步比较一个最小、同步的记忆子任务：输入仅为当前真实新材料与相关旧记录，输出真实操作或无变化，再将实际回执交回原 Host。它可以复用同一模型与 LangMem 的变换接口，不需要另一个常驻 Memory Agent。

该子任务必须走唯一写入入口，不能在每次 pre_model 重复维护同一批事件。明确输入边界与事件消费记录；业务结果成为新事件后可以另行处理。

这是有成本的候选，不是默认正确答案。只在解决真实遗漏且总成本可接受时采用。若它只是把漏写改成误写更多内容，应拒绝，而不是继续添加审核链。

## 9. 精确对象身份：让模型选择对象，不让它重命名对象

当前 plural key 被改成 singular，属于工具参数消费错误。[M1]

### 9.1 取得过真实标识时

返回可识别显示名与稳定 object reference。Host 选择该引用；程序解析回真实 key。不要让模型从摘要或标题重新生成标识。

### 9.2 只有用户自由文本时

保留用户完整文字，必要时调用业务查询取得候选；有多个对象就澄清。不得模糊匹配后静默执行，不得把测试 gold 填入工具参数。

### 9.3 API 不支持引用时

保持原始工具合同；记录精确复制失败，必要时做同信息、同工具的模型使用诊断。新的 object-reference adapter 应作为独立应用配置比较，对各臂共同开放，不能冒充原 benchmark 的未改接口。

### 9.4 实时查询与 memory search 各司其职

“以前计划多少件”查持久记忆；“现在是否预约成功”查实际业务结果或合适的新查询。一次空 memory search 不足以回答业务世界不存在。

不要求每次都重复实时查询；是否需要重查取决于当前任务、已有观察时点及工具合同。不具备实时查询能力时应说明依据和未知状态。

## 10. State–Attention：保留方向，改变它承担的责任

State–Attention 的目标是让已有材料支持当前任务，而不是解决所有动作可靠性问题。

读取 A 由当前任务、scope、疑点和实际预算决定。更新 U 由新观察及相关既有事项决定。二者不必相同，但不需要默认各一次 LLM selector。

```text
候选足够小且内容适用：直接提供。
候选较多：普通检索与必要重排。
仍存在范围冲突、缺失或预算压力：更新工作焦点并定向读取。
确有自动选择的净收益：才启用独立 selector。
```

“只有超容量才可以注意”也过窄：即使内容全部放得下，scope 和新旧状态冲突也可能需要有针对性的工作视图。应先通过当前 Host 的正常检索／State 更新表达，不立即另开一轮选择模型。

Attention 可以让旧记录进入核对材料，而不将它当作当前行动依据。相关性、适用性、可信程度、未来保留价值是不同量，不能用一个分数代替。

当前请求附近呈现记忆是 v5 的组合呈现结果，不是普遍的“新记忆永远高于历史”。历史反向任务、业务当前状态和不可信指令内容都必须保留对照。

## 11. 实际案例：计划、部分执行和复用

以下是设计示例，不是已运行结果。

1. 用户要求保存完整交付计划，同时禁止预约。
2. Host 通过真实记忆操作保存。程序返回 record ID；不调用预约工具；答案依据实际回执确认。
3. 新请求只执行首批。读取总计划，取得业务对象的准确身份；使用当前要求中的首批数量，而不是把总数量改成首批数量。
4. 业务返回主操作成功、标签失败。保存真实 operation ID；当前 TaskState 标记标签待处理。不能为修标签重做主操作。
5. 需要记忆时记录“该时点已执行首批，标签尚未确认”，长期总计划仍保留。
6. 新 session 问计划，读取计划；问实际状态，使用真实结果或查询；问历史，访问合法保留的历史。
7. 用户撤回计划或要求遗忘时，分别处理当前适用性与实际保留范围。

关键不是创建更多类型，而是同一记录与任务在计划、观察、执行三种用途下不被混用。

## 12. 模型使用诊断优先级

| 层次 | 应检查 | 不应预先断言 |
| --- | --- | --- |
| 工具协议 | 实际模板、native 与 JSON-action、工具名称和参数 | 自定义 JSON 一定较差 |
| 推理模式 | 当前 non-thinking 与支持的 thinking；完整成本 | thinking 一定修复，或 non-thinking 足够代表模型 |
| 参数约束 | 结构化输出的真实覆盖；执行侧 schema | JSON 合法就是动作正确 |
| 反复行为 | 固定请求的小规模预定重复、finish reason、实际服务身份 | temperature=0 已保证逐字可复现 |
| 输入组织 | 当前/历史/业务观察的角色与位置 | 当前记忆始终优先 |
| 模型能力 | 相同接口上独立模型的小型诊断 | 必须先做到当前模型100%才允许比较第二模型 |

第二模型可以用于定位问题是否依赖某个 Host，不必先完成所有长程验证；它不等于立即部署大矩阵。新服务、下载、模型替换与参数变动仍需授权，并以新身份计账。

## 13. 最小实施顺序

### P0：保留工程，冻结判断

保留 S1 Request Assembly、Store、严格 CRUD、隔离、审计与原失败。compact 继续 opt-in，full 不被宣布为已证实的修复。不要为本次分析重新运行全仓或发布构建。

### P1：同模型工具协议校准

先校验原生协议能否在现有服务下正确表达实际调用。对保存与业务查询各一个首断点，加只读／引用反例，做固定有限比较。最后必须完整执行相关链，不能只看首响应。

### P2：精确身份与结果消费

在现有 dispatcher 增加或复用准确对象解析。检查同一真实 key、目标 owner、参数范围和实际结果；不对自由文本做擅自改名。保持原业务工具对照。

### P3：只在漏存仍存在时收敛写入子任务

一条同步、有限、唯一写入路径，替换责任而非叠加第二维护者。输入新事件和相关旧记录；输出操作后真实执行。把额外调用和误存计入比较。

### P4：连续任务回归与反例

既有两条失败链用于开发；新任务结构用于验证。保留明确 no-write、引用、temporary、删除、同事项更新、真实 partial、当前/历史与动态查询。前置失败导致后续未激活，应另做有合法前态的诊断，不把它混入端到端成绩。

### P5：再优化工作视图与 State–Attention

只有选择本身有净价值才增加 selector。复杂代码不按行数削减，优先减少重复写入责任和同一事实的独立维护者。

## 14. 验收与实验纪律

需要分开报告：

- 模型是否选择了需要的操作；
- 工具参数是否符合用户意图；
- 程序是否真实执行；
- 持久记录是否正确、范围是否适当；
- 后续使用是否正确；
- 实际世界是否达到目标；
- 每阶段成本和失败。

机械验收可以设置零容忍：越权写入、未知执行盲目重做、凭空认证成功等，出现后先阻断该危险路径。

语义实验不能用十来个任务的100%声称一般稳定，也不能一项普通错误就永久停止全部诊断。应事先固定规模、顺序、重复数与修复范围；失败时保留原轨迹，定位一处断点，修改一类机制，在相反情况上回归。

旧评分不回写。新 evaluator 的要求必须来自合法任务；“完整计划”可以蕴含上下文可判定的必要内容，不必机械要求用户逐字段列名，但该解释需在看答案前冻结。动态 world 评分使用真实分支，不强制前序成功才可能出现的状态。

如果使用条件概率分解分析链路，应采用“某阶段在前置正确时成功的概率”，而不是将几个未定义、相互相关的质量分数直接相乘。

## 15. 质量—成本判断

架构不能只优化调用数。最终比较是在相同任务、信息权利与输出质量要求下完成工作所花的实际成本。

```text
总成本 = 记忆形成 + 维护 + 检索/交付 + 行动/回答 + 失败恢复
```

每个 provider request 只统计一次，逻辑职责重叠不重复收费。Judge 与 embedding 分列；开发代理 tokens 不混进部署估计。一次额外维护调用若可靠减少漏存和后续返工，可能合理；每轮无条件自我汇报则需证明价值。

当前账本以用户 v6 报告为历史依据：3,263 次生成、4,155,747 generation tokens、23,276 embedding tokens。该数字不是本轮重新核账结果，本轮没有新增实验生成。

## 16. 对论文目标的定位

完整 CRUD、分层记忆、状态管理、版本与回执本身都有先例。本次方案首先是可用性修复，不能因为重新画了架构图就称为新范式。

有价值的候选问题仍是：

> 在完整操作能力与合法信息相同的条件下，工作状态与精确依据的结合能否提高记忆操作选择、正确消费与持续任务成功，并形成优于简单 ReAct 的质量—成本边界？

需先排除模型调用协议、参数约束、记录表达和额外计算等解释。若主要提升来自模型原生工具适配，应据实作为基础工程，不重新归因给 State–Attention。

## 17. 最终设计决定

推荐保留：

```text
一个成熟 Agent runtime
一个逻辑 MemoryService
一套来源与真实结果记录
允许多个局部项的 TaskState
一个结构化 RequestContext/Renderer
同一 Host 的 ReAct 循环
精确对象引用和有限执行边界
按实际需要读取与维护
```

不推荐：

```text
默认多 Agent 审核
默认全库重写
每轮 A→维护→U 的串行模型税
要求所有终答填写执行证明
把 State 禁止存任何工作事实
把动态工具结果全部排除出长期记忆
把来源角色当成全局真值排序
在没有证据时继续增加架构模块
```

修复的中心是：**把需要做的动作变成模型容易正确选择、程序能够准确执行的工作；将真实结果反馈给同一个 Agent。**这比不断补充记忆标签更接近当前失败，也能继续承载原有 State–Attention 研究。

## 18. 参考资料

### 项目证据

[M1] MiLAi，v6 S4 独立任务结果与首响应诊断，固定提交 c6f335fe：
https://github.com/minguselandy/MiLAi/blob/c6f335fef7cf00c86fa3dbe201a60c802439ca12/MiLAi-Lab/docs/MILAI_NEXT_DEVELOPMENT_V6_S4_INDEPENDENT_RESULTS_20260928.md

[M2] MiLAi，langmem_chat.py，同提交：
https://github.com/minguselandy/MiLAi/blob/c6f335fef7cf00c86fa3dbe201a60c802439ca12/MiLAi-Lab/src/milai_lab/providers/langmem_chat.py

### 论文与官方文档

[R1] Packer et al. MemGPT: Towards LLMs as Operating Systems. 2023.
https://arxiv.org/abs/2310.08560

[R2] LangMem，Core Concepts；LangChain，Memory overview。
https://langchain-ai.github.io/langmem/concepts/conceptual_guide/
https://docs.langchain.com/oss/python/concepts/memory

[R3] Chhikara et al. Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory. 2025.
https://arxiv.org/html/2504.19413v1

[R4] Liu et al. SimpleMem: Efficient Lifelong Memory for LLM Agents. 2026.
https://arxiv.org/html/2601.02553

[R5] A-MEM: Agentic Memory for LLM Agents. 2025.
https://arxiv.org/html/2502.12110v1

[R6] Yu et al. Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management for Large Language Model Agents. 2026.
https://arxiv.org/html/2601.01885v1

[R7] MemR3: Memory Retrieval via Reflective Reasoning for LLM Agents. 2025.
https://arxiv.org/html/2512.20237v1

[R8] Liao et al. LeanMem: Simple and Efficient Long-Term Memory for LLM Agents. 2026, preprint.
https://arxiv.org/html/2608.03463v1

[R9] Qwen，Qwen3.6-35B-A3B-FP8 官方模型卡，工具调用与生成配置。
https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8

[R10] vLLM，Tool Calling。
https://docs.vllm.ai/en/latest/features/tool_calling/

[R11] Anthropic，Writing effective tools for AI agents—using AI agents. 2025-09-11.
https://www.anthropic.com/engineering/writing-tools-for-agents

### 本轮阅读的源码入口

[G1] LangMem，knowledge/tools.py。
https://github.com/langchain-ai/langmem/blob/main/src/langmem/knowledge/tools.py

[G2] Mem0，memory/main.py。
https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py

[G3] Qwen-Agent，fncall_agent.py 与 assistant.py。
https://github.com/QwenLM/Qwen-Agent/blob/main/qwen_agent/agents/fncall_agent.py
https://github.com/QwenLM/Qwen-Agent/blob/main/qwen_agent/agents/assistant.py

研究与源码判断均以本次可读取范围为限。没有以作者自报性能替代 MiLAi 的公平对照，没有宣称上述设计已经修复真实模型失败。
