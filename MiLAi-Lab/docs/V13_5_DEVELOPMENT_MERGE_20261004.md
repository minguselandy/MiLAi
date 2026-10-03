# v13.5 当前开发整理与 GitHub 合并交接

2026-10-04，用户明确要求“整理当前开发内容，提交合并到github上”。
**当前实现提交合并；完整功能验收仍未通过，Product 保持 NO_GO。**
最新独立完整通信轮次 `communication-r50-full` 已执行全部 11 案／27 条消息，
8 案 PASS_SCOPED、3 案 FAIL；26 条 COMPLETED、1 条预设 W1 UNKNOWN、0 条 NOT_RUN。
本次整理不新增模型实验或运行代码，未开始 r51 修复。

## 合并内容与提交身份

[PR #81](https://github.com/minguselandy/MiLAi/pull/81) 原以 v13.3 分支为 base，
依赖尚未合入 main 的 [#79](https://github.com/minguselandy/MiLAi/pull/79) 和
[#80](https://github.com/minguselandy/MiLAi/pull/80)。本次将 #81 转向 main，保留祖先提交，
合并 v13.2–v13.5 的当前 Lab 实现、配置、测试、协议及开发结果。
合并前 main 为 `95bf708bfd8aac9f7855485166e3bf739928b949`；
整理前开发头为 `d9e7c9e980f2817cb0bc63c34e79c5e6f3067da9`。
本报告所在提交、最终 CI 和实际 merge SHA 在 PR 的发布回执中核对，不预写合并成功。

相对 main 的既有修改集中于 `MiLAi-Lab/` 和两份根 CI workflow；
Product／Archive 内容未修改，Product Schema/API/权限/Canonical 未变。
新能力通过显式配置启用，旧默认与原有研究结论保持；v13.4 的 Simplify 退出不恢复 T1–T3。
数据库、请求正文、日志、连续账本及模型文件仍在本地 ignored，GitHub 仅提交代码、说明与精简哈希证据。

| 当前能力 | 实现入口 | 现有证据及限制 |
| --- | --- | --- |
| 统一真实 Agent 入口与持久化 | `tools/run_functional.py`、`runners/functional.py`、`memory/service.py` | LangGraph、SQLite Store/Saver、连续计账与进程重开；不等于完整任务可靠 |
| 分层、真实效果和异常阶段 | `application/functional.py`、`memory/service.py` | 公开来源交付接口；确定拒绝与进入提交后的未知效果分开；旧 CI 分层阻断已修复 |
| 保存说明与最终回答 | `runners/functional_response.py`、`application/functional.py` | 独立操作状态与可用回答合同；读取不算写入，回答失败保留已确认效果；自然语言仍会解释失真 |
| 片段、同 ID 维护及支持核对 | `memory/functional.py`、`memory/service_tools.py` | 程序提取原文、逐字段选源、局部修订、no_change、撤销；合法引用及模型核对都不是语义保证 |
| 历史与超限读取 | `memory/functional.py` | 明确当前／历史／指定版本／原文／片段／分页入口；超大首单元明确遗漏并推进；本轮实际覆盖专用历史入口 |
| 业务与恢复 | `application/functional.py`、`application/native_journal.py` | 实时查询、部分动作继续、unknown 不盲目重放；W1 恢复遗漏原保存请求尚待修复 |
| 遗忘与隔离 | `memory/functional_state.py`、入口重放检查 | 可见性撤销传播至材料和重放；本轮未重新暴露遗忘值，但最终回答错误推断“从未提供” |

## 最新完整通信结果

该轮重新独立准入，配置为 [r50](../configs/v13-5-functional-r50.json)，
冻结提交为 `d9e7c9e`，与 r50 候选 `e7822e9` 的 232 份运行源码和配置内容相同。
r50 只修正旧历史读取示例与实际工具目录不一致；模型、服务、上下文及调用额度没有增加。
它与此前 [r50 部分检查点](V13_5_CHECKPOINT_r50_20261004.md) 是不同封存轮次，成绩不拼接。

| 案例 | 消息数 | 本轮完整判断 |
| --- | ---: | --- |
| l4-n03 | 3 | PASS_SCOPED：保留单次／设想及其他活动限制；当前取消来源支持同 ID 修订；核对误拒仍保留 |
| communication-partial | 2 | PASS_SCOPED：一次预订、首次标签失败；后续实际查询后只补标签；原生部分状态已保存，未重复预订 |
| l4-g02 | 3 | FAIL：保存、当前来源单位更正及历史正确，但首条回答把厂商标签例外扩大为“不参考标签” |
| l4-h06 | 2 | PASS_SCOPED：实际确认已有记录，no_change／effect none；同 ID、revision 1，不虚构新写入 |
| l4-h03 | 3 | PASS_SCOPED：整条撤销后保留原文和历史，自动材料交付原文与撤销通知；最终原话摘录正确，无专用历史工具调用 |
| l4-g03 | 3 | PASS_SCOPED：实际调用 read_memory_history(record_id)，收到两个原版本及撤销状态，正确回答且没有重写记录 |
| communication-answer | 1 | PASS_SCOPED：有效普通回答，无业务或记忆写入 |
| communication-memory | 2 | PASS_SCOPED：限定语遗漏被拒后实际保存并正确回忆；另一次合法提案遭矛盾核对误拒 |
| communication-recovery | 2 | FAIL：预设 W1 中断后实际查询、无重复业务，但原“保存实际状态”请求遗漏，语义记录为零 |
| l4-n08 | 3 | FAIL：遗忘可见性与后续请求隔离通过，最终却将查不到误报为“之前没有提供过” |
| l4-f03 | 3 | PASS_SCOPED：当前取消来源支持局部修订，保留场景与其他摊位限制，随后只读回答正确 |

27 次消息尝试对应 27 个独立进程；预设 W1 UNKNOWN 是真实中断结果，不是 unknown usage。
9 条记录／44 处存储引文身份与来源区间匹配，current 等于 latest history；
这证明存储身份一致，不替代语义支持或最终回答审查。318 份原始文件已封存，不继续向该目录运行。
Root 为同模型家族的已曝光开发审查，不称独立 Judge 或新盲测。

## 尚未解决的三个直接问题

1. **恢复时丢失原保存任务。** `continuation_operations()` 只解析业务动作，保留当前消息的记忆权限关闭状态。
   W1 后实际业务查询和不重复执行正确，但原显式保存请求没有继续。后续应在现有服务／journal／入口中修复，
   同时保留纯查询、当前禁止写入、owner／可见性与 unknown 不重放边界。当前只有定位结果，没有 r51 实现或通过证据。
2. **最终回答扩大例外。** 原单位规则排除厂商标签不等于不参考标签；存储正确不能掩盖首条回答错误。
3. **不可见不等于从未提供。** 遗忘后没有材料不能证明历史不存在；本轮隔离通过与回答失败分别记录。

还保留支持核对过严／前后矛盾、误解部分成功、意图分类错误和遗忘确认冗余文案。
g02 的错误 draft 动作声明在实际预订工具目录中没有生成业务写工具，也没有业务效果；
f03 虽同时声明遗忘权限，实际只执行正确修订。实际未误执行不代表声明语义已可靠。

## 检查与 CI

| 证据 | 身份与结论 |
| --- | --- |
| r49 运行源码回归 | 586 项 PASS，保留原执行身份；本次文档整理未重跑或重标 |
| r50 实际 schema 与生产 tokenizer 探针 | 旧示例失败／新示例合法；32 项完整提示探针 PASS，脚本响应、实际 SQLite、0 实验 HTTP |
| r50 候选 CI | `e7822e9` 的 [Fast37156424019](https://github.com/minguselandy/MiLAi/actions/runs/37156424019) SUCCESS；Full37156424020 SKIPPED |
| 完整轮次准入提交 CI | `d9e7c9e` 的 [Fast37158744744](https://github.com/minguselandy/MiLAi/actions/runs/37158744744) SUCCESS；Full37158744736 SKIPPED |
| 本次发布检查 | 封存、来源／配置哈希、账本差量、历史行不变、文档链接、边界及验证矩阵；详见机器清单 |
| 本次提交与 main | 推送后核对新提交的 CI；合并后核对 main 与受检 PR 的树身份，结果登记于 PR |

Full skipped 不计为通过，旧提交 CI 不继承为新提交通过。
本轮 g03 为历史新入口提供直接模型证据；r48 的失败与 r49 的原话引用失败保留原成绩，
不因新轮次某案例通过而改写旧记录。指定版本、片段和分页的完整模型集成仍有验收缺口。

## 计账与后续范围

| 范围 | 生成次数 | 已知生成 tokens |
| --- | ---: | ---: |
| communication-r50-full | 110 | 581,707 |
| 先前 r50 部分轮次（另计） | 51 | 291,718 |
| v13.5 全部累计 | 4,683 | 25,334,410 |
| 恢复开发后累计 | 4,527 | 24,560,174 |
| 原连续账本 | 14,409 | 53,026,696 |

连续计费生成 tokens 为 53,057,083，历史 unknown usage 1、差额 30,387 保持；
embedding 累计 964,645，本完整轮次新增 embedding／unknown usage 为 0。
本次整理新增实验调用 0，不含编程 Agent 用量。

仍需修复恢复任务缺口并做直接回归，随后以一个冻结版本完成 L1 原 24／48、
L2 两工作流 12／26、L3 形成 57／读取 30、方法稳定后的新 L4，以及 FUNC-01–16／140 项终态。
历史 r40 L1 原 rubric 23／24、新合同 19／24，L2 7／12；r37 L3 形成 44／57、读取 24／30，
都保留自己的版本，不能拼为当前通过。原 48 项与历史 140 项详细行不作验收升级。
当前没有稳定推荐配置；合并交接完成也不代表完整开发目标完成。

后续入口：[FUNC 工作表](V13_5_PROGRESS.md)、[使用说明](V13_5_FUNCTIONAL_USAGE.md)、
[轮次登记](../data/manifests/v13-5-runs.json)、[本次机器清单](../data/manifests/v13-5-development-merge-20261004.json)。
回退开发整理可比较 `d9e7c9e`；撤销整体集成应针对实际 merge commit 作正常 revert，保留原提交与证据。
