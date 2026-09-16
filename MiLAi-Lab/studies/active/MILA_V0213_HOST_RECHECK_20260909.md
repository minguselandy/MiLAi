# V02-13 Host 修复与冷启动复验：H1 v2 有界通过，保留 A0

状态：`HOST_COLD_RECHECK_VERIFIED_KEEP_A0`。
本阶段按用户目标修复来源入口使用与有效调用交付，在原两道可裁定任务上验证，不增加样本或 State。
H1 v1 首次冷启动成功、第二次失败；完整保留失败后，H1 v2 两题 × 两次冷启动均正确交付。
这是已暴露开发任务的回归验收，不是四个独立新任务，不是正式 benchmark accuracy 或总体净收益。

## 已修复、已验证与尚未验证

| 要求 | 当前证据 | 范围/限制 |
| --- | --- | --- |
| Host 使用正确来源入口 | H1 v2 实际调用 source_read，按返回游标读到 EOF；两题分别 7/8 页，四次全部呈现 | A0 不变，坐标题仍只查空 Product 后弃答；不声称 A0 自主取得问题已消失 |
| 不把空调用标成完成 | 沿用原终态修复；H1 新增按已知工具定义生成的结构化交付 schema 和本地验证 | 仅格式/参数结构保证，不是语义正确保证；弃答分支仍开放 |
| 模型交付正确完整调用 | H1 v2 四次实际生成均与封存完整参数 reference 相等，每次一次生成 | 是新组合策略的有界行为验证，不是原“完成判定修复”单独的因果效果 |
| 冷启动复验 | 每轮新 Product 实例，每条件独立 Host/MCP 进程、principal/project/task，初始 Notes 空、State ABSENT | 不重启共享模型或清其推理缓存；“冷”指 Host/会话/持久作用域，不指模型权重冷加载 |
| 保留 A0，不新增 State，不扩样 | A0 初始 payload 与原 Seal B 文件逐字节一致；仅原 task-01/02，无写入或新增题 | H1 是独立 Lab 候选，不部署或替换 A0；确认集未打开 |
| 诚实评价取得/使用 | 原拒答、格式失败和 P3 不可裁定均保留；新实验单独记分母 | BM25、Product retrieval、长历史表现、独立样本和规模化成本收益仍未验证 |

## H1 实现

`tools/v0213_host_policy.py` 不读取 evaluator：只接收原始问题/已知业务工具 schema 的在线 payload。
由公开业务定义规范化 Python 类型名，生成 tools/business/abstain 三个互斥分支；business 必须非空、
工具名匹配、必填参数齐全且类型正确，未知参数被拒绝。optional 参数仍可省略，若请求明确指定则
由模型填写；不把 reference 参数硬编码为必填。允许显式弃答，不用虚构值满足 schema。

H1 v1 在模型首轮前通过原 source_read 读取每个源的首个普通页，再开放模型按需读取/搜索。
第二次坐标题虽然继续读到了坐标，却因未确认完整历史中的“惯用”指代而弃答。
因此 v1 的 3/4 正确没有通过预先设定的两轮验收，不隐藏或删除这次失败。

H1 v2 改为公开分页读取：固定源顺序、从 offset 0 开始、跟随每次返回的 next.offset，最多 16 页，
只有各源均返回 EOF 才声明 source_coverage.complete。页的 **4096 bytes 是包含元数据的返回预算**，
不是保证每次读取 4096 bytes 的原文。模型仍有最多三次生成、六次自选取得调用；Host 最多十六次
读取另外计量，整体取得调用上限二十二。A0 仍最多六次，没有偷偷扩大其条件。
超过页预算保持 partial，不伪称全文；每次生成仍检查实际 context 减 4096 输出预约。
此次短历史全部可放入上下文，模型不需要额外工具调用。

这是分页来源读取与交付约束的组合修改。没有训练、语义 detector、gold 注入、case 分支、
自发 State 或隐藏模型重试。v1/v2 各自在第一次输出前独立封存，组内不改策略；旧执行源码保留。

## 实际冷启动结果

| 版本/条件 | task-01 两次冷启动 | task-02 两次冷启动 | 实际调用意图情况 |
| --- | --- | --- | --- |
| H1 v1 | 正确、弃答 | 正确、正确 | 3 个可评分意图均正确；1 个弃答，不报告为参数错误 |
| A0（v1 对照） | 弃答、弃答 | 正确、正确 | 2 个可评分意图均正确；2 个弃答 |
| H1 v2 | 正确、正确 | 正确、正确 | 4 个可评分意图，4 个正确，4 次均一次生成 |
| A0（v2 对照） | 弃答、弃答 | 正确、正确 | 2 个可评分意图均正确；2 个弃答 |

坐标调用完整保留字符串 `40.7128` / `-74.0060`；天气调用为 Sydney、整数 days=5。
第 1 轮条件顺序 A0→H1，第 2 轮 H1→A0。原 A0 天气题的空计划失败此次没有复现；
即使 seed/temperature 固定，也不能把旧单次失败当成每次必现，更不能将 A0 报作参数 accuracy 0/2。
这里可报告 H1 v2 完整任务交付 4/4、A0 2/4，但语义参数分母分别是 4 和 2，且重复任务相关。

四份 H1 v2 工具账本中的原文页按序拼接，SHA256 都与冻结原文相等；最终请求含全部 7/8 页，
没有“读到但未呈现”的工具结果。source-only Product 没有摄取这些历史；此次没有 BM25 排名调用。
H1 的正常源入口是 Lab 普通来源接口，Product 操作仅走固定公开 MCP，不能称作 Product 检索改进。

## 成本、验证和清理

| 运行 | 新生成 | raw tokens |
| --- | ---: | ---: |
| v1（含未通过复验的候选与 A0） | 18 | 157,816 |
| v2（候选与 A0） | 12 | 118,449 |
| 本阶段合计 | 30 | 276,265 |

v2 H1 为 4 次/57,773 raw；A0 为 8 次/60,676 raw。累计 token cap 为 null。
Provider 对账覆盖完整输入重发、输出、tokenize、payload hash 与 HTTP usage；pending/violation 为零。
工具读取延迟在账本计量，v2 共有 30 次 Host source_read；每个条件另有两次真实冷状态预检
（Notes list/State get），不呈现给模型，还有 catalog 检查。编码代理评价劳动、整体基础设施费用
未独立计量，不称其免费；无额外 benchmark Judge、数据生成或真实业务动作。

新增 9 个单元回归，覆盖空/错误业务计划、未知参数、合法弃答、基线不变、游标推进、EOF 与部分预算。
最终 `uv run pytest -q`：**685 passed**；Ruff、boundary、mypy（38 文件）、build、diff --check 均通过。
Product pin verifier 在每个实例启动前通过；八工具 catalog 和模型身份逐个条件核验。
四个独立 Product 实例均停止，API 进程消失、PostgreSQL Exited(0)，卷与证据保留；共享模型未重启。
Product API/schema/权限/Canonical 无改动、无迁移、无公网部署。
Schema 仍 `0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE`。

Git 外证据：`/cra/memory/mx_memory/evidence/v0213/host-recheck-v1-20260909/` 和
`host-recheck-v2-20260909/`，含 seal、原始/候选输入、执行源码、冷状态、逐页/逐请求账本和 result。
v1 result SHA256：`4415821c89b383af45410793255754eb85161611867226ad4b2e0f0a50d26dcb`。
v2 result SHA256：`c3c9aecef855dc8acc60870d35be2c848fdcb5232c4ccac51b357d04746ecf21`。

与此前[首波](MILA_V0213_RESULTS_20260909.md)、[P3](MILA_V0213_P3_RESULTS_20260909.md)结果分别保留。
后续若评估更长历史、检索排名或部署净收益，需要新的独立合同；本阶段不以扩样填补这些未知项。
