---
status: ACTIVE
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
baseline_commit: 44f9291bb0c7f3b6d5c9c71dadf76d1924a81eb2
plan_sha256: c9a149cf5a7ad1ff6fc833702391813afd4c1494187bdb350c8e545e8b42625e
research_goal: NOT_ACHIEVED
product: NO_GO
---

# NEXT_DEVELOPMENT v4.0 执行记录

用户新 Goal 明确要求完整阅读并执行 [v4 原计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v4.0.md)。
Root 已完整读取 862 行；原文 DRAFT_PLAN_NOT_EXECUTED / NOT_STARTED 和上述 SHA 原样保留。
授权来自当前用户 Goal，不来自草案状态。v3 已关闭，历史分数、失败、锁和费用不改。

当前树 `/cra/memory/mx_memory/MiLAi-worktrees/next-development-v4`，分支
`feat/lab-memory-boundaries-v4-20260928`，从 v3 发布提交建立。原 main、旧工作树、v27 草稿均保留。
Root 负责文档/语料/冻结/真实 HTTP/评分/账本，复用 Sol xhigh 为唯一源码负责人，Luna high 负责提交推送。
不启动常驻审核者；Astra 只用于具体困难问题。实际 HTTP 并发为 1。

F0 已发布 `8d4ddc4a315bd97f4a7a62a84ec51f23fbaf53eb`，[PR67](https://github.com/minguselandy/MiLAi/pull/67)
远端 head 已核对，draft/open，base 为 PR66；没有 merge 或改写旧树。
[F0 Fast CI](https://github.com/minguselandy/MiLAi/actions/runs/36376429409) 已读回 completed/success。
[F1–F7 工程合同](MILAI_NEXT_DEVELOPMENT_V4_IMPLEMENTATION_CONTRACT_20260928.md)已实现，
[F8 A 工程验收](MILAI_NEXT_DEVELOPMENT_V4_ENGINEERING_20260928.md)通过；44 个去重相关检查、实际模板和零模型 prepare 均通过。
[F8 B 协议](MILAI_NEXT_DEVELOPMENT_V4_B_REGRESSION_20260928.md)只引用六个已暴露原输入，尚未运行。

## 完整要求与验收证据

以下各项以真实产物验收，空白或待做不能以实现意图、进程成功或 Mock 替代。

| 项 | 必须交付／验收 | 当前状态 |
| --- | --- | --- |
| F0 / §6 | [九类失败和基线](MILAI_NEXT_DEVELOPMENT_V4_F0_BASELINE_20260928.md)；32 项来源身份、原冻结哈希核查，无历史重跑/改分 | COMPLETE |
| F1 / §7 | B0 默认 answer/无 correction；真实 CREATE/UPDATE/DELETE/no_change/failed 审计，不用模型文本认证 saved；历史 C 保留 | ENGINEERING_ACCEPTED；真实链待 B/C |
| F2 / §8 | 六类信息角色的实际请求投影；checkpoint 内容、ID、工具链不变；只标来源，不替 Host 判断真值 | ENGINEERING_ACCEPTED；真实链待 B/C |
| F3 / §9 | Working State 限 goal/turn_constraints/active_refs/open_questions（可选动作引用）；当前消息逐续接可见；新 session 约束清除，引用解析当前记录 | ENGINEERING_ACCEPTED；真实链待 B/C |
| F4 / §10 | 长期理解与实时世界分工；动态事实按观察时间/来源理解，必要业务查询不被旧记忆替代，漏维护不重复副作用 | ENGINEERING_ACCEPTED；语义待验证 |
| F5 / §11 | 独立事项与局部更新保持、temporary/read-only 无写、精确删除；strict CRUD/exact READ 保留，不新增 ontology | ENGINEERING_ACCEPTED；语义待验证 |
| F6 / §12 | 程序自动记录操作所处 user/tool event provenance，模型 CRUD schema 不变；provenance 不当 semantic proof | ENGINEERING_ACCEPTED；真实链待 B/C |
| F7 / §13 | 小 bank all、超预算 ordinary retrieval、只有真实瓶颈才启用 Attention；阈值事前冻结；无默认 U/控制调用 | ENGINEERING_ACCEPTED；真实链待 B/C |
| F8 A / §14.1 | 八项机械边界＋真实模板/窄入口链；必要静态/相关回归，按文件变化决定一次构建 | COMPLETE；仅工程证据 |
| F8 B / §14.2 | 复用 v3 六脚本原输入/rubric，B0 四条持久正例不退化；当次格式、无 receipt 自报/无机械证明调用分列 | NOT_RUN；待已发布源码正式冻结 |
| F8 C / §14.3 | A/B 通过后才创建并冻结 8–12 新脚本；覆盖保存/更新/独立事项/临时/引用/动态世界/只读/删除/助手历史冲突/多记录 | NOT_CREATED；门槛待验 |
| F8 D / §14.4 | 有真实选择瓶颈后同 bank/模型/历史/工具比较 ordinary all/query、working-state query、lazy Attention，全成本 | CONDITIONAL_NOT_TRIGGERED |
| F9 / §16,19,20 | 依据任务、记忆、消费、成本四层指标判断 Go/Pivot/Stop；七项工程解释、方法稳定和研究重新准入逐项审计 | PENDING |
| 交付 | 失败模板＋每阶段十项 Reflection、复现、全成本、总体报告、Luna 发布并核对远端 SHA | PENDING |

F1–F7 按来源职责分别提交可检查的实现，不将多项变化的组合结果冒充单项因果收益。
F2 的机械正确与 Host 是否消费正确分开；如果仍选择旧助手内容，定位为消费错误，不能以改 Store 修分。
F3 不新增 LLM constraint extractor；F4 不把业务回执自动转成长期事实；F5 不按词语、句长或 embedding 自动拆卡。
F6 不增加模型手填 evidence_refs；F7 不因候选功能存在便启动真实选择实验。

## 初始证据与成本

已读回 [PR66](https://github.com/minguselandy/MiLAi/pull/66)：draft/open/unmerged，远端 head 与基线一致。
其 [Fast 36373605907](https://github.com/minguselandy/MiLAi/actions/runs/36373605907) success；Full 36373605931 skipped。
只读服务 models 核实：Host Qwen3.6-35B-A3B-FP8 / 65536，embedding bge-m3 / 8192 服务输入容量，维度仍按原锁 1024。
保持温度 0、输出 4096、thinking=false、每公开消息 12 次；未修改共享服务、下载权重或部署模型。
现场只见原服务进程，没有本项目实验 runner。服务进程存在不算实验运行。

唯一连续账本仍为原树 `artifacts/ser-v20/budget.json`，起点 **2950 generation calls / 3,729,307 generation tokens / 20,729 embedding tokens**，
SHA `28cbcfe8c0be9208aaa9e6898daa36dcaa1d9202ee27fa73a613d5f45f7a4e38`。
当前 v4 真实 generation / embedding 调用均为 0。不清零；开发代理和 Mock 使用不混入实验费用。

## 执行纪律与后续门槛

源码先完成最小通用实现和必要窄检查。真实运行前冻结源码、输入字节、参数、工具契约、scorer、顺序、
namespace/Store/checkpoint/业务隔离及账本起点。F8 B 使用已暴露材料，只检验回归；F8 C 不提前创建样本。
新样本在方法冻结后构造，运行后全部按已暴露记录；若修改方法，旧失败继续保留，不能重称 unseen。
任何失败先记 Observed、Expected、实际链、首断点、至少两个解释、通用修复候选、混杂因素、最小下一实验及决定。
没有样本特定答案修正、追加措辞循环、真实并发调用、全量 benchmark、第二模型或 Product 迁移。

最终验收须证明每项工程合同的实际入口和消费路径。方法稳定必须来自新小样本的真实持久与业务链，
不能因窄工程检查通过就声明可靠。若证据不支持，明确 Pivot/Stop 与未达项，不把较小子集改称总目标完成。
