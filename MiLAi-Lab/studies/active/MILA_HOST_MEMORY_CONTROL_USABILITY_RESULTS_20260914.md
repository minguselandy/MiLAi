# Host Memory 可用性与创新开发结果（2026-09-14）

状态：`COMPLETE`。功能、公开 OM 交接、原生比较与最终检查均完成；
完成时间：2026-09-15 00:36:46（Asia/Shanghai）。

本轮执行[可用性 Goal](MILA_HOST_MEMORY_CONTROL_USABILITY_AND_INNOVATION_GOAL_v1.0_20260914.md)。
实现为 `milai-rwc-v0.3`、`om-sync-port-v0.1`、适配器 `v0.5`，均为 Lab
`RESEARCH_PROTOTYPE`，不是产品记忆行为或上游原样复现。
[使用说明](../../docs/HOST_REVERSIBLE_WORKSPACE.md)提供开始、继续、本地和公开保存/恢复示例；
[紧凑结果与逐角色成本](../../data/results/memory-usability-20260914.json)、
[分配与冻结配置](../../data/manifests/memory-usability-20260914.json)记录原始证据位置。

## 已实现的可用性

Controller 支持稀疏 JSON：`{}` 保持当前工作区/Frame 并 ACT；无变化字段可省略；新卡片由
Host 分配编号，已有卡片省略依赖时保留依赖。合法重复选材去重，ACT 的无关字段忽略；
未知引用、无草稿交付仍整笔拒绝。一次规范化后原子提交，内容无变化不推进 revision，
不再为提交深拷贝整个工作区，复用未变卡片。合并了投影中重复的来源集合/目录计算及重复
调度入口校验，真实来源读取和模型/工具边界仍校验。默认目录优先活动卡片，Actor 可从
既有 retrieve 入口翻页及回读未选/已归档卡片。

WORKSPACE_SIMPLE 与 MILAI_RWC 共用 Actor、Host、字段缺省、容量、来源和工具；N1–N4
只进入候选政策，没有额外语义状态机。局部或整体重建、未证实线索保存、按需回读、有限
交付复核均可用。真实非零业务返回作为反馈继续；未知效果与未知 Provider 用量仍停止。

OM 是独立同步 Host，按实际 tokenizer 触发 Observer/Reflector，分别维护观察覆盖页与
Actor 接收页。只有成功批次退出默认原文；长事件保留准确页范围和遗漏入口。观察组、两项
内联提示、近期原文和真实回读进入 Actor；归并替换日志，保留来源并集。已结算的不可用
维护保留原内容，无重试/修复模型。快照包含方法/政策/配置、完整来源、各位置、提示和全部
角色账务；恢复不发模型、不重放业务动作，新目标清除旧 final/hints。终端显式分派 OM 与
RWC，既有公开压缩/CAS 传输不变；可信旧 RWC v0.2 archive 可迁移，H_ONCE 原算法/入口保留。

历史 16 个 Controller 输出按当时公布目录、卡片和草稿逐条回放：原 7 接受/9 拒绝，变为
7 DIRECT、4 NORMALIZED、5 REJECTED。剩余是2个未知卡片、2个无草稿交付、1个未公布引用。
回放不传播反事实状态，不证明任务正确性；错嵌的路由被忽略并缺省 ACT，不算实现原拟回读。
真实早期 RWC 片段有两条有内容的规范化更新，第一条被 Actor 消费并落实为实现动作，第二条
到达额度边界，尚未消费。空更新接收率不作为创新收益。

## 同题两层比较

三臂使用同一冻结实现、原生 `multi-source-data-merger` 初态、Harbor 0.23.0、
Qwen3.6-35B-A3B-FP8（thinking=false、temperature=0、seed=213）、工具与每臂14次总调用上限。
这是已暴露开发题，不是独立确认集。同一 RWC 轨迹同时参加政策层和方法层比较，只有一个
任务样本。Actor 输出上限4096、Controller/Observer/Reflector 2048、关闭段摘要1024。

| 方法 | 原生 reward / 检查 | 生成 | 输入 tokens | 输出 tokens | 总 tokens | Host final |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| MILAI_RWC | 1 / 3项通过 | 14 | 44,638 | 3,579 | 48,217 | 未提交，额度耗尽 |
| WORKSPACE_SIMPLE | 1 / 3项通过 | 14 | 52,943 | 7,391 | 60,334 | 未提交，额度耗尽 |
| OM_SYNC_PORT | 1 / 3项通过 | 7 | 41,109 | 2,561 | 43,670 | 已提交 |

RWC 为 Actor5/Controller6/摘要3；SIMPLE 为 Actor5/Controller5/摘要4；OM 为 Actor6/Observer1。
RWC Controller 为0 DIRECT/4 NORMALIZED/2 REJECTED，其中2次内容更新、2次 no-op；
SIMPLE 为0/4/1，4次均更新。RWC 最后只回显 delivery_proposal，按缺省 ACT 处理后没有
剩余 Actor 额度；不能用原生 reward 替代交付完成。SIMPLE 修好验证脚本的 KeyError 后，
最后一份摘要用完额度，也未 final。

默认 OM 的阈值是12k/16k tokens、recent2，本题自然触发一次观察，覆盖 goal 和 H001–H003，
后续 Actor 保留 H004/H005 新原文并完成交付。一次 cat Parquet 返回的大量二进制文本贡献
了阈值；其后的 pandas 命令才实际解析数据。提示仍要求检查 Source C，而新原文已有解析
结果，Actor依据新反馈交付，没有机械重复旧提示。真实 Reflector 未触发，归并接线仅由
可控响应验证，不据此报告长期归并质量。

方法层：本题 OM 产物评分打平，交付和调用开销更好。政策层：RWC 比 SIMPLE 少12,117
总 tokens，但两者均未交付，特殊政策的额外作用没有建立。保留 SIMPLE 作为普通工作区
选择、RWC 作为显式研究选项；这不是宣称 SIMPLE 成本胜出，也不把单题 OM 结果推广到
所有长任务。没有本轮同期 H_ONCE 轨迹，不声称 RWC 已超过 H_ONCE。

| 机制 | 实际观察与限制 |
| --- | --- |
| N1 范围修订 | RWC 无自然反证/版本改变机会，普通进度更新不算独立收益。SIMPLE 在实际验证错误后保留产物并局部修脚本，说明此能力非候选独有；Controller 对错误来源的文字归因仍有误。 |
| N2 未证实线索 | RWC 无自然卡片/替代路线保存机会。SIMPLE 保存一张起初含错误字段假设的卡，后续记录纠正但卡未同步纠正；之后类似字段错误再现，不能据此建立因果或正收益。 |
| N3 返回与重新评估 | 两工作区臂均无成功历史回读或阻塞解除后的自然返回机会，OM 也未历史 retrieve。记未观察，不把公开恢复当自主返回。 |
| N4 缺口到行动/交付 | 两工作区臂都实际检查产物，也有无草稿 DELIVER 拒绝和额外核对负担，未展示交付增量。OM 在实际写入/读回后交付；原生验证随后发生，不是模型当时知道的依据。 |

## 失败、资源及上游差异

总上限64，实际56次生成（Actor28、Controller14、摘要8、Observer6、Reflector0），全部结算，
无未知用量；剩余8次关闭。共193,578输入＋22,968输出＝216,546 tokens。无缓存折扣/价格
证据，不报告金额节省。9条原生尝试的累计 trial wall 为609.851秒（包含构建、原生验证），
Host执行累计199.687秒，工具18.124秒；开发与仓库测试耗时单独记录。

| 早期片段 | 生成 / tokens | 结果及修复 |
| --- | ---: | --- |
| RWC live | 6 / 19,255 | 两次真实业务动作；原生验证1，未 final；稀疏记录能推进工作。 |
| OM setup | 0 / 0 | 构造时过早记录事件，目标目录尚不存在；在调用方先创建证据目录。日志初始 method 字段是未构造 Host 的占位值，不是 HiAgent 实验。 |
| OM 初次动作 | 1 / 1,580 | Actor 参数在顶层而非 arguments；补明确例子。 |
| OM envelope | 4 / 16,301 | 观察返回字符串列表，final 又用顶层参数；本地规范化无歧义形式，继续原工具校验。 |
| OM normalized | 5 / 10,912 | goal 观察成功；来源观察回写 raw_pages 导致输出截断，原文保留。该尝试原生 verifier 未形成 reward，保留 RewardFileNotFoundError，不记0分或通过。 |
| OM schema | 5 / 16,277 | 既有维护请求启用约束 JSON；两次观察成功，H001 进入后续 Actor，final及原生验证通过。低阈值/recent1，仅为功能证据。 |

修复使用了原来未启动的诊断/修复额度，并在三臂开始前统一将每臂16改为14，腾出6次用于
OM schema 片段；没有单边追加、未知请求重试或沿用旧 Goal 余额。运行后的源码与冻结清单
一致。原始失败保留在 `/cra/memory/mx_memory/evidence/memory-usability-20260914-2vnovnhb`，
不复制语料、Provider 原始内容或整套环境进入 Git。

Mastra 固定 commit、Apache-2.0许可、关键文件和移植差异统一写在使用说明 OM 部分；
小型原始参照快照在 Git 外 `evidence/om-reference-20260914-b611980c`。本地短政策、固定
近期窗口、来源并集、受约束 JSON（字符上限不等于永不截断）、失败后保留/无自动重试和
Lab checkpoint 都属于显式差异。来源元数据仍随长历史增长，回读也可能与未观察原页重复；
不宣称无限容量。没有部署整个 Mastra，也没有加入新判断器或评分模型。

## 公开交接与最终检查

`public-om` 使用既有独立 product pin 验证后，复用隔离 Runtime/公开 SDK 配置，完成一次
跨 OS 进程 OM 保存和恢复。6次实际 SDK HTTP调用、0错误，9次脚本模型回调、0模型HTTP。
保存/加载的 checkpoint 字节hash一致，观察/提示/完整长来源和新反馈恢复，原文件动作只
执行一次；公开保存完成状态后换新目标，final/hints清空。字符计数 fixture 只验证传输和
生命周期；真实运行使用实际 tokenizer。自有服务已停止，保留原数据；不重测无关方法的
完整 CAS/撤销矩阵，也不顺带声称 H_ONCE 支持该恢复。

40个邻近用例已通过。最终冻结实现的全部交接检查通过：

| 命令 | 结果 |
| --- | --- |
| `uv run milai-lab-check-boundary` | PASS |
| `uv run pytest` | 4,578 passed、1 skipped；4067.87秒（约68分钟） |
| `uv run ruff check src tests tools` | PASS |
| `uv run mypy src/milai_lab` | PASS，45个源文件 |
| `uv build` | sdist 与 wheel 构建成功 |

跳过项为既有可选 Host SDK wheel 检查。开发中类型检查发现的类型标注问题已经修正，
最终源码与原生比较冻结清单一致。没有在通过后重复运行耗时回归。开发至结项约102.8分钟，
其中完整回归约68分钟；这些是开发成本，不混入原生模型成本。

观察“被接收”指协议与页面覆盖提交成功，不保证摘要事实正确。原生运行使用最终冻结
模型政策；较早公开交接检查后只新增维护输出约束/协议兼容和类型、lint修正，公开传输与
checkpoint数据结构没有改变；最终邻近和完整回归覆盖当前恢复代码。
