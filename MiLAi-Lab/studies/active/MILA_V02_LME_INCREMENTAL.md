# MILA-V02-02 执行与终态记录

状态：**COMPLETED_KEEP_BASELINE / 2026-09-05**。
[Product Goal](../../../MiLAi-Product/docs/goals/MILA_V02_02_LME复杂任务驱动的增量开发_GOAL_20260905.md)
与[预定计划](MILA_V02_LME_INCREMENTAL_PLAN.md)的条件出口已执行：
L0修复后通过；L1没有确证值得进入B1的通用问答缺陷，L2/L3不进入。
独立保留Lab的公开连接复用导入优化。L4完成2次真实更新、4组U/V和8次后续任务；
两侧均正确，但两条历史计入生成后都未回本。继续完整A0，不启用自动维护。

[全部分配、逐例input/output/cache/工具数与评价](MILA_V02_LME_INCREMENTAL_RESULTS.json)是紧凑总账。
14/40次分配均有终态：L0–L2占4/16，L3占0/12，L4占10/12。
实际启动13次模型会话，其中1次来源元数据无效；另1次分配在模型前取消。
问答D/V有效比较为0，L4有4组有效条件配对，不混用分母。

## 起点、身份与数据暴露

- 专用锁：`data/locks/v02-lme-incremental-product.lock.json`，Product tree
  `7fdf4f12d8c9ef63a9662145f6a1abb2e053fce2860e60ddcde8eeabcaf1fc0c`。
  源码校验、Runtime/MCP/hooks安装解析路径及最终pin通过；Product代码未改。
  公网仍为既有R1身份，旧研究的已停服务、数据与记录未复用或清理。
- 本轮run：`artifacts/v02-lme-incremental/l0l1-20260905a`，隔离env/blob/PG、随机loopback端口，
  当前迁移head；D1启用、D2 SHADOW。DEIDENTIFIED_ALLOWED且来源权限固定，不做动态撤销。
- 配置：`configs/v02-lme-incremental.json`，gpt-6-astra/high/default、完整A0、300秒/会话、
  24工具动作、每批4次/1200秒**累计在线**预算，capture/readiness另限300秒。
  120k仅软提醒。最终配置sha256：
  `9d47110e09e7f8265ea9da1a53e28befad86c42bace029caedce91a47466e0a4`。
  最终采用PUBLIC_HOOK_PERSISTENT_CLIENT；旧配置和旧批次身份原样保留。
- [D/V选择](MILA_V02_LME_INCREMENTAL_SELECTION.json)先于正文导出固定，每组6例：
  计数、组合、时间、更新、用户查找、助手查找。V未用于本轮策略设计或评分；
  这些案例历史上均已开放，不能称盲留出。
- 没有找到完整原生source-only包。独立导出器对底层277383467字节做hash和结构扫描，
  仅JSON解码白名单12例，488例未解码；不能声称没有访问底层Formal源文件。
  没有Formal500正式评分，也未把构造的Product-11片段替代原生历史。
- 首版`data-20260905a/`**不可再在线使用**：原始session ID含`answer_`前缀。
  修复包`data-20260905b/`把所有会话ID换成中性的`session-{ordinal}`；
  正文、角色、日期、顺序、重复实例和干扰全部不变，未重新打开corpus。
  每例396–550条turn；参考答案、answer-session和turn标签不进入在线包。
  修复manifest保留旧hash与转换来源，严格适配器拒绝非中性ID。
- 实际Host只挂载自己的home/workspace和只读sources；不挂载Lab、标签、未来问题或完整corpus。
  完整公开catalog为13工具，真实初始assembly、ABSENT起点和外显行为均导出。
  非模型容器复现及实际L4容器验证隔离；后续逐请求模型输入仍为UNOBSERVED。

## 最小改动与不变量

`tools/run_v02_lme_incremental.py`、`v02_lme_sources.py`、`v02_lme_host.py`薄接原完整Host：
完整历史映射、公开捕获、分阶段耗时、真实State/usage和预算。
`export_v02_lme_sources.py`完成白名单投影及去除会话身份中的答案标记。
`v02_lme_capture.py`与`v02_lme_capture_worker.py`复用公开hook函数和一个SDK client；
`benchmark_v02_lme_capture.py`、`probe_v02_lme_capture_contract.py`做非模型对照与拒绝验证。
`run_v02_lme_reuse.py`实现真实生成、独立U/V、公开引用映射和任务文件延续；
`summarize_v02_lme_incremental.py`汇总全部分配与保守净成本。

旧`run_v02_memory_flow.py`只增加显式config/实例设置参数，原默认保留；
`v02_codex_container.py`只增加阶段时间。前轮原文件已保存在
`artifacts/v02-lme-incremental/baseline-code/`，与原冻结hash逐一吻合。
不修改Product权限、Canonical、CAS、schema、公开API、Host问答提示或D2接入行为；
不新增批量写API，不绕开投影READY，不把同样A0命名为B1。

## 失败与修复全部保留

| 记录 | 事实 | 处理 |
|---|---|---|
| capture-legacy-1 | 默认SYNTHETIC_ONLY拒绝DEIDENTIFIED，403、0回执 | 核对身份后仅重启自己的API/worker，校正实例模式；旧记录保留 |
| l0-count-smoke | 模型完成后发现文件会话ID携带答案标记 | INVALID_SOURCE_METADATA，不计效果；用量照计 |
| l0-lookup-smoke | 同一缺陷影响第二次分配 | capture期间停止；228回执、80.316秒准备，未启动模型；仍占smoke额度 |
| l0-count-repair / l0-lookup-repair | 去除全部原始会话ID，新增拒绝测试 | 新批次使用两个预留DIAGNOSTIC额度；未追加smoke或给效果臂补分 |
| l1-count-testkit / -r1 | 公开testkit两次拒绝TRACING_BEHAVIOR_CHANGED | 首次与导入重叠；第二次无导入仍response_equal=false。候选池保持不可观测，不绕过中立性检查 |
| metadata-verification | SDK元数据接口有意移除content字段，脚本KeyError | 改用公开content_hash逐条核对，旧失败保留；捕获实现不改 |
| L4分支准备 | 第二个真实State含生成workspace的绝对文件路径 | 在任何U/V分配前，一般性映射两侧文件路径及引用；不改内容、未来问题或已冻结生成记录 |

以上基础设施修复不是任务效果。实际非模型子进程分别被时间和24动作watchdog终止，
失败计额度、累计在线余量、来源投影及分支映射有定向测试。
旧试验数字不代替本轮验收。

## L0–L1：返回证据与任务判断分开

| 修复后诊断 | 回答与离线评价 | input / output / cached input | 在线秒 | State |
|---|---|---:|---:|---|
| 0a995998 | 2件：西装、Zara换码靴子；参考3，标签分歧，不计二值胜负 | 194121 / 939 / 142336 | 90.435 | ABSENT→ABSENT，未尝试 |
| 8550ddae | lavender gin fizz；来源、参考及蜂蜜替代细节一致 | 30788 / 163 / 20864 | 31.703 | ABSENT→ABSENT，未尝试 |

评价者是本线程Root Codex，不是人类gold或独立Judge。
无效smoke另有157188 input、1096 output、126592 cached input及94.408秒，未从总成本排除。

来源→返回→外显判断链记录于run/probes/l1-count-public-query/coverage-review.json：
原生问题首轮返回10个Evidence，包含30:4的靴子和11:0的西装关键文字；
同查询正确predecessor翻页再返回10个Evidence，但不增加必要衣物项。
事前固定、未读答案生成的普通改写返回9个Evidence，反而不含西装。
公开Runtime映射仅用中性ordinal，并未传入文件中的旧答案会话ID。

完整Host还查阅了合法文件。19:6和30:4均描述2月5日购买、换大一码、尚待领取的靴子；
19:2另有借给姐姐的毛衣，但不符合题面store条件。逐只靴子与一双的item口径也未明确。
参考3原样保留，不宣布新的权威gold，也不据此断言模型错误或缺失第三件。
candidate pool因testkit拒绝保持UNOBSERVED；返回关键文字不等于证明后续实际模型输入。

现有证据不足以定位值得进入B1的一般性行为缺陷，因此L2六对、L3六对均不运行。
这不是声称所有D例正确，也不是用两个诊断替代六对比较。
旧LME D1/D2缺口仅作发现线索；没有恢复A1/H1提示、扩大top-k、使用答案词或案例路由。

## 独立工程收益：导入提速

三组同样完整484事件，顺序legacy/persistent、persistent/legacy、legacy/persistent。
每臂均新分支、新进程/client，串行1worker、零重试、固定DEIDENTIFIED和journal OFF，
复用已热API/PG；不称冷数据库或生产SLO性能。

| 组 | legacy capture / projection尾等秒 | persistent capture / projection尾等秒 | 总耗时比 | 返回核对 |
|---|---:|---:|---:|---|
| 1 | 162.291 / 0.014 | 3.205 / 1.156 | 0.02687 | 10个Evidence文字与归一化turn refs完全一致 |
| 2 | 170.480 / 0.453 | 3.242 / 1.432 | 0.02734 | 同上 |
| 3 | 164.296 / 0.943 | 3.253 / 2.045 | 0.03206 | 同上 |

总耗时从162.305/170.932/165.239秒降至4.361/4.674/5.297秒，中位比0.02734，
约97.3%导入时间减少。比较对象是**本轮串行CLI**，不是前轮8worker的21.92秒探针。
公开元数据逐条验证全部2904条的正文hash、日期、权限、session/turn身份；
3组READY和公开返回均一致。真实幂等重放保持Evidence/outbox/operation ID，
reader token写403，非OFF journal在写前拒绝。

仅支持该Lab导入路径，不称问答/推理净收益。证据在run/probes/capture-paired及capture-contract。
新配置选PUBLIC_HOOK_PERSISTENT_CLIENT；旧配置存run/config-before-persistent-capture.json。
回退是在**新配置/批次**选LEGACY_CLI_PER_EVENT，不回退数据库或改旧回执。

## L4：真实保存成功，净价值未成立

[两条历史、当前任务和各两个不同后续任务](MILA_V02_LME_INCREMENTAL_R.json)在生成前固定。
生成器只看到当前任务、完整合法历史和普通A0工具，未来问题/条件未挂载。
没有新增未来事实或时间外来源；这是LME_DERIVED_CONTINUATION / CONDITIONAL_UPDATE，
不是自然维护触发、原生LME得分或生产泛化。

两条都经公开提交及GET确认ABSENT/0→ACTIVE/1，来源审阅通过。
G1保存200000列价、20000估计、五英亩、deck/patio与未指定年份的春季；
G2保留35万/40万的日期、32.5万价格及来源角色，未将回忆当实时贷款确认。
两条都有真实handoff文件，U/V共同携带，只映射分支Evidence ID、source URI和绝对文件路径。
U从真实保存前ABSENT/0开始；V公开初始化为实际保存内容的ACTIVE/1。
第二种任务独立从同一生成起点分叉，不接收第一种任务的新文件或State。

| 历史 / 后续 | U input+output | V input+output | U在线秒 | V在线秒 | 质量 |
|---|---:|---:|---:|---:|---|
| 27016adc / combined_budget | 120016 | 81682 | 73.013 | 57.933 | 两侧正确；约22万及总成本限制 |
| 27016adc / contractor_brief | 84036 | 119384 | 64.951 | 64.782 | 两侧正确；scope、春季日期不确定、乡村地块另列 |
| 852ce960 / approval_timeline | 124874 | 64616 | 83.627 | 48.703 | 两侧正确；日期、5万差值、未推定实际贷款变更 |
| 852ce960 / purchase_note | 143549 | 93977 | 73.708 | 60.005 | 两侧正确；7.5万差值、实际本金/当前确认未知 |

四组均核对相同问题、Host配置、300秒预算、完整来源、生成文件及映射后的真实V快照。
8次后续均成功、未再保存；无新增重要无据断言。评价者仍为Root Codex。
真实任务文件帮助U完成全部任务；三个重访V token更少，一个更多，最大V/U token比1.421。

| 历史 | 生成token / 在线秒 | 两次U−两次V token / 秒 | 再扣生成后的净token / 秒 | 判断 |
|---|---:|---:|---:|---|
| 27016adc | 292219 / 214.773 | 2986 / 15.248 | **−289233 / −199.525** | 未回本 |
| 852ce960 | 485393 / 258.520 | 109830 / 48.627 | **−375563 / −209.893** | 未回本 |

生成/提交无法可靠从当前工作分离，保守计整次生成会话。G1为288298 input+3921 output
（251520 cached input）；G2为479751+5642（424320 cached input）。
Host启动、初次assembly和State读写在在线成本内，capture/readiness另列，cache不重复相加。
第一个生成期间短暂重叠失败的元数据读取探针（首读即KeyError，无批量读取），保留该计时限制。
小样本、顺序/缓存及共享任务文件不支持精确延迟因果归因或表示优势；两条均不满足回本门槛。

## 总账、验收、范围与退出

已知Host用量1975875 input +18166 output = **1994041 token**；
其中1625472 cached input属于input子集。包括无效smoke和两个生成会话。
只有模型前取消分配usage未产生/未知，未伪填0。跨批累计在线1216.561秒。

| 批次 | 分配 | 累计在线秒 | 终态 |
|---|---:|---:|---|
| l0-smoke-b1 | 2 | 94.408 | 1来源无效完成；1模型前取消 |
| l0-repair-b2 | 2 | 122.138 | 普通正确；计数标签争议 |
| l4-generators | 2 | 473.293 | 2有来源真实更新 |
| l4-followups-27016adc | 4 | 260.679 | 全部正确；未回本 |
| l4-followups-852ce960 | 4 | 266.043 | 全部正确；未回本 |

单批最多4分配、最高473.293秒，最多14工具动作；所有实际会话低于300秒。
120k仍仅软提醒，最高单会话485393 input+output，没有伪称硬限。

最终检查（最后的分支绝对文件路径映射编辑后已重跑）：
`uv run milai-lab-check-boundary`、`uv run ruff check src tests tools`、
`uv run mypy src/milai_lab`（30源码文件）、`uv run pytest -q`（133通过，1.61秒）、
`uv build`全部通过。
真实PG公开接口完成完整捕获/投影/检索、2904条元数据核对、幂等/拒绝、
真实State保存/初始化/恢复。Product代码未改，未重跑Product全包测试；
未用历史160项代替本轮验收，未声称动态撤销、并发或schema语义已验证。

最终代码/config/install身份在run/final-code-identity.json，检查在run/gates.json，
逐批和旧配置身份原样保留。仅停止核对过的本轮API PID1778603、worker PID1778604及
Compose项目`l0l1-20260905a-pg`。数据库卷、容器、blob、source包、失败记录、运行home和
外显日志全部保留；临时auth副本已清除。run/cleanup.json为
STOPPED_OWN_SERVICES_DATA_RETAINED。旧研究、公网及用户原有数据未改变。

适用范围是该锁定公开hooks/SDK、固定去标识来源、journal OFF、单worker、已热API/PG的
Lab导入路径。完整A0无需回退；导入选项可在新批次回到legacy。
后续若继续，先澄清计数评价口径和公开testkit中立性拒绝，再由真实任务失败决定行为候选。
本轮负收益不支持启动自动维护。

A0默认；D2 SHADOW；Product-11封存不变；公网不变；
Schema仍为 **0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE**。
