---
study_id: MILA-ADAPTIVE-MEMORY-DEVELOPMENT-20260915
status: ENGINEERING_COMPLETE_RESEARCH_CLOSED
kind: RESEARCH_PROTOTYPE
method: milai-adaptive-memory-v0.1
terminal_adapter: hiagent-method-adapter-v0.7
product_default: A0_UNCHANGED
---

# Adaptive Memory：开发与真实使用结果

## 当前状态

核心方法、两个 profile、统一修订/读取/交付及显式恢复路径已实现；147 项邻近检查通过。
公开 SDK 跨进程交接已通过。最终全量回归为 4,628 passed / 1 skipped，退出码0。
M0–M3 核心开发验收完成；E1 三臂真实使用与一对 E2 固定输入诊断已收口。

当前决定：**本工作点保留 OM；新版作为功能基线可用，特殊政策收益未成立。**
研究负结果不否定已实现的功能，也不把受控功能检查当作自然任务中的记忆收益。

[完整实验报告](MILA_ADAPTIVE_MEMORY_EXPERIMENT_REPORT_v1.0_20260915.md) ·
[详细 Goal](MILA_ADAPTIVE_MEMORY_DEVELOPMENT_AND_CONTRIBUTION_GOAL_v1.0_20260915.md) ·
[使用说明](../../docs/HOST_REVERSIBLE_WORKSPACE.md) ·
[运行清单](../../data/manifests/adaptive-memory-development-20260915.json)

原始证据：`/cra/memory/mx_memory/evidence/adaptive-memory-development-20260915-wknrheoj`。

## 已完成的功能与验证

- OBSERVE/COMPACT/REVISE/REVIEW 由同一维护角色执行；工作段变化仅登记元数据。
- 当前观察组、卡片、Frame 原子稀疏更新；无变化不推进修订号，无观察正文不移除原文。
- 暂存/焦点分离、暂缓后采用与不采用、依据修订后进入真实 Actor 输入均有功能检查。
- Actor/Controller 共用历史读取，Controller 返回可以跨静止边界保存后续修订。
- 草稿接受/替换/无变化/拒绝/继续、新反馈失效、末次 Actor 结束机会已检查。
- 公开 SDK 在不同 OS 进程保存、恢复并继续；原业务动作每个工程尝试执行一次，恢复不重放。
  修复后的检查共 9 次受控模型回调、0 次模型 HTTP，包含待回读、新反馈和当前记忆修订，
  最终 REVIEWED；已完成稿再次经公开保存恢复到新目标时，保留总调用数并清理旧焦点及复核计数。

第一次公开检查的状态载荷保存与读取成功，但恢复后输入散列不同：公开传输会规范化 JSON 键序，
原投影依赖对象插入顺序。已修复新版消息稳定序列化与目录数字排序，并加入公开规范化回归。
保留 `public-checkpoint/failure.json`；修复后检查及最终冻结源码检查均通过，最终记录见 `public-checkpoint-stable/result.json`。
这属于工程问题，不是方法效果结果；原始来源未丢失。

RWC 只提取共享纯补丁函数，历史调度与方法版本不变。OM 分页机制复用，其调度/政策/载荷保持独立。
产品默认、公开 schema 与 Working State 传输未改。

## E1：三臂完整真实使用

同一个已暴露的 multi-source-data-merger 开发任务，顺序 OM → SIMPLE → CANDIDATE。
模型实际验证为 Qwen3.6-35B-A3B-FP8，窗口65,536，temperature=0、top_p=1、seed=213、thinking=false。
每臂全角色上限32；Actor4096、维护2048，观察12k、归并16k、近期2、页长4000、回读2、复核1。
三臂各自从同一原生任务初态启动；版本/政策/任务散列、隔离检查和完整账务见清单与 Git 外证据。

| 方法 | 原生 reward / 检查 | 调用（Actor＋维护） | 输入 / 输出 tokens | 总 tokens | 结束路径 |
| --- | --- | --- | --- | --- | --- |
| OM_SYNC_PORT v0.1 | 1 / 3项通过 | 3＋0 | 13,200 / 2,221 | 15,421 | 普通 final |
| ADAPTIVE_MEMORY_SIMPLE | 1 / 3项通过 | 3＋1 | 33,087 / 2,542 | 35,629 | UNREVIEWED |
| ADAPTIVE_MEMORY_CANDIDATE | 1 / 3项通过 | 3＋1 | 27,768 / 2,315 | 30,083 | UNREVIEWED |

各臂执行2次业务命令：查看输入，然后生成与运行合并程序；最终都保存了 merged_users.parquet 和
conflicts.json。原生 verifier 的3项检查均通过，异常为空。产物散列见 `final-accounting.json`。

| 方法 | Provider 秒 | 工具秒（含交付） | 环境准备秒 | Agent准备秒 | verifier秒 | 整条轨迹墙钟秒 |
| --- | --- | --- | --- | --- | --- | --- |
| OM_SYNC_PORT | 15.98 | 2.81 | 2.20 | 1.59 | 23.11 | 59.36 |
| ADAPTIVE_MEMORY_SIMPLE | 20.33 | 1.86 | 2.13 | 1.62 | 22.40 | 62.72 |
| ADAPTIVE_MEMORY_CANDIDATE | 18.11 | 1.82 | 1.79 | 1.67 | 23.58 | 60.33 |

这些是不同计时层，不能相加视为互斥成本。费率、缓存计费及 cache tokens 未提供，不估算金额或缓存节省。
Provider 请求全量结算，无未知用量或账务违规；失败的两次 REVIEW 也计入了维护成本。

### 实际记忆—行动联系及缺席机会

本题在维护阈值前结束，三臂均没有形成观察组或观察覆盖。两个 Adaptive 只调用了一次 REVIEW；
其输出均错误地包含非空 observations，但本次没有声明观察/归并批次。接收器原子拒绝补丁，
保存既有状态，按可选复核不可用规则交付仍适用的草稿。没有把这两次拒绝解释为复核批准。
这证明了已结算拒绝后的正常结束路径；**没有出现“修订后的记忆再次影响业务动作”的自然链条**。

两种 Adaptive 的首个 Actor Provider 请求字节相同，特殊维护政策直到最后复核才被调用。
此前不同代码长度、后续输入量以及两臂总 tokens 的差别不能归因于 N1–N4 特殊政策。
与历史 RWC 的32次或历史 OM 的8次也不计算同版本效率倍数。

N1 依据修订、N2 暂存/焦点分离、N3 暂缓后再判断、N4 修订影响动作均已有功能路径检查；
本次自然任务没有检验这些能力的净收益。原生分数为1不认证所有记录准确，更不证明长历史可靠性。

## E2-D1：固定输入的模式提示诊断

**观察：** 两次真实 REVIEW 都把它当成观察整理，补丁因 `OBSERVATIONS_REQUIRE_DECLARED_BATCH` 被拒绝。
**通用修改：** 只在诊断分支的维护系统提示末尾强调先读 mode；REVIEW 对当前草稿作路由决定，
REVISE/REVIEW 无 observations 批次。Actor、来源、输出 schema、接收器和工具合同保持一致。
**预测：** 明确模式后会输出合法稀疏复核/路由，原政策仍重复无批次的观察输出。
**反例：** 原政策也正常复核，或修改后仍拒绝，即不支持这条提示有独立修复作用。

复用候选臂真实 REVIEW 的完整输入，只发一条维护响应/分支；先原政策，再附加提醒。
通过录制的真实回执重建接收状态，核对原政策的 HTTP 请求字节与原实跑完全相同；
没有新增业务动作、后续 Actor 调用或原生评分。

| 分支 | 接收与路由 | 生成 | 输入 / 输出 tokens | 总 tokens |
| --- | --- | --- | --- | --- |
| 原政策完整固定输入 | 合法 DELIVER，无记忆变化 | 1 | 10,911 / 22 | 10,933 |
| 附加模式提醒 | 合法 DELIVER，无记忆变化 | 1 | 11,015 / 22 | 11,037 |

原政策未重现之前的错误；相同请求字节没有保证本次响应相同。两分支无差异，提醒只多104 tokens。
因此不推广该提示，不把它称为实现修复或政策贡献。保留原始两次无效复核，不能用诊断的合法回复
替换先前轨迹，也不把这次局部响应接收写成原生任务成功。

## 研究收口与验收范围

E1 共11次生成、81,133 tokens；E2 共2次、21,970 tokens。本轮合计 **13次生成、103,103 tokens**
（输入95,981、输出7,122），全部结算。共分配98次位置，关闭85次已分配余量；开发包剩余94个
建议位置未分配并关闭。本轮模型发送已结束。公开工程检查和单元测试的受控回调不混作真实模型调用。

三臂同分，OM 在本工作点的调用和完整 tokens 更少；没有有解释的局部增量支持额外迁移或推广。
故保留 OM 在该工作点的使用选择，同时交付新版完整功能基线，保留其后续适用机会问题。
候选相对普通政策、长历史修订/重新采用的净收益均未建立。

第二对 E2、E3完整修订版配对、M4迁移及正式确认/续接未启动；不为补齐可选清单追加运行。
M4任务已在新结果前选为 git-multibranch、constraints-scheduling，仅为开发迁移候选。
没有新增近邻论文查新或独立创新主张；M5未开展正式创新归因，M6未来项不属于首版交付。
旧 RWC v0.4 的80次调用和358,729 tokens 属于已关闭历史额度，未合并或重开。

## 最终代码检查与验收

最终稳定源码通过 boundary、ruff、mypy（46个源文件）和 build；构建 wheel 中的新方法源码
与工作区完全一致。147项邻近测试通过，用时8.98秒。

完整 `uv run pytest`：**4,628 passed / 1 skipped，退出码0，4,004.95秒**。
JUnit包含4,629个不同测试标识，全部取得终态，没有失败或错误。跳过项是可选 Host SDK wheel；
新版公开 SDK HTTP 的真实跨进程检查已单独通过。44条 warning 保留在完整日志中。
最终日志为 `full-pytest-stable.log`，JUnit为 `full-pytest-stable.xml`，身份及散列核对见
`full-regression-acceptance.json`，均在上述 Git 外证据目录。

前两次全量分别在2,389通过/1跳过、1,681通过/1跳过时主动中断，以修复两项相关读取边界：
末次 Actor 请求历史读取时，参数校验提前读正文；超过EOF的空读取若参与修订，会加入不可恢复的
越界空范围。现在参数校验不读取正文，空页只保留EOF元数据，不增加正文披露范围。
新增3个行为测试均通过。两次中断保留原始日志，不累计进最终全量结果，也不称其为完整通过。

E1与E2对应各自冻结源码。上述最终修复发生在E1后，正式政策未改；E1仅使用exec/final，没有
历史读取、观察或修订，未执行这两条改变的行为。没有将历史实跑静默改记成最终源码重跑。
实现、测试及两份源码散列由清单区分；最终实现与政策散列全部核对一致，最终打包与回归结果已登记。

| 核心验收范围 | 对应证据 |
| --- | --- |
| 两个入口、独立调度、观察/归并、结束预留 | `test_adaptive_memory.py` 的 segments、compact、maintenance/closing 用例；Provider与终端适配检查 |
| 当前组/卡片/Frame修订，N1–N4工作能力及真实输入 | revision/recall/reconsidering 双分支、sparse retire/unretire、no-op/coverage 用例 |
| 统一读取、待请求容量、回读后继续及新反馈 | shared ranges、pending request、review recall continuation、EOF/closing read 用例 |
| 草稿接受/替换/继续、预算结束和状态边界 | optional review、draft invalidation、last Actor、unknown/atomic restore 用例 |
| 保存/恢复、同环境继续、公开新进程交接 | `public-checkpoint-stable/result.json`；公开规范化、新目标及来源绑定用例 |
| 可使用入口与工程交付 | 使用说明；147项邻近检查、4,629项全量终态、静态检查和构建 |

上述验收覆盖首版必要能力；研究验收以E1真实轨迹、E2实际执行范围、全成本和关闭决定为依据。
详细 Goal 的核心及研究清单已据此核销，条件性迁移和正式创新确认继续明确记为未启动。
