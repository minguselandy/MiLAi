# V0218 T4 扩展进度：第二建设批及分母

状态：建设继续，G-TESTBED 未通过；E0–E5 未完成，没有候选机制或创新性结论。
本报告追加到 [T3 初步审计](MILA_V0218_T3_PRELIMINARY_20260910.md)，不重写前一批结果。

## 第二建设批

`evidence/v0218/20260910/t4-note-chain-v1` 的 manifest 阶段为
`T4_CHAIN_AND_WORLD_EXPANSION_NOT_E0`。复用已验证的共同 Host/Provider/Note 实现，
按冻结来源顺序扩到 research_assistant/task3、investment_analyst/task1，未替换原两题。
2A+8B 全执行，56 requests / 93,307 raw，pending=0、violation=0。
历史 runner 的终态字符串仍带 T3，阶段以封存 manifest 为准，不将其误计成又一个初始 T3。
本批前的 154/290,773 与本批分别计费，累计 **210 requests / 384,080 raw**。
无 Judge/embedding/OCR；隔离 API/PG 已停止，卷保留，未改共享服务。

| 来源 / 家族 | A 业务 / 自写 Note | Stable N0 / N1 | Superseded N0 / N1 |
| --- | --- | --- | --- |
| research_assistant/task3 / release_control | PASS / NO_WRITE | FAIL / PASS | PASS / PASS |
| investment_analyst/task1 / financial_basis | FAIL / 1 次提交 | FAIL / FAIL | FAIL / FAIL |

发布授权 A 正确记录已知 v2.1/v3.0 不匹配时不授权发布。Stable N0 未读 policy，
将已知不匹配当成需要澄清的缺失事实；N1 则读 policy 后保持不授权状态。
此 A 为 NO_WRITE，N0/N1 都没有旧 Note，不能将分支差异解释为 Note 收益。
两个 Superseded B 都按已验证 v3.0 与提前的截止日期更新，完整通过。

金融 A 的数字比较 −1.68B 正确且真正落盘，但缺少其余四条必需指标输出。
其 Note 保存了正确的源指标和旧比较关系，同时有把 current 输入记录误认为 records 已完成输出的
错误判断。两个 Stable B 都保留缺失输出；Superseded N0 改正 gap 至 +0.5B，但仍缺四行，
N1 保留错误的旧 gap/方向且同样缺四行。不能只看一个字段修对就判完整任务成功。

## 实际持久链与语义区分

本批 `chain-audit-v1.json`：A=2、自写 Note A=1、NO_WRITE=1；B=8、公开精确冷读=2、
旧 Note 实际发送=2、当前证据实际发送=8、同一请求双呈现=2、涉及独立 lineage=1。
与 v3 合并（不包含协议失败 v2）为 A=4、自写 A=2、NO_WRITE=2；B=16、旧 Note 冷读/发送=4、
当前证据发送=16、双呈现=4，涉及日程和金融两个不同原始来源。
这满足“至少两个来源的链路被实际激发”的传输数量条件，**不代表两条 Note 的所有判断都正确**。

本开发代理作非盲逐项语义复核（非独立人工评审）：金融 Note 中 89B、90.68B、−1.68B/below
在 A 当时是正确的来源/派生事实；“四个指标已经构成完成输出”不成立，A 结果仍 FAIL。
后续可以单独分析明确旧正确比较前提的修正，不能把整条混合 Note 标为全正确，
不能将尚未存在的业务成果算作旧有效成果。单批审计文件里的 G 缺口只针对该批，
全局门还必须检查全部覆盖、语义/泄漏反例和校准，不能仅相加两个链路数签 G。

## 同请求的非确定性观测

发布授权 Stable 两个无 Note 分支的第 2 次请求 SHA-256 相同：
`c7d49d207346318844406af99427541f6fd158e8ed0a4827ee9da57d40bc718c`。
一个返回 read/records，另一个返回 read/policy；输出 hash 分别为
`b6bdbcdfa9cb6de23171aa8ab6d06293e5c8c0b913fa6b80fc8a8887b7c3ab08`、
`4781c832ac9d316f334d0d44d7f9b2612916a5851d25a5085c8ad97d9ebe61ea`。
同 seed/temperature 配置下，实际服务输出未做到逐字确定；原因未作服务侧干预诊断。
未来配对效应仍需冷重复与不确定性报告，单次差异不自动证明稳定因果收益/损害。

## 建设边界与下一步

四个已校准来源 / 四个 family，未达到 12-source 目标。第三、第四的源/合同/删减说明
见 [执行合同](MILA_V0218_TESTBED_CONTRACT_20260910.md)。8 个受控 checker 实现变异被
独立正负 fixtures 识别，另有对象重命名不变性测试；仍不是穷尽正确性证明。

第五个固定来源 journalist/task5 已审完整 task.py，原始 inspection SQLite 的 15 行以
read-only/immutable 方式读取并验证原文件 SHA-256 未变。`expansion-fifth-v1` 仅准备了
profile/初始世界：保留原生历史行和 2026-03-18 复查新增行，区分最新状态与仍真实的历史不合格。
结构化资源/本地导出替代 SQL 操作与全文报道；视频、音频、截图、邮件验证均不声称已复现。
该第五来源 checker/完整校准尚未实现，不列为第五个 ready 来源，更没有模型结果。
其余既定来源仅沿原计划继续，不按 NO_WRITE 或当前效应挑选。

G 尚未通过；Helpful/完整适用范围与未决场景的模型覆盖、剩余来源、T5 和完整 E0–E5 均待完成。
WMA 全量数据仍下载中，见 [下载账本](MILA_V0218_BENCHMARK_ACQUISITION_20260910.md)。

## 后续零模型校准：第五来源与 Helpful

上述“第五来源尚未 ready”是第二模型批结束时的状态。后续已补齐逐行导出 checker，
22 项来源专项测试及 `t4-fifth-replay-v1` 的四个真实 SQLite 分支重放通过；
当前为 **5/12 已校准来源、4 个实际模型运行来源**，不是新增模型成绩。

在第五来源尚无模型/Note 输出时，另封存 `expansion-fifth-v2`，合同 SHA-256
`f5df7fd1bf766cb758bf7b4ee4028b5e11d4f1b29384bf98a86f3553fd6b7b3d`。
新增 Helpful 是 Stable 的显示视图变体：当前页只显示每店最新检查，旧历史事实和版本不变，
完整原记录经公开 history 及内容 hash 可定位；N0/N1 的普通历史、既有业务导出均保留。
checker 从真实历史源复算完整导出，不把 Agent 自称完成或只见最新合格作为真值。
此设计未参考该来源的 Agent Note，也不保证 Note 优于历史查询。

`t4-fifth-replay-v2` 五分支前后状态符合预期，8 项新增 Helpful 校准与原 22 项专项、
9 项变异测试合计 39 通过。首次新增测试把 history[0] 误当源记录，实际首项是合法动作回执，
导致 3 个 KeyError；已将测试改为按 prior_public_record 类型定位，未改源事实或 checker 判据。
v1 源合同/重放结果保留。Helpful 目前只覆盖一个来源且尚无模型实验，跨来源覆盖仍待补齐。
本节模型新增 0，总量仍 210 requests / 384,080 raw。

## 第六来源：新闻来源权威与真实冲突

固定顺序 journalist/task1 的原 task.py 已完整读取，另作来源核验；
新合同 `expansion-sixth-v1` SHA-256 为
`812d1c4ae9857f5f064a804063fe80488eeec1c646484aabeb6f48ae3d6e5e06`。
29 项专项测试和 `t4-sixth-replay-v1` 五分支真实 SQLite 重放通过，模型新增 0。
当前累计 **6/12 世界校准来源、4 个模型尝试来源、2 个 Helpful 世界来源**。
后两个仍同属 journalism 上层聚类，不把细粒度 checker 域当完全独立职业样本。

该适配保留不同事实角色、指定来源权威、同一权威版本更新、同版本真实冲突及错误对象/
非权威新消息的适用性边界。Helpful 只改变来源入口，正常历史和已完成 register 仍可用。
原 PDF 用临时隔离的 pypdf 6.0.0 只读探查，未提取到文本；没有 OCR/转写/Judge 或视觉兜底。
因此 14:28/14:35/2 仅定位于原 task 的声明判据，不声称已独立核验 PDF/音频；
此适配将它们作为显式公开环境事实，新增初始留观状态、来源 ID/版本与控制事件均明确标注。
输出是内部结构化核验登记，不是原生文章、视频、匿名举报保护或邮件执行成绩。
模型运行时没有读取原生 gold/checker 或私有答案 fallback。

全量回归现为 966 passed / 1 optional SDK skip。后续仍需剩余六个来源及完整 T5/E0–E5。

## 第七、第八来源：符号分解与有边界的内部案件准备

按固定顺序增加两个来源，均在首次模型输出前冻结并做真实 SQLite 重放：

| 原始来源 | 合同 / 重放 | 专项校准 | 边界 |
| --- | --- | --- | --- |
| investment_analyst/task3 | expansion-seventh-v1 / t4-seventh-replay-v1 | 29 测试、四分支 | 区间端点、中点变化与 FX/经营分量符号守恒；缺 FX 不应丢掉已知净变化 |
| legal_assistant/task6 | expansion-eighth-v1 / t4-eighth-replay-v1 | 34 测试、四分支 | 收据/估算分别保留、内部暂算与最终金额区分、申请/时效截止期区分、不得自授和解权限 |

第七合同 SHA-256 `0e086ea68a60371f24fd685c9b70b9fa8a9aba77756054a194955bf5c1bab799`；
第八 `a306fd2adb22c1066493ea31d717d259d1ddbfa68082870902a5159f7d18432e`。
第七的两份原始公开 release PDF 已只读提取并固定 hash：旧区间 10555–10575M，
新区间 10560–10575M，中点差为 +2.5M，不把原 checker 近似 3M 当作精确真值。
FX −17M 仍是明确声明的本地世界假设（没有独立解析 bridge 图片），由此导出经营残差 +19.5M。
B 的新指导/FX 是适配事件，不是公司真实历史或投资建议。

第八使用原 task 的公开 sheet 种子 86000 收据、32000/18000 估算及原生截止期变更。
暂算 136000 与收据支持 86000 分列，伤残尚未评定、最终金额保持 null；这只是虚构内部流程，
不推断医疗过错、法定赔偿或司法期限，不实施申请、邮件、客户沟通或和解。
原始无时区日历明确解释为 +08:00；伤残未评定条件前置到 A 属于已披露时间线适配。

当前 **8/12 世界校准来源、4 个真实模型尝试来源、2 个 Helpful 世界来源**；
两个投资来源按 financial analysis 上层聚类，两个新闻来源按 journalism 上层聚类另报。
本节新增模型 0，累计仍 210 requests / 384,080 raw。G/T5/E0–E5 尚未完成。
第九 pm/task3 的完整 task.py、原始会议纪要和访谈已读；尚未构建世界或运行模型，不能计 ready。
其原会议 Phase 1 含两个新功能，Learning Report 已处 v2.4；后续需明确 summary 的既有功能
归类，不能不解释就套用原 checker 的 Phase1=4。这不是对完整 native rubric 的改判。

截至这次增量，全量回归 **1029 passed / 1 optional SDK skip**；boundary、Ruff、mypy 通过。
原失败协议、旧模型结果和各版已执行 checker 快照均未覆盖；新增判据不会回改旧实验得分。
构建与 git diff --check 也通过；t3-note-chain-v3、t4-note-chain-v1 的实际请求链审计
再次按各自封存 checker 执行，结果与原审计文件完全相同，没有新模型调用。

WMA 下载后续已完成：16,059 文件 / 9,959,668,254 字节全部匹配上游 Git/LFS 哈希，
零不匹配；三份代码仓库同样完整核验。上文“下载中”保留为当时阶段描述，
最终状态以 [下载账本](MILA_V0218_BENCHMARK_ACQUISITION_20260910.md) 为准。

## 第九至十二来源：完整来源覆盖，进入统一 T5

2026-09-11 继续固定顺序，四个原始 task.py 全文与必要公开资产已读，
适配合同先于模型结果冻结，四根均无模型请求。

| 来源 / 合同 pack | 完整判据及独立字面预期 | 专项测试 / 脚本分支 |
| --- | --- | --- |
| pm/task3 / expansion-ninth-v1 | feature_spec/backlog/timeline 三副本与 summary 同步；v2.4 既有、v2.5 phase1、v2.6 phase2 明确分列 | 30 / 4 |
| research_assistant/task6 / expansion-tenth-v1 | 74.8/74.3/75.1 的 mean 74.73、sample SD 0.40；selected 74.8 与 best 75.1 分列；全部四项 tuned 差值不可挑报 | 26 / 4 |
| real_estate/task4 / expansion-eleventh-v1 | 预批/正式批复、−50k/+150k 签名缺口、实际收件字段权限；额外 fully-cleared 正向 ready 控制防永远 hold | 28 / 5 |
| hr/task1 / expansion-twelfth-v1 | 原 XLSX 三项得分；五人完整排名/原因/冲突标记，HC 4→3；ATS/summary 一致 | 27 / 4 |

合同 SHA-256 依次为：

- `d5175a7d39fec7f3d794ac84cdf103d4408d0d9f111c724745f7640b4fe02065`
- `8d22e89466ad6da2648b0f235be570c4c2e94642046b8730988f07d20535f6c9`
- `32799c55a7fa4096ab9a050dba51b3b7d0e19c792f9a52f8e1bd9d79b3819ec9`
- `53410a608e9187cb230d1aeb29bf6dcae777a9f3ca1b7d21a365737075e0294b`

新增证据位于 `evidence/v0218/20260911`，原八根位于 20260910，未覆盖旧模型/校准证据。
原 pm summary 模糊口径已显式拆开，不暗套 Phase1=4；科研邮件的“74.8 最佳”与 raw 日志
矛盾，公开世界区分 selected/best，不声称模型在真实训练中得到这些分数。
房产 4.6M 内部底价前置 A、HR 初始 HC4 与加分/阈值是明确新增适配规则。
HR 原 scorecard 可核，出勤/私下支持信号只作显式结构化适配，未作音视频推断；
不实施真实招聘、签约、资金、邮件、申请或产品部署。

四根补齐后全量回归 **1140 passed / 1 optional SDK skip**。
随后新增 25 项跨根测试（逐根 reset/clone/CAS/隔离/不合法输出、每域关闭判据的错误实现），均通过。
`t5-validation-v1` 现版 checker 全池 49 分支重放通过：Stable/Superseded/Unresolved 各 12、
Irrelevant 10、Helpful 2、Resolved 1；12 个原 lineage、9 个职业上层聚类，全部 EXPOSED_D，C=0。
不把 49 分支当 49 个样本、不把 Helpful 两根 journalism 当跨职业代表性。

当前 **12/12 世界校准来源，4 个模型尝试来源，2 条实际自主 Note 双呈现 lineage**。
模型总账仍 210 requests / 384080 raw，全部 settled；新增 Judge/生成均 0。
T3-v3/T4-v1 审计再按各自封存 checker 完全复算一致，财务 Note 的正确旧比较与错误完成
推断分列；原协议失败、NO_WRITE 及非确定性请求对照全部保留。
T5 复核与签出条件见 [验收复核](MILA_V0218_T5_REVIEW_20260911.md)，
正式 G 状态只取实际 gates 后的 testbed-manifest；E0–E5 尚需执行，Goal 不收口。
