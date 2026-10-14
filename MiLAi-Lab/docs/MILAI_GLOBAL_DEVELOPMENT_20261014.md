# 2026-10-14 全局开发记录

执行 `MILAI_GLOBAL_DEVELOPMENT_PLAN_20261014.md`，完整目标仍在进行。
主目录停在旧 main，故从规划指定的 `feat/lab-evidence-development-20261013` 创建
`feat/lab-global-development-20261014`，工作树为
`/cra/memory/mx_memory/MiLAi-worktrees/global-development-20261014`。
基础版本 `f86fc5c3`；本轮首批实现 `c33e325d`。未使用 SHA 或其他内容指纹校验。

## 已实现与边界

- A1：`MemoryService._visible_sources()` 只枚举当前 owner 可见 Source。
  `search_sources()` 不再遍历语义记录、历史或形成状态；`sources()` 仍提供形成状态展示。
  无数据库迁移、无重新形成。读取仍经原 Source 可见性和版本路径。
- A2：将已有 `_lexical_tokens()` 提取到 retrieval，原 service 导入入口仍可用。
  新 `source_tokenization=unicode_v1` 对查询和候选同时使用 NFC、casefold、Unicode 词和
  CJK 相邻双字；不改原文。旧默认 `rawrag_space`、RawRAG 的用户词面与排序保持。
  Benchmark 和 Functional Host 均实际转发此配置，`source_granularity` 也已接到现有调用。
- A3：在现有 `source_retrieval` 增加枚举、材料构造、建索引、排序、打开及总耗时。
  没有新增日志系统、模型调用、索引库或事实存储。
- B4：新 `reader_target=original_question_v1` 使最终 Reader 和完整输入预算计量都只使用
  原始问题，不注入分页生成的 `read_goal`。内部选择状态继续保存计划；旧配置保持原行为。
- B5：排序容量不足或调用额度不足时直接保存实际 `ranking.json` 失败，不创建假分页状态。
  已有逐题错误处理接收该回执，HaluMem／LongMemEval 的缺答评分保留原因，后续独立题继续。
  旧的批内排序方式未改；不将批次交错结果表述成全局排名。

`milai-global-source-v1.json` 是 A 配置，明确 `evidence_variant=S0`、session 粒度、Unicode 分词。
`milai-global-reader-target-v1.json` 在此基础上增加固定最终问题；它还不是完整 readpack 方法。
Product／Archive 实现与权限、Canonical、存储 schema 均未变。Lab SDK 增加可选参数，
现有结果增加耗时字段；旧调用默认值不变。

## 实际查询反馈

先固定输入、问题、需要召回的具体来源，再运行旧实现与新实现。
机制组包含 10 条中英文问题：无空格中文改写、同名主体、否定、共同条件、工具正文、
大小写、重音及数字；来源 40 条。真实组仅使用已经暴露的第一个开发用户，按时间取前
32 个会话、1322 个 Source，先根据实际 User 原话选定 10 条问题及各自必要来源。
两组保存在同一新建 SQLite 银行，查询按显式 Source allowlist 隔离。真实前缀长于 K20。
未读取其他用户或最终保留集，未把参考答案、QA 或 memory_points 写入 Source。

每题记录的是一个预先指定的必要来源是否进入候选，不是所有必要证据的完整性判断。
问题由开发者根据原文编写，不冒充官方 QA 评分或独立用户样本。

| 实现／分词 | 机制 Top-1／10 | 机制 Top-20／10 | 真实 Top-1／10 | 真实 Top-20／10 | 真实平均耗时 |
|---|---:|---:|---:|---:|---:|
| 旧实现／空格 | 2 | 2 | 5 | 10 | 1.425 秒 |
| 新枚举／空格 | 2 | 2 | 5 | 10 | 0.555 秒 |
| 新枚举／Unicode | 10 | 10 | 9 | 10 | 0.687 秒 |

保留空格分词时，两实现 20 题的交付材料逐字段相等，包含顺序、分数、正文和来源范围。
机制组的旧失败来自完整中文句子、大小写与标点不能匹配，零分来源由原平分规则排序；
没有把这些失败删除或改成成功。真实组新分词仍有一题必要来源只排第 7（旧为第 19）：
多个会话均讨论 mental health 与职业变化，词法相关性仍不等于指定时间的事实适用性。

真实组新 Unicode 路径平均分项：枚举 331.8 ms，材料构造 2.3 ms，建索引 141.2 ms，
排序 1.0 ms，打开 207.6 ms。建索引约占总耗时 21%，主要开销仍在枚举与打开；本切片
先保留重建路径，优先进入 B，后续在正常查询复用量与更长前缀下决定缓存收益。
未增加新向量库。这是单机每题一次的开发测量，不是稳定延迟分位数或服务承诺。

60 次查询为旧 20、新空格 20、新 Unicode 20；另有未计时空池预热。
模型／embedding 调用均为 0，语义写入为 0；不把本次纯检索结果称为新模型准确率。

结果索引：`data/manifests/global-source-v1-summary.json`。完整问题、银行、材料、计时和
诊断脚本保留在 ignored 的 `artifacts/global-development/source-v1/`：
`queries.json`、`memory.sqlite`、`legacy-results.json`、`new-results.json`、`summary.json`、`probe.py`。
旧历史银行和已有实验产物均未修改。脚本 prepare 用正常 capture API 建立这份新来源库；
legacy/new 只调用正常查询与读取，不调用形成、Reader、Judge 或 ActivationIndex。

## 验证与入口

分批通过 187 项直接相关检查：Source 4，baseline alignment 49，Reader／ranking／replay
95，新增逐题失败及评分闭环 2，Functional source／forget／formation 37。
首次新增 owner 测试的 namespace 构造不符合既有 owner 规则，已修正测试并通过；没有放宽规则。
Ruff、6 个修改源码的 strict mypy、包依赖边界和 tools Product 边界通过。
CLI prepare 已实际运行成功，未执行本轮模型 predict／score、全仓 CI 或远端 CI。

```bash
cd /cra/memory/mx_memory/MiLAi-worktrees/global-development-20261014/MiLAi-Lab
export PYTHONPATH="$PWD/src"
PYTHON=/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python
"$PYTHON" tools/run_baseline_alignment.py configs/milai-global-source-v1.json \
  artifacts/global-development/source-config-prepare-v1 --phase prepare \
  --benchmark halumem --runtime-dir artifacts/global-development/runtime
```

后续新的预测使用同一现有 CLI 的 `--phase predict --backend MiLAi-memory-only`，
须指定新的输出根；本次 prepare 根只有准备结果，不是已完成的预测。
固定最终目标对照使用 `configs/milai-global-reader-target-v1.json`。
旧实验保留原配置与根，不重跑已关闭的 patch 或 CPU MemSifter 失败分支。

## 尚未完成与下一步

| 规划项 | 当前证据与下一步 |
|---|---|
| A | 枚举、分词、耗时、双语机制与真实 32 会话查询已执行；后续按实际成本判断增量缓存 |
| B1–B3 | 现有 turn 分组仍不能独自保证跨轮指代、共同条件和语义 unit 支持闭包；需共享证据组合与预算内选择、明确缺口补读；不能把本次粒度参数接线当完成 |
| B4/B5 | 实现与接线回归通过；固定最终问题尚无新模型对照结果，排序仍是原批内策略 |
| C1–C4 | 尚待独立命题、完整受影响含义与时间原话改进；必须从模型实际 before 状态验证新连续故事及真实事件，旧 patch 语义损伤仍是已知问题 |
| D | 尚待按实际需要维护明确 unit/revision 依赖的状态视图；不能默认每消息总结 |
| E | A 的配置已共用 MemoryService；B/C 共用方法、完整 Functional Host 故事仍待实现验证。Product 接入以 Lab 实际收益为前提 |
| F | 条件性研发，尚无新瓶颈证据支持训练；不继续 CPU FP32 排序框架 |
| 实验／交付 | B 的同池 8–12 题、C 的更新联合成功、2–4 段短中长历史、最终保留用户及保存—更正—历史—撤销例外—忘记跨入口验证尚未完成 |

下一步优先让细粒度命中实际减少 Reader 输入，保留主体、角色、时间、条件与原始支持；
从同一候选池比较必要证据和任务结果，不能靠固定 top-k 或全池读完替代证据选择。
范围计数／穷举单独验证覆盖。代码保存在本地分支，未推送／合并，未核验远端 commit；
可回退本轮提交恢复原实现，不涉及数据迁移。完整目标继续保持 active。

## B 接通与真实反馈（后续实现 8fe9968d）

在原 A 分支上增加 `methods/evidence_reading.py`，初版 `7c2c1c17`，
首次真实问题修复后为 `8fe9968d`。配置 `milai-global-readpack-v1.json` 的
`evidence_policy=question_pack_v1` 已进入普通 Benchmark 与历史证据 replay 路径。
原分词／来源枚举和旧 Reader 默认不变。

- 原 session 候选按实际 User／Assistant／Tool 交流边界拆开；每包携带完整命中交流与
  前一交流。必要时模型显式选择 `expand_context`，只能打开该问题冻结的父会话范围，
  不从最终银行补入后到来源。不截取前 N 个字符作为证据。
- 单元命中按已有 `modifies`／`overrides` 边打开必要条件和例外，读取这些单元及关系的
  实际支持。共同条件不会自动打开其他无关目标；被直接命中的条件则保留其实际作用域。
- 模型只接收短标签、角色、报告／捕获时间、原文范围、事实和支持。内部来源定位、
  原件／unit 身份和完整上下文范围留在原 snapshot，当前可见性仍经 MemoryService。
  撤销的原文也不进入候选摘录。
- 大池先读导航，按模型给出的优先级准入完整证据包。整个请求包装参与预算计量，
  排除项返回给同一 Reader；只有明确缺口才继续选材。小池可直接一次回答。
  模型可以在其余候选未读时回答 lookup；调用总额没有增加。无进展时用剩余额度
  输出受支持部分和缺口，不伪造已消耗调用数。

60 项相关回归通过，真实故障修复后又跑过 6 项直接测试；Ruff、2 个修改源码 strict mypy
和 package boundary 通过。另有旧未来来源排除、忘记后正文／目录不泄露、真实 SQLite
语义单元与支持、预算排除反馈和无进展停止回归。未完成全仓或远端 CI。

### 固定两题与保留的首轮失败

从原 fixed24 中预先取第一道 direct（U1/S0/Q1）和第一道 paged（U1/S4/Q2），
固定来源到达范围、问题／日期、主模型与预算。控制组用旧 S0 材料路径，但显式固定
最终原始问题；新组在同一实际原文池内构造证据包，不重新形成、检索或写 ActivationIndex。
两题是一个已暴露用户的接通反馈，不能据此推断多用户效果。

初版 readpack 的 direct 正常交付；paged 的模型却直接根据导航摘录回答，正式证据为 0。
官方首次标签虽然也是 Correct，仍判定 B 的事实交付机制失败，不把它算作成功。
`e8a30cc8` 将尚未打开正文的选择阶段 schema 中 `answer` 限定为 null；后续类型／格式
修复组成 `8fe9968d`。只在新根重跑受影响 paged 题，原输出、费用和标签保持。

| 实际条件 | direct | paged | paged 调用／生成 tokens | paged 耗时 |
|---|---|---|---:|---:|
| 历史原 S0（79749893，参考） | 原历史不重跑 | Correct | 4／79,701 | 72.95 秒 |
| 本轮 S0＋固定最终问题 | Correct | 读取额度耗尽，缺答 | 11／93,917 | 173.91 秒 |
| readpack 初版 | Correct | 官方 Correct；**正文交付失败** | 1／11,018 | 19.22 秒 |
| readpack 修正，仅 paged | 不重跑 | 已答、正式交付 7／82 包；官方 invalid | 2／26,399 | 34.03 秒 |

历史原 S0 的 read_goal 条件不同，不能与本轮控制混作纯单变量对比；它原本就能答对此题，
所以也不能把本轮控制缺答当作整个 S0 的能力上限。新方法目前只有成本／交付信号，
没有已确认的准确率提升。

修正版第一次实际选择响应 `answer=null`，提名 7 包；第二次输入包含这 7 包完整正文，
其余 75 个候选没有被迫翻页。User 原话包含品种交互、温和／适应性、情感陪伴、
平衡与放松；角色、原始报告时间和引用范围都到达最终输入。Root 非独立来源复核认为
主要宠物选择推断有支持，但“用户承认事业 demanding”的措辞比已选 User 原话更强，
相关职业框架也来自题目与 Assistant，不据此宣布完整来源忠实通过。

修正版官方 Judge 首次输出 `{}`，故保持 invalid；没有补判或择优评分。
这与答案是否得到原文支持分别记录。direct 两臂均一次调用：控制 5,097 tokens，
候选 4,719 tokens。新调用未因为简单题多出选择步骤。

上述全部实际尝试合计 20 次生成、149,457 已知 tokens：预测 16 次／141,150，
Judge 4 次／8,307；新增 embedding、语义维护、未知用量均 0。
全局未知用量仍为 generation 9／embedding 1，没有重置账本或退回旧未知预留。
共用源运行的形成与召回成本沿上一轮报告单列、只复用一次，未从系统成本中抹去。
所有三个 predict／score 终态均已关闭、`resources_settled=true`；没有自动重试队列。

可读结果：`data/manifests/global-readpack-pilot-v1-summary.json`。
原件位于 ignored 的 `artifacts/global-development/{readpack-pilot-v1,control-pilot-v1,readpack-pilot-v2}/`，
来源复核为 `readpack-pilot-source-review.json`。各自 CLI 配置为同名的
`configs/milai-global-*-pilot-v*.json`；代码快照在 `source-readpack-v1` 和 `source-readpack-v2b`。
中间未运行的 v2／v2a 快照不是额外实验。

### 下一切片仍需完成

B 当前是已接通 MVP，不是全部完成：范围／穷举仅有 task 标记和明确的不完整覆盖描述，
尚未建立对声明范围的完整交付证明；实际模型主动请求扩大上下文也尚未测到。
必须用新条件／否定／跨轮样本和约 8–12 题同池比较继续验证，不能用这个正向宠物例子
反复调提示。单元与支持闭包只有真实 SQLite 回归，尚无新语义路径模型成绩。
共享核心已提取，但 Functional Host 仍需接入，不能把“模块可复用”当作 E 验收。
C／D、2–4 段连续长历史、最终保留用户与规定的完整状态／撤销／忘记故事仍未完成。
本轮没有推送或合并。完整目标保持 active，下一项优先补齐范围覆盖和正常 Host 接线，
再做有限多题比较与 C 的完整命题更新。

## 范围覆盖、Host 共用和 C 的实际更新反馈

`4205c74b` 接通请求时可见 Source 范围和正常 Functional Host。查询可显式保留超出 lookup
配额的范围描述；普通 lookup 的目录仍按原配额，`task=range` 使用当时捕获的完整范围。
程序比较实际打开的 Source／revision／原文区间，后到来源不会进入旧问题。小范围（包括
空范围）可以证明已完整交付；装不下时明确记录排除和缺口，不把 lookup 停止当作完整性。
这里证明的是当前可见来源的覆盖，不是外部世界或任务答案正确。

Host 的 `read_evidence` 与 Benchmark 复用 `build_evidence_packs`、`open_evidence_packs`、
`admit_pack_indices`、`project_pack` 和范围比较。Host 继续由其原 Agent 做决策，没有嵌套
第二个 Reader Agent。新工具沿用现有读取额度和重放身份；保存、历史、忘记与实际业务工具
保持原边界。所选正文经当前可见性重开，操作定位仍在程序侧。

实际新合成 Host 两题使用 K1 故意触发范围读取：

- 项目枚举真实打开全部 3 条来源，得到 A→李明、B→王芳与外部确认规则。
- 跨轮条件题打开了澄海上下文；青岚信息却只经旧 `search_memory` 目录到达，未完成该部分
  新证据包正文读取，不能计为完整 B 交付成功。
- 两题首次均出现已确认 `stop` 但正文为 null。各沿既有 CLI 做一次无工具、只读回答恢复后，
  文本可交付且与原文相符。首次失败保持；恢复成功不是首次成功，也不是独立语义评分。
- 合计 11 次生成／51,680 tokens，embedding 0、新 unknown 0；没有语义记录或业务变更。
  详细索引 `data/manifests/global-host-packs-v1-summary.json`。

相关检索／范围／Functional 回归 421 项通过；空范围及新直接路径 9 项通过。已运行 Ruff、
受影响类型与包／tools 边界。`host-packs-v1` 只有 CLI prepare；实际模型根是
`artifacts/global-development/host-packs-run-v1`，运行源 `4205c74b`，逐 attempt 原件保持。

### C：从实际形成状态开始，不把提交数当联合成功

`a709bb2c` 增加显式 `edit_features.proposition_updates`，默认关闭。
Editor 指导独立命题、完整受影响表达、保留非目标和限定；Extractor 的既有 time 字段用于
原话，Writer 不应把报告时钟填成事件时间。配置 `milai-global-propositions-v1.json`
明确使用 single-pass，保留已有算子与提交边界。195 项 edit／Functional Edit 检查通过。
合成 12 事件与独立的 evaluator-only review 文件位于 `data/fixtures/milai-global-propositions-v1*`；
review 内容不进入 Host／Writer。没有手写理想 before。

Host 首次在事件1遇到重复 `new_assertion` 类别标签，被旧接口拒绝，维护未运行。
`42fe55bd` 仅在模型输入边界合并重复类别／禁止项，仍校验每个值，不处理实际业务动作列表。
原失败根 `propositions-v1` 保存。新根 `propositions-v2` 真实形成一个6单元记录，事件2保持r1，
事件3改到r2，事件4保持，事件5添加临时例外到r3。事件3需一次只读回答恢复；事件5原答复及
一次恢复均为已确认空正文。后续事件6又被 Host 的业务续接引用解析阻断，尚未进入 Editor。
该连续 Host 只实际尝试到6，不能宣称完成12或 C 验收。

实际事件6的分类同时认可 `memory_requests=[explicit]`，却要求解析没有可用对象的业务续接。
`f5ef26c9` 让已配置的 `independent_memory` 政策也处理这一确定的无业务许可结果：保存失败
业务分项，继续当前明确的独立记忆工作；不为缺少原件的旧保存续接开通权限，未知结果仍停止。
同一提交让 Host 在真实读取额度变成0时立即说明应据已交付材料回答，无须再发一次必拒读取。
19 项相关接口回归通过，覆盖无记忆许可、fail-fast、未知用量与业务权限；新代码尚无真实 Host
复核，不把该修复算作已完成正常链。

为了继续研究写入方法，另外通过普通 baseline CLI 调用同一维护核心，使用同12条原始输入、
各自空银行。原 Host 的失败不被覆盖；两个入口的实际产物与条件分开，不能混称同一结果。
Core 配置没有 QA 或参考答案，仅运行到达和维护；并非通过跳过 QA 取得准确率。

| Core 条件 | 实际事件 | 生成调用 | 输入／输出 tokens | embedding 调用／tokens | 当前记录／可读历史版本 |
|---|---:|---:|---:|---:|---:|
| core-v1（2e8f1895） | 12 | 18（11 edit＋7 select） | 36,862／33,055 | 11／601 | 4／5 |
| core-v2（f5ef26c9） | 12 | 12（全部 edit） | 48,366／2,236 | 18／2,627 | 1／7 |

core-v1 首次形成和未来更新返回空提案，后续不能当成从理想状态继续；第11事件的 selector
达到输出上限。core-v2 在完整候选和旧支持能按整体输入预算容纳时直接给 single-pass Editor，
省去模型选择；不截正文，不降低候选范围。预算不足仍走原选择路径；两个直接回归覆盖两种分支。
它还澄清空 change_candidates 不等于没有新事实。成本降低没有替代质量要求。

core-v2 **仍未通过 C 的联合成功条件**，已经检查实际 proposal 和状态：

- 初始形成把完整复合叙述与 A/B 等条目重复保存，没有达到可靠的独立命题粒度。
- 事件3、12因为新文字错误保留旧断言／不匹配支持而被拒绝，分别为
  `EDIT_UNIT_SUPPORT_BINDING_INVALID`、`EDIT_CHANGED_ASSERTION_REQUIRES_NEW_EVIDENCE`。
  保留拒绝，未放宽来源绑定来让更新通过。
- 事件6撤销例外后，A 的未来赵敏安排没有形成正确当前状态；事件9将 B 单元改为陈琴，
  旧概括仍写王芳，存在同记录矛盾。
- “最近开始考虑”和“仍在考虑”仍被填入精确 event_at。值已在模型原始提案中，
  不是程序提交时注入。保留原话提示尚不足以确保时间忠实。
- 事件2、4、10实际保持版本，SMS 正文的未决定语气保留；但这些局部结果不能抵消以上损伤。
  在只读复制的银行中分别重开全部5／7个历史版本，均可读；历史可读也不等于当前含义正确。

两个 Core predict 终态均为 `PREDICTIONS_SAVED`、资源已关闭；无新的 Judge／QA 调用，
没有从已有原文 Reader 的正确性给存储损伤补分。全部逐事件结构与成本在
`data/manifests/global-propositions-core-v1-v2-summary.json`，原件保留在
`artifacts/global-development/propositions-core-v1`／`propositions-core-v2`。
`propositions-v2` 的首次 run、event3恢复、event4–5尾段和event6尝试分别保留，不自动重启。

### 下一步仍围绕原规划

优先修正 C 的生成契约与源支持接线：完整命题与概括分离，新文字不使用旧断言 keep，
精确时间必须有原文依据。避免继续围绕同一食品例追加提示，也不以关闭校验换取提交。
随后从真实 before 比较 single-pass／extract-then-edit，并加入真实开发更新来源。
Host 的独立工作恢复与读取终止修复需实际重查；B 仍需约8–12题同池质量／成本反馈、
真实缺口扩读与覆盖语义检查。D 的依赖视图、连续长历史、最终保留用户及完整
保存—更正—历史—撤销例外—忘记故事均未完成。Product／训练仍按规划条件推进。
截至这个检查点没有活跃模型任务；后续仍核对实际进程与终态，不以旧 PID 作为依据。
全部新结果和失败均保留，未推送／合并，完整目标继续 active。

## C 的源绑定契约、D 按需依赖与 B 扩展读取

### 生成契约修复（be7c5e6f）

新增 `memory/source_times.py`，只从实际交付原文形成时间候选。ISO／中文／英文完整日期、
原文 ISO 时间保留其精度；有报告日期锚点的明确相对日只作为带锚点说明的候选，模型必须确认
该短语确实使用该报告时钟。模糊“最近”等和无可靠锚点不提供精确值。捕获／提交时间不参与。
模型选择 `t#`，程序填入既有 applicability 字段；整日 `t#:end` 展开为下一日的排他边界。
没有候选时不提供可自由填写的精确时间字段。规范化后的存储 schema 不变。

新 replace 的生成 schema 使用新断言来源，不再提供 `assertion.keep` 给新文字；
旧支持限定为该目标单元的实际支持。精确时间引用还须属于该提案实际选择的证据。
现有提交检查保留。条件／命题的描述更明确，禁止用重复概括替代独立命题。
208 项相关测试、四源码类型、Ruff 和包边界通过。

同12事件、各自空银行的 core-v3 明确打开 Editor thinking，保持原8192输出上限与窗口，
因此不是只改 schema 的单因素归因。12次 edit 用54,332输入＋36,416输出，19次embedding／1180tokens。
实际形成四条独立主张，未来A联系人修改成功，例外撤销保留赵敏一般安排，B历史纠错与C局部
规则均进入状态；“最近／仍在考虑”没有虚构精确 event_at。最后为通知记录r8和财务记录r1。
从只读备份重开全部9个版本均成功。

在另一份副本调用现有 SDK 忘记财务记录及来源：当前／历史／原文均不可再读，通知记录完整value
保持，通知历史仍可读。实际 effect=visibility_only，physical_erasure=false。此为 SDK 机制证据，
不是已完成正常 Host 自然语言遗忘。Root 检查说明：事件7的简写正文省略“最近”，原话仍在实际
支持来源；部分正文还保留请求式措辞，未宣称完美规范化或无源语义视图已经足够。
详见 `data/manifests/global-propositions-core-v3-summary.json` 和 ignored 的 `c3-state-audit/`。

### 同一真实 before 的 recipe 比较与新自然来源

从上述真实模型形成的最终状态逐题复制，三个新事件分别比较未来联系人变化、短信计划否决、
明确保持；两 recipe 每题 before 的完整记录值逐项相等。没有手写理想前态。

| recipe | 3题生成调用 | 输入／输出 tokens | embedding调用／tokens | 实际观察 |
|---|---:|---:|---:|---|
| single_pass | 3 | 18,165／6,506 | 6／1077 | 两项修改提交，保持题不变 |
| extract_then_edit | 9 | 23,950／28,534 | 6／1073 | 新11月1日错选旧10月20日时间引用被拒；保持题重写并丢失旧纠错说明 |

时间拒绝原提案选 `t2`，其原文属于旧来源，未作为本项新证据选择；保留拒绝，不放宽边界。
该对比支持在这个已声明的简单变化切片继续 single-pass，不能外推全部复杂事件。
结果见 `data/manifests/global-recipe-pairs-v1-summary.json`。

另选同一已暴露开发用户的两个新主题，未重跑旧食品／就业分支：实际原文中的旅行偏好与
工作着装变化。正常模型先从两段原始交流形成2条记录，再为两个更新分别复制同一真实seed。
旅行更新保留“文化丰富＋人群可控”，四项非目标旅行偏好和另一条服饰记录原样保持；
着装由casual business改为smart-casual，另三项偏好（含不喜欢正装）及旅行记录原样保持。
目标各仅一个单元变化，历史v1与seed相同，没有补出精确事件时间。
共享seed和两次更新共4生成／21,330输入＋14,821输出，6embedding／2804tokens。
这是 Root 的来源复核，不是独立确认或两个独立用户。见 `global-natural-propositions-v1-summary.json`。

### D 的最小明确依赖（a171b814）

证据视图记录实际 record revision、选中 unit IDs、根命中和关系 IDs。普通 Host 重开时，
只有这些单元或关系变化才重建视图；同记录无关单元变化只标注依赖保持。被撤销单元不再作为
当前事实。实际使用的支持来源用于曝光记录。全程没有新摘要模型、相似度依赖图或第二事实库。
冻结 Benchmark replay 只重开原版本，不访问最终银行的后来版本；新回归实际禁止了这种读取。
更新B不刷新A，更新A的真实条件则刷新A，两种路径均在真实SQLite上验证。新D/读取回归12项通过。
D 还需通过实际查询比较其价值，未以“依赖字段存在”代替收益验收。

### 固定8题同池读取（a171b814）

按旧fixed24的时间／类型／既有direct-paged元数据预定2个direct＋6个paged，覆盖原4个开发用户。
原始问题、日期、主模型、窗口、调用额和到达前缀相同；不重新形成或检索，不写ActivationIndex。
控制用S0＋固定原始目标，候选用证据包，均保存首次官方标签。

| 条件 | Correct／8 | 其余结果 | 预测调用 | 生成tokens | 逐题耗时合计 |
|---|---:|---|---:|---:|---:|
| 控制 | 3 | H4、invalid1 | 33 | 712,686 | 565.38秒 |
| readpack | 5 | H2、缺答1 | 13 | 222,603 | 390.29秒 |

配对仅候选正确3、仅控制正确1。生成tokens约下降68.8%，调用下降60.6%；不能把小样本时延
当稳定服务分位数。Root 对两道分歧题做了两臂实际最终输入复核：部分被Judge称为不存在的
公司／职务细节，实际上有User原文；另一方面，两臂也混入部分Assistant扩展描述。
因此保持官方3/8与5/8，但不把整个净差都归因于质量改善，也不重判invalid。
结果与复核范围见 `data/manifests/global-read8-v1-summary.json`。

缺答是首次目录选择达到32768输出上限。新增选择阶段独立 thinking 接线，并用两题有限试跑：
原缺答题及首个paged成功题。v2在配置验证阶段暴露遗漏的select允许项，0模型调用；修复后新v3
两题均有答，原缺答修复为Correct，另一题由原Correct变Hallucination。共5调用／91,752tokens，
首次标签1C1H保留；没有扩大整套矩阵，也不宣称这是新的质量提升。最终 Reader thinking 未变，
选择 thinking 仍为显式选项。见 `global-selector-pilot-v3-summary.json`。

### 正常链与长期机制的剩余执行

完整正常 Host 故事已准备并启动：12更新＋生效前／后查询、真实历史、遗忘与重开，共17消息。
配置 `milai-global-story-v1.json`，fixture `milai-global-state-story-v1.json`，运行源 `dbc3bda8`。
前5消息完成，第6消息已真实撤销例外到r4，一般赵敏规则和此前李明均保留，但自然答复和一次
既有只读恢复仍为null正文。已保留失败；后续未尝试输入从实际已确认状态继续。
当前运行状态必须查看 `global-story-v1` 的逐attempt和实际进程，不从这段文字推定终态。

长期机制已在 `artifacts/global-development/long-history-v1` 预定两个开发用户的前32会话，
在8／中段（18或20）／32观察，每点两条已有非boundary题，选取规则在运行前固定。
初版前两题规则在一个短段只得到boundary题，故在零长期运行前按既有类型元数据改为优先非boundary，
初版协议保留。原始历史、问题及既有标签没有改写；长跑尚未派发。

仍待：完成并复核17消息正常链；D真实查询价值；两段连续长历史与全部成本；最终候选冻结后的
保留用户确认；按收益条件决定 Product 公开适配与后续训练。整体目标仍 active，未推送或合并。
