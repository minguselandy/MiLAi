# HiAgent 依据维护开发与原生任务结果

日期：2026-09-14。执行 [Goal](MILA_HIAGENT_EVIDENCE_MAINTENANCE_DISCOVERY_GOAL_20260914.md)，类型 `RESEARCH_PROTOTYPE`。研究与工程验收均已完成；原生任务未完成，迁移未取得评分。

**结论：`KEEP_SIMPLE_SPECIAL_POLICY_NOT_SUPPORTED`。** H_ONCE 的段内缓存和独立记录维护已实际运行；EVIDENCE_0 与一次修订 EVIDENCE_1 都没有完成原生任务。同维护时机的普通增量摘要与 EVIDENCE_1 原生结果相同、调用数相同，少用 215 tokens。没有证据支持特殊的依据范围修订规则产生额外任务收益。保留 H_ONCE 工程实现和显式研究入口，不将依据维护设为推荐方法或产品默认。

实际启动 **8 次 Harbor 原生尝试：7 条模型轨迹、1 次零模型的保留产物原生补评分**；另外记录了 3 次无模型、无原生评分的环境准备构建。共 **60 次生成、421,083 输入 + 13,528 输出 = 434,611 tokens**，全部结算。一个迁移槽位未启动；迁移环境不可用，不能得出跨 root 或跨领域收益结论。

## 实现与冻结版本

旧 `hiagent-terminal-v0.1` 保留原有每轮摘要行为；其算法模块只扩充内部调用类别以标记维护请求。独立 [evidence_maintenance.py](../../src/milai_lab/methods/evidence_maintenance.py) 提供：

- **H_ONCE / `hiagent-once-v0.1`**：闭合段首次需要展示时摘要；以原始 subgoal、真实 action/observation 对、政策全文和版本计算来源身份，未变则复用。缓存属于当前 Host，不跨 trial。当前段及主动展开段保留详情，已结算空摘要的末次观察回退有明确降级标记。
- **EVIDENCE_0、EVIDENCE_1 / `evidence-maintenance-v0.1`**：每批尚未维护的已完成动作/观察在下一次 Actor 前触发一次独立维护。输入包含独立用户目标、上一记录、新反馈和已发布来源入口；模型生成自由文本。没有新反馈、只重装输入或 retrieve 时不维护，final 后不维护。Actor 同时看到记录、当前段真实详情及主动展开历史；其他旧段只保留编号和子目标，不把旧正文全部附回。
- **INCREMENTAL**：同一 EvidenceHost、相同 Actor、来源、输入组织、维护时机与输出容量，只将维护政策换成普通增量过程/结果摘要。这是本轮选择的一项解释性对照。

维护状态、来源管理和输入装配由 Host 执行，证据语义由同一模型解释；代码没有任务名称、答案关键词、固定步骤数或语义状态图。`changed` 仅记录文本是否变化，不代表语义质量。政策在 [configs/policies/evidence](../../configs/policies/evidence)，共同接口在 [hiagent_terminal_session.py](../../tools/hiagent_terminal_session.py)，真实 Provider 接入在 [hiagent_harbor_agent.py](../../tools/hiagent_harbor_agent.py)。末版接口为 `hiagent-method-adapter-v0.2.1`；各 trial 保存当时源码、政策、配置和 SHA-256，后续修改不覆盖历史快照。

共同模型为现有 `Qwen3.6-35B-A3B-FP8`，实际窗口 65,536，输出容量 4096，temperature 0、top_p 1、seed 213、关闭 thinking。Actor、摘要、维护、检索决策和失败请求共享每轨迹 64 次上限，实际没有额度截断。没有美元费率，未编造美元成本。

REVIEW 保留原有同次决策的可选复核记录及能容纳的历史，H_ONCE 使用闭合段摘要，EVIDENCE 使用当前记录及当前段详情。这是方法层比较，不是三臂逐字相同输入的单变量实验。只有 INCREMENTAL / EVIDENCE_1 的输入组织、Actor 和维护时机相同，维护政策不同。三条 EvidenceHost 轨迹的首个 Actor 载荷 SHA-256 完全相同；每臂单次运行仍不能排除模型输出与服务时序变动。

## 全部尝试与原生结果

任务快照固定为 Terminal-Bench 2 `2fd12b88aafdd04a52c298e3940bcb189f9766d6`，沿用 Harbor 0.23.0、原生任务时限、1 CPU / 2048 MiB / GPU 0。模型轨迹串行、独立容器、同一业务工具权限。`cancel-async-tasks` 是已暴露开发题，政策不加入已知失败检查名称、正确代码或特定中断方式。

| 尝试 | 原生结果 | Actor / 摘要 / 维护 | 输入 tokens | 输出 tokens | 总 tokens |
| --- | --- | ---: | ---: | ---: | ---: |
| 1. cancel-v0 / EVIDENCE_0 | 1 failed, 5 passed in 12.83s | 3 / 0 / 2 | 6,194 | 920 | 7,114 |
| 2. cancel-v0 / H_ONCE | 1 failed, 5 passed in 12.85s | 8 / 6 / 0 | 17,958 | 2,079 | 20,037 |
| 3. cancel-v0 / REVIEW | 评分无效：uv 下载失败 | 29 / 0 / 0 | 382,487 | 8,465 | 390,952 |
| 4. cython-v0 / H_ONCE | 未评分：命令超时 | 1 / 0 / 0 | 989 | 60 | 1,049 |
| 5. cython-v0 / REVIEW | 未评分：人工中止 | 1 / 0 / 0 | 1,185 | 73 | 1,258 |
| 6. cancel-review-rescore / REVIEW_ARTIFACT | 2 failed, 4 passed in 10.87s | 0 / 0 / 0 | 0 | 0 | 0 |
| 7. cancel-revision-control / INCREMENTAL | 1 failed, 5 passed in 12.79s | 3 / 0 / 2 | 6,046 | 947 | 6,993 |
| 8. cancel-revision-control / EVIDENCE_1 | 1 failed, 5 passed in 12.80s | 3 / 0 / 2 | 6,224 | 984 | 7,208 |

所有有效评分的原生 **reward 均为 0**。5/6 或 4/6 是同一任务的子检查结果，不是任务成功率，也不是独立样本。EVIDENCE_0、H_ONCE、INCREMENTAL、EVIDENCE_1 均未通过超出并发上限时的原生取消清理检查；REVIEW 的保留产物还未满足最大并发约束。

第 3 次原始 REVIEW 的 raw reward 为 0，但日志显示 uv 安装失败、`uvx` 缺失，未启动 pytest，故其分数无效。第 6 次在新原生环境中复制该 `run.py` 的原样字节，预装同版 uv 0.9.5 后运行未修改的原生 test.sh 和测试，获得 4/6、reward 0。两份产物 SHA-256 完全一致；没有恢复模型轨迹、修复产物或将其他臂信息交给模型。补评分单独占一个 trial，零模型生成，其环境和 verifier 成本仍归入 REVIEW。

最后两臂共同采用外部 Dockerfile 附加 uv 0.9.5 和兼容 PATH 文件；原始任务文件、测试和评分合同未改，原生安装脚本仍运行。此修复降低评分依赖缺失风险，不能消除下载等待；它与方法政策变化分列，不能把不同 verifier 等待时间算成记忆收益。

完整任务结果按 root 配对：EVIDENCE_0 对 REVIEW、H_ONCE，以及 EVIDENCE_1 对 INCREMENTAL，各为 **0 胜 / 1 平 / 0 负**。只有一个可评分 root，不能跨方法把这三对当三个任务样本。同题 EVIDENCE_0 的总 tokens 比 H_ONCE 少 12,923，比 REVIEW 少 383,838，但都是未完成任务的轨迹，不能据此确认效率提高。EVIDENCE_1 比普通增量摘要多 215 tokens，没有任务或调用数优势。没有同期无缓存 HiAgent，不量化 H_ONCE 相对历史 HiAgent 的实际收益。

## 维护行为与一次政策修订

H_ONCE 形成 7 个模型声明的子目标：6 个闭合段各生成一次摘要，后续共复用 15 次。当前段和闭合段视图按预期切换。未出现摘要回退。这里能确认缓存复用实际发生，不能将“少发了重复请求”扩大成质量不变的因果收益。

EVIDENCE_0、INCREMENTAL、EVIDENCE_1 各有 **3 Actor / 2 维护**；两份非空记录均进入后续两次 Actor 输入。每次维护恰好消费一个新完成反馈，没有 final 后维护、无新回执维护或隐藏补调用。没有真实 retrieve 或返回旧段机会，历史展开只由单元测试验证，不称为本轮实跑恢复能力。记录均有文本更新，不能把更新次数当正确修订次数。

EVIDENCE_0 在成功写入文件后就把实现意图表述为能保证清理。随后自建测试只执行普通并发，记录仍把清理能力当作已具备，Actor 提交。REVIEW 做了 28 条终端动作，包括多次不同的自建检查和代码修订；没有完全相同的重复命令。其最终产物在进入信号量前启动内部任务，实际违反并发约束。因此不能将 REVIEW 的所有额外工作都算作浪费，也不能将候选较早停止直接算作优点。

唯一政策修订的三句记录：**观察到 EVIDENCE_0 将代码描述继承为行为已确认，仅验证普通执行就结束。EVIDENCE_1 要求保留判断的代码描述/实际执行/特定检查依据，并保留缺少相关观察的重要用户要求。接着在同维护时机的 INCREMENTAL 对照中检查，已失败的早期迁移尝试完整保留。** 没有第二次修订，也不为填满额度追加“更仔细”要求。

EVIDENCE_1 的真实记录同时写出了“没有执行专门的取消测试”和“代码结构满足清理要求”，Actor 没有因此补查或改变路线，仍提交。普通增量摘要得到相同原生分数和相同步数。因此本轮不保留“特殊范围修订规则有效”的主张；记录措辞更丰富没有转化为行动收益。

## 迁移缺失与接口失败

首轮后、修订前按原政策冻结迁移顺序 **H_ONCE → REVIEW → EVIDENCE_0**。首选 `query-optimize` 原始环境在下载固定 OEWN 数据库时 curl 28 失败，连接约 129.9 秒后终止；主机来源检查发生重定向但目标连接未完成，镜像站检查也未完成。没有修改数据库、换 pin 或读答案。这次环境准备零模型调用，按预案改用 `build-cython-ext`，不因模型分数换题。

备选原始环境构建成功，但 H_ONCE 的首次指定源码克隆在 60 秒命令时限处超时。Harbor 将异常包装为 RuntimeError，最初运行器只识别特定超时类型，错误地继续启动 REVIEW。发现后发出停止信号，REVIEW 一次生成已结算，原生终态为 CancelledError，第三臂未启动。两容器已删除，确认没有遗留副作用执行后才开展后续工作。此处是不符合原定停发合同的接口缺陷，不能称作干净完成的迁移波次。

修复后任意执行 exception_info 都停止该波；合法的低 reward 仍继续。新增测试覆盖 RuntimeError 包装、原生超时和合法 0 分。另修复失败终端动作耗时未累加的问题；两者均为接口/计时修复，不计入候选政策修订。没有服务重启、GPU 操作、跨进程缓存或新评分平台。

因此 **没有取得迁移评分，EVIDENCE_0 未在备选 root 真正执行维护**。该缺失不支持机制的正面或负面迁移判断；`build-cython-ext` 即使完成也只会是跨 root 工程任务，不能冒充跨领域。未为凑第二来源搭建网络平台或改用事后挑选的获胜任务。

## 完整成本与分配关闭

| 尝试 | Provider 秒 | 工具秒 | 环境 / Agent setup 秒 | Agent 执行秒 | verifier 秒 | trial wall 秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1. EVIDENCE_0 | 7.21 | 1.08 | 3.33 / 1.47 | 8.77 | 24.46 | 50.39 |
| 2. H_ONCE | 15.89 | 2.25 | 1.78 / 1.47 | 19.45 | 24.47 | 59.01 |
| 3. REVIEW | 105.09 | 10.91 | 2.19 / 1.58 | 129.19 | 97.95 | 243.55 |
| 4. H_ONCE | 0.81 | 0.00* | 1.96 / 1.61 | 61.60 | — | 77.06 |
| 5. REVIEW | 0.72 | 14.59 | 2.01 / 1.50 | 15.42 | — | 30.73 |
| 6. REVIEW_ARTIFACT | 0.00 | — | 1.80 / 5.85 | 0.10 | 151.98 | 171.70 |
| 7. INCREMENTAL | 6.84 | 0.75 | 1.79 / 1.52 | 7.95 | 25.64 | 48.80 |
| 8. EVIDENCE_1 | 14.07 | 0.76 | 1.81 / 1.56 | 15.12 | 153.24 | 183.64 |


全部 8 次尝试累计 trial wall 为 864.89 秒，已结算 Provider 等待累计 150.63 秒；其中失败、人工中止与补评分都保留。表中 Provider 秒为已结算请求等待总和；环境、Agent setup、Agent、verifier 取原生阶段时间，trial wall 另含产物导出和清理，不能互相相加。带 * 的原始 0 是失败工具未累计时间的计时缺陷，并非没有等待；该次原生 Agent 阶段 61.60 秒保留了失败成本，命令超时至少约 60 秒。末版代码已补记失败耗时，未覆盖原记录。REVIEW 两次尝试总 wall 包括原评分失败及补评分。

| 生成类别（包含失败尝试） | 次数 | 输入 tokens | 输出 tokens | 合计 tokens |
| --- | ---: | ---: | ---: | ---: |
| Actor | 48 | 409,123 | 12,069 | 421,192 |
| 闭合段摘要 | 6 | 5,055 | 332 | 5,387 |
| 记录维护 | 6 | 6,905 | 1,127 | 8,032 |
| 全部 | 60 | 421,083 | 13,528 | 434,611 |

全部调用分类：**48 Actor、6 摘要、6 维护**。辅助 Provider HTTP 为 7 次 `/v1/models`、60 次 tokenizer；另有 60 次生成 HTTP，共 127 次请求全部返回，生成 ledger 无 pending 或违规。环境包下载属于环境/verifier 阶段，不混为 Provider 调用。

开发成本另外保留：query 原始构建失败、cython 原始构建成功、uv 准备构建与补评分 setup；初版 109 项邻近检查、接口修复 16 项、修订后 29 项、末次计时修复 24 项，包含重叠，不相加冒充独立覆盖。最终全仓回归另外计时。开发代理自身模型 tokens/美元费用没有逐请求计量，不能称这 60 次生成是完整开发模型成本。定稿前另保存 Goal 工具计数器快照：`tokensUsed=472492`、`timeUsedSeconds=5978`，采集于 10:14:20 UTC；该计数不是 Provider 逐请求账单，不与实验 tokens 混算。全部原始构建和测试日志见证据目录。

规划上界 12 trials / 768 次生成；实际先分配 3 条，再分配迁移 3 条、补评分 1 条和最后对照 2 条，总计分配 9 个槽位 / 512 次生成。启动 8 次尝试，迁移中的一个槽位关闭未启动；另 3 个规划槽位从未分配。已分配但未使用的 452 次及未分配的 256 次生成全部关闭，合计 **708 次余额关闭**。旧 Goal 额度从未转入。本轮所有模型、trial 及补评分进程退出，所有 8 个自有容器删除，自有准备镜像标签移除；全仓回归进程亦已退出。

## 保留与交付

保留 H_ONCE 的 trial 内复用、真实反馈后的维护调用时机、原始反馈直达 Actor、可显式回读的历史以及统一用量账务。保留 EVIDENCE_0/1 与 INCREMENTAL 的可执行显式入口和冻结政策，便于复现与诊断；不把 EVIDENCE_1 作为推荐升级，不将特殊依据修订规则推广为有效机制。没有产品默认、公开产品 Schema 或 canonical 数据改变。

工程验收完成：边界、ruff、mypy（42 源文件）与构建通过。唯一一次全仓 pytest 以 exit 0 结束，**4497 PASS / 1 SKIP / 0 FAIL / 0 ERROR**，44 条警告，耗时 **4021.24 秒（67 分钟）**。唯一跳过为可选 Host SDK wheel。JUnit 与本轮收集的 4498 项身份完全对应，无缺项、重复计数或借用历史通过；最终源码哈希与回归启动时一致。详见 [regression-final.json](/cra/memory/mx_memory/evidence/hiagent-evidence-discovery-20260914-jAPC0Z/regression-final.json)、[checks-final.json](/cra/memory/mx_memory/evidence/hiagent-evidence-discovery-20260914-jAPC0Z/checks-final.json)；定稿交付包另记于 delivery-build.json。

紧凑清单：[manifest](../../data/manifests/hiagent-evidence-discovery-20260914.json)。原始证据：[evidence root](/cra/memory/mx_memory/evidence/hiagent-evidence-discovery-20260914-jAPC0Z)，其中 [summary.json](/cra/memory/mx_memory/evidence/hiagent-evidence-discovery-20260914-jAPC0Z/summary.json) 提供逐类 tokens、时间和产物哈希，[research-close-audit.json](/cra/memory/mx_memory/evidence/hiagent-evidence-discovery-20260914-jAPC0Z/research-close-audit.json) 保留关闭、补评分一致性及计时限制，[final-code-freeze.json](/cra/memory/mx_memory/evidence/hiagent-evidence-discovery-20260914-jAPC0Z/final-code-freeze.json) 保存末版源码身份。`summarize.py` 只离线读取证据，不调用模型。
