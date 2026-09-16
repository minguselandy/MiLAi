---
document_id: MILA-V02-03-CORRECTION
date: "2026-09-06"
status: COMPLETED_KEEP_BASELINE
N4: PASS_FOR_CONFIRMATION
N5: INCOMPLETE_BUDGET_GATE
---

# Payload 保真修复与原定 F/S 续做

前轮因笔记末尾换行而将 N4 收尾为“无合格机会”，这个工程判断过于脆弱。应修复一般性
输入缺陷并继续验证。旧报告和失败回执保留为修复前事实，不再作为当前候选不可评估的依据。

此次已修复通用输入缺陷并完成 **12 次后续任务、3 条历史的完整 F/S 对照**，均通过离线任务
审阅，三条历史分别达到原成本门槛。第四条历史完成了普通笔记和原样保存，后续因累计 token
启动闸门未运行。N5 尚缺一条完整确认历史，所以继续完整 A0；保存候选保留为 Lab 实验工具，
未获完整有限场景确认。通用 payload 保真修复独立保留。详见
[完整累计机器总账](MILA_V02_PAYLOAD_FIDELITY_RESULTS.json)。

## 通用修复与验证

Product 将绑定标识的空白清理限定到标识字段，任意 State payload 的字符串及嵌套键保持原值。
正文无需剪裁、转码、补字符或重新生成。见
[ADR-040](../../../MiLAi-Product/docs/adr/ADR-040-working-state-payload-fidelity.md)。
权限、Canonical、CAS 算法和 API 形状不变；内容摘要现在区分原本不同的空白内容。
旧 operation ID 若对应旧版已归一化的请求，新版可能报告冲突，不能盲目重试或改写历史回执。

Runtime：真实 PostgreSQL 全量 `uv run pytest -q` 为 **971 passed, 1 skipped**；唯一 skip
是 Runtime 环境缺少 milai_client 的 context-chat 测试。`uv run ruff check src tests migrations`、
`uv run mypy`（189 文件）、`uv build` 通过。原始日志保留在新隔离运行目录。
Lab：`uv run pytest -q` **158 passed**，Ruff、mypy（30 文件）、boundary、build 通过。
回归覆盖首尾空白、CRLF、Unicode、代码缩进、空字符串、纯空白字符串、嵌套键、摘要区分、
幂等重放和 CAS；既有真实 PG 权限、引用撤销和审计检查继续通过。

原来两份 G 文件经实际公开 MCP/PG 保存及读取，正文 UTF-8 字节与原文件完全一致：

| 历史 | 字节 | SHA-256 | Delta_save 秒 | 重复调用 |
|---|---:|---|---:|---|
| 27016adc | 1718 | c7ed047b321201d91aa5abd091d4bcfd976c5e3990863399c9097affb3ce3e03 | 0.237639 | NO_OP，版本仍为 1 |
| 852ce960 | 1673 | 67d03c0aa4d4d1041232841db7a606c758a0cb1ab06d3ba8c8409a38756e0c50 | 0.164133 | NO_OP，版本仍为 1 |

每次保存包含 GET/UPDATE/确认 GET，0 模型调用。首条保存及重复读取成功后，汇总代码的
`st_size()` 笔误导致退出；修正汇总代码并复核已有回执后继续第二条，未重做第一次保存。
这些是工程修复证据，不能单独证明后续任务收益或普遍泛化。

## 对照身份与成本口径

新运行：`artifacts/v02-state-payload-fidelity/run-20260906a`。
新 Product tree：`c5561412b0440f84e628d69a7c271c96d66bae7f89d4e3f1db46ede97a1608bf`。
新 lock digest：`d1cfd517a7c4e53bdfcd5d280065c26fad055f3af605bc4c927dddb850523c97`。
配置：[v02-fidelity-followup.json](../../configs/v02-fidelity-followup.json)。

沿用 G 前已固定的 [两条历史、四个未来任务和顺序](MILA_V02_LOW_COST_REUSE_R.json)。
G 只使用原来的两次已完成任务，其原始笔记和历史不变，不再调用模型生成笔记。G 来自修复前
Product pin，两臂共享这份共同产物；全部新 F/S 使用同一修复后 pin，因此不能把它写成 G
也在新 pin 下重跑过的端到端实验。旧 G 实际 H 为 ABSENT/0，S 的 H′ 来自此次公开真实保存。
公开重新导入历史产生的新 Evidence ID 只按会话/turn 做一一绑定映射，保留映射回执。
两臂完整 A0、普通文件（含前一任务答案）、允许历史和当前问题相同，S 额外得到保存的 State。

原来的 3 次分配、2 次模型会话和 482794 input+output tokens 仍计入总预算。
预算扫描显式纳入旧运行目录，去重同一路径，旧分配缺终态或已启动 usage 未知时拒绝后续启动。
N3/N4 仍上限 12、总计 28、累计已知 tokens 达 2400000 后禁止新启动，每批 4 次/1200 秒。
共同 G 成本在两个反事实路径中都列出，在差值中抵消，但研究实际成本只计一次。
每条历史独立检验两个后续合计 token 降幅至少 10%、计入 Delta_save 后在线墙钟净节省为正，
且质量无损；不以跨历史抵消判通过。N5 仅在原合同条件满足时进入。

## F/S 结果

原定 8 次 F/S 均完成，首次外显实质判断和最终产物均核对了原始来源；任务正确 8/8。
审阅是执行者离线审阅，不是独立 Judge 或人类 gold。contractor 的 S 回答省去了 F 提到的
乡下地块面积/挂牌价，但保留了本题要求的装修内容、估价、时间及不同工地；这项简略差异已
记录，不作为关键任务错误。两组保留的原文件及其机械路径映射一致，实际 launcher bootstrap
与分支 State 对应，13 工具均可见；逐请求模型输入仍未观察。

| 历史/未来 | F tokens | S tokens | F 在线秒 | S 在线秒 |
|---|---:|---:|---:|---:|
| 27016adc / contractor | 144834 | 92831 | 73.596 | 52.280 |
| 27016adc / planning_table | 129337 | 99380 | 57.197 | 58.681 |
| 852ce960 / lender_email | 131934 | 98708 | 49.760 | 46.108 |
| 852ce960 / seller_credit | 125347 | 117952 | 61.180 | 59.193 |

| 历史 | 两次后续 token 降幅 | 计入 Delta_save 后净省秒 | 含共同 G 的 F/S tokens | 含共同 G 的 F/S 秒 |
|---|---:|---:|---|---|
| 27016adc | 29.8938% | 19.5935 | 495520 / 413560 | 247.0508 / 227.4572 |
| 852ce960 | 15.7886% | 5.4749 | 518726 / 478105 | 274.2815 / 268.8066 |

N4 两条历史分别达到原门槛，进入 N5 确认。单任务并非时间都下降：planning_table 的 S 慢约
1.485 秒。截止 N4 共 11 次分配、10 次实际模型会话、1423117 tokens（含原有 G/失败）。
逐项回执与总账冻结为运行目录 `n4-results-sealed.json`。

N5 选择唯一的保存确认分支，使用 R 前已固定的 ba358f49、cf22b7bf，见
[C 任务、顺序和审阅标准](MILA_V02_FIDELITY_CONFIRMATION_C.json)。两条历史属于已开放开发集，
不是严格盲留出；本轮未来任务在 C 的 G 前封存。候选、Product pin、Host、模型、阈值不变。
N5 单列阶段额度，原 N4 及失败成本继续纳入 2400000-token 新启动闸门。

## N5 确认、预算终态与资源收尾

两份新普通 G 笔记也无需改动即可成功保存，均为 ABSENT/0→ACTIVE/1，0 模型调用：

| 历史 | G tokens | G 在线秒 | 笔记字节 | Delta_save 秒 |
|---|---:|---:|---:|---:|
| ba358f49 | 241400 | 100.301 | 1737 | 0.086155 |
| cf22b7bf | 258630 | 114.418 | 1885 | 0.087830 |

ba358f49 的四次后续均完成并通过来源、意图/完成状态、时间合计审阅：

| 未来 | F tokens | S tokens | F 在线秒 | S 在线秒 |
|---|---:|---:|---:|---:|
| advisor_email | 125560 | 137938 | 65.190 | 62.716 |
| study_allocation | 137353 | 78259 | 58.617 | 55.301 |

该历史两个后续合计 F=262913、S=216197 tokens，**减少 17.7686%**；计入保存后净省
**5.7035 秒**。含共同 G 的 F/S 路径分别为 504313/457597 tokens、224.1070/218.4035 秒。
该确认历史达到阈值。单任务最大 S/F token 比为 **1.098582**，即 advisor_email 的 S 多用
约 9.9%；不能声称每个任务都节省。N4 最大单任务 S/F token 比为约 0.941。

最后一次合法启动前已知用量为 2264904 tokens，完成该分配后增加 137353，累计
**2402257 tokens**。原规则是达到 2400000 后禁止下一次启动，允许已运行分配越过闸门；
下一项 cf22b7bf/coach_message/S 在预分配检查被 `KNOWN_TOKEN_LAUNCH_GATE` 拒绝，未启动模型、
未占新的模型分配。cf22b7bf 的四次后续均未分配，其质量、完整路径、成本比及净收益均未观察，
不填零。N5 已完成的一条历史通过，但另一条没有结果，不能据此判 N5 通过或失败。

累计 **17/28 次分配、16 次实际模型会话**；N0–N2=0/4、N3–N4=11/12、N5=6/12。
input=2382863、output=19394，总计2402257；cached input=1965056，是 input 子集。
所有启动按原累计闸门重放核验通过；所有分配都有终态，没有未知的已启动 usage。
总原始在线时间为1242.789秒，包含旧的模型执行前失败；四次成功 G 的成本各计一次，
两条未配对的假想未来成本没有填补。旧失败、研究导入/分支初始化/观测开销保留原口径，
Root 工程总耗时和旧首次诊断墙钟仍不完整，不能把它们当成零成本。

最终保留 `COMPLETED_KEEP_BASELINE`：修复输入保真并继续实验是必要的；目前有三条历史的
局部复用收益证据，尚不满足 N5 两条确认历史齐备的合同，也不支持普遍优势或自动维护上线。
没有为补齐样本扩充预算、改用更小模型、裁剪 A0 工具或更改阈值。

最终 Lab 158 项测试、Ruff/mypy/boundary/build 通过；Product 971 项真实 PG 测试和静态/build
结果如上。仅本次 API/worker/PG 停止，14 个本次 Host 容器均已退出，MCP 残留0、认证副本0。
新旧数据库、volume、网络、普通文件和全部失败回执保留；公网未变，无提交或 Schema freeze。
源码/协议、原始回执、N4 冻结结果、N5 分支选择和预算拒绝分别位于本次运行目录，
以 `cleanup.json`、`terminal-results.json` 及机器总账给出最终核验状态。

Lab 最终检查命令为 `uv run pytest -q`、`uv run ruff check src tests tools`、
`uv run mypy src/milai_lab`、`uv run milai-lab-check-boundary`、`uv build`。
N4 汇总在 N5 之后重算仍复现相同历史成本，原冻结回执保持不变；最终总账保留所有17次分配。
Schema 仍为 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
