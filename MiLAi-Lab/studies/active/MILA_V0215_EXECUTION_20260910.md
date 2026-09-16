# V02-15 开放研究执行记录

## 用户执行授权与范围

2026-09-10 用户明确要求详细阅读并执行 Goal v0.2，作为文档设计之后的新执行指令。
已完整读取 371 行，原始 SHA256 为
`64e65edd57949e08759841e20ff2e51ac39c1f49409d48440fa47ce365aa899b`。
本记录保留其 R0→R5 的条件分支，不将旧工程通过当成新机制证据。

首批 `V0215_R0_B1_20260910`：两个自制合成 cluster（软件交付诊断、研究申请审查），
各有错误初始交接、无关变化、相关变化三阶段。比较普通笔记 NOTES、普通适用性提醒
REMINDER、可纠正检查点 CHECKPOINT；顺序理由是既有冷恢复基础可直接检验新观察下的
控制使用，不需要先实现另一个系统。CHECKPOINT 是 A+C+E/B 外部化的探索 bundle，
没有把潜在收益先验归因给其中一个字段。

每个 task/arm/phase 启动真实新 Host 进程，消息不继承。共同合法源保留，只有该 arm
自己的公开 TASK State 可继承。错误交接是明确受控注入，三组同信息；不是自然外部失败。
所有正文、gold 和三阶段安排在执行前由研究者已知，只作为 discovery。阶段间变化事前
固定，不根据是否已保存或哪个 arm 成功调整。普通笔记组也能多读、多搜、记事、返回分支。

资源合同：18 phase slots × 最多 5 次请求，共最多 90 次本地 Qwen 请求；每阶段 300 秒、
整批 5,400 秒，12 source reads/4 searches，最多四个并发 source reads、一个模型请求在途。
65,536 context / 4,096 output / 12,288 final reserve；累计 raw cap 为 null。记录全部
构造/选择/保存/恢复成本；Judge/付费分配为零。State 写入只在自建隔离 PG/MCP 通过公开
CAS 发生，源文本和控制笔记不增加权限；不执行真实业务、部署公网、打开保护池或修改 Schema。

Host 使用冻结 Client 0.1.4 SDK；服务保留 MCP 0.1.15 / Client 0.1.3 / Runtime 0.1.4
hash-backend 交付。每次实际运行验证安装 pin；不把它当线上 BGE 或原 A0 的新结果。
基础设施仅在 Lab 新增探针及薄 runner，复用既有 Provider/预算/SDK/公开 State/回执。

首批制品目录：`/cra/memory/mx_memory/evidence/v0215/r0-b1-20260910`。
配置：`configs/v0215-discovery-b1.json`。旧 V02-10 至 V02-14 结果不变。

## 当前结论

终态：`NO_PROMISING_CANDIDATE_IN_THIS_BATCH / KEEP_SIMPLE`。R0 开放探索、R1 机制卡、
R2 选择备忘完成；本批选择 **0 个**候选进入 R3。没有以“必有创新/必跑确认”为目标。
R3/R4/R5 按 Goal 的条件分支未触发，不冒充已验证，也不据此否定所有持续记忆方向。
[机制卡与选择依据](MILA_V0215_MECHANISMS_AND_SELECTION_20260910.md)保留下一步可区分的解释。

## 执行故障与修复（原事实保留）

首批 State create 成功，但模型选择保存笔记时，更新调用遗漏正版本所需的 `state_id`。
9 次生成 / 23,642 raw 均已结算，9 个阶段为协议失败，余下 9 个未运行；3 个受控 seed
保存成功，模型自选笔记保存成功数为 0。先暂停本轮调度进程，待当时的子进程结束再触发
清理；没有中断正在传输的模型请求、没有未知用量。原 leaf result、公开错误回执、账本
和 manifest 保留，补充 `interruption.json`，不记为候选机制无效。

通用修复为 public GET 返回的 `state_id` + exact current version，增加 create/update
差异测试及真实接口形状的 mock。另让后续批次遇到该类 State 协议错误在边界停止，
避免继续消费同类失败。修复版 `r0-b1-repair1-20260910` 使用新环境和新源码封存；策略、
任务、模型及每阶段资源不变，最多使用原 90 次中的剩余 81 次，不擅自扩额。

## 近邻核对（服务 R1/R2，不是新颖性证明）

本次重新核对了原始论文页面。与本轮有关的具体区别为：

- [MemoBrain](https://arxiv.org/abs/2601.08079) 使用依赖感知执行记忆，并裁剪/折叠工作上下文。
  本轮没有上下文投影；这一区别本身不证明创新。
- [StateMem](https://arxiv.org/abs/2608.19652v1) 显式追踪 supersession/关系依赖并提出 wrapper；
  所以“更新 State 后使用当前事实”不能作为独有机制主张。
- [RuleMem](https://arxiv.org/abs/2609.03915v1) 从历史归纳规则以指导取证和推理；
  本轮短检查点不是其官方复现，普通提醒应当是强简单对照。
- [ReDNA](https://arxiv.org/html/2605.28465v1) 将反思及发散—收敛组合用于交互任务；
  仅记录未选路径或分开候选与行动不足以声称首次。

这些方法的 benchmark 分数未与本轮小型合成探针横比。本次没有训练、部署或复现这些方法。

## R0 全部尝试与成本

| 执行版本 | 已尝试/分配阶段 | 生成 / raw tokens | 结果及含义 |
| --- | --- | --- | --- |
| 原 b1 | 9/18 | 9 / 23,642 | State 更新缺少 state_id；9 协议失败、9 NOT_RUN；不评分机制 |
| b1-repair1 | 18/18 | 43 / 212,673 | 17 交付、1 无最终交付；两领域均含三个冷阶段 |
| delivery-diagnostic | 6/6 | 24 / 172,102 | 4 交付、2 无最终交付；通用决策语义说明未消除错误 |
| readiness-diagnostic | 6/6 | 12 / 49,654 | 6 交付；普通笔记/提醒各 2/2，检查点 1/2 |
| 全部实际开销 | 39 attempted | **88 / 458,071** | unknown 0，原 90 次分配内；未用 2 次随本批结束，不自动滚存 |

四个目录均在 `/cra/memory/mx_memory/evidence/v0215/`，后缀为 `-20260910`。
`observations-v1.json` 从实际 Provider 请求/HTTP/usage/tokenize 账本复算，明确保留 NOT_RUN
与 NO_FINAL_DELIVERY。原 batch 无 parent result 时，以 leaf results、interruption.json
和停止回执为准，未补造当时没有的 parent 成功终态。

| 版本/组 | decision 正确/attempted | 生成 | raw tokens | 模型自选 State 写入 |
| --- | --- | --- | --- | --- |
| repair1 / NOTES | 4/6 | 15 | 79,090 | 10 |
| repair1 / REMINDER | 5/6（1 无交付） | 16 | 84,201 | 10 |
| repair1 / CHECKPOINT | 4/6 | 12 | 49,382 | 6 |
| delivery / NOTES | 1/2 | 7 | 48,144 | 6 |
| delivery / REMINDER | 1/2 | 7 | 49,141 | 6 |
| delivery / CHECKPOINT | 0/2（2 无交付） | 10 | 74,817 | 10 |
| readiness / NOTES | 2/2 | 4 | 15,873 | 0 |
| readiness / REMINDER | 2/2 | 4 | 16,288 | 2 |
| readiness / CHECKPOINT | 1/2 | 4 | 17,493 | 2 |

这是每版本固定候选标签的描述性计数，**不是混合 accuracy、独立样本效果或显著性检验**。
共两个合成根 cluster；两个领域仍共享“前提变更”的工作流形态。重复使用 pipeline 和其
变体不增加独立样本数。17+4+6 次最终交付、3 次无交付与9次基础设施失败分别列出。
raw 不含开发代理劳动；没有 Judge/付费模型请求，GPU/货币等未测量量不推断为零。
共 203 次公开 MCP 调用、52 次模型自选成功 State 写入、15 次受控 seed 写入；写入均在
隔离的非 Canonical HOST_WORKING State，源文本没有进入 Canonical 表。

## 两次适应性诊断改了什么

delivery-diagnostic 选择已打开 pipeline 的阶段 0/2，保留三组政策及每阶段 5 请求，
共同明确“当前下一步建议不等于真实执行、不能跳过未满足前提”。这是领域无关的政策
改动，但来自已见失败；不得称为独立确认。此轮观察到知识已写入 State 却没有 final，
以及把来源未陈述的“应该自动触发 publication”当作决定依据。

readiness-diagnostic 进一步发现新薄 runner 没沿用 V02-14 的 readiness-first 顺序。
于是三组共同恢复 assessment→delivery，禁止空 read，并将原来已有的 final-only 槽
落实为输出合同。每阶段上界改为 3、整批最多使用原分配剩余14次；实际12次。源码、
输入合同和资源同时改动，**不能将跨版本改善孤立归因给其中一项，更不能归因给 State**。
原有完整来源、普通笔记能力和合法非最终槽工具保持可用；没有按 gold 选择决策或修输出。

## 评价、持久回执及边界

预先固定的 exact-decision v1 参考未修改。研究者以同一 task/来源逐一查看实际交付、
说明、引用及未交付末次动作；这是主开发代理的非盲离线判断，不是独立人工审核或另行
运行的 Judge 模型。该劳动计入代理追踪，不混入实验 Provider 的 raw 账本。
repair1 的 grant 九个交付均能区分 Call N/E，并在 amendment 后使用当前要求；pipeline
的提前 publication、已批准却继续等待、凭类比继续查 exporter 都保留为真实模型错误。
部分正确标签的说明用“无错误日志”作过强的排除性表述，标签正确不等于逐句完整语义正确。
readiness 下 CHECKPOINT 阶段0仍把“publication 需要 approval”与“现在可以推荐
publication”混淆；不重标成成功。

污染按可追溯现象报告：delivery/NOTES/phase2 将无 J42 证据的旧 exporter 类比用于最终
因果判断，还引入来源没有的自动触发假设。这是待解释的实例，不证明单独的联想因果效应。
不计算统一污染率：原方案没有预先冻结跨任务 claim unit，三个无最终交付不能算零污染。
源码读 ID、实际取得文本、HTTP 确认呈现和最终采信分别可回放，未把命中 ID 当证据已使用。

无关变化和相关变化的外生机会在 repair1 各有每组2次；各组均读到所需当前状态来源。
不把这种读取自动称“认知分支恢复”。CHECKPOINT 在无关变化的 pipeline 上发生错误决策，
grant 上则保持正确；不存在统一稳定性优势。再次读取未变版本是 POST_HOC_EXPLORATORY
计数，不能直接说是不必要的工作。只有两个合成 cluster，也没有随机化不同策略执行顺序。

39 个实际 Host 均已退出。跨阶段 GET 的 `state_id/version/payload` 与前阶段最后成功
公开写入逐字一致，PID 不同、继承消息为0；每 arm/task 身份隔离，未借用别组笔记。
这是持久机制回执，不是外部化收益。最后 readiness/NOTES 未写新笔记仍2/2说明简单取证
在该短探针足够，不能据此推断长中断任务不需要保存。所有阶段仍有共同完整合法来源。

## 工程门与复现

`uv run milai-lab-check-boundary`、`uv run ruff check src tests tools`、
`uv run mypy src/milai_lab`（39 文件）、`uv build` 均通过。
含实际 SDK wheel 的全套测试 **761 passed，9.76s**；新 V0215 定向测试9项通过。
默认 Lab 环境不强制安装 SDK；Product 代码、六份适配器锁、API/Schema/权限/迁移均未修改，
故未重复无关 Product 包门。真实 PG 是上述冻结公开包，未假装新 SDK 接管 MCP 子进程。

在 `MiLAi-Lab` 中用 `uv run --offline --locked --with
../MiLAi-Product/integrations/python-client/dist/milai_client-0.1.4-py3-none-any.whl python`
运行 `tools/run_v0215.py`。先通过 `--root NEW_ROOT --prepare-from INPUT_ROOT --config CONFIG`
封存，再通过 `--root NEW_ROOT --installed
/cra/memory/mx_memory/evidence/v0210-v05/e3a-20260909` 执行。
输入由 `tools/prepare_v0215.py --root NEW_INPUT_ROOT` 生成；使用对应的四份 `configs/v0215-*.json`。
每次使用新目录；旧 source snapshot 与评价不可覆盖，单元测试不发送真实模型请求。
最后 `uv run python tools/summarize_v0215.py --root NEW_ROOT` 生成一个新的 observations-v1。
配置中的历史授权不是未来自动运行授权，重跑需另有明确分配。

四个自有环境的 API/Host 均退出、各精确 Docker project 的 PG 均 exited，制品根0700、
卷及所有失败证据保留；未重启/停止共享模型、公网或他人服务。退出临时 SDK 环境和不选择
新研究入口即可回退，无数据库迁移或数据回滚。A0、OAuth部署及 Schema NO-GO 保持不变。
