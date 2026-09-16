---
report_id: MILA-ADAPTIVE-MEMORY-EXPERIMENT-REPORT-01
version: "1.0"
date: "2026-09-15"
report_status: FINAL
experiment_status: ENGINEERING_COMPLETE_RESEARCH_CLOSED
kind: RESEARCH_PROTOTYPE
method: milai-adaptive-memory-v0.1
terminal_adapter: hiagent-method-adapter-v0.7
task: multi-source-data-merger
task_role: EXPOSED_DEVELOPMENT_TASK
decision: KEEP_OM_AT_THIS_WORKPOINT / SPECIAL_POLICY_BENEFIT_NOT_ESTABLISHED
experiment_generations: 13
experiment_input_tokens: 95981
experiment_output_tokens: 7122
experiment_total_tokens: 103103
report_generation_model_allocation: 0
report_generation_experiment_calls: 0
product_default: A0_UNCHANGED
public_schema: UNCHANGED
---

# MiLAi Adaptive Memory v0.1 实验报告

**报告范围：首版 M0–M3 功能开发、E1 三臂原生使用、E2-D1 一对固定输入诊断，以及最终工程验收。**

本报告整理已经结束的实验，不启动新实验。执行与验收依据为[完整 Goal][goal]、[开发结果][results]及[运行清单][manifest]；报告新增了按角色的成本分解、自然机制机会分析和耗时口径核对。原始结果、失败记录及关闭额度保持原样。

## 1. 摘要与主要结论

Adaptive Memory v0.1 已完成首版核心功能：观察与归并、当前记忆修订、Frame 与选材、Actor／Controller 回读、按需控制、可选交付复核和公开保存恢复。两个政策配置共用同一方法实现。最终工程验收为 **4,628 passed / 1 skipped**，公开 SDK 跨进程检查、静态检查和构建通过。

在已暴露的 `multi-source-data-merger` 任务上，OM、Adaptive SIMPLE、Adaptive CANDIDATE 三臂均获得原生 reward 1，各通过全部 3 项检查；分别使用 **3／4／4 次生成**及 **15,421／35,629／30,083 tokens**。在这个工作点，OM 以更少生成和更少 tokens 达到相同原生完成度，继续保留 OM 的使用选择。

本题在观察维护阈值前结束。三臂均未形成观察组，两个 Adaptive 只进行了最终 REVIEW；两次 REVIEW 均因在没有声明批次时输出观察正文而被拒绝，随后按已有规则交付有效草稿。因此，本轮真实使用支持正常执行与复核不可用时的结束能力，**没有形成“记忆修订后再次影响业务动作”的自然轨迹**。

一对局部诊断比较原提示与附加模式提醒，两者均返回相同合法 DELIVER。新增提醒仅多用 104 tokens，没有显示增量，未被推广。整个实验共 **13 次真实生成、103,103 tokens，全部结算，已分配余量关闭**。

当前结论分为三个层次：

- **工程结论：** 首版完整功能基线可用，M0–M3 验收完成。
- **方法结论：** 本任务支持保留 OM；Adaptive 本轮成本更高。
- **贡献结论：** 特殊政策收益未建立；自然记忆修订、跨任务迁移及正式创新确认尚无本轮证据。

## 2. 研究背景与问题

此前 RWC v0.4 的同题开发中，SIMPLE 和 RWC 都将大量生成用于 Controller 与段摘要；RWC 用满 32 次仍未完成。新的[总设计][master]据此将任务执行、历史整理和按需控制分开组织，同时保留完整工作区能力。

首版遵循“先完成功能，再依据真实使用优化”的开发顺序。观察、修订、返回和复核都已实现；不要求短任务为了证明架构存在而强制触发这些能力。本轮回答以下问题：

| 问题 | 本轮依据 | 能回答的范围 |
| --- | --- | --- |
| RQ1：完整功能是否可运行和交接？ | 邻近行为检查、公开 SDK 跨进程检查、最终全量回归 | 首版工程完整性及相应边界 |
| RQ2：新方法能否正常完成原生任务，代价如何？ | E1 同一初态的三臂独立完整运行 | 该工作点的交付、原生质量与完整成本 |
| RQ3：特殊政策是否产生独立价值？ | E1 实际介入位置、E2-D1 固定输入诊断 | 本轮是否存在可解释的局部增量，不能替代泛化确认 |

历史 RWC 的 80 次生成和 358,729 tokens 属于另一轮已关闭实验，不计入本报告总账。历史版本的 32 次或 OM 的 8 次也不用于计算本轮的同版本效率提升。

## 3. 方法与比较对象

| 方法 | 实现及维护方式 | 在本轮的作用 |
| --- | --- | --- |
| OM_SYNC_PORT | `om-sync-port-v0.1`；独立阈值观察、日志归并、近期原文与来源回读 | 外部方法的本地移植对照，保留自身算法 |
| ADAPTIVE_MEMORY_SIMPLE | `milai-adaptive-memory-v0.1`；普通维护政策 | 与候选同结构的政策对照 |
| ADAPTIVE_MEMORY_CANDIDATE | 相同 v0.1；候选维护政策包含 N1–N4 工作规则 | 检查特殊维护政策的作用 |

两个 Adaptive 共用 Host、Actor、来源能力、调度、输入投影、预算、读取与复核合同，仅维护政策不同。维护角色提供 OBSERVE／COMPACT／REVISE／REVIEW 四种用途，支持 ACT／RECALL／DELIVER；并不要求每次 Actor 前都维护。

新方法发布一份当前 MemoryView，包括观察组、短工作记录、Frame、相关卡片、新反馈、原始页及有界目录。Actor 已接收范围、成功观察覆盖及维护尝试身份独立记录。没有观察正文或更新被拒绝时，不将原文标为已整理。

完整功能和使用接口详见[使用说明][guide]。所有结论均属于 Lab `RESEARCH_PROTOTYPE`；产品默认保持 A0，公开 Schema 与 Working State 传输未改变。

## 4. E1 实验设置

### 4.1 任务与评价

任务要求合并 JSON、CSV、Parquet 三类用户数据，统一字段，按来源优先级处理冲突，输出 `merged_users.parquet` 与 `conflicts.json`。该任务已进入此前开发和诊断，属于**已暴露开发题**。

采用 Terminal-Bench 2 的原生任务和 verifier，固定来源 commit：

```text
2fd12b88aafdd04a52c298e3940bcb189f9766d6
```

Harbor 为 0.23.0；使用任务 Dockerfile 本地重建的独立 CPU 环境，串行运行。网络覆盖配置、任务文件与输入数据散列保存于[冻结设置][allocation]。该设置不称为官方预构建镜像排行榜复现。

原生 verifier 的三项检查分别为输出文件存在、合并数据精确值、冲突报告值。三项是同一任务内的检查，不能计为三个独立任务样本。

### 4.2 模型、资源与顺序

| 配置项 | 实际设置 |
| --- | --- |
| 模型 | Qwen3.6-35B-A3B-FP8；Provider 记录的模型服务为 vLLM |
| 上下文窗口 | 65,536 tokens |
| 解码 | temperature=0、top_p=1、seed=213、thinking=false |
| 每臂生成上限 | 32 次，所有实际角色和失败调用合计 |
| Actor 输出上限 | 4,096 tokens |
| 维护输出上限 | 2,048 tokens |
| 观察／归并阈值 | 12,000／16,000 tokens |
| 近期原文与分页 | 最近 2 个事件；默认 4,000 字符 |
| Adaptive 回读扩展 | 上限 2 次 |
| Adaptive 可选复核 | 每目标上限 1 次 |
| 原生 Agent／verifier 时限 | 各 900 秒 |
| 方法顺序 | OM → Adaptive SIMPLE → Adaptive CANDIDATE |
| 业务环境 | 同一原生初态，各臂独立环境，concurrency=1 |

方法各自选择上下文、维护时机和动作；不要求三臂发送相同输入。两个 Adaptive 的共同 Actor 与机械能力一致，用于限制政策比较中的结构混杂。单次固定顺序没有消除服务波动或顺序效应。

### 4.3 版本归属

E1 使用自己的冻结源码；最终工程验收前又修复了两项历史读取边界，方法名仍为 v0.1，但源码散列不同：

| `adaptive_memory.py` 所属阶段 | SHA-256 |
| --- | --- |
| E1 冻结源码 | `99d3af971394843fc5045f5b0a92356cf9e1ba2a49924e4124b136be37e6fc8b` |
| 最终工程验收源码 | `dd6d77e377c80811a1e4aae208813c9526d041d4f5b81e108d58886ab2fb581e` |

最终变更涉及“参数校验不读取正文”和“超过 EOF 的空读取不生成正文披露范围”。E1 只有 exec／final，没有触及这些读取行为；正式政策未变。**E1 成绩仍归于 E1 冻结源码，最终回归归于最终源码，不声称最终源码重新完成了实跑。** 完整映射见[运行清单][manifest]与[源码验收记录][source-acceptance]。

## 5. E1 主结果

### 5.1 原生质量、交付与完整 tokens

| 方法 | Reward | 原生检查 | Actor | 维护 | 总生成 | 输入 tokens | 输出 tokens | 总 tokens | 交付路径 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| OM | 1 | 3/3 | 3 | 0 | 3 | 13,200 | 2,221 | 15,421 | 普通 final |
| Adaptive SIMPLE | 1 | 3/3 | 3 | 1 | 4 | 33,087 | 2,542 | 35,629 | UNREVIEWED |
| Adaptive CANDIDATE | 1 | 3/3 | 3 | 1 | 4 | 27,768 | 2,315 | 30,083 | UNREVIEWED |
| **E1 合计** | — | 3 条同题轨迹 | **9** | **2** | **11** | **74,055** | **7,078** | **81,133** | — |

三臂各执行 2 次业务命令：查看输入，然后生成并运行合并程序；第三次 Actor 形成最终答复。均产出要求的两个文件，原生结果无异常。两个 Adaptive 的两份业务产物分别具有相同散列；OM 产物散列不同，但同样通过全部原生检查。[原始结算][accounting]

这里的 UNREVIEWED 表示没有合法内部复核批准，不表示任务失败。原生 reward 1 只确认本次产物通过该任务的既定检查，不扩展为任意输入下均正确。

### 5.2 按角色分解成本

下表由 11 条 E1 已结算生成记录重新汇总。维护列在本题全部为 REVIEW，观察、归并、主动修订与回读决策均未调用。[Provider 账单][ledger]

| 方法 | Actor tokens | REVIEW tokens | REVIEW 占本臂 tokens | 比 OM 多用 tokens |
| --- | ---: | ---: | ---: | ---: |
| OM | 15,421 | 0 | 0.00% | 0 |
| Adaptive SIMPLE | 22,017 | 13,612 | 38.20% | 20,208 |
| Adaptive CANDIDATE | 18,989 | 11,094 | 36.88% | 14,662 |

SIMPLE 与 CANDIDATE 的完整 tokens 分别比 OM 多 **131.04%** 与 **95.08%**。这是同一工作点、相同原生完成度下的实测差异，不是总体效率倍数。

额外成本包含两部分：Actor 阶段分别比 OM 多 6,596／3,568 tokens，以及最终复核的 13,612／11,094 tokens。两种 Adaptive 首次 Actor 的输入各为 2,758 tokens，OM 为 1,565 tokens；说明共同方法输入本身已有开销。具体应优化哪些提示、目录或投影内容，需要另外按实际发送内容分析，不能把 Actor 成本差全归于某个单一字段。

这只是已发生轨迹的账务分解。它不代表关闭复核后模型必然生成同一轨迹，也不将较少字符直接换算为缓存命中或价格节省。

### 5.3 为什么候选比 SIMPLE 少用 tokens 不构成政策收益

CANDIDATE 比 SIMPLE 少 5,546 tokens，即 15.57%。但两种方法的前两次 Actor Provider 请求分别逐字节相同，第二次响应开始出现长度差异；特殊维护政策直到最终 REVIEW 才运行。

因此，维护政策尚未介入时发生的代码、返回和输入长度差异不能归功于 N1–N4。最终两次复核都没有产生合法补丁，整个过程也没有提供“候选记录使 Actor 少做工作”的链条。该 token 差异保留为事实，不升级为特殊政策效果。

### 5.4 时间结果

单位：秒。

| 方法 | Provider | 工具，含交付 | 环境准备 | Agent 准备 | Verifier | 整条轨迹墙钟 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| OM | 15.98 | 2.81 | 2.20 | 1.59 | 23.11 | 59.36 |
| Adaptive SIMPLE | 20.33 | 1.86 | 2.13 | 1.62 | 22.40 | 62.72 |
| Adaptive CANDIDATE | 18.11 | 1.82 | 1.79 | 1.67 | 23.58 | 60.33 |

这些数值来自不同计时层，不能直接相加为互斥时间。单次运行的墙钟差很小，且受准备、校验和服务波动影响，不作稳定延迟优势主张。未提供费率、cache tokens 或缓存计费记录，不估算金额。

## 6. 实际维护过程与机制机会

### 6.1 本轮调用结构

```text
OM：
Actor 查看输入 → Actor 生成并运行程序 → Actor final

Adaptive SIMPLE / CANDIDATE：
Actor 查看输入 → Actor 生成并运行程序 → Actor final 草稿
    → REVIEW 输出非空 observations，但没有声明观察批次
    → 原子拒绝补丁 → 原状态保留 → 当前草稿 UNREVIEWED 交付
```

| 自然运行中的维护活动 | OM | SIMPLE | CANDIDATE |
| --- | ---: | ---: | ---: |
| Observer／OBSERVE | 0 | 0 | 0 |
| Reflector／COMPACT | 0 | 0 | 0 |
| REVISE | — | 0 | 0 |
| REVIEW | — | 1 | 1 |
| 最终观察组 | 0 | 0 | 0 |
| 已观察覆盖页 | 0 | 0 | 0 |

短任务未达到阈值是方法允许的正常运行状态。不能为了展示维护功能事后降低阈值，再将强制触发的结果混入本轮自然使用成绩。

### 6.2 两次无效复核

两个 Adaptive 的真实 REVIEW 都输出了任务摘要式 `observations`，附带 `working_note: null`，没有合法交付路由。本次模式没有声明观察／归并批次，接收器返回：

```text
ADAPTIVE_PATCH_REJECTED
mode: REVIEW
reason: OBSERVATIONS_REQUIRE_DECLARED_BATCH
```

原始提议完整保留；Host 未部分提交，也未把拒绝当成确认正确。在原草稿仍适用的条件下，沿可选复核不可用路径交付。

这支持“复核失败不阻断当前有效答复”的运行结论，也暴露了复核模式的使用负担。两次样本不足以估计可靠的格式失败率，更不能据此认定所有维护模式都存在相同问题。

### 6.3 N1–N4 的证据分层

| 候选能力 | 首版功能检查覆盖 | 本次自然任务提供的证据 |
| --- | --- | --- |
| N1：依据及适用范围修订 | 观察／卡片更新、保留未改变内容、当前修订进入 Actor 输入 | 没有自然发生的成功修订与再使用 |
| N2：联想、焦点与采信分离 | 暂存、目录、选择、退役及重新采用 | 没有需要比较暂存或焦点切换的有效链条 |
| N3：可逆再判断 | 真实范围回读、暂停后采用／不采用、控制续接 | E1 未发生历史回读或路线返回 |
| N4：未决项影响行动与交付 | 草稿接受、修订、继续、失效及预算尾部处理 | 自然观察到复核被拒后的正常交付；未观察到特殊规则改善业务动作 |

因此，本题检验了可用性和低维护需求场景中的负担，未有效激活主要记忆贡献问题。它支持本工作点保留 OM，同时保留“完整功能在其他适用任务是否有用”这一未回答问题。

## 7. E2-D1：固定输入模式提醒诊断

### 7.1 设计与执行范围

针对两次 REVIEW 输出模式不匹配，选取候选臂真实 REVIEW 的完整输入，比较原维护提示与附加一段通用模式提醒。提醒要求先识别 mode，REVIEW 对当前草稿作路由处理，REVISE／REVIEW 没有 observations 批次。

Actor、来源、输出 schema、接收器和工具合同保持不变。每分支仅生成一次维护回复，用录制的真实回执重建接收状态；没有新增业务动作、后续 Actor 或原生评分。原提示分支请求与原实跑请求的字节一致性由执行记录确认。[局部结果][diagnostic] [原始结算][accounting]

预期是新增提醒产生合法复核、原提示重现无批次观察。若原提示也正常，或提醒后仍失败，就不能支持新增提醒的独立修复作用。

### 7.2 结果

| 分支 | 接收结果 | 记忆变化 | 生成 | 输入 tokens | 输出 tokens | 总 tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| FROZEN_BASELINE | 合法 DELIVER | 无 | 1 | 10,911 | 22 | 10,933 |
| MODE_FIRST_REMINDER | 合法 DELIVER | 无 | 1 | 11,015 | 22 | 11,037 |
| **E2 合计** | — | — | **2** | **21,926** | **44** | **21,970** |

两分支均输出：

```json
{"dispatch":{"kind":"DELIVER"}}
```

原提示未重现此前错误；同一请求字节没有保证相同响应，记录不足以确定具体原因。不能把 temperature=0 或相同 seed 当作结果逐次一致的证书。

新增提醒没有产生可区分行为，仅增加 104 tokens。保持原正式政策，不推广提醒；不把两条局部合法响应替换进原轨迹，也不填原生成功分。该诊断不证明提醒永远无效，只说明本次没有支持采用它的证据。

## 8. 工程验证、失败与修复

### 8.1 最终工程结果

| 检查 | 最终结果 | 范围与说明 |
| --- | --- | --- |
| 邻近测试 | 147 passed，8.98 秒 | 新方法、共享补丁、OM、Provider、读取与 checkpoint 等受影响路径 |
| 全量回归 | 4,628 passed / 1 skipped，退出码 0 | 4,629 个唯一测试标识全部有终态；无失败或错误 |
| 公开 SDK 交接 | PASS | 不同 OS 进程保存、恢复并继续，PUBLIC_SDK_HTTP |
| Boundary／ruff／mypy | PASS | mypy 覆盖 46 个源文件 |
| Build | PASS | wheel 内新方法源码与最终验收源码一致 |

全量耗时为 4,004.95 秒，约 66.75 分钟。唯一跳过项是可选 Host SDK wheel 检查；新版公开 SDK HTTP 跨进程验证单独通过。44 条 warning 保留在原日志中。邻近通过数不加入全量通过数。[全量验收记录][regression]

### 8.2 公开保存恢复

首个公开尝试成功保存并读取状态载荷，但恢复后的模型输入散列与保存前不同。原因是公开传输规范化 JSON 键序，而原投影依赖对象插入顺序。修复采用稳定消息序列化及目录数字排序，补充公开规范化回归；原始失败文件保留。

修复后的工程检查共使用 9 次受控模型回调、0 次模型生成 HTTP，覆盖待回读、新反馈、当前记忆修订及最终 REVIEWED。完成稿再次保存恢复到新目标时，累计调用数保留，旧焦点和目标复核次数正确清理。最终冻结源码的公开检查亦通过。[公开检查结果][public-result]

这些是实际 SDK／HTTP／进程交接上的功能验证，模型响应由受控回调提供；不计入 13 次真实模型生成，不作为自然续接记忆收益。

### 8.3 两次中断回归及最终修复

| 全量尝试 | 中止／完成时结果 | 已记录耗时 | 原因或终态 |
| --- | --- | ---: | --- |
| 第一次 | 2,389 passed / 1 skipped，中断 | 1,007.66 秒 | 修复末次 Actor 的读取参数校验提前读取正文 |
| 第二次 | 1,681 passed / 1 skipped，中断 | 121.73 秒 | 修复超过 EOF 空结果形成不可恢复披露范围 |
| 最终稳定版 | 4,628 passed / 1 skipped，完整结束 | 4,004.95 秒 | 新增 3 个相关行为检查后，最终退出码 0 |

两次中断保留日志，不计作完整通过，也不累加到最终 4,628。三个已记录回归区间合计 5,134.34 秒，约 85.57 分钟；这是回归执行时间合计，不等于整个项目的互斥工时拆分。

这些修复涉及真实读取与披露范围的工程边界，不能作为 N1–N4 政策贡献。源码与实跑归属依 §4.3 分开登记。

## 9. 总账、额度关闭与时间口径

### 9.1 真实模型总账

| 阶段 | 真实生成 | 输入 tokens | 输出 tokens | 总 tokens |
| --- | ---: | ---: | ---: | ---: |
| E1 三臂完整使用 | 11 | 74,055 | 7,078 | 81,133 |
| E2-D1 两个维护响应 | 2 | 21,926 | 44 | 21,970 |
| **本轮实验合计** | **13** | **95,981** | **7,122** | **103,103** |

按角色合计为 9 次 Actor、4 次维护生成；其中 2 次维护属于 E1 REVIEW，另 2 次属于 E2 固定输入诊断。已结算的无效 REVIEW 同样计入调用与 tokens；pending usage 与 accounting violations 均为空。[原始结算][accounting]

生成次数不等于所有 HTTP 请求数。模型信息查询、tokenizer 请求和公开 SDK 存取不混作模型生成；它们的实际请求和工程成本仍由对应日志保留。

### 9.2 额度收口

| 项目 | 数量／状态 |
| --- | --- |
| 实际分配 | 98 个生成位置：E1 96，E2 本次 2 |
| 实际使用 | 13 |
| 已分配未使用 | 85，已关闭 |
| 192 次开发建议包中未分配位置 | 94，未分配并关闭 |
| 第二对 E2、E3 改进版完整配对 | 未启动 |
| M4 迁移、真实模型续接 | 未分配／未启动 |
| 正式创新确认 | 未启动 |
| 后续模型发送 | 已结束 |

实际分配、未分配建议和条件包分别记录。旧轮余额没有转入本轮；本报告不重新开放任何位置。

### 9.3 总耗时的两个来源

| 来源 | 时间口径 |
| --- | --- |
| 用户执行更新 | 总耗时约 2 小时 4 分钟 |
| manifest 的 started_at → completed_at | 北京时间 2026-09-15 12:09:50.851 → 14:08:17.393；约 1 小时 58 分 26.54 秒 |

二者覆盖边界尚未被统一记录，本报告分别保留。登记区间外是否包含准备、文档整理或其他工作，现有记录不能精确拆分，不补造时间。方法比较采用 §5.4 的各臂实际时间，不用整体开发耗时评价模型求解速度。

## 10. 结论强度与局限

| 观察 | 支持的结论 | 不能推出的结论 |
| --- | --- | --- |
| 完整测试与公开交接通过 | 首版核心功能和相应工程边界完成验收 | 自然记忆收益、产品化或广泛可靠性已证实 |
| 三臂 reward 均为 1 | 三条轨迹在这一原生任务上完成 | 总体成功率为 100%，或覆盖三个独立任务 |
| OM 成本更低 | 本工作点保留 OM | OM 在所有长历史或变化任务上更优 |
| Adaptive 两次复核被拒后交付 | 可选复核不可用时仍能交付当前有效稿 | 复核已正确批准，或复核功能应立即删除 |
| 没有 OBSERVE／COMPACT／REVISE | 本题未检验自然整理和修订再使用 | N1–N4 已得到干净负面检验 |
| 候选总 tokens 少于 SIMPLE | 保留实测差异 | 在政策介入前形成的差异来自特殊维护规则 |
| E2 两分支回复相同 | 本次不支持推广新增模式提醒 | 提醒永远无效、确定性根因已被定位 |
| E1 后修复读取边界 | 最终工程状态更完整，E1 冻结轨迹仍保留 | 最终源码已重新完成全部真实实验 |

本轮没有多任务、多种子重复或正式确认样本，不报告统计显著性或泛化成功率。没有自然历史依赖机会时，功能单测可以验证实现，却不能代替语义效果证据。

## 11. 研究决定与后续方向

维持本轮正式决定：

```text
ENGINEERING_COMPLETE_RESEARCH_CLOSED
KEEP_OM_AT_THIS_WORKPOINT
ADAPTIVE_FUNCTIONAL_BASELINE_AVAILABLE
SPECIAL_POLICY_BENEFIT_NOT_ESTABLISHED
```

首版完整能力继续保留。后续在完整版本上优化实际使用负担，不能因为本次短任务没有用到某项能力就追溯性裁掉首版验收范围。

有后续执行范围时，优先处理两个问题：一是复核模式的输入／输出负担及维护为何产生不适用字段；二是在具有真实跨步依赖的任务中，观察记忆修订是否改变选材、行动或交付。两者分别对应工程可用性与记忆贡献，不混成同一胜负。

`git-multibranch`、`constraints-scheduling` 已在新结果前选为开发迁移候选，但未运行，也不称为独立确认来源。后续局部代码优化先做受影响检查，稳定交付时集中全量；无需为本报告生成或纯政策讨论重跑长回归。

以上是结果导出的方向，不是新增实验安排。本报告不扩建架构、不新建评测平台、不追加模型调用，也不新增外部查新或正式创新主张。

## 12. 证据索引与本次报告核对范围

原始证据根目录：

```text
/cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj
```

| 资料 | 用途 |
| --- | --- |
| [完整 Goal][goal]、[总设计][master] | 实现目标、完整功能优先及实验边界 |
| [开发与验收结果][results]、[使用说明][guide] | 执行叙述、功能映射、当前接口 |
| [运行 manifest][manifest] | 版本、里程碑、实验设置、成本、关闭状态和证据路径 |
| [E1 冻结设置][allocation] | 任务 commit、数据与环境散列、资源上限和方法顺序 |
| [最终实验结算][accounting]、[E1 Provider 账单][ledger] | 总账、逐次生成和按角色分解 |
| [E1 原生试验目录][trials] | 三臂 verifier CTRF、reward、业务产物及日志 |
| [E2-D1 原始结果][diagnostic] | 两分支原始回复、接收结果、零业务动作及无原生评分 |
| [公开 SDK 最终检查][public-result] | 跨进程、公开传输、产品 pin 和受控模型边界 |
| [全量回归验收][regression] | 唯一测试身份、通过／跳过、退出码及日志散列 |
| [最终源码验收][source-acceptance] | 最终源码与 E1 冻结源码的归属，以及公开尝试清理记录 |

报告编制时重新核对了三臂原生检查摘要、11 条 E1 已结算生成账、E2 两分支结果、两次无效 REVIEW 正文，以及两种 Adaptive 前两次 Actor 请求的逐字节一致性；重新读取 JUnit，确认 4,629 个唯一测试标识、4,628 通过、1 跳过且无失败／错误，JUnit 散列与验收一致。清单中的 12 项最终实现／政策／测试文件散列与当前文件一致。

本次属于对已有证据的只读核对与文档生成，未重新执行业务动作、模型请求、公开恢复或工程测试。没有声称逐条重新验证所有程序逻辑或全部历史轨迹。原始 Provider 内容、任务数据和运行产物继续保存在 Git 外；本文件只保存紧凑结果、分析和证据入口。

[goal]: MILA_ADAPTIVE_MEMORY_DEVELOPMENT_AND_CONTRIBUTION_GOAL_v1.0_20260915.md
[master]: ../../docs/MILA_ADAPTIVE_MEMORY_MASTER_DESIGN_AND_ROADMAP_v1.0_20260915.md
[results]: MILA_ADAPTIVE_MEMORY_DEVELOPMENT_RESULTS_20260915.md
[guide]: ../../docs/HOST_REVERSIBLE_WORKSPACE.md
[manifest]: ../../data/manifests/adaptive-memory-development-20260915.json
[allocation]: /cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj/e1-native/allocation.json
[accounting]: /cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj/final-accounting.json
[ledger]: /cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj/e1-native/provider/provider-ledger.jsonl
[trials]: /cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj/e1-native/trials
[diagnostic]: /cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj/e2-d1/results.json
[public-result]: /cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj/public-checkpoint-stable/result.json
[regression]: /cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj/full-regression-acceptance.json
[source-acceptance]: /cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj/final-source-acceptance.json
