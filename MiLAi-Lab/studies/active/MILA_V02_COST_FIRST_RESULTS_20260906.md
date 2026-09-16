---
document_id: MILA-V02-04-RESULTS
date: "2026-09-06"
status: COMPLETED_NON_MODEL_INCREMENT
C0: AUDIT_COMPLETE
C1: READABLE_ENVIRONMENT_VERIFIED
C2: COST_CONTROL_REVIEW_COMPLETE_NO_GO_FOR_PAID_PILOT
C3: NOT_ENTERED
new_experimental_model_allocations: 0
new_experimental_model_tokens: 0
---

# 单任务成本审计与读取环境修复

已执行当前 Goal v0.2 的 C0–C2 零新增实验模型增量：重算历史成本，修复实际容器读取能力，
完成无模型验证和绝对成本控制审查。**24 条原先失败的命令全部重放成功；12 份历史经有界
分页后逐字节还原。** 这证明工具链修复成立，尚未测得修复后的 Host token/时延收益。
现有控制无法核验为单任务累计 raw tokens 的硬上限，因此 C3 不进入，也不请求一笔新的
大额预算。旧 N5 仍不完整；原总账及240万启动闸门不变。

执行授权来自用户要求详细阅读并执行 Goal；它覆盖本次非模型工程增量，不取消 Goal 内
明确的零新增实验预算及 C3 的前置条件。没有启动实验 Host/Provider、MCP、Runtime 或 PG。
Docker 构建和12个断网 smoke 容器不属于模型分配；执行者开发和本次对话并非免费。

## C0：复核成本和可观察输入

`uv run python tools/audit_v02_task_cost.py` 从冻结总账和每会话实际 events 重算，使用
`item.completed / command_execution`，未把 started/completed 双算。16个实际会话 usage
与总账逐项相等，原17个分配（含模型前失败）保留。

| 组 | 会话 | raw tokens 总量 | 每任务平均 raw tokens | 平均非缓存 input | 平均 output | 平均在线秒 |
|---|---:|---:|---:|---:|---:|---:|
| G | 4 | 982824 | 245706 | 36675 | 2343 | 123.579 |
| F | 6 | 794365 | 132394.167 | 28113.667 | 920.500 | 60.923 |
| S | 6 | 625068 | 104178 | 17070.833 | 749.833 | 55.713 |

历史总计2402257 raw tokens，input2382863、output19394、cached input1965056，非缓存
input417807。缓存是 input 子集；实际货币费用未知，没有按统一单价换算。
12次后续中，非零退出为 python缺失12次、python3缺失11次、jq缺失1次。
advisor_email/F 的两条完整历史输出各540357字节，SHA-256均为
`a9e4053ab3d5400f9097ad64f5f388966d191ae1644683ff49891b02dd2bbf7d`。

固定组件只测已留存文件，不追加 prompt-input 导出：

| 可读组件，advisor_email配对 | 观测字节 | 解释边界 |
|---|---:|---|
| 当前 user prompt | 424 | 文件内容，不是完整 Provider 输入 |
| F / S developer bootstrap | 770 / 3227 | 实际 launcher profile 中的文本 |
| MCP instructions | 1541 | 目录中的服务说明 |
| 13个 MCP工具 schema 紧凑JSON | 15145 | 是否在每个请求完整装配未观察 |
| 模型消息目录完整JSON | 62237 | 含条件分支，不能当活跃提示直接相加 |
| 其中 persistent instructions / template | 5741 / 21269 | 仍不能推断实际请求选择和 token 数 |

目录记录 context window=272000、tool truncation policy=10000 tokens；旧Host配置没有显式
`tool_output_token_limit`。这些是目录/配置值，不是已捕获的逐请求输入。每会话一个
turn.completed usage 汇总不代表只有一个 Provider 请求。失败命令究竟占多少 token、
54万日志字节实际向模型呈现了多少、固定输入精确 token 数及实际账单均保持未知。

## C1：同一个通用读取瓶颈的最小修复

新增独立 Lab 镜像及入口，旧 wrapper、旧配置、旧结果不改：

- [镜像构建文件](../../tools/containers/v02-readable.Dockerfile)：继承原 pgvector 基础镜像的
  固定 digest，安装 Python3、jq，提供 python别名；实际版本Python3.11.2、jq1.6、rg15.2.0。
- [通用读取命令](../../tools/v02_read_file.py)：`milai-read PATH` 默认整个JSON响应不超过4096
  UTF-8字节，可设512–16384字节。返回原文、文件SHA、总字节、当前offset、显式truncated
  及next；续读须传入offset和SHA，文件变化拒绝混读。路径限任务workspace，拒绝绝对路径、
  `..`、symlink、缺失/非普通文件及非法UTF-8。原文中的来源身份、角色、日期和正文不改。
- [新容器入口](../../tools/v02_readable_container.py)：沿用read-only根、cap-drop、2GB/2CPU、
  独立home/workspace和只读sources。两臂追加同一条270字节工具能力说明，MCP配置和原bootstrap
  保留；不嵌入案例ID、问题关键词或指定turn。新入口目前在模型执行前拒绝C3。
- [环境身份](../../configs/v02-readable-environment.json)：固定新image ID和源码SHA，并明确
  `model_execution_authorized=false`、`provider_cost_control_verified=false`。这些false表示禁止
  当前执行；将来把字段改为true本身也不构成成本硬限的证明。

构建出的镜像为
`sha256:822880bdaaa648ae9c1fa3c9bc20abfc88c7335030104b16038e46514b3362ad`。
APT仓库将来可能更新，重建必须记录新的image ID，不能仅凭同一tag追认为相同环境。

分页示例，不含任务提示或答案路由：

```bash
milai-read sources/history.json
# 继续时采用上一页 next 的 offset 和 sha256；同一文件内容变化会明确拒绝。
milai-read sources/history.json --offset OFFSET --sha256 SHA256
```

Python标准库与jq可按当前任务自行解析/选择JSON字段；完整文件及原查源/保存能力继续可用。
分页并不要求Agent逐页穷尽历史，不强迫只读笔记，也没有隐藏F的文件。旧打印整份JSON的
Python命令修复后仍可输出54万余字节，说明仅有解释器并不保证低成本；分页是额外可用的
有界入口，模型是否采用以及总成本是否降低尚未验证。

## 真实无模型验证与检查

`uv run python tools/check_v02_readable_environment.py` 用新入口的同一个Docker命令构造器，
仅把网络设为none、entrypoint设为Python smoke，未运行Codex。输入是旧产物的隔离副本；
无认证文件/Provider token，sources只读。旧命令先经只读审阅；其查询词仅作为历史重放
数据保留在Git外，不进入通用工具实现。

- 12个容器通过；24条旧失败命令全部exit0，没有改写命令来冒充解释器修复。
- 12份完整历史共3216页还原，源文件和还原数据SHA逐份相等；观测最大整页响应3688字节，
  低于4096上限。Unicode/换行/空字段/null在实际Python/jq/读取命令中保留。
- 正常读取、非法/缺失路径的CLI反馈、source写入拒绝通过；单位测试另覆盖纯空文件、
  转义膨胀、跨Unicode边界、非法offset、symlink与跨页内容变化。
- 真实新入口通过当前配置校验后返回`C3_NOT_AUTHORIZED_OR_COST_CONTROL_UNVERIFIED`，
  在profile修改和模型执行前退出。能力说明对实际12个旧profile可解析，MCP字段保持相同。
- 相邻测试22项通过；最终Lab **180 passed**，Ruff、strict mypy（30文件）、boundary及build通过。

针对用户指出的首尾字段依赖，增加6种结构变体：有效正文分别位于首、中、尾，分别保留或
删除可选首尾字段。每种输入均逐字节还原，字段顺序、正文、空值及首尾换行保持不变。
删除仅用于独立测试中的可选包装字段，不修改历史来源。此检查证明读取器对这些结构变化
不敏感；不能由此推断Agent端到端泛化，更不能靠删除必要信息或裁剪历史获得通过结果。

实际命令：

```bash
docker build --pull=false --iidfile artifacts/v02-cost-first/run-20260906a/image.id \
  -t milai-lab-readable:v0204 -f tools/containers/v02-readable.Dockerfile tools
uv run pytest -q tests/unit/test_v02_read_file.py tests/unit/test_v02_readable_environment.py
uv run ruff check src tests tools
uv run pytest -q
uv run mypy src/milai_lab
uv run milai-lab-check-boundary
uv build
```

Product源码未改，原pin实算仍为
`c5561412b0440f84e628d69a7c271c96d66bae7f89d4e3f1db46ede97a1608bf`；本轮不重跑无关Runtime/PG
测试，也不把历史971/1当成本轮验收。没有API、Schema、权限、Canonical或CAS变更，无迁移。
回退新环境只需继续使用旧wrapper/config；原研究已经保留该路径，不需要恢复/改写历史数据。

## C2：绝对成本审查与独立轻路径方案

本轮只提出待验证工程目标：普通续做单任务≤20000 raw input+output tokens、≤30秒；若未来
获授权只做一个F/S配对，则目标合计≤40000 tokens、≤60秒。**当前授权仍为0会话/0 tokens**，
这些目标不是已批准额度，也不是已经实现的SLO。cached/uncached input和output继续分别报告；
货币上限与账单未知，未代用户接受金额或在途超额。

本地`codex-cli 0.153.0`的exec帮助没有可核验的累计raw-token硬限参数。现有Lab闸门在会话
结束后才汇总usage；watchdog限制时长/动作数，不能追回已发出的请求。旧120k rollout配置下
已有raw usage超过120k的会话，不能把提醒改名为2万硬限。
官方配置文档将rollout字段描述为预算跟踪，将tool_output_token_limit限定为单个工具输出
在历史中的存储预算，context window及自动压缩阈值也有各自作用域；本次没有据此证实一个
任务级累计硬限。[OpenAI配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)

**C2决定：当前付费路径NO-GO。** 精确固定输入与逐请求用量未观察，最坏在途超额无法给出
可信数值，货币上限未确定。不能用日志字节/近似token估计或“模型会遵守提醒”填补这些缺口。

更轻路径的独立方案已经明确，但本轮不实现另一个平台：

1. 在单任务轻宿主中显式装配完整请求，暴露全部13个合法记忆工具及同一允许历史/普通文件；
   两臂同宿主、同模型/推理配置，只有实际State不同。这是新Host/装配条件，要新建F/S基线，
   不能加入原N5确认分母。
2. 发出前核算完整输入，并使用经验证的单请求输出约束；一次只允许一个在途请求，为可能
   超额预留上界。不能取得可信计数/上限就拒绝发送，不靠事后usage停止来冒充硬限。
3. 先用无模型回放证明请求预算、错误、超时、未知usage与无隐式重试；所有请求和工具输出
   的归属可追踪，不记录私有思维链。只有控制证明及用户接受的token/时延/费用边界齐备，
   才提出最多2会话的独立授权请求。
4. 唯一候选任务仍是预选的`ba358f49/advisor_email`，复用原G及保存回执，公共接口初始化隔离
   F/S；不重做G，不加Judge、备用样本或自动重试。先验任务质量与绝对成本，再报告相对值；
   一个配对不补齐旧N5，也不支持泛化或自动维护结论。

## 收尾与证据索引

[机器结果](MILA_V02_COST_FIRST_RESULTS.json)记录汇总及结论边界。逐项出口核对如下：

| 要求 | 证据与出口 |
|---|---|
| C0 历史用量、失败及固定组件 | `cost-audit.json`；16会话用量一致，费用与逐请求输入未知 |
| C1 工具真实可用、完整来源、错误和有界续读 | `smoke-results.json`、22项相邻测试及最终检查日志；通过 |
| C2 成本控制能力和不可核验时的轻路径方案 | 本报告C2；付费NO-GO，独立方案已列出，未授予预算 |
| C3 条件分支 | 前提未满足，不进入；`launch-guard.json`记录启动前拒绝 |
| 冻结身份和收尾 | `completion-audit.json`；Product、旧总账及来源通过，容器与认证副本均为0 |

Git外证据根：`artifacts/v02-cost-first/run-20260906a`，包含cost-audit、构建日志/image ID、
12个重放目录、smoke-results、launch-guard、本地CLI帮助和最终检查。所有新容器已移除，
认证副本0；镜像、输入副本及回执保留。两套旧研究PG仍为exited，未修改旧卷或公网。
来源/原总账/原C合同及16个实际会话配置身份终审通过；首个模型前失败的旧配置摘要单独
保留，不冒充当前配置。历史仍17分配、2402257 tokens，见`completion-audit.json`。
原始Provider日志、source、产物没有进入Git。Schema保持
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`，A0默认与D2 SHADOW保持。
