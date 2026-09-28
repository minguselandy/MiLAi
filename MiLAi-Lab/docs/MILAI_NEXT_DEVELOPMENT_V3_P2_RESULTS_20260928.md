# v3 P2：普通记忆形成与有限结果纠正结果

**P2 未达到扩大门槛。保留本切片更简单的 B0，停止 C 的默认化与效果主张，不追加同题提示调整。**
B0/B1 的五次新事项形成和一次联合修订均成功，七次后续查询均正确；两者都漏了当次 BRIEF 格式。
C 正确处理该格式，但丢失两个持久正例，成本更高；真实结果校验暴露了错误声明，未使所有声明和行为收敛。
[完整机器清单](../data/manifests/next-development-v3-p2-results-20260928.json)保存逐消息评分、操作/身份摘要、实际请求用量与全部失败。

## 身份、输入与真实执行

- 方法提交：`2a7284bcbd405057d3a5fb4a70ca9ad3b99c6328`，[PR66](https://github.com/minguselandy/MiLAi/pull/66)。
- 执行 freeze：`d608f4c1601a0dac16d8af94baf31f9de002ac4b93bb852459fdbe46393a8343`；18 个 prepare 均核对 157 个 runtime 源码/入口身份与该 Git 提交字节一致。
- [事先协议](MILAI_NEXT_DEVELOPMENT_V3_P2_FORMATION_20260928.md)和[九份冻结 JSON](../data/diagnostics/next-development-v3-p2-formation-r1/)包含配置、六输入、rubric、顺序；真实运行后均未改字节。
- 六个新构造开发脚本，每臂 15 消息、7 次后续查询；18 个 job/45 消息全部执行，均单次尝试，无替换、重试、补种或轨迹拼接。这些样本现在全部已暴露，不是独立确认或原生 benchmark。
- 每条消息新 session，各 job 的 namespace、Postgres 普通记忆、checkpoint 和 SQLite 业务世界隔离；共同 Retained，只交付当前消息和实际持久记录。P2 没有进程重启业务链或真实 DELETE，这些能力不能由 P1 Mock 检查补成真实 P2 结果。

Host 仍 Qwen3.6-35B-A3B-FP8，temperature=0、thinking=false、4096 输出、65536 容量、每公开消息 12 次上限；
embedding bge-m3/1024 维。Root 串行执行，未改服务设置、下载权重或部署新服务。
实际 69 个 generation provider ID 唯一、19 个 embedding 事件；无 HTTP/本地容量错误、额外 Judge 或 controller 调用。
Root 核查全部 69 份实际 HTTP：当前用户字节精确、只有本会话用户消息、实际当前记录确在请求中、
真实工具回执带可见引用且原 JSON 后缀保留；C 纠正时业务工具已从目录移除。所有业务动作均为 0，符合脚本要求。
链路审计 SHA `223881fffc7ff892634ddea0c859b9403748dc04884ce6192ba670a1a63703f2`。

## 五层结果

| 口径 | B0 | B1 | C |
| --- | ---: | ---: | ---: |
| 实际完成公开回合 | 15/15 | 15/15 | 15/15 |
| 新事项形成 | 5/5 | 5/5 | 3/5 |
| 局部修订＋保留其他条件 | 1/1 | 1/1 | 0/1 |
| 明确持久要求联合成功 | 6/6 | 6/6 | 3/6 |
| 后续独立会话使用 | 7/7 | 7/7 | 5/7 |
| 四个持久正例完整语义链 | 4/4 | 4/4 | 2/4 |
| 引用／临时／只读未误持久化 | 3/3 | 3/3 | 3/3 |
| 当次 BRIEF 格式 | 0/1 | 0/1 | 1/1 |
| 六脚本完整通过（含当次格式） | 5/6 | 5/6 | 4/6 |
| 最终保存声明无实际记录支持 | 0/6 | 0/6 | 2/6 |
| 实际 memory CREATE / UPDATE | 5 / 1 | 5 / 1 | 4 / 0 |

进程/回合完成不等于语义成功。C 的四次 CREATE 中一次仅创建新的 link 偏好，不能补成最初三项偏好形成或联合修订通过。
C 原始偏好未形成，真实 UPDATE 因此没有被激活；0/1 是完整修订＋保持链失败，不是 strict UPDATE 工具执行失败。
所有臂都未将引用或一次格式要求升级成长期规则，只读回合也没有无必要写入；这不消除 B0/B1 当次格式漏执行。

| 脚本 | B0 / B1 | C |
| --- | --- | --- |
| field_plan | 真实 CREATE，下一会话正确给出数量、目的地、包装及未预订状态 | 两次终答都声称保存且引用虚构标识，无工具调用/记录；下一会话如实说无计划，持久链失败 |
| editorial_revision | CREATE 后对同一真实 ID UPDATE，只改 source links，保留 heading/date；后续三项正确 | 初始三项未保存；修订时空 search 后 CREATE 仅新 link 偏好，后续只能回答该项，heading/date 缺失 |
| independent_note | 两件独立事项自然形成并共同复用，无覆盖 | 两次初始无写入声明触发纠正，随后分别实际 CREATE，后续两事项完整；第二次终答错把记录 ID 当 receipt ref，协议仍失败 |
| quotation | 正确解释引用，后续无本人采纳偏好；无写入 | 同样通过，后续直接使用空实际记录视图，无额外 search |
| temporary | 没有当次 BRIEF；下一会话格式正常、无持久污染 | 当次 BRIEF 与下一会话正常格式均正确，无写入 |
| read_only | 实际保存后两次只读复用正确、原内容保持 | 初始错误声明后，纠正中实际保存；两次复用正确，无额外写入 |

独立事项和 readonly 的语义成功，不能被 C 的引用校验结果替代；独立事项第二条即为“正文真实正确、结构引用不合合同”的实例。
保存声明错误只按每公开回合最后交付的回答计分；内部初始失败候选仍保留，不能重复计成多个独立用户样本。

## C 实际激活与未完成

15 条公开消息产生 20 次终答候选，全部带结构字段。5 次初始声明无当前真实写入支持，均进入唯一纠正；
纠正消耗 8 次实际生成、10,934 tokens，占同一原有容量，未加公开用户消息或重放业务。

| 纠正后的观察 | 数量 | 解释 |
| --- | ---: | --- |
| 真正 CREATE 且终答引用实际工具回执 | 2 | independent handoff、readonly 初始保存 |
| 真正 CREATE，但终答引用新记录 ID | 1 | independent key note；保存正文正确，结果字段仍不受支持 |
| 仍无写入并声称已保存 | 2 | field_plan、editorial 初始形成 |

终答 12/15 机械受支持：3 个 committed、9 个 no_change；另 3 个 committed 不受支持。
模型未发出 unresolved。field_plan 中先后出现 `mem_001`/`mem_002`，校验准确标记缺失实际回执，但模型没有据此写入。
第二类错误使用真实 ordinary record UUID；它也不是本回合工具回执引用，不能为满足声明而放宽旧冻结评分。

这些是本轨迹的实际续接观察，不是 C 相对“相同 C 无纠正”的随机因果效应。C 对 B0 没有持久任务优势；
同计算 E6 未触发，不因观察到三次补写就声称纠正带来方法净收益。
全部 real CRUD 回执成功；失败发生在未提案、没有前态或声明不符，不能重新归因为 Store 丢写。

## 全部成本与互斥阶段

| 臂 | Generation calls | 输入 tokens | 输出 tokens | 总生成 tokens | Embedding calls / tokens | HTTP wall 秒 | 进程 wall 秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 22 | 18,884 | 868 | 19,752 | 7 / 230 | 10.012 | 37.296 |
| B1 | 22 | 25,301 | 905 | 26,206 | 7 / 220 | 9.974 | 34.014 |
| C | 25 | 30,940 | 2,087 | 33,027 | 5 / 123 | 18.001 | 41.920 |
| 合计 | **69** | **75,125** | **3,860** | **78,985** | **19 / 573** | **37.987** | **113.230** |

B1 与 B0 在本冻结评分上相同，总生成 tokens 多 6,454（约 32.7%）；C 比 B0 多约 67.2%，且持久质量更低。
C 的单次格式优势保留，不声称 B0 在所有质量轴上支配 C。B1 的 HTTP/进程 wall 较低不推出速度优势：
这里只有一次小运行，进程含导入/初始化、CPU 可与服务等待重叠，未做独立延迟试验。
更少 embedding/存储字节可能来自漏形成、内容长度或空记录，不能称为压缩收益。

| 臂 | formation 生成 tokens | maintenance 生成 tokens | use 生成 tokens | recovery |
| --- | ---: | ---: | ---: | --- |
| B0 | 7,488 | 3,944 | 8,320 | 本切片未设计 |
| B1 | 9,834 | 5,072 | 11,300 | 同左 |
| C | 13,155 | 8,297 | 11,575 | 同左 |

按执行前 rubric 互斥计账，独立新增 note 的质量属于形成，但该混合持续任务阶段的费用只归 maintenance 一次。
quotation/temporary 初始解释归 use；每项实际请求仅计一次，C 纠正已包含在表中，不能再加到总额。
六脚本 R 分别为 1、1、1、1、1、2；失败仍在分母。聚合总 tokens/7 为 2,821.7、3,743.7、4,718.1，
仅是不同脚本混合的计划查询机会摊销，不是每次查询边际成本，更不是每个成功生命周期成本。

| 已测观察项 | B0 | B1 | C |
| --- | ---: | ---: | ---: |
| 实际 ordinary snapshot 读取 calls / 逻辑 bytes | 43 / 6,129 | 43 / 5,905 | 46 / 4,446 |
| post-turn checkpoint 读取 calls / 逻辑 bytes | 15 / 21,692 | 15 / 21,706 | 15 / 45,509 |
| C 同 ID 标记写入 calls / 逻辑 bytes | 0 / 0 | 0 / 0 | 5 / 11,137 |
| 初始化 namespace guard calls | 18 | 18 | 18 |
| 整进程 user / system CPU 秒 | 34.411 / 2.974 | 33.759 / 2.530 | 34.039 / 2.497 |

这些只覆盖明确测量的观察边界，不是全部物理 DB I/O。普通写入 CPU、物理 I/O、GPU 小时和货币成本保持 unknown。
持续账本由 **2881 / 3,650,322 / 20,156** 到 **2950 / 3,729,307 / 20,729**（生成调用／生成 tokens／embedding tokens）。
终点 SHA `28cbcfe8c0be9208aaa9e6898daa36dcaa1d9202ee27fa73a613d5f45f7a4e38`；
69/78,985/573 与逐请求 trace 差额一致，sealed history 原字节结构保留。当前 known=charged、unknown=0，旧账本中历史未知费用没有抹除。
成本审计 SHA `a11257a2ac91af61137aba2ccbbf7c1a2fae4a8b66f0a7ff10ba136e4eb16dd5`。

## 失败解释与门槛

**C 漏形成及错误引用。** Observed 是初始“已保存”的终答先于任何工具提案，错误由校验发现却两次仍未修复；
Expected 是真实写入/合法沿用，未完成则如实报告。实际链为合法用户输入与相同工具目录→直接终答假引用→
零工具/空库→一次 memory-only 反馈→零写入或实际补写→下一会话实际记录→实际回答。
首断点是 Host 选择终答而非执行记忆操作；独立 note 的另一个断点是写入后的标识类型选择。
竞争解释至少有二：结果 schema 被当成声明式操作，诱发“写出 committed 等于完成”；新增的 record ID／receipt ref 区分增加报告负担。
后者能解释已写却错引 UUID，不能单独解释 field/editor 的零写入。另有输出结构/注意分配和单模型偶然性混杂，不能由这六例确认唯一机制。
通用修复候选可以是更简单的普通职责流程，或另立清楚的结果引用接口比较；禁止按样本/标准答案自动写正文，禁止改服务 parser。
最小未来区分实验若另获授权，应固定任务、合法材料及预算，只比较一种结果接口，并使用新任务族；本批不执行或调词重跑。

**B0/B1 当次格式遗漏。** Observed 是回答未以 BRIEF 开始，后续并无泄漏；Expected 是只在第一条适用。
实际请求保留该指令，原 provider 答案即无 BRIEF，排除了适配器剥掉前缀。
首断点是当前回答没有消费当前约束。竞争解释为模型倾向直接给知识答案，或同时处理“本次/长期”范围时忽略正向格式要求。
这不是持久记忆污染，新增 State 或在 runner 硬拼固定前缀不成立；未来可用独立临时约束任务区分，但本轮不扩样。

| 条件分支 | 判定与依据 |
| --- | --- |
| P3/E2–E5 | NOT_TRIGGERED：B1 无完整脚本改善；C 仅 temporary 更好，同时 field/editor 更差，未达到两个独立改善 |
| P4/E6 | NOT_TRIGGERED：无 P2/P3 有效持久收益；C 没有相对强普通法的记忆优势可供等计算确认，未运行 raw 外部对照 |
| P5 | NOT_TRIGGERED：部分 bank 已非空，但没有有任务依据的 query/all 瓶颈，也没有满足五项共同条件的新 State 操作问题 |
| P6 | 完整报告、反思、复现及发布收口；不把条件未触发伪称已完成实验 |

Continue 保留普通工具、隔离和真实成本记录。Pivot 到此切片足够的 B0，不将长职责说明默认化为有益。
Stop C 的默认化/论文效果主张，保留显式 opt-in 入口复现。小样本结果不否定所有未来完成接口，也不证明稳定 unseen 等价。

## Reflection：总规划 §32

| 问题 | P0 接口/历史核对 | P1 实现与检查 | P2 真实结果 |
| --- | --- | --- | --- |
| 1 支持什么 | 旧回执已送达，责任提示已存在 | 同 graph/同容量的机械边界可实现 | 普通 B0 在明确短任务可实际形成、修订和复用 |
| 2 反驳什么 | 不能归咎于提示完全缺失或回执丢失 | 工程通过不证明语义保存 | 单一强职责/结果字段必然改善持久效果未获支持 |
| 3 首断点 | 旧 Host 未提案或未维护正文 | 旧最终 schema 无结果字段；有限扩展已完成 | C 先报完成后无操作；B0/B1 未消费当次格式 |
| 4 更简单解释 | 历史替代感、双库职责负担 | 公开 graph 续接足够，无需新平台 | 短明确输入和单普通库已足够；与旧 N5 多变量不同 |
| 5 更简单方法 | 核对实际链，不重造历史 | 普通 CRUD＋可关的核对 | 本切片 B0，保留 C 的单次格式正例 |
| 6 复杂度是否值得 | 一份协议足够 | 有工程价值，无先验算法收益 | 额外 schema/引用/调用未获净持久收益支持 |
| 7 过拟合风险 | 两条历史仅用于定位 | 合成 Mock 不当模型样本 | 六新构造脚本均已暴露，不调参后称 unseen |
| 8 未来反例 | 合法回执后仍不采用 | 未覆盖任意崩溃/跨库原子性 | 新任务族的业务维护/退出/实际检索瓶颈，须另有触发证据 |
| 9 决定 | Continue 到已定义 P1/P2 | Continue 到冻结小样本 | Pivot 普通方法；Stop C 默认化；不触发 P3/P4/P5 |
| 10 理由 | 首断点是模型行为，不是缺平台 | 必要工程边界已足够检验候选 | 两脚本门槛失败；扩大规模/第二模型不能补正旧失败 |

## 复现

在独立树检出方法提交 `2a7284bc`，使用其锁定 foundation 环境、既有服务和已忽略的私密 DSN（仅注入
`MILAI_LANGMEM_POSTGRES_DSN`，不打印）。按 execution-order.json 逐 job 创建全新 runtime/namespace；不复用本批目录。

```bash
PYTHONPATH=src python tools/run_persistent_memory.py prepare \
  --config data/diagnostics/next-development-v3-p2-formation-r1/config.json \
  --inputs data/diagnostics/next-development-v3-p2-formation-r1/field_plan-inputs.json \
  --run NEW_UNIQUE_RUN --arm B0 --runtime-root NEW_EMPTY_ROOT \
  --output NEW_EMPTY_ROOT/prepared.json
PYTHONPATH=src python tools/run_persistent_memory.py run-phase \
  --config data/diagnostics/next-development-v3-p2-formation-r1/config.json \
  --inputs data/diagnostics/next-development-v3-p2-formation-r1/field_plan-inputs.json \
  --run NEW_UNIQUE_RUN --arm B0 --runtime-root NEW_EMPTY_ROOT \
  --prepared NEW_EMPTY_ROOT/prepared.json --phase 0 --stage NEW_UNIQUE_STAGE
```

对其余17项按冻结输入/顺序更换参数；Root离线读取实际记录/HTTP/答案并使用原 rubric。不要把 rubric 传给 runner。
prepare不调用模型，run-phase产生新费用；自然 UUID 和响应可能不同，新尝试不覆盖本结果。
原始轨迹/DB/完整 freeze 留在 ignored `artifacts/next-development-v3/p2-formation-r1`；公开清单只保留精简身份、操作、评分和用量。
当前源码不必匹配全部旧阶段 lock，旧结果按各自提交复现。没有新的下载、部署、完整 benchmark 或参数扫描。
