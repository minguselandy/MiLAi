---
status: EXPERIMENT_STOPPED_F9_REPORTED
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
baseline_commit: 44f9291bb0c7f3b6d5c9c71dadf76d1924a81eb2
plan_sha256: c9a149cf5a7ad1ff6fc833702391813afd4c1494187bdb350c8e545e8b42625e
method_stability: NOT_ACHIEVED
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
工程发布提交为 `e070456b57ce0b941813948464b2c1bf870c99f6`，Root 已读回 PR67 远端一致；
[Fast 36380454177](https://github.com/minguselandy/MiLAi/actions/runs/36380454177) completed/success，Full skipped。
[F8 B R1](MILAI_NEXT_DEVELOPMENT_V4_B_R1_RESULTS_20260928.md)已完成：持久正例4/4、后续使用7/7，
当前临时格式仍失败，完整脚本5/6，门槛未过；C仍未创建。
[R2 条件回归](MILAI_NEXT_DEVELOPMENT_V4_B_R2_RESULTS_20260928.md)已完成：当前格式通过，但 field_plan 完整回答遗漏物品身份，
完整脚本仍5/6；原问题点名的数量/目的地/包装3/3正确，这项局部成功保留。按[事前协议](MILAI_NEXT_DEVELOPMENT_V4_B_R2_PROTOCOL_20260928.md)拒绝唯一候选，停止措辞/anchor变体。
R2 方法提交 `24ef49945cd12eccbd85792fee3c256bf3fe6d2a`，Root 已核对远端一致；
[Fast 36381555861](https://github.com/minguselandy/MiLAi/actions/runs/36381555861) success，Full skipped。
[F9 总体报告](MILAI_NEXT_DEVELOPMENT_V4_OVERALL_EXPERIMENT_REPORT_20260928.md)完成要求审计、四层结果、费用和交接。
C没有创建，D没有触发；方法稳定和研究目标仍未达成。按用户任务结束后暂停的要求，发布核对后由实际Goal工具设置状态；本文不宣称Goal已complete。

## 完整要求与验收证据

以下各项以真实产物验收，空白或待做不能以实现意图、进程成功或 Mock 替代。

| 项 | 必须交付／验收 | 当前状态 |
| --- | --- | --- |
| F0 / §6 | [九类失败和基线](MILAI_NEXT_DEVELOPMENT_V4_F0_BASELINE_20260928.md)；32 项来源身份、原冻结哈希核查，无历史重跑/改分 | COMPLETE |
| F1 / §7 | B0 默认 answer/无 correction；真实 CREATE/UPDATE/DELETE/no_change/failed 审计，不用模型文本认证 saved；历史 C 保留 | ENGINEERING_ACCEPTED；两轮暴露基本链通过，C未创建 |
| F2 / §8 | 六类信息角色的实际请求投影；checkpoint 内容、ID、工具链不变；只标来源，不替 Host 判断真值 | ENGINEERING_ACCEPTED；两轮暴露基本链通过，C未创建 |
| F3 / §9 | Working State 限 goal/turn_constraints/active_refs/open_questions（可选动作引用）；当前消息逐续接可见；新 session 约束清除，引用解析当前记录 | 工程通过；R1格式失败，R2格式通过；两轮无泄漏，稳定性未证 |
| F4 / §10 | 长期理解与实时世界分工；动态事实按观察时间/来源理解，必要业务查询不被旧记忆替代，漏维护不重复副作用 | ENGINEERING_ACCEPTED；动态世界语义NOT_RUN |
| F5 / §11 | 独立事项与局部更新保持、temporary/read-only 无写、精确删除；strict CRUD/exact READ 保留，不新增 ontology | 工程通过；暴露形成5/5、修订1/1、负例3/3，新场景NOT_RUN |
| F6 / §12 | 程序自动记录操作所处 user/tool event provenance，模型 CRUD schema 不变；provenance 不当 semantic proof | ENGINEERING_ACCEPTED；两轮暴露基本链通过，C未创建 |
| F7 / §13 | 小 bank all、超预算 ordinary retrieval、只有真实瓶颈才启用 Attention；阈值事前冻结；无默认 U/控制调用 | ENGINEERING_ACCEPTED；两轮暴露基本链通过，C未创建 |
| F8 A / §14.1 | 八项机械边界＋真实模板/窄入口链；必要静态/相关回归，按文件变化决定一次构建 | COMPLETE；仅工程证据 |
| F8 B / §14.2 | 复用 v3 六脚本原输入/rubric，B0 四条持久正例不退化；当次格式、无 receipt 自报/无机械证明调用分列 | R1/R2均GATE_FAILED 5/6；R2完整持久链退化为3/4 |
| F8 C / §14.3 | A/B 通过后才创建并冻结 8–12 新脚本；覆盖保存/更新/独立事项/临时/引用/动态世界/只读/删除/助手历史冲突/多记录 | NOT_CREATED / NOT_RUN；A/B共同门槛失败 |
| F8 D / §14.4 | 有真实选择瓶颈后同 bank/模型/历史/工具比较 ordinary all/query、working-state query、lazy Attention，全成本 | CONDITIONAL_NOT_TRIGGERED |
| F9 / §16,19,20 | 依据任务、记忆、消费、成本四层指标判断 Go/Pivot/Stop；七项工程解释、方法稳定和研究重新准入逐项审计 | REPORT_COMPLETE；方法/研究未达成 |
| 交付 | 失败模板＋每阶段十项 Reflection、复现、全成本、总体报告、Luna 发布并核对远端 SHA | 报告/清单完成；Luna发布与远端核对为最后步骤 |

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
F0/F8 A 新增真实调用为0。B R1 新增22次 generation／27,613 tokens，7次 embedding／262 tokens；
R1后累计 **2972／3,756,920／20,991**，SHA `207f2e6909724e687400d45d194674d33ef2d852f95290647e78b71fed8db2da`。
R2新增22次generation／28,571 tokens，7次embedding／246 tokens。本v4累计新增44／56,184和14／508。
当前连续账本 **2994／3,785,491／21,237**，SHA `e47de5a370b7c6dad581d836a440411055c01c137ec4c589f95389109a4ca668`。
不清零；开发代理和 Mock 使用不混入实验费用。

## 执行纪律与后续门槛

源码先完成最小通用实现和必要窄检查。真实运行前冻结源码、输入字节、参数、工具契约、scorer、顺序、
namespace/Store/checkpoint/业务隔离及账本起点。F8 B 使用已暴露材料，只检验回归；F8 C 不提前创建样本。
新样本在方法冻结后构造，运行后全部按已暴露记录；若修改方法，旧失败继续保留，不能重称 unseen。
任何失败先记 Observed、Expected、实际链、首断点、至少两个解释、通用修复候选、混杂因素、最小下一实验及决定。
没有样本特定答案修正、追加措辞循环、真实并发调用、全量 benchmark、第二模型或 Product 迁移。

最终验收须证明每项工程合同的实际入口和消费路径。方法稳定必须来自新小样本的真实持久与业务链，
不能因窄工程检查通过就声明可靠。若证据不支持，明确 Pivot/Stop 与未达项，不把较小子集改称总目标完成。

## F9 最终处置

Stop 本轮单一候选修订循环；保留两版本完整结果和全部费用，不拼接为6/6、不放宽原完整性要求。
C十类新覆盖仍未运行；真实world/助手冲突未验证；44次生成均all，无Attention研究准入。
[最终验收清单](../data/manifests/next-development-v4-final-acceptance-20260928.json)区分工程完成、门槛失败和方法未达成。
这不是把v3负结果收口规则套用为v4方法成功；实际暂停来自用户任务结束后暂停的要求。
后续新方向需新的明确指令；原计划、历史ACTIVE和保留源码均不授权继续实验。
