# V0222 残余意图边界诊断

日期：2026-09-12。类型：`RESEARCH_PROTOTYPE / INTENT_ORACLE / VALIDATE_ONLY`。

最新结果：`INTENT_BOUNDARY_SIGNAL / SELECTED_B1`，16次有界运行已结束，最终独立审计通过。
原B0为4/8，独立消息B1为8/8；完整执行与Memory仍未准入。
全部逐位置结果、成本与制品hash见[紧凑结果](MILA_V0222_BOUNDARY_RESULTS_20260912.json)。

## 实例与准备时阶段（历史记录）

原 V0222 首次完整输出选择了合法但未授权的目标，永久停止状态不变。
本诊断按用户“执行并反思改进、委托 subagent 审查”的要求，只检验
[已冻结的单一边界对照](../../docs/V0222_RESIDUAL_INTENT_BOUNDARY_DIAGNOSTIC_PLAN.md)，不恢复旧批。

新实例：`/cra/memory/mx_memory/evidence/v0222-boundary/20260911-http-r1`。
批 ID 在跨日前固定，实际准备/运行日期另记，不通过换目录重置候选。
binding SHA256：`7b7d4659f7250af493470882e8c6c2f0009e1762ddd751c3a79c431e0a0b928a`。
manifest SHA256：`4111eb762afd8b1fdfd380160445c25c35deb387a4f6806f30423477806c2521`。

离线准备已完成，16 个参考位置、原四根、唯一 B1 候选；初始状态为
`PREPARED_NOT_REVIEWED_NOT_LIVE`，0 真实 HTTP、0 生成、0 业务派发。
独立实例审查与实际 HTTP 容量门尚需分别满足，不能用离线测试代替。

## 冻结比较

- B0：原完整 canonical messages，所有字符不变。
- B1：仅将最后 user JSON 中唯一 authorized_intent 连同原值移成独立末尾 user 消息；
  不重复答案、不裁剪资料、不重排 Schema、不改变 D11 或参数。
- 原目标依次为 manager_report、manager_report、placement_plan、triage。
- 首遍四根各 B0→B1，共8次；仅同根配对改善触发完整反序8次。
- 每位置一个冷客户端、一次生成、并发1、output4096、阶段1800秒、HTTP≤60秒；raw cap=null。
- 可信用量下的预定内容差异可继续观察，任何 HTTP/身份/证据/权限/新未知异常停止整批。
- B1 需四根两遍8/8，且同根改善重复，才选择候选；诊断信号不是 full/finish、业务或 Memory 门。

## 已完成工程验证

全仓库 **1959 passed / 1 optional Host SDK skip，366.97秒**；边界检查、Ruff、
Mypy（39源文件）、构建与 git diff 检查通过。证据为新实例 `engineering-checks.json`。
147项新增测试包括50项纯合同、59项批/传输、37项接线和1项真实历史准备集成。
后者使用原四源、28历史账、真实新 Batch 与模拟 HTTP，覆盖准备→预检→工作者→独立审计；
该单测的父/子 PID 用 monkeypatch 模拟，不是实际冷子进程证据。
旧批 SQL/持久文件/账本前后不变。模拟通过不计入真实模型或容量成绩。

## 成本与后续边界

历史为29请求、62874已知 raw，以及独立未结算预约28284；总实际仍未知。
旧未知不是本批新未知的白名单，累计 token 不封顶不解除有限矩阵和永久停止规则。
Agent 工作用量另账，不与模型实验 raw 合并。

原 P3 未运行15位置、P4未运行24链不变。P4/E1/E2/M0/M1均未由本诊断准入。
模型相关操作仅调用现有 vLLM HTTP，不调用 GPU/CUDA/NVML/容器或修改服务，不读取凭据。

实际预检、生成、独立结果审计和下一步决定将在发生后追加；当前不宣称诊断完成或能力通过。

## 正式实例范围审查（追加）

`/root/v222_review` 已独立通过本实例范围审查：`G_AUTH_SCOPE_REVIEW_PASS`。
`scope-review.json` SHA256：`75f95d33c7017b4091325dcd6935bfa47e591fb3bfbe2c5b78e0498e805e7f1d`。
33源码/执行副本、2087输入、16参考、28历史账及父批停止状态均核对；206项不可变文件绑定。
该审查确认具体实施处于原用户委托范围，不创造新用户同意，不开放后续 full/P4/Memory。
工程与范围制品已登记；现在只执行实际 HTTP 容量预检，生成须等待其独立验收通过。

## 实际 HTTP 容量门（追加）

16/16完整参考、32次tokenize和起终4次身份GET已通过，104份收据由独立验收器复算并冻结。
`preflight/result.json` SHA256：`60bbce7b281772a310c1b7b47e1c1a4c5820cfe8f24edd83094276fea56d2235`。
最大输入54136，最大参考输出814，完整 input+4096≤65536；B1相对同根B0增加5个input token。
实际HTTP身份仍为 Qwen3.6-35B-A3B-FP8、context65536、version0.27.1；
这不证明完整服务配置或内部decoder路径未变化。

唯一 runner 已启动首遍有界诊断。结果尚未结束，不提前选择呈现候选。

## 真实矩阵终态（追加）

唯一runner正常退出，16/16位置均为OBSERVED，未运行位置为空。首遍B0为2/4、B1为4/4，
同根配对改善触发全部反序8次；最终固定选择器为`INTENT_BOUNDARY_SIGNAL / B1`。

| 原root序号／完整目标 | B0两遍精确 | B1两遍精确 | B0偏差 |
| --- | ---: | ---: | --- |
| 1／manager_report | 0/2 | 2/2 | 两次选择S01，每次38处差异 |
| 3／manager_report | 0/2 | 2/2 | 两次选择facts，每次25处差异 |
| 31／placement_plan | 2/2 | 2/2 | 无 |
| 56／triage | 2/2 | 2/2 | 无 |

16次严格JSON和原完整Schema均通过、finish_reason均为stop；差异属于完整合法对象目标选择，
不是业务Schema失效或4096输出额度耗尽。B1在同一完整输入合同下恢复原授权完整值，
但不能据此证明自然任务理解、内部后端选择或消息边界各子因素的独立因果。
这仍是4个已暴露root的重复诊断，不是16个独立业务样本或无偏总体效果估计。

本批模型输入559228、输出9568、合计568796 raw，16请求全部结算，新未知0。
B0共284686 raw，B1共284110 raw；输入边界开销为每份+5，不把小样本输出长度差异当稳定节费结论。
在线另有48次tokenize（预检32＋生成前16）、36次身份GET（预检4＋运行32），Judge/回退0。
旧历史29请求62874已知raw，合计45请求631670已知raw；旧未知预约28284仍单列，总实际仍为null。
Agent工作用量由平台另计，不把它填0或混入模型账。
平台Goal累计工作量快照为2655269 token（Unix1789145012），涵盖整个仍在执行的Goal，
不是本诊断单独的Agent消耗，后续仍会增加。

没有业务World、Note或派发；原P3永久停止及15P3/24P4未运行位置不变。
累计费用允许标记不授权再次启动：本诊断全部16位置已耗尽，唯一launch不重开。

## 下一步：新完整门，不越级进入Memory

交付[唯一呈现候选的完整门设计](../../docs/V0222_PRESENTATION_FULL_GATE_DESIGN_NOT_ADMITTED.md)。
现诊断函数只支持单个put_record，不能直接用于finish、完整ordered_writes或含回执的多轮Session。
拟推广仍只移动原完整意图，保留全部来源/历史/预算观察，不代填下一动作或CAS；
这些未测边界须先离线实现与独立审查，再单独冻结16 full/finish及条件24冷链的新实例。
当前诊断不分配这些后续生成。原P4/E1/E2/M0/M1继续NOT_TRIGGERED，整体用户Goal仍在推进。

## 最终独立审计

`/root/batch_guard`从全部原始请求、输出、实际身份正文、tokenize、中央/本地usage和SQLite语义
独立复算通过：`BOUNDARY_RESULT_REVIEW_PASS`。
`independent-result-review.json` SHA256：`99a9c0caf97743ad0aaf6769f46e62b6f6b0ed12d13132ec6f9e3d69b39d40e3`。
3556项稳定制品绑定由主代理再次逐hash复核，64事件、16互异冷PID、唯一launch和全部exit0一致。
模型事件跨度692.235秒，最大生成HTTP记录13.079秒；各阶段/请求界限通过。
SQLite仅作只读语义和审计前后稳定性检查，不以可变DB/WAL/SHM充作永久依赖。
该审计确认本诊断信号和费用，不创造下一实例授权。至此满足下一设计所要求的离线实施前提。
