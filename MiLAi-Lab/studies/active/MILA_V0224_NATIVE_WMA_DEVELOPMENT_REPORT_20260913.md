---
report_id: MILA-V02-24-DEVELOPMENT-EXPERIMENT-REPORT
version: "1.0"
date: "2026-09-13"
evidence_snapshot_utc: "2026-09-13T09:45:47.072Z"
kind: DEVELOPMENT_AND_PARTIAL_EXPERIMENT_REPORT
gate_a: GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY
native_batch_revision: v4
native_batch_terminal: NATIVE_BATCH_FAILED
research_status: PARTIAL_RESULTS_JUDGE_LIMITED_MEMORY_EFFECT_INCONCLUSIVE
stop_reason: JUDGE_READ_TIMEOUT_WITH_UNRESOLVED_USAGE
planned_independent_roots: 4
roots_with_model_answers: 2
roots_with_both_primary_answers: 1
planned_primary_run_units: 8
answer_complete_run_units: 3
fully_scored_run_units: 2
answers_completed: 165
valid_scored_questions: 164
paired_scored_questions: 54
recorded_generations_with_usage: 511
unresolved_generation_attempts: 1
known_raw_tokens: 13520967
total_actual_raw_tokens: null
new_report_model_requests: 0
new_report_provider_http: 0
new_report_product_requests: 0
new_report_full_regression: false
---

# V0224 开发与原生 WMA 实验详细报告

## 1. 执行摘要

**功能 Gate A 已完成；WMA 原生 QA 已真实运行但比较未完成；当前阻塞在 Judge 请求超时与未知用量，没有形成新的 Memory 机制收益结论。**

本报告汇总已有开发与运行成果，不启动新的实验、评分、服务或测试。数据复算快照为2026-09-13 17:45:47（北京时间）；最新批次在17:34:57结束。原始运行目录为[20260913-native-wma-v1](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1)。

| 层面 | 已成立的结果 | 不能据此主张 |
| --- | --- | --- |
| CPU功能验收 | Gate A证书已签发；完整参考16+80、CPU P3 16/16、P4 24/24；40次成功/41次尝试 | 真实模型P3/P4全通过、效率门通过或Memory机制有效 |
| 原生接线 | 两个baseline单元和一个普通Note单元完成答题，共165份答案 | 四根/两臂全批次完成、官方完整leaderboard复现 |
| 普通Note | 一根30个会话经公开ADD/GET完成机械持久化与读取；两臂55题的题目/检索记录/图片列表相同 | 自主写入、学习了更好的检索策略、真实跨会话认知恢复 |
| 答题与评分 | 164题有有效格式评分；一根54题可配对，baseline独对5题、Note独对4题 | 净差1题构成可靠的Memory效应 |
| 评分可靠性 | 4个相同答案获得不同标签；有效评分混用了v1/v2/v3配置 | 独立、统一配置、人工确认的行为真值 |
| 成本与停止 | 511次生成有用量记录，已知13,520,967 raw tokens；另1次超时生成用量未知 | 总费用已结清、失败请求成本为0、可直接自动重试 |

保留A0默认、普通方案、Schema NO-GO与未消费确认池。旧B–E路线仍暂停，不因本报告重新放行。

## 2. 范围、合同与证据优先级

本轮衔接[Goal v0.4](MILA_V0224_功能GateA收口与原生Benchmark最小实验_GOAL_v0.4_20260913.md)，实际执行依据[WMA运行合同](../../configs/v0224-native-wma.json)及Git外v1—v4冻结副本。
Goal中的“新增额度为0/尚未启动”是其制定时的快照；随后原生运行合同记录了执行与vLLM Judge授权，不能继续用旧规划标签描述当前运行状态。

证据优先级为：**实际批次/worker终态与逐次记录 → 已绑定开发验证 → 接线说明 → 初始规划与运行中预览**。
`final-results-preview*.json`产生于首根答题期间，不是当前总用量、完成数或最终结论。
本报告没有重写它们，也没有把原始`NATIVE_BATCH_FAILED`改成PASS。

报告更新与真实实验授权分开：本轮新增模型、Provider HTTP、Product请求和确认配额均为0。
不修改冻结Goal、原始合同、运行代码、Product、失败证据或用量记录。

## 3. 已关闭的工程阶段：功能 Gate A

[功能证书](/cra/memory/mx_memory/evidence/v0224/20260913-cpu-completion-segment-v1/functional-gate-a.json)状态为
`GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY`，保证为`COMPOSED_CPU_COMPLETION_WITH_R03_R04_FRESH_SCOPES`。

- 完整参考：16个P3参考、80个P4参考输出。
- 成功组合：原P3 16条、原P4前8条、新段P4第9—24条。
- 合计40个成功冷worker、41次实际尝试；原第9条退出期间超时失败保留，不是单批40次全部成功。
- 成功路径mock生成96次，失败尝试mock生成4次，合计100次；不能计为真实模型请求。
- 六项工程检查通过，4285测试通过、1项既有可选依赖跳过。
- 一次组合验收确认正确性、隔离、CAS、回执、世界效果与账务；CPU效率不再阻断。

证书SHA256：`3d097412d70592454ae13d27352a03b79f526cd47069dda5f4c688c3c86419a8`。
[工程回执](/cra/memory/mx_memory/evidence/v0224/20260913-a-completion-priority-v1/engineering-v2/engineering-checks.json)、
[组合验收](/cra/memory/mx_memory/evidence/v0224/20260913-cpu-completion-segment-v1/independent-composed-k3-completion.json)与
[执行历史](MILA_V0224_EXECUTION_STATE_20260913.md)保留原边界。

**4285项是该CPU修订的既有工程证据，不是本报告重跑结果，也不自动覆盖随后所有原生WMA代码。**
本轮没有返工Gate A，没有增加性能候选。

## 4. 原生实验设计与实现

### 4.1 数据、抽样与任务单位

| 项目 | 冻结配置 |
| --- | --- |
| Benchmark | 已下载WorldMemArena，personal开发池 |
| 官方代码revision | `15ea25b723d9c4fb35e8062037aec6a5601e4442` |
| 数据revision | `e2148757921fc7e2d66d8ed899823b763227c341` |
| 顺序 | personal_18 → personal_10 → personal_01 → personal_19；沿既有V0217预定顺序 |
| 每根 | 30个会话、5个原生checkpoint、55个问题及原有图片 |
| 主比较 | 4根 × 2臂 = 8个运行单元，440个答题位置 |
| 条件复核 | 最多原4根/220题，不新增根 |
| 暴露边界 | 全部开发暴露；未打开reserve、candidate57或确认集 |
| 评价范围 | `NATIVE_TASK_LOCAL_ADAPTER / QA only`；不是完整官方榜单 |

220个不同问题、440个臂内位置、同根checkpoint都不能冒充独立root。
已运行答案覆盖2根；具有双臂答案的只有1根，不能声称跨独立root复现了Memory效果。
四个计划root都来自personal池，也不构成跨领域确认。

### 4.2 两个主要臂与实际对照含义

**B_native**：使用固定revision的官方`MMFU_Single`，按原生顺序导入合法文本、时间和图片，保留官方FIFO上下文淘汰。

**M_note**：将每个会话的标准化turn无损序列化，经公开Note ADD保存；在checkpoint通过公开分页GET读回，验证提交、版本与digest，再交给同一个官方adapter。
其来源明确为`HARNESS_INGESTED`，不是Agent自主选择保存的经验，也没有增加新的State机制。

这两臂首先比较的是**普通Note存取接线是否保真且可用**。
Note读回后仍由相同reader使用相同材料，不应预期仅因换了持久存储就自然获得认知收益。
本轮没有测试Product语义搜索、BM25/BGE检索排名、选择性维护或控制State策略。

**R_review实际实现偏差必须单列**：
Goal规划倾向同一次正常调用中的普通复核；[当前runner](../../tools/run_v0224_native_wma.py:327)则在M_note完整答案之后，追加原草稿与review提示，再发一次模型请求。
它属于额外一轮普通复核，不应改称“同调用R1”，也不能忽略额外生成成本。
本轮尚未触发或执行该臂，所以没有review效果结果。

### 4.3 模型、上下文与评分参数

| 参数 | 实际配置 |
| --- | --- |
| 答题/Judge模型 | 同一现有本地vLLM：`Qwen3.6-35B-A3B-FP8` |
| 答题参数 | temperature=0，top_p=1，seed=2240401，关闭thinking，max_tokens=1024 |
| 模型context | 65536；官方GPT2预算tokenizer，发送前另调用vLLM tokenize |
| 预算配置 | answer buffer=8000，safety buffer=300，retrieval top_k=10 |
| 图片 | 历史最多25张；答题最多5张、45 MiB |
| Judge | 官方QA/Evidence提示；v1上限1024，v2起8192；v3 JSON Schema，v4紧凑JSON regex |
| 评分方法 | Correct/Hallucination/Omission、官方lexical F1/BLEU1、文本Evidence Judge |
| 局限 | 同模型Judge不是独立模型验证；Evidence Judge只看检索文本，不验证图片事实 |

完整导入历史不等于全部历史同时进入每题模型输入：官方FIFO与图片上限仍然存在。
本报告不会把这个profile描述为无截断的full-history模型条件。

### 4.4 开发落地与边界

| 组件 | 本次作用 | 保留边界 |
| --- | --- | --- |
| [原生runner](../../tools/run_v0224_native_wma.py) | session/checkpoint循环、真实答题、评分及结果落盘 | reader不打开gold/evaluator字段 |
| [批次协调器](../../tools/run_v0224_native_wma_batch.py) | 两波安排、冻结版本与已有成功位置复用 | 子进程exit0不等于评分完整；检查worker业务终态 |
| [HTTP Provider](../../tools/v0224_native_wma_provider.py) | tokenize/生成、完整输出解析、用量与超时记录 | 不自动重试，不把缺回执费用记0 |
| [Note映射](../../tools/v0224_native_wma_note.py)与[MCP客户端](../../tools/v0224_native_wma_mcp.py) | 无损会话写入、分页读取、提交/digest检查 | 仅公开接口；主体由可信服务绑定 |
| [隔离服务工具](../../tools/v0224_native_wma_service.py) | 本次独占API/MCP/PostgreSQL环境 | 不改共享服务，不清理共享网络 |
| [只读报告工具](../../tools/report_v0224_native_wma.py) | 已有记录的评分/成本汇总 | 运行中预览不是最终结果；本报告未运行其写出入口 |

gold、evidence标签与类别位于独立评价输入，只用于离线Judge；不回流在线答题。
替换存在gold回退或异常吞没风险的官方answer factory，记录为本地adapter差异，不声称完全未修改的官方runner复现。
运行合同将Note操作标为`PRODUCT_BLACK_BOX`，整套QA实验仍是`NATIVE_TASK_LOCAL_ADAPTER`；Product默认行为与公开部署未改变。

## 5. 开发修订与运行经过

### 5.1 启动与局部实现问题

已记录的启动修订包括：Docker默认地址池耗尽后使用本次独占空闲子网；PostgreSQL初始化未完成时迁移失败，等待同容器healthy后继续；MCP启动器已有内部max-retries=0，去掉不支持的重复外层参数。
可选tokenizer依赖/导入顺序与tenacity缺失在隔离环境修正。
这些都是接线/环境问题，不是Memory语义错误；首次失败保留在[service目录](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/service)和原始启动日志。

### 5.2 四次批次均保留真实停止状态

下表时间均为2026-09-13北京时间；各版本仅复用合同允许的成功位置，不重跑已完成答案。

| 实例 | 起止 | 主要进展与停止原因 | 终态 |
| --- | --- | --- | --- |
| v1 | 16:28:25—16:42:17 | 首根B答案55/55；Judge 54/55，QA00:09在1024 token处截断 | NATIVE_BATCH_FAILED / STAGE_INCOMPLETE |
| v2 | 16:44:25—16:58:11 | 提高Judge上限，补首根1题；第二根B答案55/55，评分50/55，5题JSON/计数格式无效 | NATIVE_BATCH_FAILED / STAGE_INCOMPLETE |
| v3 | 17:00:42—17:15:44 | 对Judge加JSON Schema约束，补第二根5题；首根M答案55/55，评分54/55，QA04:05空白循环后截断 | NATIVE_BATCH_FAILED / STAGE_INCOMPLETE |
| v4 | 17:24:55—17:34:57 | 仅补首根M的1题；使用紧凑JSON regex，首次生成约600秒ReadTimeout，用量未知 | NATIVE_BATCH_FAILED / STAGE_FAILED |

原始终态：[v1](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/batch-terminal.json)、[v2](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/batch-terminal-v2.json)、[v3](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/batch-terminal-v3.json)、[v4](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/batch-terminal-v4.json)。

v3失败说明中记录Judge输出了7348个TAB并到达8192 token上限；v4试图限制字段间无界空白及解释长度。
**CPU/mock格式验证通过没有保证真实请求成功。** v4请求超时与新regex同时出现，不足以认定regex编译、GPU、排队或推理中的哪一层是根因；本轮没有做服务端诊断。

v1—v3若干Judge worker的进程exit0，仍带`JUDGE_PARTIAL`。父批次识别到评分不完整而停止是正确行为，不能把进程正常退出解释成整臂PASS。

### 5.3 失败与补评账

共有7条历史`JUDGE_INVALID`记录：首根B 1条、第二根B 5条、首根M 1条。
前6题在受限新版本中补评为有效；首根M的QA04:05仍未裁定。
v4超时没有产生新的有效评分或完整generation回执，单列为1次未知用量尝试，不能简单并入“又一个错误答案”。

判定规则是每个问题取最后一条有效`SCORED`记录，保留全部旧失败；不是在多个合法分数中择优。
当前有效分数的版本组成：首根B为54条v1+1条v2，第二根B为50条v2+5条v3，首根M为54条v3。
所以分数是**组合版本的开发评价**，不是同一Judge配置下的一次性确认。

## 6. 运行完成度与评分结果

### 6.1 全分母

| root | B_native答题/有效评分 | M_note答题/有效评分 |
| --- | --- | --- |
| personal_18 | 55/55 | 55/54，QA04:05未裁定 |
| personal_10 | 55/55 | NOT_RUN |
| personal_01 | NOT_RUN | NOT_RUN |
| personal_19 | NOT_RUN | NOT_RUN |

共8个计划主单元：3个答题完整，其中2个评分完整、1个评分部分；其余5个单元未运行。
440个计划答题位置中已有165份答案；164题有完整、格式有效的QA/Evidence评分记录。
所有R_review未运行，也没有正式完成触发判定。不能把后5个单元或未触发review计为答错。

### 6.2 质量评分

这里的“正确/幻觉/遗漏”均指**模型Judge标签**，不等于人工裁定。
格式有效也不等于Judge语义正确；未知评分不计为错误。

| root / 臂 | 有效评分 | Correct | Hallucination | Omission | Correct/有效评分 |
| --- | ---: | ---: | ---: | ---: | ---: |
| personal_18 / B_native | 55 | 21 | 12 | 22 | 38.18% |
| personal_18 / M_note | 54 | 20 | 14 | 20 | 37.04% |
| personal_10 / B_native | 55 | 22 | 7 | 26 | 40.00% |

两个baseline根合计43/110正确（39.09%），但不能拿它与单根M_note直接做组间效果比较。

| root / 臂 | 平均lexical F1 | 平均BLEU1 | Judge文本证据覆盖 |
| --- | ---: | ---: | ---: |
| personal_18 / B_native | 0.1698 | 0.0539 | 200/202 = 99.01% |
| personal_18 / M_note | 0.1805 | 0.0489 | 198/201 = 98.51% |
| personal_10 / B_native | 0.1811 | 0.0763 | 217/226 = 96.02% |

F1/BLEU1来自已评分记录中的官方确定性lexical计算，不与Judge标签混成总分；本报告未重新调用评价模型。
表内M_note少1题，F1/BLEU1全行不是严格同分母比较。共同54题F1为B 0.1729、M 0.1805，仅为开发观察。
文本证据覆盖也是同模型Judge输出，不是独立oracle确认；不能由约96%—99%覆盖直接推出所有失败都属于evidence-use或State错误。

### 6.3 唯一可配对root：personal_18

| 共同54题的Judge判定 | 题数 |
| --- | ---: |
| 两臂都正确 | 16 |
| 仅B正确 | 5 |
| 仅M正确 | 4 |
| 两臂都非Correct | 29 |

同一54题中B正确21/54、M正确20/54。净差仅1题，且受后述同答案不同评分直接影响。
没有进行显著性、泛化或独立机制确认；只有一个配对root，不把54题当成54个独立任务族。

### 6.4 输入与评分分歧：比净差1题更重要的发现

从两臂`answers.jsonl`逐题复算：

- 55/55的`question / retrieval / images`记录相同。
- 38/55答案文字完全相同，17/55文字不同。
- 共同有效54题中37题答案相同，其中4题Judge标签不一致。
- 只看答案确实不同的配对题，B独对4题、M独对4题；另一个“B独对”来自同答案评分分歧。

| 相同答案的题号 | B标签 | M标签 | 有效评分版本 |
| --- | --- | --- | --- |
| QA00:06 | Omission | Hallucination | v1 / v3 |
| QA00:09 | Correct | Hallucination | v2 / v3 |
| QA02:08 | Omission | Hallucination | v1 / v3 |
| QA04:06 | Hallucination | Omission | v1 / v3 |

这证明存在跨评分配置的标签不一致，但不能把4/37直接当作某个固定Judge的自然错误率。
本报告只复算记录中的题目、检索内容与图片列表，没有为报告重新哈希约1.15 GB的全部答题HTTP请求体，因此不把该检查夸大为全部wire字节一致性认证。

**解释：**M_note当前没有改变reader的可见检索材料。相同记录下仍出现答案/标签差异，必须与模型运行非确定性、生成/评分配置及其他未隔离因素区分，不能直接归因于普通Note存储。
这是需要保留的实验设计边界，不是鼓励再增加一套全历史准入流程。

## 7. 普通Note与隔离实际验证

首根M_note的[note日志](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/runs/personal_18/M_note/notes.jsonl)有30条`SESSION_NOTES_COMMITTED`，全部标`HARNESS_INGESTED`。
公开客户端记录如下：

| 范围 | ADD | GET | operation查询 | 初始化/通知/会话DELETE | HTTP意图/已观察 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 首根主任务 | 30 | 437 | 0 | 3 | 470/470 |
| 四主体隔离探针 | 4 | 8 | 0 | 12 | 24/24 |

这里的HTTP DELETE是关闭MCP会话，不是删除Note内容。
[隔离终态](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/service/isolation/terminal.json)确认4次本人读回、4次跨主体`NOTE_NOT_FOUND`符合预期。
辅助写入未进入主任务Note读取列表。全部客户端记录均有HTTP观察；预期的工具级跨主体拒绝不能误算成无效实验。

主任务客户端请求耗时合计约2.858秒，隔离探针约0.338秒。
这些是本地HTTP客户端span，不是完整存储部署、序列化或生命周期成本；Product内部HTTP未单独计数，不能写为0。

**实证支持的工程结论：**此根、此公开接口与本地隔离配置中，机械写入/分页读取能够承载原生历史并恢复相同reader材料。
**未验证：**自主记忆选择、检索召回收益、BGE线上效果、memory维护策略、真实独立Host冷恢复、动作世界与Recovery。

## 8. 成本、延迟与未知用量

### 8.1 生成与token账

从各Provider目录的generation记录及blocked回执复算，包含失败格式输出和补评，不只统计最后有效答案。

| 用途 | 有用量记录的生成 | 未知用量尝试 | 已知prompt tokens | 已知completion tokens | 已知raw tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| 三个主单元答题 | 165 | 0 | 7,060,104 | 3,479 | 7,063,583 |
| 任务评分及补评 | 338 | 1 | 6,390,275 | 64,176 | 6,454,451 |
| 四个评分校准样例 | 8 | 0 | 2,359 | 574 | 2,933 |
| 合计 | 511 | 1 | 13,452,738 | 68,229 | 13,520,967 |

总实际生成尝试为512；已知token不是全额结算值。正式表达为：
**总实际raw tokens未知；可确认部分为13,520,967，另有1次请求待查。**
不以预留上限、超时秒数或0去代填未知用量。

已知成本中，任务Judge及补评约占47.74%；输入token约占99.50%。
这反映长历史答题与重复评价输入的实际成本，不证明可以不经验证地压缩来源。
该数字仅属于本次原生WMA范围，不能与Gate A的mock次数、其他Goal历史token或代理自身用量混算；没有据此推算货币费用。

按主单元归属：首根B已知4,488,609 raw，第二根B 4,585,505 raw，首根M已知4,443,920 raw且另有未知请求。
不能把不同版本Judge修订成本差当作Note策略效率差。

### 8.2 HTTP与时间账

- Provider答题/评分/校准：1024次HTTP尝试，包含tokenize与512次生成尝试；另有2次身份预检，合计1026。
- Note主任务470次HTTP，主体隔离24次，合计494；与Provider分账。
- 客户端这些已列范围合计1520次HTTP，不是整个服务栈所有内部调用的总数。
- Provider客户端HTTP span合计约3077.28秒，包含未知请求的约600秒等待。
- 四个批次实际执行时长之和3167.71秒，约52分48秒。
- 首个批次启动至最新批次终止跨越3992.09秒，约66分32秒，包含修订间隔；不是完整项目开发工时。
- 以上span互有包含关系，不能相加成“总耗时”。

累计raw-token硬上限仍为空，但不表示请求无限或未知费用可以忽略。
v4合同有限包络为最多2002次生成、4006次Provider HTTP（含身份预检）、1884次Note HTTP；这是含条件review与修订的上界，不是实际消耗。
600秒请求、4小时worker、24小时批次用于防挂；当前停止并非累计token门触发。

### 8.3 当前未知项

[blocked.json](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/runs/personal_18/M_note/judge-provider-v4/blocked.json)记录：
`ReadTimeout`、`generation_attempts=1`、`observed_usage=null`、`unresolved_usage=true`。
本地未收到完整生成结果，不等于服务端没有运行或已被取消。
在没有请求状态/用量证据前，不应自动重试或把这一调用记为已结清。

## 9. 开发验证及其证明力

下面均为已有制品，本报告没有重新执行它们。

| 验证 | 已记录结果 | 证明范围 |
| --- | --- | --- |
| Gate A完整工程 | 4285 PASS / 1既有可选SKIP，六项检查PASS | 原CPU执行修订；不是最新WMA全仓回归 |
| Note映射synthetic | 9 PASS，Ruff通过 | 序列化、回执/分页等局部合同 |
| MCP客户端synthetic | 最终9 PASS，Ruff通过 | 公共调用/错误与隔离接线的局部实现 |
| Provider synthetic | 最终15 PASS，后续elapsed检查15 PASS | 结构与计费记录；两次可能重叠，不累计成独立30项 |
| 服务工具零网络检查 | 6项检查通过 | 所有权、环境、固定作用域等离线边界 |
| Judge v2/v3/v4修订检查 | `PASS_ZERO_NETWORK` | 保留已有分数/失败、仅补缺口；不证明真实vLLM成功 |
| Judge语义smoke | 4个简单样例，8次真实生成，`JUDGE_CALIBRATION_PASS` | 少量正/错/否定/遗漏样例，不保证长历史评分一致性 |
| 原生公开主体隔离 | 4主体、24 HTTP，PASS | 本地原生实例的读取隔离 |

[验证目录](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1)保留早期Provider测试collection error以及后续修复，不能只保留最终绿色摘要。
接线说明另记录v4的25项mock/regex检查；它与上述旧测试范围可能重叠，且没有使随后真实评分请求完成，因此不作为新整仓通过数。

## 10. 失败归因与研究判断

| 现象 | 最早可证实层 | 当前结论 |
| --- | --- | --- |
| 网络池、迁移初始化、启动参数、依赖问题 | 实验启动/适配 | 已有局部修订；不能归为Memory错误 |
| Judge截断、无效JSON/计数、TAB循环 | 评价输出协议 | 7条历史invalid；6题完成补评，1题未裁定 |
| v4读取超时、无usage | Provider/评价执行 | 批次停止；具体服务端根因未知 |
| 相同答案标签不同 | 评价一致性/组合配置 | 不能可靠解释1题净差 |
| 题目/检索/图片记录相同但部分答案不同 | Reader行为差异，归因尚未隔离 | 不自动归为Note因果 |
| 约38%—40%的局部Correct率 | 当前模型Judge下的QA表现 | 未做独立答案语义审阅，不能说都是记忆固着 |
| 没有自主写Note、动作或纠正窗口 | 研究对象未覆盖 | 相应inertia/conditional reactivation/Recovery指标N/A |

本轮正面结果首先是**原生Memory接口往返与真实答题可运行**。
当前对照没有提供新的State调控变量，也没有形成比强简单方案更优的候选；这与“Memory调控无效”是两回事。

真正的研究限制有四项：

1. 双臂只覆盖一个独立root，后续五单元未运行。
2. 两臂可见检索材料相同，收益归因空间主要不在Memory使用政策。
3. Judge同模型且输出配置混合，存在直接可见的同答案标签分歧。
4. 普通Note为机械导入，没有完整自写—冷读取—世界变化—行动—恢复链。

因此本次选择为**保留简单方案，不选新机制；原生实验部分完成、效果判断INCONCLUSIVE**。
不能由本次暂停否定长期研究方向，也不能把已完成CPU工程包装成Memory创新。

## 11. 当前运行状态与服务边界

最新批次及Judge worker已记录终止；v4状态仍为`NATIVE_BATCH_FAILED`。
未运行的答题单元与review没有被追认完成，原始失败和未知用量保留。

只读进程核对还发现：本次隔离API PID885845与MCP PID891413仍存在，starttime与已记录所有权匹配。
**“实验批次停止”不等于“隔离服务全部停止”。** 本报告没有停服务、改数据库、重启共享vLLM、调用GPU或发出任何HTTP请求，也未以进程存在替代服务健康验收。
服务保留/后续清理由其明确所有权与后续指令决定；共享服务不能顺带处理。

旧Goal和导航中的`NATIVE_BENCHMARK_NOT_STARTED`已经落后于这些执行证据。
本报告同步当前状态与索引，但保留冻结Goal和历史终态，不回写历史。

## 12. 后续开发建议：先让现有结果可解释

这些是建议，不构成新增实验授权。

1. **先处理未知请求。** 使用已有请求追踪与服务端可用记录核对v4状态/用量；未查明前不自动补评。
2. **保留165份答案与164条有效评分。** 不重跑Gate A，不为更换评分方式重做全部答题。
3. **先决定评价口径，再修评价实现。** 把QA标签与Evidence评分完成度分开；抽核已有同答案分歧。任何新Judge配置都单列，不追溯替换旧失败或伪装统一评分。
4. **重新确认这两臂要测什么。** 若目的是公开Note存取保真，已有一根材料一致性与接线结果可作为有界工程结果；若目的是记忆政策收益，需要明确实际政策/输入差异，不能单靠存储名称不同。
5. **如继续原批次，只按新明确合同补受影响缺口。** 不扩root、不动确认池，保留所有成本；未运行项是否继续需结合实验价值，而不是为填满表格自动消费。
6. **若启动review，先承认额外调用。** 当前实现不是同调用基线；准确率比较应区分额外推理机会，效率比较应计入复核与评分成本。
7. **机制探索仍从重复失败出发。** association、可逆适用性、stability–plasticity等仍是待检验方向；Runtime不承担隐藏语义推理，不新增State schema来修评分格式。

不建议继续无限增加Judge约束、重复准入或审计抽象。
若更便宜、可解释的已有评价不能成立，应缩小评价主张或交付当前部分结果，而不是为一个缺失分数重建实验框架。

## 13. 可追溯证据与本报告验收

### 13.1 关键制品摘要

以下是本报告读取时的SHA256，不是对整个历史闭包重新认证。

| 证据 | SHA256 |
| --- | --- |
| [v1运行合同](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/frozen-manifest.json) | `169b561f10286242153c5c1086a4c682923f090bd4aa5e65e558457ec385fb22` |
| [v2运行合同](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/frozen-manifest-v2.json) | `6f5f4f2b112ea2a4d23ce9b7cd579535e9da6779b939ca59c911ec7ddfbd8182` |
| [v3运行合同](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/frozen-manifest-v3.json) | `fc0f75a16ccb098c22ccd2648ffe8b50e8ea81e0ece928b935f05f6fd7fe6e35` |
| [v4运行合同](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/frozen-manifest-v4.json) | `73431de1d8c07bc396d1842d84f4ae7f80b03500b353c04d3c37eb5368d0f162` |
| [最新批次终态](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/batch-terminal-v4.json) | `e622246ff72e530e20723820baaf865a7682e4d1935bfe38622a83fdcb497071` |
| [未知用量阻塞](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/runs/personal_18/M_note/judge-provider-v4/blocked.json) | `c7d1bb6293f3f0f35e1008351a481ca315459285a15f82ef04c192ce731bbff3` |
| [personal_18 baseline评分](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/runs/personal_18/B_native/scores.jsonl) | `08a9de05bd161a7272f68a09f5e6b208596ba08ef072021736ff455508e1eed1` |
| [personal_18 Note评分](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/runs/personal_18/M_note/scores.jsonl) | `bd371857923777448e5fb75244189a8c0d3add31b1ed8c6c37a1a4d93d7e6332` |
| [personal_10 baseline评分](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/runs/personal_10/B_native/scores.jsonl) | `4bab2b8eb5c4cb8229c6e6611e6917bdaebbefdb35f2b8834406502a1f159a64` |

三个答题记录、评分记录、四版合同、Gate A证书、旧Goal与接线说明在本轮报告期间保持原文。
完整来源/模型/接口配置以冻结manifest为准，不在报告中复制私密配置、密钥、原始corpus或图片。

### 13.2 本轮文档验证

仅检查报告与导航的本地引用、Markdown、算术/分母一致性，以及本次绑定的保留文件摘要是否变化。
**未运行模型、Judge、Product请求、CPU矩阵或全仓回归。**
原生批次失败与未知账务不会因“报告完成”而变成实验完成。

最终收口：**Gate A功能完成；原生WMA部分结果保留；Judge超时与未结清用量阻断继续；Memory效果与新机制价值尚不能判断。**

