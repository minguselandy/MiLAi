# MILA-V02-05：非模型工程增量与成本审计

状态：`PARTIAL_ENGINEERING / FORMAL_E2E_NOT_ENTERED`。本轮模型会话、生成请求和生成
token 均为 **0**；另有两次本地 `/tokenize`。不能宣布 D0–D3 整体通过，不能宣布分层降本、
保存增量或留出泛化通过。当前目标仍未完成。

最新增量见 [Working State 异步传输](MILA_V02_P1_ASYNC_STATE_20260906.md)：
GET/UPDATE 已接通异步客户端；真实 PG 并发/撤权回归通过，但 MCP 8 并发 P95 未达候选目标。
该结果不授予 P1/D3 整体通过。源码 pin 为 `fd93b919c24965586bf9c71f32b0802fe9349fae4ef568487a1e32fd7908bd12`。

前一 v0.8 P1 增量见 [调用等待点与 State 基线](MILA_V02_P1_SERVICE_CALIBRATION_20260906.md)：
同步 SDK 实例串行点取得机制证据，真实 PG 完成 1,000 条 State 的保存与 1/8 并发读取，
CAS/直读/回放正确。尚非完整 P1 或网关 SLO 验收，新增模型请求仍为 0。
以下章节和验证数量保留此前 v0.5–v0.7 的历史归属。

## 实际修复与证据

真实 PostgreSQL / 公开 MCP 复现了权限披露问题：Evidence 撤销后，Working State GET
及旧操作的幂等回执仍返回受控正文，只有 warning。现在两条返回路径在声明的引用不可读时
隐藏整个不透明 payload，并返回 `payload_withheld=true`。历史内容、CAS、幂等身份和
Canonical 治理不变；没有迁移、没有公网发布。协议依据为 Product ADR-041。
撤销不代表内容为假，也不代表任务已解决；没有声明的来源关系不在此修复的自动发现范围。

Lab 的通用 L1/L2 适配器现在保留 Markdown 字节语义及 JSON 值、旧字段和显式引用，
区分 no-op、操作确认、当前 head 和 UNKNOWN；不靠一次 GET 猜测丢失回执的操作结果。
真实测试覆盖提交后其他操作推进 head、响应丢失、CAS 拒绝和 L2 写好但 L1 未提交。
独立冷进程验证恢复；受控派生文件及已进入上下文的来源在下一请求前重新检查资格。
独立合法文件继续可读。文件映射由 Host 持有，模型文本不能声明自己的权限。

现有本地模拟 runner 复用这些函数；历史 SIM01 配置保持关闭，runner 和 transport 两处
都拒绝零新增授权。no-op 可以保留已有 A/B 机会，但不记成新的成功保存。
该 runner 仍不是原生 Codex Host；完整 LME 分叉尚未接入，不能据此开始 SIM02。

第二次非模型增量把 G 的必要保存/确认移回 G 进程，使用同一个绝对截止时间覆盖准备、绑定、
恢复、工具、生成、交付及保存。Linux 主线程计时器可中断阻塞调用；子进程继承截止时刻，
不为每次工具调用重置预算。已交付答复与尾部保存超时分别记录，清理不能把超时追认为成功。
`finish` 在截止时间内生成 `final-delivery.json`，该最终输出产物是本地 Host 的交付观察边界，
时间戳和正文先于必要保存落盘；不能仅凭尚未输出的内部 action 宣称已经交付。
生成取消保留未决预约；迟到但可信的 usage 可以结算，输出不再进入任务行动。
保存中断保留操作 UNKNOWN，不追加 GET/重写。该机制尚无新模型/原生 Host 性能证据。

新增 `summarize_v02_e2e_generality.py` 检查实际请求正文哈希、预约、发送标记、HTTP 回执及
usage 的关联，区分待发、未知及回执确认。片段定位只报告消息位置，不推断理解或任务质量。
16 项新回归包括实际进程计时器、预约后 SIGKILL、重启阻断、尾部保存超时、迟到结算，
以及实际 JSON-action Host 路径的 A/B 请求装配和未呈现负控。HTTP 通过 MockTransport，
不向真实生成端点发送。此增量没有启动服务。

第三次非模型增量通过公开 Hook/SDK 在独占实例分别导入 G/A/B 各 **484 条事件**，
每臂保留全部 **44 份会话文件**。逐条 GET 核对正文、原始会话时间、角色、归属、
作用域、保留状态及前后 turn 链接，再通过新进程恢复 State 和核验完整文件资格。
只重绑定公开声明的 `evidence_id` / `evidence_refs`；不替换正文里的 UUID 字符串。
会话时间按原来源保留，顺序由 turn ordinal 表达；旧导入器的加秒默认值留作历史兼容。

该历史的首个固定来源查询在三臂返回相同证据内容、原始时间和事件顺序，均为 `DEGRADED`。
公开 Runtime 诊断为 `context_budget`，不是来源丢失或组件宕机。保持原预算与部分结果，
不扩大上下文、改题或把降级计为干净通过。修正 MCP 的误导性警告文案，仍保持同一
warning code、状态、返回证据和权限；没有 Runtime、Schema、Canonical 语义变更。

同时，以关闭的 SIM01 G **真实产物**为母本，运行文本、JSON 文本包装、内容分布到
不同字段、字段换序、删除首尾字段五条“公开保存→新进程→实际 Host 装配→mock transport”链。
前四者可无损还原母本；删除例可以合法保存且所有原始文件仍在，但被明确记为信息删除负控。
字段换序在恢复后的 L1 中被 JSON 序列化消除；完整请求仍可能因来源哈希等元数据不同，
不能借此宣称模型位置鲁棒性。Mock 配置禁止接入真实网络 transport；五次为 mock 请求，
真实生成仍为零。完整模型 LME runner 尚未接入这份已核验的来源分叉。

证据根：`artifacts/v02-e2e-generality/eng-20260906a/`（Gitignored）。

- `revocation-before/result.json`：原缺陷，GET / replay 两处正文泄漏。
- `live-after/`：文本/JSON、旧字段、no-op、CAS、幂等、操作/head 分离、冷进程及双向 canary。
- `live-followup/`：同一来源公开重绑定、L2/L1 部分失败、撤销后的两条新进程恢复。
- `sim01-cost-audit.json`：逐请求 payload 哈希、usage、重复历史及固定/L1/L2 字节构成。
- `opened-history-audit/`：固定首条已打开历史的完整文件、映射和无生成输入计数。
- `cleanup.json`：本轮两套 API/worker/PG 停止核验；数据保留，共享服务未改。
- `control-20260906a/`：第二次非模型源码摘要、检查日志和 SIM01 请求呈现只读审计。

第三增量证据根为 `artifacts/v02-e2e-generality/eng-20260906b/`：

- `source-branches/G/source-receipts.jsonl`：首次 `DATA_MODE_BLOCKED` 拒绝，0 条提交；
  `data-mode-repair.json` 记录只把独占实例调整为 `DEIDENTIFIED_ALLOWED`。
- `source-branches-allowed/`：1452 条公开回执、元数据、文件、映射、冷恢复、双向 canary；
  G 的查询状态断言失败后从既有完整回执恢复检查，没有重新导入 G。
- `source-search-diagnostic/`：保留最初降级及公开 Runtime 的 `context_budget` 诊断；
  `budget-warning-after/`：修正后的实际 MCP 提示，降级状态保留。
- `representation-chain/`：母本、五种变换、公开保存、恢复、实际 mock 输入与负控。
- `final-source-integrity.json`、`final-checks.json`、`cleanup.json`：完整来源复核、当前
  pin/检查和独占实例停止证据。此增量不使用新 tokenizer 或真实生成请求。

## 成本与任务结论

只读审计重新关联 SIM01 全部 **7** 个实际请求及预约/结算，合计仍为 **21,880 raw token**。
G=13,096；A=3,287；B=5,497。B 多 2,210（**+67.23%**）。重复发送的历史逐次计入 input；
cached 若可知是 input 的子集，不额外相加。提示、L1/L2、schema 的字节数不能相加冒充
Provider token 分摊或金额。原始配置、总账、失败记录和模型结果的哈希未改变。

A/B 三个决策字段正确，但已交付 reason 均没有回滚后核对指标这一步；A 也未交付通知步骤。
审计器记录有限字面锚点及来源/答案哈希；它不是通用语义 Judge，其他语义维度仍未评价，
不能把字面命中当作完整动作或论证质量 PASS。历史模型结果不因本轮审计而重写。

已打开清单 D 的固定首条为 `0a995998`，不是按效果选题。保留 44 个历史会话、484 条事件，
候选 G 输入未带未来问题或 gold。本地 tokenizer 对候选首输入计得 **4,011 token**；
一次性附加完整历史的诊断输入为 **124,356 token**。后者不是模型请求。
首请求容得下不证明后续读取、重复历史及输出能落在累计 20k 内。完整来源的公开导入、
排序/资格等价及分叉还未验证；不删历史、不换简单题来凑预算。

## T01–T32 实际覆盖

`PASS` 只指本行列出的工程边界；`PARTIAL` 不能计入完整 D3 出口。单元用 mock 的项目
不证明 Provider/原生 Host 合同。所有模型语义、留出与变体任务效果均 `NOT_RUN`。

| 项 | 状态 | 本轮证据或剩余边界 |
|---|---|---|
| T01 Markdown | PASS | Unicode/CRLF/空白通过公开保存、新进程恢复 |
| T02 JSON | PASS | 嵌套、数组、false/0/null/空值，单元及真实 PG |
| T03 原有字段 | PASS | 保存保留旧字段与引用；实验装配仅呈现声明层 |
| T04 无候选 | PARTIAL | [无候选编排增量](MILA_V02_NO_SAVE_ORCHESTRATION_20260906.md)：脚本G/真实State保留任务交付与H、无候选写入/追加会话；模型自主不保存选择仍未验证 |
| T05 自然/no-op | PARTIAL | 真实 no-op 不新增写；自然 Agent 保存证据尚无新增运行 |
| T06 正常保存 | PASS | 公开操作回执、版本和 head 可关联 |
| T07 CAS | PASS | 实际 PG 拒绝后写，不覆盖较新 head |
| T08 丢回执/head 推进 | PASS | 真实提交后传输故障注入，UNKNOWN 与 CONFIRMED 分开 |
| T09 幂等 | PASS | 正常 replay、冲突及撤销后的旧回执 |
| T10 L2 成功/L1 失败 | PASS | 真实文件＋PG CAS，保留新 head 和未引用 L2 哈希 |
| T11 L2 版本 | PARTIAL | 变化/缺失/越界/资格拒绝；历史版本定位全矩阵未覆盖 |
| T12 超限 | PARTIAL | L1/预载/装配拒绝且不截断；全部 Host 发送路径未证明 |
| T13 冷恢复 | PASS | 独立 Python/MCP 进程；正常及撤销后的冷启动 |
| T14 A/B 装配 | PASS | 真实冷恢复＋当前 JSON-action Host 到 mock transport 的请求正文核对 |
| T15 取得/呈现 | PASS | 待发文件、取得记录、未知发送均不冒充确认呈现；正文篡改拒绝 |
| T16 正常发现 | PARTIAL | 完整 LME 普通文件/来源可发现；固定查询返回预算限制下的三条证据 |
| T17 项目隔离 | PARTIAL | 双向公开搜索、外项目引用写入拒绝、文件边界；原生 Host 未验 |
| T18 canary | PARTIAL | 工程两项目互不返回对方正文；全工具/启动请求矩阵未验 |
| T19 撤销 | PARTIAL | GET/replay/冷进程/受控文件/旧上下文重发阻断；未声明来源不自动识别 |
| T20 重绑定 | PASS | 三臂各484事件公开导入/核验及完整文件；固定查询顺序一致，不外推所有查询 |
| T21 表示变体 | PASS | 真实G产物、变换记录、公开保存、冷恢复、当前Host mock输入逐条关联 |
| T22 结构可观察性 | PASS | 分别比较恢复L1和完整请求；记录键序被消除，模型效果未运行 |
| T23 删除/坏协议负控 | PASS | 首尾信息删除仍可保存但不计等价，母本来源完整；坏envelope/布局拒绝 |
| T24 零授权 | PASS | runner、worker、transport 在启动/构造 HTTP 前拒绝；预算不足阻断 |
| T25 完整请求上界 | PARTIAL | SIM01 请求/usage 哈希一致；非本地 Provider 未验证 |
| T26 预约/在途 | PARTIAL | mock transport 锁与额度回归；正式 Provider 合同未验证 |
| T27 未知 usage | PARTIAL | mock 断线/缺失 usage 保留预约并停止；远端取消费用未确认 |
| T28 崩溃恢复 | PASS | 真实子进程在预约落盘后 SIGKILL；重启后无新网络发送（mock transport） |
| T29 隐式请求 | PARTIAL | 本地单发送点/无重试；原生 Host 全路径仍未观察 |
| T30 deadline | PARTIAL | 新本地 Host 共用绝对截止时间，含 G 保存；模拟时钟/阻塞进程验证，正式 Host 未验 |
| T31 评价/隔离 | PARTIAL | gold 不进入模拟 workspace；原生沙箱和完整语义判据未齐 |
| T32 清理 | PASS | 两套独占服务停后检查；临时 MCP token 仅在已退出进程环境 |

## 验证与 pin

- Product Runtime：`uv run ruff check src tests migrations`、`uv run mypy`（189 文件）、
  `uv build` 均通过。新独占 PG 上 `uv run pytest -q`：970 通过、2 跳过；补充测试环境
  和公开 adapter 路径后，两项各自补跑通过。没有把第一次的跳过改写成当时通过。
- MCP：Ruff、mypy（12 文件）、build 通过；pytest 160 通过、1 跳过；配置独占 PG
  后 `MILAI_MCP_BASELINE_E2E=1` 补跑生命周期测试 1 通过。
- Lab：第二增量 boundary、完整 pytest（244 通过）、Ruff、mypy src（30 文件）、build
  均通过；逐条退出码及日志见 `control-20260906a/checks.json`。
  补充最终交付观察边界后的 pytest/Ruff/build 复核见该目录 `delivery-checks.json`。
  deadline、核心适配器、请求汇总器另以 `mypy --follow-imports=silent` 检查（3 文件）。
  首增量的 228 项结果仍保留在原 `final-checks.json`，不重写旧日志。
  不把 src 类型检查外推到所有 tools。

第三增量复核：Lab **250 通过**，boundary、Ruff、mypy src、三个核心 tools 的 mypy、
build 均通过；MCP **161 通过、1 跳过**，该真实 PG 生命周期项另以本轮独占 PG 补跑
**1 通过**，其 Ruff/mypy/build 通过。Runtime 源码未改，不重复借用其旧测试数作为新执行。

旧 SIM01 Product pin：`c5561412b0440f84e628d69a7c271c96d66bae7f89d4e3f1db46ede97a1608bf`。
修复后 pin：`1f49c15194a7a8187a48f321437b024f8a7b12cdb96f5f35e6ce6b5bc2d29c4a`，
采用独立 `data/locks/v02-e2e-disclosure-product.lock.json`；不改旧结果的 pin。
服务恢复配置含数据所需密钥，以 0600 保留在私有 artifact 目录；临时 observer token 不落盘。
Schema 仍为 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。

MCP预算提示修正后的当前pin为
`baf29ec03b264d22fcee0fde238d970ac52a3c106b3ad507159ad991af3a0754`，
配置采用 `data/locks/v02-e2e-budget-status-product.lock.json`。
本轮完整来源/变体检查发生在该提示修改前的 `1f49…` pin；提示修正后另跑公开 MCP 检查，
不把前面的证据改标为新源码运行。旧 lock、SIM01 原始配置/费用/结果仍保留。

按更新 Goal v0.8，MCP State 异步接入已完成，下一步先定位剩余等待、补来源引用/检索和混合负载出口；
来源分叉接入已有单元验证，完整编排/权限/真实工具 deadline 及任务判据仍待补齐。
工程检查不代替真实 G/A/B；完整正式 Host/Provider 合同仍未验证。
正式 Host/Provider 合同及新增模型额度未满足，SIM02、D4、D5 均不启动。
