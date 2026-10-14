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
