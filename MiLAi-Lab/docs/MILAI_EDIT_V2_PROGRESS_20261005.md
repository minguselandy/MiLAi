# MiLAi-Edit v2 实验进度与复现入口

本报告记录 2026-10-05 11:55 Asia/Shanghai 的工程检查点。起点为 PR84
`c16e109c247c37cd84cfe779989d3815f380ddae`，新分支
`feat/lab-milai-edit-v2-20261005`。完整跟进计划仍执行；本次发布不合并、不暂停实验，
也不代表候选冻结、科学确认或 Product 就绪。

## 当前进度

| 工作 | 当前证据 | 尚待完成 |
| --- | --- | --- |
| v1 E1 历史四臂 | B0/B1 各 277/277 封存；B2 257/277；M 未开始。原进程及冻结方法不改 | B2/M 全部完成后的四用户配对比较及错误分析 |
| R0 输入诊断 | B0/B1 各 277 个会话、共 560 个批次；153 次容量失败 token 精确复原；固定 24 原输入 | 真实 Writer 检查、最终 v2 队列完整输入统计 |
| R1 分臂接口 | B0 create/rewrite/no_change，B1 create/edit，B2 条件全量重写，M 条件局部编辑；局部短引用及实际 schema 请求接线 | 真实服务的语法、空数组、多提案、引用与支持效果 |
| R2 共用交付 | I1 保留重复呈现；I2 等信息去重；可选 I3 自然段核心、相邻条件及整记录工作集；预调用容量安排 | 固定前缀的 I1/I2 因果比较；仅必要时进入 I3 |
| R3 支持语义 | 旧 h 仅保留已有支持，改变主张须新 e；未改单元支持保留；SDK、CAS、重启和 UNKNOWN 恢复检查 | 真实跨会话条件保持、override/retract 与损伤评估 |
| R4 评估视图 | 原作者 extracted 原样保留；实际 delta（含删除关系）、state；固定类别分母；缺失旧正文标 UNKNOWN；参考引导只读评估 | 三视图真实评分、共同 Judge、所有方法人工成功/失败/分歧核对 |
| R5 A/B | 已固定 24 输入；准备 12 个旧/新 Writer 探针及四臂各 3 次正常路径；四开发用户各前 8 个按时间排序会话配置 | CI 与 v1 通道释放后串行真实运行；当前 0 次 v2 模型 HTTP |
| R5 C/D | 全量范围仍为 277×4 会话；32 个既定原生机会及全部 277 历史漂移 | 冻结一个共同配置，从各自空库开始；实际旧状态 NeverWrite/RetainAll 对照 |
| R5 E/F | 既定 3 簇/10 受控变化、16 保留用户及 LongMemEval 28 问范围保留 | 候选冻结后确认；LongMemEval 1,354 次历史出现及 10 个完整答案审计、外部方法比较 |
| R5 G 与交付 | 四臂正常 Host I2 已准备，权限/预算仍沿用 r52 | 同一最终候选的旧 135 案例实际回归，以及冻结后新故事；复现、归因、成本及贡献稿 |

尚未开始的 v1 E2/漂移任务于 02:51 UTC 取消，后续调用数 0。v1 已有模型输出、
失败和评分保持历史含义；后续机制与漂移须使用 v2 自身形成的状态。

## 固定输入容量结果

在看到任何 v2 输出之前，选定四用户、早中晚阶段的 24 个不同原输入：容量、
非法动作、错误引用、正常对照各 6 个。全部投影保留完整旧记录、原始时间戳、
来源正文/范围与关系；I1 保留重复旧正文与支持属性，I2 仅去除重复呈现。

| 六个容量输入的实际模板 token | 最小 | 中位数 | 最大 |
| --- | ---: | ---: | ---: |
| 原始 v1 | 58,564 | 64,374.5 | 73,613 |
| I1 | 33,126 | 37,615.5 | 39,964 |
| I2 | 17,160 | 19,124 | 21,346 |

I1/I2 各 24/24 在 65,536 上下文内保留 8,192 输出 token 和 512 余量。
这些是容量结果，不是 Writer 语义成功率。分项 token 非可加统计。
原型 `capacity-preflight-v1.json` 有时间戳丢失及 I1 过早去重，不作为等信息证据；
有效产物为 `artifacts/milai-edit/v2-r0/capacity-preflight-v2.json`。
详细拒绝、引用类别和非单调状态增长见 `MILAI_EDIT_V2_R0_DIAGNOSIS.md`。

## 工程验证与行为边界

受影响正常 Host、SDK、四臂方法、恢复、作者接线、外部接线及分析检查共
**419 passed**。其中普通 Host 的业务成功/partial 路径已有 I2 参数化检查：
真实公共沙箱和 SQLite 效果、请求局部 e 引用，以及重复调用不重放业务；模型响应
为模拟值。后续定向复核覆盖未知 HTTP 停止和重启不重发、截断不提交、整记录容量
缺口、四臂同 ID 更新、旧 v1 接线，以及只删关系的 delta，**24 passed**。
集合重叠，不相加。四臂 I2 功能配置各完成一次 prepare 校验，零 HTTP，
该准备校验不计作实际功能实验。

12:10 的工程补充保留“仅删除关系”的旧/新端点正文，即使全量重写重分配了单元
ID，也不会把条件取消的上下文省略；Stage A 的引用诊断同时检查
withdrawal_evidence。补充后相关检查 **14 passed**，两处严格类型与 Ruff 通过。
这不改变上面的 11:55 实验快照，也未增加 v2 模型调用。

严格类型检查 11 个改动源码/工具通过；Ruff、Lab DAG/tools/root 边界与
243-source 所有权矩阵通过。完整原计划逐字节保留。远端新提交的 Fast/Full CI
结果在草稿 PR 上核对并登记；核对完成前不准入 v2 真实模型。

Lab 的 opt-in proposal schema 与 SDK 参数新增 v2 行为；原 v1 默认保持。
短引用只在一次实际交付中有效，映射保存真实 ID 和读取版本；模型不填写 UUID 或
base revision。h 是已有支持的限定保留，不是新证据。完整旧记录不够容量时显式
记缺口，不拼接未交付正文；无新事实允许空 proposals。未知模型返回立即停止，
既有请求不可盲目重发；已确认提交丢失响应通过原操作恢复。整个实验沿用现有
连续账本和串行锁，未增加预算。交付字符覆盖率不等于事实维护成功率。

没有 Product/Archive 源码、权限、Canonical 或部署变更。Product 保持 NO_GO。
保留用户及未来问题不交给方法源码负责人；原始语料、数据库、请求和本地路径
产物均 ignored。生成、Reader、Judge 只用现有 Qwen3.6，Judge 不独立，
不形成跨家族推广结论。

## 13:30 工程补充：实际三视图评分接线

R4 的原生机制评估现保存 `r4-three-view-results.json`，分别报告原作者分数、
实际净 delta 与实际 state。原作者结果直接复制；state 复用已有评分，不额外
调用一次 state Judge。没有可评 delta 的机会保留在固定分母内，不计为新事实
形成成功，也不补发模型调用。delta Judge 使用实际新增、删除及关系变化，
附实际前后状态所引用的来源范围；旧引用正文不可用时保留 UNKNOWN，不能
把缺失证据判为零损伤或已确认旧事实。

评估使用结构性匿名标签，正文中的同名文字保持原样；不读取未被实际状态
引用的未来来源。v2 原生/漂移评估拒绝复用 v1 队列；恢复时拒绝混用旧评分
协议。受控变化改走公共 `maintain` 入口，使已选择的 v2 接口实际生效；
受控实验仍须等最终候选冻结，不因接线完成而提前准入。

准备 packet 的来源与已确认响应对应的实际交付来源分别记录，容量失败的
来源不计为 Writer 已收到。相关检查 **59 passed**，包括四臂实际 SQLite
状态、旧/新来源绑定、未来来源排除、缓存恢复零额外请求和原库值不变；
该集成检查使用模拟传输的 40 次请求，不是实际模型实验。四处改动源码的
严格类型、全局 Ruff、DAG/tools 边界、243-source 所有权矩阵及 diff 检查通过。
本轮与前面检查有重叠，不相加；真实三视图评分及人工审计仍未完成。

13:30 核对时 v1 原进程仍运行；B0/B1/B2 均已封存 277/277，M 正在继续。
Stage A 等待原进程结束，v2 生成/嵌入 HTTP 仍为 0。已保存的 Stage A 使用
`7885559` 源码及其成功的 Fast/Full CI，不被本轮评估补充替换；本轮评估代码
自己的远端 CI 须另行通过才可准入。此补充不重写上面的 11:55 历史快照。

## 受控确认材料的开发暴露

既定三簇、十条受控历史保持原样。完整对话及要求由 Root 编写，且工程测试
已读取全部观察序列；计划 R3 示例和 Stage A 例子也共享部分更正、保留限定及
撤销机制。因此它们不能称为独立未见来源。登记见
`data/manifests/milai-edit-controlled-exposure-v2.json`；方法源码负责人的历史
完整材料访问没有独立可核查记录，标 UNKNOWN，不据此推断未暴露。

实际受控模型确认仍须在最终候选及共用 Writer 配置冻结之后运行，结果不能
再用于挑选或调参。语言改写及独立事件交换按原簇统计，十条历史不当作十个
独立来源。运行时仍只交付已发生的对话、角色和日期，问题、要求及暴露登记
不进入 Writer。该登记新增模型调用 0，也不替代保留用户和冻结后新功能故事。

## 14:39 失败结束及实际 Stage A 启动

原 v1 进程于 14:31 前在 M 第二用户原会话 63 的自然 QA 请求 index 1
断开连接退出；M 的真实终态为 FAILED。完整评估检查点 128/277，完整维护
检查点 129/277；另有一个已维护、QA 未完成的会话。未完成评估 149、
尚未维护 148，均保留原分母。B0/B1/B2 各 277/277 已封存，不能把本次
失败写成四臂全部完成。M 1,209 次生成请求、5,311,729 已知 token，
新增生成未知用量 1；连续未知总数由原 1 增至 2，嵌入未知仍为 0。

Root 检查确认该失败是 Reader 回答请求，无 Writer 或业务提交；原缓存无
响应，服务通用日志不能恢复精确答案或用量。服务 health 200，仍为原
vLLM 0.27.1 / Qwen3.6-35B-A3B-FP8，串行锁已释放，无新部署或重启。
按计划第 3 节明确登记 v1 以实际失败／不完整历史队列结束，保留原源码、
库、请求、评分和 FAILED 终态，不重发未知请求，也不将其用量猜为零。

自动 Stage A 等待任务已在 v2 调用前停止，原 Stage A 输出目录不存在。
Root 于 14:39 启动其首次实际尝试：原批准 `7885559` 源码、原固定输入、
原未使用输出 `artifacts/milai-edit/v2-stage-a-v1`，每组正常路径独立库。
新阶段沿用包括两次历史未知事件的连续账本，原 Reader 不恢复／不重发。
状态与逐请求原件保存在 ignored artifacts。此时尚在运行，不能称接口或
语义通过；实际 Stage A 结果须审查后才推进 pilot。

当前主分支检查点 `f3e9ae7` 的 Fast/Full CI 已成功，逐项核对 Full 21/21、
Fast 8 成功/4 按范围跳过。此文档补充另有自身发布 CI；实际 Stage A 源码
仍绑定其既有成功 CI。完整 v2 四臂及全部后续确认、六项交付范围不缩减。

## 复现与后续准入

以下命令从本分支 `MiLAi-Lab` 执行，使用已有环境。`OLD_SUITE` 指原 v1
`artifacts/milai-edit/e1-dev-v1` 的绝对路径，`PYTHONPATH=src` 明确使用本分支。
诊断 v1 时须按工具说明指向原封存 v1 evaluator 源码，避免换 schema。

```bash
PYTHONPATH=src /cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python \
  tools/prepare_edit_v2_preflight.py --suite "$OLD_SUITE" \
  --selection artifacts/milai-edit/v2-r0/fixed-input-diagnosis.json \
  --output artifacts/milai-edit/v2-r0/capacity-preflight-new.json
```

真实命令须在本提交 CI 通过、v1 E1 完成并释放连续账本锁后执行，串行且使用
新的独立空库；旧/新探针只读、不初始化正式库。工具缓存原请求及响应，遇未知
结果停止，重启不得通过换输出目录盲目重复同一未确认请求。

```bash
PYTHONPATH=src /cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python \
  tools/run_edit_interface_checks.py --config configs/milai-edit-v2-pilot-i2.json \
  --preflight artifacts/milai-edit/v2-r0/capacity-preflight-v2.json \
  --output artifacts/milai-edit/v2-stage-a-v1
PYTHONPATH=src /cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python \
  tools/run_edit_suite.py configs/milai-edit-v2-pilot-i1.json \
  artifacts/milai-edit/v2-pilot-i1 --benchmark halumem
PYTHONPATH=src /cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python \
  tools/run_edit_suite.py configs/milai-edit-v2-pilot-i2.json \
  artifacts/milai-edit/v2-pilot-i2 --benchmark halumem
```

前缀结果只用于按计划选择公共交付方案，不作为最终科学结论。全量配置、
最终候选与 Writer 冻结分别在对应门槛处登记，当前尚未完成。回滚代码起点为
`c16e109`；运行中的 v1 及历史产物另行保留，不因回滚代码自动重跑。
