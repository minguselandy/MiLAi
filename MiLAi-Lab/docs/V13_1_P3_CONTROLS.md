# v13.1 强简单基线实际验收

状态：CORE_MECHANICAL_PASSED_SCOPED_WITH_ORIGINAL_COUNTER_BUG。完整目标 ACTIVE，Product NO_GO。

[源码验收](../data/manifests/v13-1-p3-controls-source-acceptance.json)冻结 1ca26ad 的 205 个源文件，
聚合 SHA 为 cda9bf914dfdd9291626c219c32c3cff8c5b1cd28ae13596e0b28b599b20b68a。
80 项机械检查、Ruff、mypy、canonical matrix 和两份 CI 对齐检查通过；初始失败日志保留。
新策略 opt-in，旧 P5 和外部微型验收的资源与结果未改。

[预注册协议](../data/manifests/v13-1-p3-controls-micro-protocol.json)在模型调用前冻结。
六类输入覆盖保存→重开、偏好变更、相对日期、真实工具角色与 ID、owner 隔离和失败成本。
原始已捕获用户/工具行保持不变，额外脚本闭合回合有独立脚本 ID。
一个草稿回合误复用了旧 ID，另一个容量探针缺少执行标记；均在首次冻结与 HTTP 前修正。
每臂 34 步、13 个闭合形成边界；每一步实际新进程连接同一持久资源，生成和 embedding 合计并发为 1。

[实际结果](../data/manifests/v13-1-p3-controls-micro-results.json)共有 238 个不同进程：
224 步完成，7 次按预期拒绝跨 owner 查询，7 次按预期拒绝当前超容量输入；没有 NOT_RUN 或普通执行中断。
Root 另用公开 SDK 重新打开 42 份持久资源，原始角色、ID、时间与工具正文均与输入一致，外 owner namespace 为空。
B0 按声明丢弃过去；B6 的检索材料仅覆盖实际操作回执。原文归档存在不等于所有方法都向 reader 交付全部归档。

| 方法 | 实际生成次数/token | 实际 embedding 次数/token | 历史问题有限正确/未知（共5） |
|---|---:|---:|---:|
| B0 NoMemory | 5 / 1,757 | 0 / 0 | 0 / 5 |
| B1 FullHistory | 5 / 4,525 | 0 / 0 | 5 / 0 |
| B2 StrongRawRAG | 5 / 7,530 | 18 / 3,441 | 5 / 0 |
| B3 RollingSummary | 9 / 5,790 | 0 / 0 | 5 / 0 |
| B4 Ordinary-Matched | 31 / 24,665 | 18 / 564 | 5 / 0 |
| B5 Prompt-only | 31 / 26,268 | 18 / 596 | 5 / 0 |
| B6 Receipt-RAG | 5 / 2,775 | 2 / 404 | 1 / 4 |

这是 Root 对固定开发事实的非盲复核，不是官方任务分数或独立泛化证据。
B0/B6 对其未保留的事实如实回答未知，不计历史任务成功，也不能称每臂六个语义检查全部通过。
相对日期不凭运行日期补全；B0/B6 没有对应历史证据，保守记作未知。
B3 实际执行了四次摘要更新：保存故事一次、偏好变更故事三次，不是预制摘要。
B4/B5 使用同一现有自然语言 CRUD，B5 只增加 writer 提示；reader 提示一致。
真实 partial 回执在 B1–B6 的相应材料中支持“预约存在、原 UUID 正确、标签未创建”，不把失败解释为没有任何副作用。

容量探针是公开当前输入的机械压力检查，实际 Host plain-token 数为 80,023，超过 65,536；
不用于语义准确率或 Attention。B2/B4/B5 的实际查询路径由 BGE 的 8,192-token 检查在 embedding HTTP 前拒绝；
没有回执索引的 B6 不发 embedding 查询，由 Host 容量检查拒绝。所有七臂拒绝前后银行相同，随后只读重开也相同。

这次运行发现并保留一个计数错误：旧 runner 监听 `vllm_request`，而 provider 仅在完成/失败时发出
`vllm_response`/`vllm_error`，因此旧 receipt 的调用计数显示 0。原始 wire、usage 与连续账本正确存在。
Root 单独从完整 trace 派生 91 次生成、56 次 embedding 请求，并逐项核对账本增量
73,310 个生成 token、5,005 个 embedding token；unknown usage 均为零。原 0/0 字段没有覆写，未重跑该批。
后续 Source 在主工作树修正该计数，冻结的实际 replay 保持不变。

另外，[NoMemory 当前工具协议](../data/manifests/v13-1-b0-live-query-protocol.json)与
[实际结果](../data/manifests/v13-1-b0-live-query-results.json)使用旧已付费 R2 clean world 的字节副本，
不给 Host 旧 bank、checkpoint、历史或预期状态。全套三个原生业务 schema 正常可见，当前用户仅授权查询。
Host 实际执行一次 `get_reservation`，回答“预约存在，当前标签状态为已创建”；
长期记忆前后及 SDK 重开均为空，业务 world 与原世界字节未变，错误提案和副作用均为零。
新增 2 次生成、1,252 个 token。此任务当前查询足够，不证明历史恢复能力，也不通过禁用工具制造记忆依赖。

两项实际工作合计新增 93 次生成、74,562 个生成 token、5,005 个 embedding token。
累计账本为 6,762 次生成、12,788,273 个生成 token、425,835 个 embedding token；unknown usage 与 Judge 均为零。
238 个冷 CLI 步骤合计约 1,983.5 秒，包含导入和身份核查；这是刻意每步重开的验收成本，不是产品服务延迟。
完整 provider 成本有证据，Store I/O、CPU、GPU 时间和美元成本只按实际覆盖范围报告，不能由 token 推算。

[相等配置候选](../data/manifests/v13-1-development-configuration-candidates.json)每方法两套，
[开发身份](../data/manifests/v13-1-equal-config-development-selection.json)为相同八个已曝光原始组件：
四个 scope、两个 valid、两个 personalized。48 个配置×问题对尚未执行，因此 P3-fair 尚未通过。
新 pilot 仅预留身份，本批没有读取其问题或评分内容；正式 nominal 来源题量缺口仍保留。

后续完成源码计数修正、实际等额配置试跑、四臂生命周期比较和 pilot。
当前验收不支持独立双类型收益、Field-grounded 的一般行为增益、任意并发 exactly-once 或正式发布结论。
