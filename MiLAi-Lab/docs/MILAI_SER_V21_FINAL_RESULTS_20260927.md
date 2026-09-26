# v21 最终开发结果：进入 P7

P6 R2 的三个来源权威控制与随后十个确认控制在同一源码上全部通过：13/13，覆盖原十二种非温度类型和一个明确来源优先级反例。该结果只支持继续已暴露原任务回归；尚无 unseen 效果或整体成本下降结论，长程 Goal 保持 ACTIVE。

## 修复及身份

[P5 R1](MILAI_SER_V21_P5_R1_RESULTS_20260927.md)的四次失败均保留：当前数值正确，但模型缩写业务目标。随后只在 fixture 的 item 参数说明中要求复制完整引用，[P5 R2](MILAI_SER_V21_P5_R2_RESULTS_20260927.md)四次严格动作通过，没有运行时目标归一化或答案注入。

[P6 R1](MILAI_SER_V21_P6_R1_RESULTS_20260927.md)的 current_conflict 仍记 FAIL。两个 CURRENT 正文完整送达，模型却将后写入约0.225秒的 Store.created_at 解释成跨来源优先级，并在冲突未消除时执行 West。第一断点是来源权威推理，非版本获取或正文投影。竞争解释包括存储时间误读、先前推荐造成的审批锚定、排名与写入顺序混淆；完整 Failure Review 留在原报告。

本轮唯一运行时修改是在既有 SOURCE_AUTHORITY 后追加：存储时间和检索排名不建立冲突来源间的权威关系；没有适用优先级时，先澄清再行动。它是明确的模型可见协议干预，不能归为纯 SER 算法因果收益。无新增模型、真值 gate、自动业务阻断、语义 State、case 分支或 vLLM 调参。

- 最终 mapping：`7ee904cba80c0facf0f513fe7607b15ea4fa5a61fc1a0553c1ef4e85144411e9`，64个运行源文件。
- [P6R2 lock](../data/locks/milai-ser-v21-p6r2.lock.json) SHA：`e80faf16a649308add7200a965fb29ab9d38fbf34cc6f5f789b37619208e9405`。
- recipe `milai-ser-v21-json-action-v1`；transport `json_action_ser_v21_v1`；arm `a5_rank_bounded_rebase`。
- source checkpoint 前身为 `c82a89de44031e85f3987204a60fec857be59b29`；该检查点保留全部 P5/P6 R1 失败，最终修复由后继 Luna 检查点发布。
- A5 保持每 search 最多一次新的 exact read，遇到更高排名当前候选便停止读取后续 stale，后续 stale 仍隔离。CURRENT 不等于任务充分或来源权威。
- schema 形状、工具参数结构、排序、lineage、Store、checkpoint、Product 和 vLLM 设置均未改。

## P6 R2：3/3

[计划](MILAI_SER_V21_P6_R2_PLAN.md)、[协议](../data/manifests/milai-ser-v21-p6r2-protocol.json)、[运行前冻结](../data/manifests/milai-ser-v21-p6r2-freeze.json)、[结果](../data/manifests/milai-ser-v21-p6r2-results.json)分别保存。

| 控制 | 实际结果 | 解释 |
| --- | --- | --- |
| current_conflict | 0业务动作，持续请求澄清优先级 | 不再从存储时间自行选来源 |
| no_stale | 完整目标，Central；0 exact get / 0 demotion / 0追加search | 无冲突时正常行动 |
| explicit_source_priority | 完整目标，East；两条 CURRENT 均送达 | 明示 Alpha 优先仍能行动 |

明确优先级反例中，Beta 不仅后写，而且排名第一（score 0.6332931518554688）；Alpha 排名第二（0.6299203854846736）。Alpha.created_at=`2026-09-26T17:24:39.857354+00:00`，Beta=`2026-09-26T17:24:40.067199+00:00`。模型按正文明确声明的 Alpha 优先规则选择 East，支持其区分存储/检索元数据与明确来源优先级；仍不是不同模型、多个顺序重复的因果证明。

本阶段14生成 / 14529 tokens / 8 embedding请求、226 tokens / 0 exact read；9 ordinary lineage，0 demotion。

### P6 R2 Reflection

1. 支持：通用权威说明可修复本例元数据误读，并保留正常及明确优先级行动。
2. 反驳：两个 CURRENT 正文同时送达即足以避免冲突动作的假设。
3. 第一断点：原模型把存储先后当作来源优先；修复后本例未再出现。
4. 简单解释：额外澄清提示本身可能主导结果，不能宣称 rank 或 lineage 单独解决冲突。
5. 简单方法：追加已有协议常量，足以先检验假设；无需 source resolver 或语义 gate。
6. 复杂度：只增文本，每生成额外39tokens，需在后续实际回归承担成本。
7. 过拟合：反例来自同一 East/West 框架，仍是开发；该句不含来源名或预期值。
8. 反例：明确优先级与写入先后/检索排名相反已验证；后续还需不同任务及长历史。
9. 决定：Continue，完成最终同源十例确认。
10. 理由：最小修复通过三个可区分控制，但旧源码成功不能替代新源码完整覆盖。

## 最终同源确认：10/10

[协议](../data/manifests/milai-ser-v21-p6confirm-protocol.json)、[冻结](../data/manifests/milai-ser-v21-p6confirm-freeze.json)、[结果](../data/manifests/milai-ser-v21-p6confirm-results.json)绑定同一新源码。统一完整目标合同使用 v2 fixture；rubric 只由离线评分读取。

| 类型 | 实际动作或终态 | 额外关注 |
| --- | --- | --- |
| numeric_amount | 6595 | 当前版真实送达，整数及完整目标正确 |
| categorical_route | South | 更新后旧结论处理 |
| boolean_approved | true | JSON boolean 类型正确 |
| boolean_cancelled | false | JSON boolean 类型正确 |
| retained_metadata | 48 | 数值不变仍实际取得当前版本 |
| irrelevant_lower_rank | North | 0 exact get、0追加search，但有3次 snapshot-risk demotion |
| deleted_evidence | 0业务动作，澄清缺失 | 模型自然追加两次空search，成本保留 |
| multi_revision | West | 按各真实更新边界绑定版本 |
| assistant_only_stale | South | 旧search不在请求副本，最终自然search取得当前证据 |
| mixed_memories | South | 四种状态同时实际交付；CURRENT/UNKNOWN正文保持 |

最终确认52生成 / 52764 tokens / 37 embedding请求、703 tokens / 18 exact reads；30 ordinary lineage，34 demotion。与 P6R2 合并是同源66生成 / 67293 tokens / 929 embedding tokens / 18 exact reads。机械风险 rebase precision=34/34、recall=34/34；无 eligible 对象的0/0保持 undefined。这些指标描述生成快照风险处理，不证明被屏蔽回复的每个词都来自失效记忆。

所有严格业务动作验证完整目标、参数类型和值，检查实际 Provider 请求、实际动作收据、lineage 与原 checkpoint。P4 的 assistant-only 中间虚称 search 仍保留在历史报告；本轮成功不抹去该缺陷。

### 最终确认 Reflection

1. 支持：同一实现可处理多种数值、分类、boolean、删除及多版本更新，并保留当前/未知正文。
2. 反驳：新协议只要修好冲突即可直接宣布旧成功继续有效；已实际重跑其余十例。
3. 第一断点：本轮严格动作/机械检查未发现新断点；自然语言搜索效率仍有缺陷。
4. 简单解释：短历史、明确问题与完整目标合同有利于成功，不能外推长程记忆管理。
5. 简单方法：既有 request-copy rebase 与默认自然search已经足够，无需加入持续语义状态。
6. 复杂度：18次 exact read 和1054个已计费marker tokens并非零成本；无关更新仍引起3次风险失效。
7. 过拟合：所有控制均属已知开发分布，尚无 held-out 证据；运行时不读case/rubric。
8. 反例：原任务跨session的漏写、漏搜与动作后旧记忆应在P7暴露；长历史/多用户等仍待后续。
9. 决定：Continue P7，同源 B1/A5 跑原12例和 arc0，先不消费 unseen。
10. 理由：版本及派生文本机制已在小范围成立，下一断点可能在形成、检索或动作后维护，需独立定位。

## 成本、存储与验证

[连续对账](../data/manifests/milai-ser-v21-final-accounting.json)按 SHA 引用七个阶段结果并保留所有失败：P3、P4、P5 R1、P5 R2、P6 R1、P6 R2、最终确认。

| 累计 SER 项 | 实际用量 |
| --- | ---: |
| 生成请求 | 202 |
| input / output / total tokens | 188298 / 7442 / 195740 |
| embedding 请求 / tokens | 134 / 2837 |
| 版本解析 exact Store.get | 75 |
| projection CPU / wall ns | 190007699 / 242343992 |
| exact-read wall ns（已含于projection，不相加） | 97110218 |
| Provider收据 wall 秒 | 86.23198152147233 |
| unknown usage / truncation / Judge | 0 / 0 / 0 |

Provider收据耗时不是包含模型内部所有步骤的因果端到端延迟对比。B1观察器额外读取/CPU另列于逐阶段accounting，不能与75次版本解析读取混同。历史repair45生成/41457tokens/808embeddingtokens及更早ODR/M1/B1费用仍封存在账本history，不清零或并入本轮成功分母。

本轮authority从24增至63个本地固定tokenizer tokens，每生成增39；最终66生成的增量片段共2574 tokens，已包含在Provider账单中。31-token demotion marker本轮送达34次，共1054tokens，也不得再次加到账单。P5旧对照虽使 irrelevant get 3→0，tokens却5161→5213；最终删除例的两个额外search再次说明不能声称总体效率胜出。

[P6R2 storage](../data/manifests/milai-ser-v21-p6r2-accounting.json)与[确认 storage](../data/manifests/milai-ser-v21-p6confirm-accounting.json)合计：trace 2932154 bytes、instrumentation SQLite 1294336 bytes、checkpoint 1085440 bytes、business journal 8720 bytes。快照/事件字节是这些文件的子集，不能重复求和。新增持续语义 State=0 bytes，但 factual Store、原history和分析存储并非0；共享PostgreSQL物理页未按run摊分。

P5实现已通过11个必要窄检查、静态和依赖边界及一次累计构建，包含当时25个diagnostic输入文件；v20延后sdist问题由此闭合。P6R2纯协议文字修改仅做ruff、diff、AST前缀保持、实际CLI A4/A5 schema/参数/协议及token核对，不重复pytest、decoder probe或build。这些本地验证收据保存在ignored artifacts。新P6R2锁未宣称存在于旧包中，P7新增入口时统一打包。

## 复现与后续

源码入口为 `tools/run_milai_ser_v21.py`，config为 `configs/milai-ser-v21.json`。使用本报告新锁，不能依赖该CLI默认的旧P5锁；两阶段freeze分别记录每case完整实际schema、参数、协议、输入SHA、prepared manifest与空namespace。输入在 `data/diagnostics/selective_adaptation_v2/`，原历史输入、评分和锁均保留。

```sh
.venv/bin/python tools/run_milai_ser_v21.py prepare \
  --config configs/milai-ser-v21.json \
  --lock data/locks/milai-ser-v21-p6r2.lock.json \
  --mode mechanism --run YOUR_NEW_RUN --arm a5_rank_bounded_rebase \
  --fixture data/diagnostics/selective_adaptation_v2/current_conflict.json \
  --mechanism-freeze data/diagnostics/selective_adaptation_v2/freezes/current_conflict.json \
  --output YOUR_NEW_PREPARED_JSON
```

实际run使用相同参数及 `--prepared YOUR_NEW_PREPARED_JSON --stage YOUR_NEW_STAGE`，将 `--output` 改为独立新目录；连接信息只通过本地私密环境注入，切勿提交DSN。保留现有累计账本，禁止覆盖已执行run。Host为原Qwen3.6-35B-A3B-FP8/7860，embedding为原bge-m3/7861，温度0、max_tokens4096、max_calls12；不修改vLLM服务设置。原始Provider、SQLite和控制台产物保持ignored，Git只包含可核对的紧凑结果/冻结与源码。

当前范围是 `RESEARCH_PROTOTYPE`，不改变Product Schema/API/权限/Canonical语义。尚未证明高排名当前候选的任务充分性；request级风险可能过度失效无关回复；跨session形成、动作后维护、长历史和正式未见样本仍待研究。Luna负责本轮已授权发布与remote SHA核对。P7接入原runner/scorer做匹配回归，之后按总Goal继续P8–P12，不因本阶段13/13宣布整个项目完成。
