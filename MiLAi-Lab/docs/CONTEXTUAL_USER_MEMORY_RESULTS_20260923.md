# 情境化用户记忆 Lab：实施与结果记录

本文件记录 [当前开发 Goal v3.0](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v3.0_20260923.md) 的持续实施状态；v2 的阶段结果按原样保留。
当前是 **RESEARCH_PROTOTYPE：八类生命周期与六候选已实现，固定小样本比较及一次 H5 确认已结束，默认普通记忆**。候选未证明稳定收益，长历史检查含未完成项；没有 Product 变更或正式全量效果结论。
用户要求先轻量查看效果、开发完全完成后再做大规模测试；formal-v2 已停止，不自动恢复全量运行。
前轮修复见“源码诊断与后续开发”；最新实现与结果见文末 v3.0 D1–D5 记录。下文各轮代码状态按当时快照记录，旧的“待完成”不覆盖文末新状态；此前答案、分数和成本保留原样。

## 本轮轻量效果

固定使用原有四道开发原题，选择清单早于判分：PersonaMem-v2 的 `train_text-000000`、`val_text-000000`，PersonaMem-v1 的 `acd74206-37dc-4756-94a8-b99a395d9a21`，LongMemEval 的 `e47becba`。
八个记忆臂答案来自 `final-answer-probe/`，QUERY_ONLY 使用最新明确无历史／无工具协议的 `query-only-final/`；没有从中断的正式批次挑题或挑答案。
记忆臂复用 development-v3 的历史快照，再按收尾答题协议恢复执行。这是分阶段开发比较，不是一次从头生成的正式 benchmark，开发题也不是未见 holdout。

| 原题范围 | 题数 | BASELINE 正确数 | CANDIDATE 正确数 | QUERY_ONLY 正确数 |
| --- | ---: | ---: | ---: | ---: |
| PersonaMem-v1 开发题 | 1 | 0/1 | 0/1 | 0/1 |
| PersonaMem-v2 train 开发题 | 1 | 0/1 | 0/1 | — |
| PersonaMem-v2 val 开发题 | 1 | 0/1 | 0/1 | — |
| LongMemEval-S 开发题 | 1 | 1/1 | 1/1 | — |

9/9 答题实例完成、原生格式有效且判分已解决。三道 PersonaMem 题的错误属于正常选错，并非格式错误；本小样本没有显示候选相对基线的正确性提升。
LongMemEval 使用官方 rubric＋固定 vLLM Qwen Judge，属于同模型自评，不能解释为独立模型验证。每个数据集仅 1–2 道暴露题，不支持总体效果结论，不合并为任意总准确率。

Sol xhigh 对这四题做了定向诊断：冻结输入的选项顺序与 loader 一致，未发现数据／评分错接。v2 验证题两臂各三次重复检索，随后各四次 `memory_read` 缺少 `ref` 被拒绝；这些重复操作没有取得新材料。搜索本身已返回正文，不能仅因 read 失败就断言 Host 没有取得任何证据，也不应强制为已取得的正文再调用 read。v1 两臂已检索到相关原文仍选错，候选另有两次把自然语言填进 `memory_state.intentions` 的错误。v2 训练题没有有效展开正确选项依赖的历史条件。这些是实际工具使用、选源和最终决策限制，不能将“答题完成”解释为所有工具操作成功或效果有效。

由此完成两项通用接口修正：`memory_state.intentions/conflicts` 明确只接受工具返回的精确引用、叙述放 `context`；native／JSON-action 两种模式都将内层 `status=ERROR` 标为外层 `ok=false`，完整结果和已成功保留的来源仍返回给 Host。新增两个行为回归验证错误进入下一次模型请求及工具轨迹；未为文案增加快照测试。
这些修正发生在上述答案冻结之后，**没有重新测量修正后的正确率，不宣称效果提升**。修改前两个生产源码保存在 `interface-receipt-fix/before/`，摘要与停止批次的 manifest 一致；当前源码不得以原 formal-v1/v2 身份续跑。

本轮新增 **0 次 Host 请求、2 次 Judge 请求，共 256 tokens**。此前为这些结果真实发生的历史摄取成本为 6,713,570 tokens（含 embedding），答题成本为 903,206 tokens（其中 Host 428,768、embedding 474,438）。这些已有成本没有隐藏或重复执行；历史 embedding 缓存跨臂共享，实际调用归于首先使用的臂。
分项请求、失败、耗时和来源答案 SHA 保存于 `artifacts/contextual-user-memory/lightweight-effect-v1/{manifest,summary}.json`，答案与原始轨迹保持冻结；GPU 时间未知。

利用本地已有答案复现此次判分（已存在的冻结评分直接复用）：

```bash
uv run python artifacts/contextual-user-memory/lightweight-effect-v1/score.py
```

若后续确需从头复现四题开发流程，可使用 `configs/contextual-user-memory-dev.json` 和标准 runner 的 `--phase develop`，输出到新目录；本轮没有再次执行历史摄取，也没有扩大原题清单。

## 实现与接口

- `src/milai_lab/methods/contextual_user_memory.py` 复用 MemoryCard、Workspace 稀疏 patch、ExperienceBank 向量选择和 Attention；提供统一 `memory_search`、`memory_read`、`memory_save`、`memory_state`。
- 适配器通过 `publish(Observation(...))` 绑定原始角色、制品及事件身份；模型不能自填作者。原文不可修改，取得纠正可显式声明 `supersedes`；记忆修订依赖已读版本，旧版本保留，过期依赖显式标识。
- 同一用户有独立 bank 和当前任务 State。情境改变查询；Host 可依据新材料更新情境或修订持续理解。材料包保持完整单元，原文过长可按明确字符范围读取。来源展开去重，GAP 可以执行一次有界补充检索，仍需 Host 判断覆盖。
- checkpoint 将长期记忆与显式任务域对象分开；未保留的原始历史不自动全部写入用户 bank。新任务使临时对象过期，显式交接携带相关临时对象并保留新问题。遗忘删除对应历史版本和派生记录。
- `tools/contextual_host_adapter.py` 是真实 HTTP vLLM 驱动；当前端点采用显式 JSON-action，支持工具 schema、实际分派与回执。模型调用预算包含最终回答，截断/耗尽不充当正常答案，缺失 usage 保持未知。
- `datasets/contextual.py` 提供三种原生 loader，评分字段留在 EvaluationCase，Host 只取得 TaskInput。`scorers/contextual.py` 提供原生 MCQ 解析和 LongMemEval 官方 rubric。12 种题型／拒答分支的模板已与固定官方源码逐字比对。
- `tools/run_contextual_user_memory.py` 装配顺序历史摄取、两主臂、v1 QUERY_ONLY、按题恢复、历史与 embedding 缓存、答案冻结、独立 Judge 和分数据集结果。四道固定原题的端到端联调已完成；正式批次按用户最新要求停止，输出保留。

最小操作示例（引用由真实回执返回）：

```python
source_ref = memory.publish(Observation("event-1", "original text", "user", "artifact-id"))
receipt = memory.dispatch("memory_save", {"source_ref": source_ref, "content": "Host interpretation"})
target_ref = receipt["record"]["ref"]
memory.dispatch("memory_read", {"ref": target_ref})
memory.dispatch("memory_save", {"target_ref": target_ref, "content": "revised interpretation"})
```

## 数据与暴露

原始文件在 `/cra/memory/mx_memory/benchmarks/`，不入 Git。三个 `data/manifests/contextual-*.json`
固定来源版本、路径、摘要和协议；适配器不修改原文／角色／顺序／标签。

| 数据 | 当前证据与范围 |
| --- | --- |
| PersonaMem-v1 32k | 589 题、37 个共享 context、222 个合法截止历史；全量 loader 已读取验证格式 |
| PersonaMem-v2 text | val 2,061 题、benchmark 5,000 题；train 已按固定 revision 重取，真实为 18,549 行；全 split 仍引用 999 份历史，1,002 个 v2 文件均与上游大小／LFS 哈希一致 |
| LongMemEval-S cleaned | 复用现有固定文件，全 500 题；摘要匹配原 manifest，已有历史 Lab 暴露 |

v2 train 的问题由 Sol 在格式验证中发现：初次落盘 109,055,741 bytes，而上游固定制品应为
157,116,318 bytes，官方 LFS SHA-256 为
`62abb042f529818a22be4ced84b683364f000af68608008c20186527740276d6`。
本地自算 SHA 只能证明本地文件身份，不能证明下载完整；未以截断文件开始正式评估。
完整 train 已重取且官方大小／LFS SHA 均匹配；v1/v2 合计 1,004 个文件均经上游大小和 Git blob／LFS 哈希核对，0 mismatch。manifest 与开发配置已更新。

开发题 ID 固定于 `configs/contextual-user-memory-dev.json`，仅作为原题外置选择清单。
这些题留在正式全量范围中，后续报告必须披露开发暴露；不宣称未见 holdout。

## 已取得的运行证据

- 34 项新增定向回归：核心 15、Host 11、数据／评分 3、runner 3、embedding 2；最终一次合并执行为 **34 passed，0.60 秒**。runner 回归验证合法前缀、失败后续跑、题目 overlay 隔离及分母／实际成本。
- 真实 vLLM 工具闭环：`artifacts/contextual-user-memory/host-contract-smoke/result.json`；
  Host 调用 `memory_save` 后调用 `memory_read`，正常结束，实际两次工具操作；usage 为
  2,954 prompt tokens、127 completion tokens、3,081 total tokens。
  这是工程传输验证，使用工程 fixture，不是 benchmark 分数；该闭环未使用 embedding；另一次真实 embedding 连接检查已返回 1,024 维向量，回执存于同目录 `embedding-trace.jsonl`，尚非检索效果证据。
- Host 端点：`http://127.0.0.1:7860/v1/`，served model `Qwen3.6-35B-A3B-FP8`，服务窗口 65,536。
  embedding 端点：`http://127.0.0.1:7861/v1/`，`bge-m3`，服务窗口 8,192。
- 配置中的 Judge 暂用同一个 vLLM 模型；必须标记同模型自评。Host/embedding 的实际权重 SHA-256 和配置／模板文件哈希已生成外置制品，并绑定到第三轮开发配置；当前正式配置为 `configs/contextual-user-memory-formal-v2.json`，原 v1 配置保留。

最终包检查：package／tools boundary、Ruff、mypy 69 个模块及 sdist/wheel 构建均通过。
全包 pytest 为 **4,959 passed、19 skipped，3,828.55 秒**；跳过项为缺失的可选 Host SDK 或外置历史 tokenizer 证据。
该进程在收尾修改前开始；最新受影响切片以定向回归补充，未重复运行整个重型历史回归。

首轮原题开发运行 `artifacts/contextual-user-memory/development-v1` 已停止（进程确认退出 143）。
v2 train／val 两臂均未完成历史构建；轨迹显示无效 JSON、自创 `target_ref` 名称，以及每段四次
模型调用耗尽。运行器没有把这些历史标为 BUILT，也没有提供完整主分数。该失败证据保留。
第二轮 `development-v2` 已停止（原 session 32040 确认退出 143），证据保留。
JSON-object 输出约束和引用说明促成真实成功保存，但长工具响应仍触及输出上限，最后一次请求也可能继续调用工具。
第三轮 `development-v3` 保持同四个开发 ID，输出预算 4,096 tokens、每段八次模型响应；
截断响应不执行工具，在同一预算内反馈并允许短操作重试；最后一次请求使用实际端点已验证的 final-only JSON schema。
解释通常限制在 250 词，以来源引用保留原文。并发固定为两组，共用历史题目在组内串行；Judge 在每个数据集答案冻结后单独串行。
模型自行决定工具动作，版本和用户隔离检查保持启用。以上修改发生于开发阶段，当时尚未开始正式评估。

第三轮 train／val 的四个答题实例均已完成，并按原生 scorer 记录错误／格式错误；不据此改评分规则。
train 两臂首轮直接回答且未访问记忆，Sol 仅查看调用协议（未读 gold）后发现答题消息未明确说明历史已摄入工具。
随后用相同 train checkpoint 在新进程做一次独立 answer-stage 实际验证：说明历史已在工具中，先咨询相关记忆，最后才按指定格式回答。
两臂各完成 7 次实际工具操作并产生符合 v2 原生格式的答案；未作正确率筛选，原第三轮回答保持冻结。
证据在 `artifacts/contextual-user-memory/answer-protocol-probe/`，包括脚本、协议、来源 checkpoint 摘要、完整 HTTP／embedding／工具轨迹及结果。
Host tokens 分别为 BASELINE 90,386、CANDIDATE 109,102；embedding 另见原始 trace，未重新摄取历史。
这也验证了新进程从真实历史 checkpoint 恢复后仍可检索和读取来源。协议澄清已在第三轮正常结束后纳入最终 runner；没有在运行中修改其代码。

成本统计扫描每个数据集／split 下真实 trace，按 arm 与 history/answer/judge、LLM/embedding 分列。
SQLite embedding 缓存可跨两臂复用，因此其实际请求计入首先发生请求的臂；该成本是本次共享运行实际开销，不能解释为各臂独立冷启动成本。
缺失 usage 与不可归属的共享端点 GPU 时间保留未知；请求 wall time 不当作 GPU time 或批次总 elapsed。


## 子代理与已知余项

用户最新澄清：**仅数据／项目／测试集下载用 Luna high；其他任务按 Goal 的模型档位执行**。
初期误将 Host／数据适配及一次审查也分给 Luna high，已停止；Sol xhigh 接续实现和语义审查。
审查发现的临时对象恢复、旧版本遗忘、原文分页及 GAP 扩展问题已经修改并加入最小回归。
收敛审查进一步修复了旧 handoff 在 forget 后复活内容、重复发布造成来源版本回退、临时替代来源的恢复／清理及检索遗漏当前来源。
未 save 的来源仅当前任务可用；answer runner 在开始新任务后才发布合法原历史，避免被任务切换清理。
后续下载修复仍由 Luna high 负责。主会话模型由环境固定，不能通过子代理设置切换；
子代理 tokens 与服务费用未提供，记为未知，不用静态价格估算。

## 最终收敛与正式执行

第三轮 `development-v3` 已正常退出 0，四道固定原题产生 9 个完成的答题实例及对应原生评分／Judge 回执。
这些仅是开发证据：v2 train/val 均记录错误，部分为原生格式错误；v1 三臂均错，LongMemEval 两臂均被固定 vLLM Judge 判对。
不据此选策略、改分数或报告正式效果。

最终协议下，在 `final-answer-probe/` 用同四题、原冻结历史 checkpoint 重做答题阶段，9/9 完成且格式有效；
新协议让历史臂先咨询可用记忆，最终响应保留题目规定格式。它使用真实 Host/embedding，不重做不变的历史摄取，也不挑选正确率。
候选独有的 `memory_state` 仅向候选暴露；基线保留正常保存、读取、更正、来源与语义检索，仍可在显式查询和记录中表达情境。
QUERY_ONLY 另用 `query-only-final/` 验证了明确无历史／工具的控制条件：0 次工具尝试、格式有效、659 Host tokens。

LongMemEval 原始消息长度检查发现超过 bge-m3 8,192-token 上限的输入，最长 17,230 tokens；仅检查长度，未查看正式 gold 或按效果筛题。
`contextual_embeddings.py` 对超限文本保留全部 token，按固定 tokenizer 的 special-token 规则分窗，以原 token 数加权并 L2 归一化合并向量。
短文本路径保持不变，来源原文和 read 单元不分割。真实端点探测验证短文字符串／token IDs 向量完全一致，以及 9,001-token 工程文本两窗调用成功；
证据在 `embedding-window-probe/`。正式配置固定 tokenizer 文件 SHA、8,192-token 窗口和池化策略。

已停止批次的正式配置：`configs/contextual-user-memory-formal-v2.json`。固定 v1 589 题（三臂）、v2 benchmark_text 5,000 题（两臂）、LongMemEval 500 题（两臂），合计 **12,767 个答题实例**。该范围后置，不是本轮继续执行的任务。
每个数据集全部答案冻结后才进入正式评分；缺失／失败不改写为完成。输出保留在 `artifacts/contextual-user-memory/formal-v2/`，未完成全量、未产生正式分数。
原 `formal-v1` 使用 16 个独立历史组、串行 Judge，服务 KV 容量为 1,303,769 tokens／19.89 个完整序列。实际运行发现大量重复 prefill 和 Host 请求超时，因此单独检查运行时缓存。
Sol xhigh 只读核对了已安装 vLLM 0.27.1 的混合模型实现：需在启动时启用 `--enable-prefix-caching --mamba-cache-mode align`；`all` 不受该模型支持，现有服务不能热启用。
新实例使用同一已有 Docker 镜像、只读权重、模板、TP2 和 65,536 窗口，在 GPU 2/3、`127.0.0.1:7873` 独立运行，显存比例为 0.80；未停止或改动原共享服务。
`prefix-cache-probe/` 保存启动参数、运行时身份、日志和合成输入检查：16 路冷请求共 47.38 秒，重复热请求共 2.12 秒，热轮前缀 token 命中率 95.75%，32/32 请求完成且 JSON 有效，0 preemption。这是缓存工程证据，不代表全评测加速比例或效果分数。
新实例实际 KV 容量为 874,763 tokens／13.35 个完整序列，故 `formal-v2` 固定并发 12；Judge 仍在原 7860 端点串行运行。方法源码、权重、数据、提示及调用预算保持一致。
vLLM 将混合模型缓存标为实验性，不承诺逐 token 数值一致；因此完整范围使用新版本重新生成，不复用或拼接 v1 的答案／历史。没有读取正式 gold 或正确率来选择运行时。
`formal-v1` 已于 2026-09-23 11:12 UTC 停止并确认 exit 143：保留 93 个已完成答案（BASELINE 28、CANDIDATE 28、QUERY_ONLY 37）、17 份完成历史、3 次 ReadTimeout，以及至少 14,642,885 个实际回执 tokens（含 embedding）；尚未评分。
其 `interruption.json` 和 `interrupted-summary.json` 记录原因与分项成本。中断时未返回的请求 usage 未知，已知 tokens 是下界；失败成本单独保留，不算入新版本的效果。
方法源码、依赖锁、模型及数据身份由运行 manifest 固定；同输出目录拒绝不同源码／配置续跑。

原正式启动命令仅作复现记录；当前不要续跑：

```bash
uv run python tools/run_contextual_user_memory.py \
  --config configs/contextual-user-memory-formal-v2.json \
  --output artifacts/contextual-user-memory/formal-v2 --phase evaluate
```

用户于 2026-09-23 11:23 UTC 要求先轻量查看效果。formal-v2 已停止并确认 exit 143：保留 67 个完成答案（BASELINE 18、CANDIDATE 17、QUERY_ONLY 32）、15 份完成历史、0 失败记录和至少 11,914,486 个实际回执 tokens（含 embedding），中断请求的未返回 usage 未知。
专用容器 `milai-contextual-prefix-probe` 已停止，原 7860/7861 共享服务未改动。当前没有全量任务运行。
本轮固定四题判分、问题分析、两项通用接口修复及开发交付已完成；完整全量评价明确后置。后续效果优化应关注检索覆盖、工具参数使用和证据到最终选项的推理，不扩大测试规模来替代修复，也不按开发题 gold 添加特例。

本轮没有修改 Product Schema、公开 API、权限或 Canonical 行为；不涉及产品 pin 门禁。
尚未创建提交／回滚 tag 或核对远端提交，当前代码和证据保留在工作树。历史用户改动未覆盖。

当前本地工具会话（续作先轮询实际句柄）：

- `96508`：正式 `formal-v2` 已按用户范围调整停止，exit 143；`33433` 已确认专用缓存容器停止，exit 0。
- `13247`：固定四题的轻量评分完成，exit 0；新增两次 Judge 请求，256 tokens。
- `91035`：原 `formal-v1` 已停止，exit 143；`33284` 的独立缓存检查已通过，exit 0。
- `85342`：全包 pytest 已正常退出 0，4,959 passed / 19 skipped。
- `37116`：第三轮固定原题联调已正常退出 0。
- `14094`：最终九个答题阶段验证已正常退出 0；`63810` 的 QUERY_ONLY 补充验证及 runner 定向检查也退出 0。
- 审查代理误启动的一次重复全包 pytest（session 75896）已停止、exit 130；未当作包检查完成证据。

Sol xhigh 完成核心／Host 修正、runner 审查、协议诊断与 embedding 分窗实现；下载工作使用 Luna high。
前轮按 Goal v2.2 记录为完成开发与轻量交付。最后两项接口修正后，34 项定向回归、全目录 Ruff、mypy、package boundary 和构建通过；未重跑已通过的重型全包 pytest，也没有追加真实 Host 请求。下文源码诊断重新打开了开发工作；原始判分与运行记录继续保留。

## 源码诊断与后续开发（2026-09-23）

### 判断与证据范围

**当前实现具有可运行的记忆原型、数据适配和实验记录，但“完整开发完成”的判断过早。** 问题既有确定性的状态／版本接入错误，也有过高的模型交互成本和未分离清楚的方法贡献。继续扩大题数不能修复这些问题。

本次核对实际工作树、上述冻结结果及工具轨迹，并用无模型脚本复现核心错误。仓库基线仍为 `5f233a16829b9c2db603153b0e7d28dd6edb2188`，但新增 contextual 文件尚未提交，**该 commit 不能代表被评估的新实现**。本轮修改前 `contextual_user_memory.py` SHA-256 为 `f57e3c32ac8d320b75d3a7d60de13d2bbbffe2ca5011fb3dd9240c3b253aba04`，对应核心测试为 `123ef9ce4089863e8369908891fd3ab1cb63e53152b320f3aba3721ebd361f1e`。

必须分开三类结论：四题轨迹证明发生过的行为；无模型复现证明的程序错误；需要后续固定版本测量的优化假设。下面的核心错误不能未经轨迹归因就宣称是三道 PersonaMem 答错的直接原因。既有来源身份、版本引用、删除传播、原生数据适配及成本记录值得保留，当前没有发现需要修改测试集或评分答案的理由。

### 已定位的问题

下表的行为以本轮修复前源码为准，修复范围和验证另列。

| 优先级 | 具体问题与证据 | 应采取的改动 |
| --- | --- | --- |
| P1：状态错误 | [update_state](../src/milai_lab/methods/contextual_user_memory.py) 先修改 `self.state` 再应用 Workspace patch；save 的卡片上限为 10,000，state patch 却沿用默认 64。无模型复现：保存 65 卡后，状态更新返回 `ACTIVE_CARD_CAPACITY`，但情境与 intentions 已改变，Workspace 未改变。 | 复用 [apply_workspace_patch](../src/milai_lab/methods/controlled_workspace.py) 的纯提案合同，先算新 State 和 patch，成功后一起赋值；统一容量设置，不增加事务框架。 |
| P1：覆盖判断错误 | 每次 search 都把同一个 `state.coverage` 字符串包装成针对新 query／snapshot 的 `CoverageReview`。两卡复现：alpha 被判充分后搜索 beta，语义基线为 beta，旧 alpha 仍可压过它。 | 覆盖只绑定 Host 实际收到的那次搜索及版本、选集；查询、情境或材料改变后回到 UNKNOWN，禁止自动重新认证。 |
| P2：扩展接线不完整 | GAP 分支取得新材料，却用原 snapshot 再调用 Attention。复现得到 `ABSTAIN_MEMORY` 和空主材料，同时扩展列表中已有新卡。 | 按 [decide_attention 的调用说明](../src/milai_lab/methods/state_attention.py) 合并取得的材料后再决策；新材料的充分性仍未知，所有返回正文共享预算并去重。 |
| P2：历史依赖显示错误 | 保存旧卡时把当时的 `dependency_status` 一并存入 history，读旧版本不重算。来源后来被纠正时，现版显示 NEEDS_REVISION，旧版却仍显示当时的无失效状态。 | 历史正文和当时引用保持不变；当前依赖状态在读取时计算。历史事实与当前适用性分别表达。 |
| P2：恢复身份缺口 | restore 接受新 embedding 回调，同时原样使用旧向量。二维基向量互换的复现中，恢复实例检索 alpha 错返 beta，新建实例正确。 | checkpoint 绑定实际 embedding 模型／权重及分窗策略的身份；不匹配时重建派生索引。标准 runner 已把配置纳入缓存身份，降低了固定批次的风险，不能据此断言已有结果使用了错配向量。 |
| P1：昂贵且无进展的交互 | v2 val 每臂重复三次同一搜索、四次缺 ref 的 read；前述工具文案和错误标志修正后还没有真实 Host 复测。[Host 循环](../tools/contextual_host_adapter.py) 继续累积并重发这些材料，普通 JSON-action 回合只限制为 JSON object。 | 将现有工具参数 schema 用于实际生成约束；相同状态下重复的只读调用返回紧凑回执，连续无进展时结束该工具循环并如实标记。不得把重复写操作随意去重，也不以更多重试掩盖错误。 |
| P1：历史构建性价比差 | [build_history](../tools/run_contextual_user_memory.py) 每段开启多轮 Host 操作，提供已有记录的 ID 列表，却不直接提供相关记录的精简内容。四题历史摄取约 671 万 tokens，答题约 90 万 tokens，均含 embedding；候选尚无正确性收益。 | 将历史摄取改成有界批量提案：相邻原始消息＋相关已有记录视图→一次 Host 批量操作提案→既有记忆操作执行。首先减少必须由模型往返完成的步骤。 |
| P2：贡献与运行协议不够清楚 | 答题阶段重新发布全部合法原始历史，既可搜整理，也可搜原文；当前两臂对照不能单独说明昂贵的历史整理是否值得。runner 在局部异常后仍会评分已有答案，未建立“全数据集答案冻结”的完整屏障。 | 增加便宜的原文检索控制，分开看 State 增益与整理增益；正式评分前固定本次答案集合及失败／缺失项。若只冻结部分批次就明确称部分批次，后续补答另记。没有发现 Judge 结果被传给 Host 的证据。 |

另一个容易误读的合同是：`intentions` 引用在 `coverage=UNKNOWN` 时不能保证覆盖语义基线。这是既有 Attention 的回退规则；State 的情境正文仍会改变检索 query。应说明何时状态影响 query、何时允许改变材料选择，不能为了显示“Attention 生效”就默认设置 SUFFICIENT 或偷偷改变 baseline。

当前向量发现还存在需要验证的限制：来源和整理按单向量排序，长消息的多个 embedding 窗口最后池化成一个向量；大于材料包上限的完整单元可能不进入首轮材料。分窗解决了端点长度限制，**尚未证明解决了长消息中的细粒度召回**。不要把它报告成已证实的答错原因；下一增量可比较派生片段索引，再按原始消息、范围和版本回读，原始测试文件保持不变。

`complete` 只表示 Host 输出了最终字符串；格式有效、调用成功、取得相关材料和回答正确须分开记录。`memory_search` 已返回正文，未调用 `memory_read` 并不等于没有看到证据。先分析材料里缺了什么条件、模型采用了什么，再判断应修检索还是最终决策。

### 实际阅读的开源实现

以下引用固定到本次取得的提交及源码，未运行这些外部项目，没有把其托管产品能力算作开源能力。许可证分别核对了 [LangMem MIT](https://github.com/langchain-ai/langmem/blob/9d033b47d9ce53e37e92c92241b0496c0278932e/LICENSE)、[Mem0 Apache-2.0](https://github.com/mem0ai/mem0/blob/f8082a7345dadd9e042ebbc40b57b1498c8f6d63/LICENSE)、[Memobase Apache-2.0](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/LICENSE) 和 [Graphiti Apache-2.0](https://github.com/getzep/graphiti/blob/16cdf7045378c8d53ae01f94e2fa60d238cb0f68/LICENSE)。源码只读下载到临时目录，没有增加项目运行依赖或复制整套框架。

随后按用户要求，由 **Luna high** 将这四个官方仓库的源码完整浅获取并固定到上述提交，保存到仓库外的 `/cra/memory/mx_memory/reference-sources/contextual-v2.3/`。四份 checkout 的 HEAD／origin 均匹配，工作树干净，Git 对象检查通过；下载清单记录 tree SHA、LICENSE SHA-256、文件数和时间。入口见[本地源码索引](../../../reference-sources/contextual-v2.3/README.md)及[下载清单](../../../reference-sources/contextual-v2.3/download-manifest.json)。已逐一定位批量提案／embedding、上下文预算、混合召回／RRF 和简单记忆工具的实际函数；本次下载未改方法实现、运行依赖或开发完成状态，R1–R4 仍按下文推进。

| 项目与固定提交 | 已核对的实现 | 对 MiLAi 的实际用途与限制 |
| --- | --- | --- |
| LangMem `9d033b47d9ce53e37e92c92241b0496c0278932e` | [knowledge/tools.py：manage_memory 与 search_memory](https://github.com/langchain-ai/langmem/blob/9d033b47d9ce53e37e92c92241b0496c0278932e/src/langmem/knowledge/tools.py#L271)：按 content/action/id 执行写入；搜索直接返回记录内容。 | 保持简单的保存／修改／删除意图，并让搜索结果可以直接用于工作。无需另加 Evidence/Note 分类模型。此实现不能替代 MiLAi 的来源、版本与权限合同。 |
| Mem0 `f8082a7345dadd9e042ebbc40b57b1498c8f6d63` | [memory/main.py：_add_to_vector_store](https://github.com/mem0ai/mem0/blob/f8082a7345dadd9e042ebbc40b57b1498c8f6d63/mem0/memory/main.py#L917)：先找相关已有记忆，单次提炼调用产生一组记录，再批量 embedding／持久化。 | 借用批处理与“提供相关旧内容”的执行形态，减少逐条工具往返。提案仍由当前 vLLM Host 生成，MiLAi 自己执行版本和来源操作；不照搬其 additive 语义、解析兜底或以文本 hash 合并不同来源事件。 |
| Memobase `358c16bbc6d687937d79bc2f984a11c3be8da901` | [buffer.py](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/controllers/buffer.py#L66) 按累计 token 触发处理；[context.py](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/controllers/context.py#L115) 组合 profile 与 event gist 并分配 token 预算。 | 借用有界摄取及查询相关的紧凑上下文包。MiLAi 保留原始来源和可展开引用；event gist 本身是整理，不能当原文。该项目处理链包含多次模型处理，不能直接推断整套系统更便宜。 |
| Graphiti `16cdf7045378c8d53ae01f94e2fa60d238cb0f68` | [search.py](https://github.com/getzep/graphiti/blob/16cdf7045378c8d53ae01f94e2fa60d238cb0f68/graphiti_core/search/search.py#L283) 组合全文与向量候选，再按配置做 RRF／MMR 等排序；[nodes.py](https://github.com/getzep/graphiti/blob/16cdf7045378c8d53ae01f94e2fa60d238cb0f68/graphiti_core/nodes.py#L318) 保留 episode 原始内容，[edges.py](https://github.com/getzep/graphiti/blob/16cdf7045378c8d53ae01f94e2fa60d238cb0f68/graphiti_core/edges.py#L267) 保存派生关系的 episodes 引用。 | 借用多路召回、融合及共同出处去重；先在现有 Lab 索引实现小范围对照，无需图数据库或实体抽取流水线。检索排序和来源链接都不自动证明陈述真实。 |

vLLM 的 [Structured Outputs 官方文档](https://docs.vllm.ai/en/stable/features/structured_outputs/)明确支持按 JSON Schema 约束输出。当前适配器末轮已使用 final-only schema；下一步应把普通回合的“最终回答或某个工具及其必填参数”也编成互斥操作分支。仍需针对实际部署版本验证兼容性；schema 可以减少缺字段，不能保证 ref 来自真实记录或最终推理正确。

**基于源码开发的含义是复用已明确的行为和边界，再验证适配结果。** 本轮核心修复首先依据仓库自身 Workspace／Attention 合同；外部实现用于确定后续批处理、上下文组织和检索结构。不是把四个框架串成流水线，也不是看过 README 就重写一套近似代码。

### 开发顺序与代码结构

| 顺序 | 改动落点 | 完成条件 |
| --- | --- | --- |
| R0：修正核心合同 | `contextual_user_memory.py`，复用 `controlled_workspace.py`／`state_attention.py` | State 失败无半提交；coverage 不跨 query／版本冒用；GAP 新材料进入二次决策；历史读取显示当前依赖状态。先做确定性回归。 |
| R1：收敛 Host 协议与回执 | `contextual_host_adapter.py` | 实际生成约束包含每个工具的必填参数；重复只读动作不会反复塞入相同正文；无进展与正常最终回答可区分。已有搜索正文足够时直接回答。 |
| R2：批量历史提案 | 从 runner 的 `build_history` 提取一个专用函数；仅在出现独立职责后拆文件 | 将原始消息和相关旧记录交给同一 Host，一次返回多项提案；服务端沿用 save/read 的来源和版本要求。允许空提案；逐项回执和部分失败如实保留，不承诺跨对象原子提交。 |
| R3：补齐检索与索引身份 | 现有 embedding 缓存及检索实现 | 来源索引与可修订记录索引分别更新，共同返回；索引身份含实际 embedding 配置。必要时增加派生片段／关键词召回与 RRF，先证实缺失的条件能被找到，再考虑额外 reranker。 |
| R4：轻量比较与报告 | 既有 runner、原题清单和结果表 | 用同一新版本、同一模型及预算比较；显示原文检索控制、已有记忆基线和情境候选各自贡献。答案及失败清单先冻结，需 Judge 时只使用 vLLM。 |

代码结构按数据流保持直接：**来源取得 → 有界 Host 提案 → 版本化记忆操作 → 索引 → 按问题组织材料 → 最终回答**。TaskState 的覆盖绑定只归一个位置负责；runner 只负责编排、配置和结果保存；Host 适配器只负责协议与调用。先解决已有函数的职责交叉，不预建通用 Agent 工作流、后端插件系统或第二个语义审核模型。

R1–R3 是后续增量，不能写成已从开源项目移植完成。批处理、混合召回与 profile/event 分层已有明确先例；MiLAi 的研究价值需要在同等条件下证明来源与更正语义、情境适用性和成本的共同收益，当前四题不足以支持创新性或有效性结论。

### 最少的验证与本轮交付边界

核心变更只扩展真实缺陷所需的确定性用例，并运行受影响的 contextual、Workspace、Attention 切片及包边界／静态检查。已有全包 pytest 用时约 64 分钟；本轮不为局部修复再跑一次重型历史回归，不新增测试平台。核心模型行为尚未复测，修复通过单元检查不等于 PersonaMem 正确率提高。

后续轻量比较继续用已经暴露的四道固定原题；不替换问题、选项、历史、标签和官方 rubric，不按 gold 加词表或路由。摄取策略改变必须在新输出目录重建相关历史；仅答题协议改变才可复用同版本兼容 checkpoint。旧 formal-v1/v2 和冻结答案不得用新源码续写。

报告至少分开：正确／错误／未完成、实际取得的新材料、重复无效操作、来源／版本错误、history／answer／embedding／judge 的调用与 tokens。共享缓存的实际花费与独立冷启动成本分别说明。开发 Agent 延续 Sol xhigh 常规档、Luna max 窄任务、Astra xhigh 疑难问题的分工；下载按已有执行约定使用 Luna high，普通修复不再叠加一轮常驻审核。

### 本轮实际修复与验证

本轮修改 [记忆核心](../src/milai_lab/methods/contextual_user_memory.py) 和 [核心单元测试](../tests/unit/test_contextual_user_memory.py)，完成了 R0 的四项确定性修复：

- `memory_state` 先计算新状态和合法 Workspace patch，再一并提交；两条写入路径使用相同卡片容量。
- 覆盖绑定保存在服务端，Host 不新增抄写回执 ID 的负担。先搜索，再单独提交 coverage；同时改变情境／intentions 与提交非 UNKNOWN coverage 会被拒绝。新查询、状态或来源版本变化清除旧绑定，新任务／handoff 不继承旧充分性判断。
- GAP 新取得的来源合入 snapshot 后重新执行 Attention，覆盖保持 UNKNOWN；主材料与扩展材料去重并共用正文预算。扩展后的充分性尚未自动建立，需要后续对具体查询和选集重新确认；这不代表完整的 Host 自适应策略已经验证。
- 旧卡保留当时正文和引用，读取时计算当前依赖版本及来源更正状态。

方法／checkpoint 格式升级为 **`contextual-user-memory-v2`**。旧 v1 checkpoint 不用新实现恢复，冻结实验及其源码身份不改。修复后核心 SHA-256 为 `5a43c35bf0169ab176a41c208045c3d047eaf3b22c9bf0c68a6665a274e1f0c7`，核心测试为 `d0e43a91068c9c3536c2b23ee8548a643ef5b62c15ff5f54f0100cf44d87f297`。

验证结果：核心 **18 passed**；合并 contextual 五个文件、Workspace 和 Attention 的受影响切片为 **127 passed，0.81 秒**。包边界、tools 依赖边界、全目录 Ruff、mypy 69 个模块、sdist/wheel 构建通过。命令在 Lab 目录运行：

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_contextual_user_memory.py tests/unit/test_contextual_host_adapter.py \
  tests/unit/test_contextual_runner.py tests/unit/test_contextual_datasets.py \
  tests/unit/test_contextual_embeddings.py tests/unit/test_state_attention.py \
  tests/unit/test_controlled_workspace.py
.venv/bin/milai-lab-check-boundary
.venv/bin/milai-lab-check-tools-boundary
.venv/bin/ruff check src tests tools
.venv/bin/mypy src/milai_lab
uv build --offline
```

本轮新增 **0 次 Host、0 次 Judge 请求**，没有新正确率或成本收益结论；未重跑重型全包 pytest，未运行外部项目。embedding 身份绑定、批量摄取、普通回合生成约束、无进展处理和批次冻结语义仍是未完成项。仅改变 Lab 方法合同和文档；Product API、权限与 Canonical 行为无变更，原测试集及历史答案保持不变。没有创建 commit／回滚 tag 或核对远端新提交，改动保留在工作树；不能用基线 commit 代替这些尚未提交文件的回滚副本。

## 本地 ReFind／ReMe／OpenViking 源码增补（2026-09-23）

### 阅读身份与当前结论

本次使用用户已下载的三个本地目录，阅读存储／模型、默认配置、摄取、检索、材料组织、相关测试和许可证。未安装或运行这些项目，未读取测试答案来设计检索规则。**适合 MiLAi 的增量是会话与时间定位、范围展开、预算内材料组织和增量修订；源码并不支持直接把三套系统叠加为默认运行链。** 实施规划已写入 [Goal v2.4](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v2.0_20260923.md) §3.5–3.8、§8.3。

| 本地源码 | 实际身份 | 引用边界 |
| --- | --- | --- |
| [ReFind](../../../ReFind/docs/METHOD_CARD.md) | origin `https://github.com/imlrz/ReFind.git`；HEAD `a80175ca0eeb52a938d7cab7a602bc780de8a577`；工作树干净；[MIT](../../../ReFind/LICENSE) | 这是作者的挑战适配实现；区分源码行为、论文方法和 README 成绩，本次没有复现其效果 |
| [ReMe](../../../ReMe/reme/__init__.py) | 包版本 `0.4.1.6`；目录没有 `.git`；[Apache-2.0](../../../ReMe/LICENSE) | 使用根目录 `reme/`，不使用 `build/lib` 副本；无法把这份混合快照标成某个官方提交。`search_v2.py` 明确标注 local fork，必须与默认 `search.py` 分开 |
| [OpenViking](../../../OpenViking/openviking/retrieve/hierarchical_retriever.py) | origin `https://github.com/volcengine/OpenViking.git`；HEAD `499995f3ed2e7f551a715179c4053772c51ff819`；工作树干净；[AGPL-3.0](../../../OpenViking/LICENSE) | 以当前 checkout 的具体分支为准，QUICK 与 THINKING、摘要视图与全文、同步返回与后台完成不能混称 |

ReMe 的关键文件身份如下，供以后复核本地差异；包版本不能替代这些文件的确切内容：

```text
reme/steps/index/search.py
  eac4b57896d80f8dc784643bc8518bff8bd5ec78b82d08919624ab9ef4a9bb52
reme/steps/index/search_v2.py
  14189a25d708ac0a573a767209c188fee231a032ebecc706de08dc5ea46344b9
reme/steps/evolve/auto_memory.py
  ad8cc580614a19767b00e85893d9802c67a2a035bb1d50de9afc40e4d2dbc4dd
```

### 先对齐 MiLAi 当前工作树

新读取的实现已是 **`contextual-user-memory-v3`**，不再是上一节修复后记录的 v2。以下为本次源码事实，不表示本次运行了模型或测试；127 passed 等前轮数字仍归属当时的修复快照。

| 已有代码 | 确认的行为 | 尚未覆盖的能力 |
| --- | --- | --- |
| [核心 `_index_entries`／`_rank`](../src/milai_lab/methods/contextual_user_memory.py) | 长来源按 2,048 字符窗口、256 字符重叠建立派生项；来源与当前整理共同参与 lexical/vector RRF-60；索引策略为 `source-range-2048-overlap256-lexical-vector-rrf60-v1` | lexical 是子串计数而非 BM25；按 source ref 聚合后仅保留一个呈现范围；没有会话排名、日期参数或稳定消息 ordinal |
| [embedding 身份与恢复](../tools/contextual_embeddings.py)／核心 checkpoint | 实际 embedding 身份传入创建／恢复；不匹配的派生向量不会直接沿用 | 本次未验证真实服务和新恢复路径；新 BM25／材料策略仍须进入方法与缓存身份 |
| [批量摄取 `ingest_chunk`](../tools/contextual_ingestion.py) | 每批合法消息及相关旧记录形成一次 schema 约束的操作提案；允许空操作，逐项执行并保留部分失败 | 增量合并策略与实际成本效果待验证；没有必要再创建第二套批量摄取框架 |
| [Host 循环](../tools/contextual_host_adapter.py) | 普通 JSON-action 使用工具 schema；相同只读参数返回先前回执入口；连续无进展单独退出，写操作清理只读缓存 | 不同 query 命中同一范围仍可能重复返回；成功调用不保证取得了新的相关信息，不能等同于语义进展 |
| [runner](../tools/run_contextual_user_memory.py) | 历史按合法前缀发布；已有 RAW_RETRIEVAL；`freeze_answers` 包含请求集合的答案、缺失及失败身份，先冻结后评分 | 新接线未在本次复测；RAW_RETRIEVAL 仍使用 embedding，不能称为纯 BM25 或零模型控制 |

读取时四个实现文件的 SHA-256 为：

```text
src/milai_lab/methods/contextual_user_memory.py
  f6fd59b1b5dd9b9b8741c8c0ccb0954d4462bf421ddc0435e53dbc255899a8b9
tools/contextual_host_adapter.py
  d54ce52cf2b8cc79527e697b649421710d713dfa18655c4cebc25fc0e484eb2e
tools/contextual_ingestion.py
  6e229beeabb01b1fdf1fbe6e87e21ef58ec741bc118a968bddd4360cfbffdda2
tools/run_contextual_user_memory.py
  b080d46cfa1b9c9aa038b3f66f69210b50c681b8eaec8ad16b988082d2cc5af2
```

这些文件仍不能用仓库基线 commit 代表。当前已有 `seen` 维护读取／版本要求，GAP 扩展补的是其他排名来源，二者分别**不是检索排除账本和同会话邻接展开**。这两处语义需要新代码，而非重命名现有字段。

### ReFind：轻量会话检索的具体机制

阅读主链为 [请求模型](../../../ReFind/app/models.py) → [SQLite 存储与 `list_chunks`](../../../ReFind/app/store.py) → [BM25](../../../ReFind/app/bm25.py) → [direct／agent Search](../../../ReFind/app/retriever.py)，并核对 [METHOD_CARD](../../../ReFind/docs/METHOD_CARD.md)、[配置](../../../ReFind/app/config.py)与[测试](../../../ReFind/tests/test_api.py)。

| 源码事实 | 对 MiLAi 的启发与限制 |
| --- | --- |
| `store.add` 保存原消息；Search 按 user 取出历史，每次重建 chunks 和 BM25。按 session 排序后每两条消息配成一个 chunk，排序优先时间戳，再用请求中的 ordinal，必要时回退到入库顺序 | 值得借用稳定会话定位；不直接复制固定两条配对或请求 ID 猜顺序。MiLAi adapter 已知原顺序，应直接保存 ordinal；派生索引可缓存，无须每个 query 重建 |
| `_score` 是 BM25；`_rrf_with_session_ranking` 将正分 chunk 在同 session 内的 BM25 分数相加，再融合 chunk 名次和 session 名次 | 证明会话信号可以与片段信号并存，不证明“求和”不会偏向长会话。MiLAi 的 lexical/vector RRF 已有，新增的是真 BM25 和可单独检验的会话信号 |
| `_context` 取同会话前后 chunk；`_within_dates` 按 anchor 最早时间筛选，缺时间／非法筛选放行，邻接不再筛日期 | 借邻接结构，不照搬日期放行和边界遗漏。邻接必须同时服从 MiLAi 的合法前缀与当前取材约束 |
| 方法卡将论文的 seen-session 改成 chunk 过滤；`_agent_search` 把每次返回的 anchor 加入 excluded_ids | 不能将“读到一段”实现成整会话排除；邻接仍可能跨结果重复，MiLAi 需要版本和范围级的呈现去重 |
| 默认最多四轮 planner，每轮上限 900 输出 tokens；`take_note`／`finish_search` 控制选择和停止；最终只返回 evidence，由平台回答 | 可借停止行为，不另叠一个 Planner。MiLAi 已由 Host 驱动工具；四轮上限不等于总输入／token 硬预算 |

直接搜索会合并 query 与选项；agent 搜索也把选项交给 planner。这是它的任务接口选择，不是适用于所有数据集的查询优化。MiLAi 若改变选项参与检索的方式，须同样作用于可比臂并记录，不从正确选项提词。其 tokenizer 的英文停用词和词干处理也不能直接等同于多语言检索能力。

ReFind 的确定性 BM25 路径不需要 embedding；agent 模式则仍有 Planner 调用。可以适配小型 MIT 算法实现或作为后续独立对照，但无需搬 SQLite、TTL、API 服务及正则 action parser；MiLAi 现有来源保留、删除和结构化调用合同继续负责这些行为。

### ReMe：默认检索、本地增强和记忆演化要分开

默认工具路由由 [default.yaml](../../../ReMe/reme/config/default.yaml) 指向 [SearchStep](../../../ReMe/reme/steps/index/search.py)。它组合关键词／向量候选、加权 RRF、范围标识与可选日期筛选；[LocalFileStore](../../../ReMe/reme/components/file_store/local_file_store.py) 从派生 chunks 建关键词索引，并按内容复用 embedding。默认配置中的 embedding／vector store 段被注释，未配置 embedding 时 vector search 返回空列表，不能仅凭类支持向量就宣称默认是混合检索。

[JSONL chunker](../../../ReMe/reme/components/file_chunker/jsonl_file_chunker.py) 尽量保留消息行和重叠，单行本身超长时仍允许大块，不能直接解决 MiLAi 超长来源。读取工具 [read.py](../../../ReMe/reme/steps/file_io/read.py) 支持精确行范围；可选邻接链接不等于自动取得邻居全文。[link_expansion.py](../../../ReMe/reme/utils/link_expansion.py) 展开的是 wiki 链接名称、描述等入口，也不应当作完整邻接读取。

本地 [search_v2.py](../../../ReMe/reme/steps/index/search_v2.py) 开头明确写了 local fork。它调用 [_source_format.py](../../../ReMe/reme/steps/index/_source_format.py) 的 `merge_session_chunk_intervals` 合并重叠／相邻行区间，并使用 [_dedup.py](../../../ReMe/reme/steps/index/_dedup.py) 的工具上下文去重；这条路径由本地 LME／BEAM 配置启用，默认 search 不能据此获得全部能力。MiLAi 可适配**同源区间合并算法**，映射到 source_ref／版本／字符范围；不导入这些 benchmark 配置、提示或题目特例。

记忆形成和整理有三条不同路径：

| 路径及源码 | 实际行为 | 本轮采用程度 |
| --- | --- | --- |
| [`auto_memory.py`](../../../ReMe/reme/steps/evolve/auto_memory.py)／[提示](../../../ReMe/reme/steps/evolve/auto_memory.yaml) | 原始 transcript 按消息 ID 增量保存，找当前会话／日期笔记，Agent 读后创建或更新；跳过闲聊、每会话少量笔记等主要由提示表达 | 借增量和相关旧记录输入，继续使用 MiLAi 的版本操作；提示要求不能替代程序保证。它过滤 tool result，MiLAi 应只阻止自己生成的记忆回执循环摄取，保留合法外部工具来源 |
| [`dream/extract.py`](../../../ReMe/reme/steps/evolve/dream/extract.py) → [`dream/integrate.py`](../../../ReMe/reme/steps/evolve/dream/integrate.py) | 从近期变更文件抽取少量待整合单元，逐项调用 Agent 搜索并创建／修订；NodeSearch 先给名称／描述 | 借“只处理变更＋查相关旧记录”。默认流程有多轮、逐项调用及重试，不照搬为低成本默认后台任务；CREATE/CORROBORATE/REFINE/CORRECT 是模型提案，不自动证明语义正确 |
| 本地 `search_v2._compress_session_entries` → [`compressor.py`](../../../ReMe/reme/steps/evolve/compressor.py) | 配置开启后对 session 命中逐条调用 LLM，压缩更短时使用，否则保留原文 | 本轮不启用。每个 hit 都可能增加调用，且没有源码保证条件、否定、例外不丢；优先准确摘录和已有记录视图 |

`default.yaml` 的 Agent wrapper 可多轮执行；一次上层 `reply` 不能按一次底层 LLM 请求记成本。MiLAi 现有每批一次提案已经更接近当前成本目标，适合在其内提高更新质量，而非回到多 Agent 逐条整理。用户记忆与 Agent 程序性经验也不能因 ReMe 同时支持它们就混进一个无主体的画像。

### OpenViking：分层材料规划比整套层级后端更适合当前 Lab

首先区分检索分支。[`HierarchicalRetriever.retrieve`](../../../OpenViking/openviking/retrieve/hierarchical_retriever.py) 的 QUICK 路径做一次向量检索和 URI 去重，提前返回，**没有执行目录递归、rerank 或 hotness 排序**；THINKING 才进入入口点选择、优先队列递归、父级分数传播和收敛停止。是否启用 intent／session 查询上下文另由 [SearchService](../../../OpenViking/openviking/service/search_service.py) 控制。不能用“层级检索”四字概括所有请求，更不能据此声称一次完整系统查询只消耗一次检索或模型调用。

对 MiLAi 最直接的参考是 `retrieve/context_assembler`，而非先引入目录树：

| 文件／函数 | 已读实现 | 适配选择 |
| --- | --- | --- |
| [pipeline.py：`assemble_context`](../../../OpenViking/openviking/retrieve/context_assembler/pipeline.py) | 候选获取、所需视图读取、预算规划、渲染、可选 rewrite、记录真正呈现的条目 | 拆出小型材料函数；query expansion／rewrite 涉及额外调用，默认不移植 |
| [budget.py：`plan_entries`](../../../OpenViking/openviking/retrieve/context_assembler/budget.py) | 先铺多个候选，再用剩余预算升级；单项上限，full／overview／abstract／URI 之间降级，不随意切字 | 借分配顺序和显式降级；MiLAi 用现成记录或准确原文范围，不为每条来源新生成摘要 |
| [tiers.py](../../../OpenViking/openviking/retrieve/context_assembler/tiers.py)／[params.py](../../../OpenViking/openviking/retrieve/context_assembler/params.py) | 视资源种类取得已有 overview、结构提纲或正文；部分 memory 的 abstract 本来就是整个正文 | 视图名不保证大小。按实际内容计预算，不照抄分类配额，不将 L0 自动解释为“短且足够” |
| [ledger.py：`RecallLedger`](../../../OpenViking/openviking/retrieve/context_assembler/ledger.py) | 按 session 和 turn 冷却已呈现 URI，纯 URI 条目不算正文已读 | MiLAi 要再绑定版本和范围。旧 URI 被看到不应遮住新修订；先前摘录不应遮住同一来源其余部分 |
| [semantic_sidecar.py](../../../OpenViking/openviking/storage/semantic_sidecar.py) | 保留摘要来源、生成组件／触发原因和 freshness 信息 | 借来源／加工／新鲜度的分离；元数据不认证语义支持关系，也不能替代 MiLAi 的版本依赖 |

写入侧，[`Session.commit_async`](../../../OpenViking/openviking/session/session.py) 先归档原始 `messages.jsonl`，再把派生任务放入持久队列，返回 task ID；后台由 [commit processor](../../../OpenViking/openviking/storage/queuefs/session_commit_processor.py) 接续。[`extract_loop.py`](../../../OpenViking/openviking/session/memory/extract_loop.py) 可预读旧文件并生成写入操作，但初始迭代数还会因工具结果、修复等增加；[`compressor_v3.py`](../../../OpenViking/openviking/session/compressor_v3.py) 还包含可选 Agent 演化路径。它们说明“保存原始输入”和“整理完成”应分别记录，不说明 Lab 需要同样的队列与多轮写入器。

阅读相关 [材料组装测试](../../../OpenViking/tests/retrieve/test_context_assembler_pipeline.py) 和 [检索分支测试](../../../OpenViking/tests/retrieve/test_hierarchical_retriever_rerank.py) 可核对延迟读正文、超预算降级及 QUICK 分支的预期。这些测试未在本次运行，也不能替代 MiLAi 的任务效果实验。当前规划只借鉴这些机制，未复制 AGPL 实现。

### 对可行性、成本和研究价值的判断

**工程上可分三个有限增量实现。** 第一，补 source ordinal、BM25、时间与会话定位；第二，把已有片段视图扩展成按版本／范围去重的材料规划器；第三，在已有一次摄取提案内改善增量修订。前两项不需要增加生成式模型调用，第三项默认沿用现有调用次数；这只是结构上的成本约束，不是已测得的 token 或准确率收益。

优先级依据是已经观察到的重复调用与高历史构建成本，以及源码确认的缺失能力。它们不是三道 PersonaMem 错题的全部已证实原因：已有原文仍可能推理错误，更多会话命中也可能挤掉关键条件。下一次固定版本轻量比较同时看最终答案、实际新增／重复材料、条件与来源是否保留、修订后的旧表达是否仍被采用，以及 history／answer／embedding／judge 的真实花费。

**单独使用 BM25、RRF、分层摘要、记忆整理或工具去重不构成新的方法贡献。** 可检验的研究点是：在保留来源与可修订表达、准确版本及情境例外的同时，统一的 Host 操作与 State 驱动取材是否比原文检索和无 State 记忆基线更有效、更省调用。当前四道已暴露开发题只能检查运行与初步假设，尚不足以判断创新性效果或泛化。

本次只更新 Goal、本文和 Lab 导航；做文档链接／格式及状态一致性检查，不运行 Python 方法测试、外部项目或模型实验，新增 **0 次 Host、0 次 Judge 请求**。三类原始测试集、冻结答案、代码、依赖及 Product 合同均未修改。正式全量运行继续后置，未创建 commit／tag、未推送或核对远端新提交。

## v3.0 D1：可比较执行链与三题接线（2026-09-24）

本轮按新 Goal 连续开发，未恢复旧 formal、未运行全仓测试。已提取 `contextual_memory/models.py`、共享 `providers/contextual_vllm.py`、`runners/contextual_host.py` 与 `harness/contextual_artifacts.py`；旧导入入口保持可用。Host 和历史摄取共用 `receipt_outcome`：来源保留成功而记录版本冲突会如实返回部分失败，读到 `NEEDS_REVISION` 材料不被误算为工具执行失败。历史保持每批一次提案，旧记录视图直接提供精确版本，部分操作失败不会伪报全部成功。

新增 MemSyco 薄适配与三类原生 Judge 协议。Host 只接收原始对话／问题；任务类别、gold memory、evaluation 和 metadata 留在评测侧。三份 rubric 与固定上游实现逐字核对，Judge 的输出上限为 1,024 tokens。运行器支持明确命名的臂、原生任务分项与同题配对；答案、失败和缺失清单先整体冻结，评分必须匹配冻结摘要。每次运行同时保存配置、源码 SHA 和紧凑源码内容，避免拿旧基线 commit 代替尚未提交的实现。

共享运行预算在每次 Host／Judge／embedding 请求前预留输入估计和最大输出；实际 usage 返回后更新，失败或缺失 usage 保留未知标志和估计占用。预算在磁盘保存，可恢复且计入失败请求。跨臂共享 embedding 的实际支出与各臂独立冷启动输入估计分开。

实际协议探测先遇到完整工具 schema 的 HTTP 500。Astra xhigh 只读核对部署中 vLLM 0.27.1，证明两个可用 grammar backend 均不能处理 `uniqueItems`；裸 xgrammar 编译会忽略该约束，不能据此证明支持。现仅在生成 schema 显式移除该项，执行入口仍用完整原 schema 拒绝重复 refs；工具必填字段、const 名称、`minProperties` 和 `maxItems` 保留。修正后完整工具分支的真实请求成功。空 500 的具体 HTTP 异常路径没有完全证明，不将其写成已找到的断言错误。三次工程请求中两次成功，共 93 已知 tokens；一次失败的 usage 未知，均保留在 `v3-d1-protocol-probe/`。

联调配置为 [contextual-memory-v3-d1.json](../configs/contextual-memory-v3-d1.json)，输出为 `artifacts/contextual-user-memory/v3-d1-wiring-1/`，进程正常退出 0。选题为既定 screen 清单中三类各自第一题；未读 confirmation 正文。三题上限、两臂、单并发，最多 64 次生成请求／200,000 生成 tokens／200,000 embedding tokens。每题最多八次 Host，历史每批一次；两臂都有相同合法原始档案权限。

| 原生任务与题目 | RAW_RETRIEVAL | ORDINARY_MEMORY | 原生判定 |
| --- | --- | --- | --- |
| scope，`mso_hard_000068` | 完成 | 完成 | 两臂 accuracy=1、incorrectly_used_preference=0、scope_pass=true |
| valid selection，`v11_000977` | 完成 | 完成 | 两臂 uses_latest_preference=1、outdated_preference_contamination=0、valid_selection_pass=true |
| personalized use，`v11_001210` | 连续重复只读调用后 no_progress | 下一请求预留量超出剩余预算 | 两臂未完成，无 Judge，不记为正常判错或移出分母 |

冻结清单记录请求六项、已有五份答案制品、四份正常完成，整体为 **PARTIAL**；四份可评分答案均使用原生 rubric＋本地 Qwen3.6-35B-A3B-FP8 vLLM Judge，同模型自评。三个任务不合并总准确率。这是执行链联调，不是候选机制比较，更不能据两个成功原题证明记忆整理有效。

| 臂／阶段 | 生成请求 | 已知 tokens |
| --- | ---: | ---: |
| RAW 作答 | 15 | 97,101 |
| RAW Judge | 2 | 2,717 |
| 普通记忆历史摄入 | 3 | 9,484 |
| 普通记忆作答 | 12 | 66,901 |
| 普通记忆 Judge | 2 | 2,518 |

本批共 34 次生成请求，178,721 已知生成 tokens；embedding 11 次、4,275 tokens，usage 均已知。三个历史各一次提案，均完成且无操作错误。实际共享 embedding 费用分别归 RAW 3,673、普通记忆 602 tokens；按各臂独立缓存估计分别为 3,673、4,269 输入 tokens，不能据 602 宣称普通记忆内生成本更低。请求壁钟时间分别保留在 summary，共享 GPU 时间未知。

轨迹仍显示首题多次读取已有材料；第三题 RAW 有三次紧凑重复回执，普通记忆有一次，后者在再请求前被预算拒绝。无 schema 缺字段、来源版本冲突或部分失败误报；未完成行为仍是需要后续机制解决的问题。冻结 summary 中 RAW 第三题 `native_tracks.judge_parse_failed=1` 是汇总器把 HOST_INCOMPLETE 当成 Judge 响应的分类错误；实际未发 Judge。该汇总错误已在下一开发版本修正，不重写本批冻结原始制品。

核心类型／回执切片 23 项通过；Host、runner、预算和 MemSyco 切片合计 25 项通过。修改文件 Ruff、受影响包模块 mypy、包依赖边界通过；没有全包构建、全仓 pytest 或新增大规模评测。源码与数据适配由 Sol xhigh 执行，已复现的 vLLM 兼容问题交 Astra xhigh 诊断；未新增下载或更改模型权重。工作树未提交、未建 tag 或推送，运行源码身份以该批 manifest／sources.json 为准。

下一步是 D2 的 H1：声明共同／替代支持、提案别名及局部原子变更组，用固定 valid-selection 切片比较正常增改和支持维护。STALE 的薄适配作为独立数据工作推进；其后按 Goal 顺序做 H2–H6。六候选尚未实现／验证完毕，Goal 保持 active。

## v3.0 D2：H1 支持维护与固定四题结果（2026-09-24）

H1 状态为 **IMPLEMENTED / RUN / DROP_DEFAULT**：当前方案不进入默认配置或确认组；支持关系作为后续事件与材料实验的最小基础保留，不声称机制已被证明有效。`contextual-user-memory-v4` 实现共同支持与替代路径、精确版本／来源范围、提案内别名、局部原子组、支持反向索引、持久恢复及遗忘清理。普通 profile 保持普通增改；历史 `source_refs` 仅表示出处，不自动推断 AND/OR。未知条件为 PENDING，无支持想法仍可保存，USABLE 只表示声明路径可用。

固定配置 [contextual-memory-v3-h1.json](../configs/contextual-memory-v3-h1.json)，输出 `artifacts/contextual-user-memory/v3-h1-screen-1/`。valid-selection 的四个既定 screen ID 全部纳入，两臂各自重建相同合法历史；第一题已在 D1 暴露，confirmation 未使用。八份答案全部先冻结，再发八次原生 rubric＋本地同模型 vLLM Judge；无未完成或未判定。方法、源码全文／SHA、模型及输入身份由本批 manifest 固定。

| 指标 | ORDINARY_MEMORY | H1_SUPPORT |
| --- | ---: | ---: |
| 使用最新偏好 | 4/4 | 2/4 |
| 旧偏好污染 | 0/4 | 2/4 |
| valid_selection_pass | 4/4 | 2/4 |
| 历史提案请求／tokens | 4 / 17,211 | 4 / 19,594 |
| 作答请求／tokens | 21 / 157,562 | 20 / 182,521 |
| Judge 请求／tokens | 4 / 4,791 | 4 / 4,988 |
| 生成 tokens 合计 | 179,564 | 207,103 |

配对退化为 `v11_000569`、`v11_001002`，改善为零；另两题两臂均通过。前者的候选答案援引较早的建设性讨论偏好，并将推荐任务误收窄为“历史是否已有推荐”；后者虽提到新的理论学习偏好，又推荐了旧的实践活动。两项为原生 Judge 判定的旧偏好污染，不等同于已证明某个支持操作造成错误。候选多消耗约 15.3% 生成 tokens；两臂提案 schema 和提示不同，本批是系统比较，不能把变化单独归因于 AND/OR。

四次支持摄入中三次成功，共八个支持组，每个 Claim 只有一个组；没有形成可比较的替代支持保留或撤回事件。另一题 `v11_000977` 的提案包含越界来源范围，整个局部组正确拒绝为 INVALID_SOURCE_RANGE，历史标记 BUILT_WITH_OPERATION_ERRORS；该题最终仍通过，因此该错误不是两道退化题的直接解释。已声明组的受影响引用由真实回执记录，没有关系 gold，无法报告真实影响召回率。

本批总计 57 次生成请求、386,667 已知生成 tokens；14 次 embedding 请求、9,541 tokens，usage 全部已知。共享 embedding 实际费用普通臂 9,055、支持臂 486 tokens；独立冷启动输入估计分别 9,055、8,541，不能把后者的缓存命中当成机制节约。请求耗时分阶段保留，归属 GPU 时间未知。没有追加随机种子、同题调参或扩大样本。

机械语义的 26 项核心定向检查、Ruff、mypy 与包边界通过。一次工程提案只产生 Claim 而未声明支持，依据这一非 benchmark 输入明确了协议要求；第二次工程提案正确产生 Claim＋Justification，再固定版本运行上述四题。后续继续开发 H4 时间／事件、H2/H5 统一读取和 H3/H6 有界维护；STALE 原生适配已实现，尚未运行 STALE 模型实验。全量 benchmark、全仓 pytest、Product 迁移仍不在本轮范围，Goal 保持 active。

## v3.0 D2：H4 事件语义与固定四题结果（2026-09-24）

H4 已在方法 v5 实现 `state_change / task_override / reinterpret`，公开读取与搜索支持 `valid_at/known_at`。状态变化保留旧有效区间；未知发生日期保留为未知，当前旧态不可用而新态可用，历史有效时间无法确定时为 PENDING。任务覆盖只随同一任务续接，换任务清除；解释纠错仅重绑定提案明确选定的支持组，新命题不自动继承所有旧依据。来源初次获知、替代、Claim 版本与支持撤回都按已知时间裁剪，后知更正不进入此前回放。旧 v4 快照明确拒绝，不作静默迁移。

配置 [contextual-memory-v3-h4.json](../configs/contextual-memory-v3-h4.json)，输出 `artifacts/contextual-user-memory/v3-h4-screen-1/`；运行进程退出 0。使用固定 screen 的四道 scope 题，普通增改与 events 两臂全部完成，共八份冻结答案、八次原生 rubric＋本地同模型 Judge，无未完成／未判定。两臂原生 accuracy 和 scope_pass 均为 2/4，incorrectly_used_preference 均为 1/4；`mso_hard_000041` 改善，`mso_hard_000068` 退化，其余一题同时通过、一题同时失败。

**H4 为 IMPLEMENTED / RUN / INCONCLUSIVE_UNCOVERED。** 实际成功事件计数只有 claim=8、justification=7，三种新事件操作均为零；四份历史单批摄入，没有构建失败或变更组错误。这批公开输入／Host 行为没有激活待测事件机制，不能将同分解释为时间或事件设计有效或无效，也不据此进入确认组。

| 臂／阶段 | 生成请求 | 已知 tokens |
| --- | ---: | ---: |
| 普通记忆历史／作答／Judge | 4 / 25 / 4 | 13,077 / 162,184 / 5,454 |
| H4 历史／作答／Judge | 4 / 27 / 4 | 16,488 / 237,104 / 5,764 |

总计 68 次生成请求、440,071 tokens；embedding 10 次、5,515 tokens，全部 usage 已知。普通记忆总生成 180,715 tokens、H4 259,356，增加约 43.5%。实际共享 embedding 分别 5,073、442 tokens，独立冷启动估计分别 5,073、4,147。H4 的对象／schema／提示不同，额外输入与流程成本不能归因为单个事件操作。保持原始配置与结果，不追加同题调参。

H4 涉及的核心／Host／runner 54 个定向检查和静态检查通过。随后开发版补了 H5 的精确范围交付、H6 的同次提案原文展开与独立于 checkpoint 的删除记录，尚不算其原生实验完成；新的磁盘修改不改变本批已冻结源码和在内存执行的 v5 身份。D3 的公共 BM25／会话顺序／更正关联和 D4 的有预算未决维护继续进行。

## v3.0 D3：共享快照的 H2/H5 小比较（2026-09-24）

方法 v6 提取 `retrieval/materials`，共同基础改为真实 BM25＋向量 RRF；稳定来源序号、会话邻接、日期过滤及同来源多个准确范围由所有臂共享。连续／重叠范围合并，分离范围分别给出原文、offset 和内容 SHA。关联读取让普通增改和支持维护都可链接旧／新解释、来源替代与必要限制；更正放不下时隐藏旧正文并给必需展开引用，不截半段更正后继续展示旧材料。H5 只省略当前消息列表内仍存在的精确版本／范围；状态及更正保留，差量序列化反而更大时保留全文。换 Host／上下文压缩不继承“已经读过”的假设。

配置 [contextual-memory-v3-h2-h5.json](../configs/contextual-memory-v3-h2-h5.json)，输出 `artifacts/contextual-user-memory/v3-h2-h5-screen-1/`，退出 0。固定四道 valid-selection screen 原题已在 H1 暴露。三臂十二答案全部完成、冻结和评分；逐题检查 `history_cache_id` 完全相同，每份历史只实际摄入一次。这里比较读法，不能拿 v6 与 H1 的跨运行差异单独宣称 BM25 效果。

| 原生指标／成本 | SUPPORT 全文 | SUPPORT_LINKED | SUPPORT_DELTA |
| --- | ---: | ---: | ---: |
| uses_latest_preference / valid_selection_pass | 1/4 | 2/4 | 3/4 |
| outdated_preference_contamination | 3/4 | 2/4 | 0/4 |
| 作答请求／tokens | 19 / 174,873 | 23 / 275,842 | 20 / 149,482 |
| Judge 请求／tokens | 4 / 4,658 | 4 / 4,518 | 4 / 4,479 |
| 加回同一历史构建的独立生成成本 | 199,969 | 300,798 | 174,399 |

共享历史实际为 4 次请求、20,438 tokens，只计一次批次费用；上表独立成本为每臂都加回该成本，避免将共享当成免费。批次共 78 次生成、634,290 tokens，embedding 10 次、8,836 tokens；usage 全部已知。各臂独立冷启动 embedding 输入估计分别为 8,812、8,812、8,813；实际 shared cache 费用分别 8,818、10、8，不用于比较内生成本。

H2 改善 `v11_000977`，无退化；作答 tokens 增加约 57.7%。轨迹实际出现 source_provenance 和 supported_interpretation 各 11 次，没有发生解释修订或来源更正。因此当前只观察到额外关联材料的系统差异，**真正“更正随旧材料交付”的公开样本覆盖仍不足**。H2 为 IMPLEMENTED / RUN / DROP_DEFAULT，保留统一关联接口，不进入确认组。

H5 改善 `v11_000977`、`v11_001002`，无退化；作答 tokens 减少约 14.5%，加回相同历史及 Judge 后减少约 12.8%。15 次交付检查累计省去 6,068 正文字节，连同差量元数据后净省 4,018 字节。最终输入还受后续工具和答案选择影响，不能把全部 token 差异等同于静态压缩节约。H5 为 IMPLEMENTED / RUN / CONFIRM_NEXT：只进行一次预先固定 valid-selection 确认切片，再作保留判断。

四份摄入快照的 pending_records 均为零，未激活 H3 队列。D4 长历史检查预先缩为既定 STALE 清单首个 T1 场景的全部三问；保留 50 个 session、594 条消息、673,289 字符，不按相关会话标注裁剪。共同历史块上限设 48,000 字符以减少往返，三臂最多 256 次生成／2,000,000 生成 tokens。其余三个固定场景不在这次轻量运行中，不能宣称 T2 或全四场景已经验证。

## v3.0 D4/D5：运行时能力与结构收敛（2026-09-24）

运行主链已迁入 `src/milai_lab`：`runners/contextual.py` 负责历史、作答、冻结与评分调度，`runners/contextual_ingestion.py` 负责一次有界提案，`providers/contextual_embeddings.py` 负责分窗批量 embedding。CLI 保留参数解析、身份核对和装配，旧 tools helper 仅兼容导出。核心拆出 models/store/revision/retrieval/materials/deletion；服务及 State/Attention 装配继续保留原入口，不为文件形状再加转发层。移动前后接口和行为保持，方法 v6 的具体实现以每次运行 `manifest.json` 和 `sources.json` 为准。

H3 同步沿已声明反向关系计算结构状态，语义重整理另入不含正文的 pending 队列。eager 按全部已知队列顺序取材，pending 按查询排序最多选四项，两者都受同一字节预算约束；这里的 eager 不是无预算的额外模型循环。每批历史仍一次提案，任务开始若有 pending 最多补一次显式维护提案，单列 maintenance 成本。`review keep` 只表示复核完成，不使无效支持变为有效；未处理项保留为 pending，未算成失败或完成。该队列只保存当前操作状态，不提供历史队列重放；Claim、支持及来源的 `known_at` 回放与之区分。

H6 在同一次提案内展开相关记录明确引用的旧原文，按准确来源版本／范围取材；总正文材料预算 4,096 字节，最多八页。未展开范围明确返回。首批没有旧记录时不插入空的证据提示，不增加独立模型调用；以后实际多给了什么，由 ingestion_source_context 记录。对原始材料的额外供给本身不能被称为新的修订算法。

| 八类事件 | 当前执行路径与机械证据 |
| --- | --- |
| 新信息 | adapter publish 原始 Observation，save/claim 保存理解；支持 task-only 和不持久化，来源身份与作者分别记录 |
| 补充佐证 | justification 的共同项、替代组与反对组；精确版本／范围，局部组原子提交及别名解析 |
| 临时要求 | task_override 只改变当前 TaskState；同任务可续接，换任务清除，不进入耐久画像 |
| 真实状态变化 | state_change 结束旧区间并创建新态；未知发生时间保留未知，旧世界状态和已知前缀可查询 |
| 解释纠错 | reinterpret 只迁移显式选定组；旧原文不改写，新含义不自动继承全部支持 |
| 未决冲突 | 正反依据、适用条件和 PENDING 分别呈现；已知失效即时可见，有界 review 不冒充语义解决 |
| 整理压缩 | 展示层去重、准确范围合并及当前上下文差量交付；原文入口保留，不自动用摘要覆盖原文 |
| 遗忘／退出 | 删除正文、依赖、旧版本及向量；外部删除记录阻止旧 checkpoint／handoff 恢复和同来源重新摄入；runner 清理其管理的缓存与日志 |

删除记录独立于 checkpoint，并保存引用、代次和 ID 高水位，不保存正文。历史及每个答案实例各有删除域，一个臂或 probe 的遗忘不污染其他比较实例；磁盘旧快照恢复前重新应用删除事实。收到 FORGOTTEN 后立即清理该实例历史 chunk、checkpoint、trace 和所用 embedding 键，后续 trace 改为最小元数据；Host 丢弃旧工具／任务正文并重置交付记录，下一模型请求不再发送被删除内容。基准原文件以及其他运行的制品不在这个实例的清理域内。已经发出的远端模型请求无法撤回；已冻结最终答案保留为评分制品，不能把这套本地机制宣传为全系统物理销毁。

定向检查覆盖替代支持、已知失效与六项待维护闭包、时间前缀、临时覆盖、选择性纠错、范围交付、Host 换上下文、遗忘后下一请求及旧快照复活阻断。runner 另有历史受管文件清理与答案实例隔离检查。结构迁移相关的 17 项已有检查、修改文件 Ruff/mypy、包边界及 CLI help 均通过；后续多范围紧凑材料修正通过四项检索检查。没有为文档运行模型或全仓测试，没有构建／打包改动。

STALE 运行中又复现一个调度成本错误：某历史块提案校验失败后，后续 probe 隐式继续同一个未完成历史，形成最多三次入口尝试，先前失败的 probe 却不会得到答案。实际原因分别为 `source_refs` 重复违反原 schema 的 `uniqueItems`，以及一次输出达到 4,096 tokens 后截断。最终 schema 继续严格校验，没有静默清洗模型输出。修复为每个精确历史组先构建一次，失败向该组所有 probe 传播，其他历史／臂继续；已完成缓存和共享 owner 仍可复用。14 项 runner 定向检查及 Ruff/mypy 通过。此修正发生在该批进程启动后，不追改其源码、失败和费用，也不为得到完整答案重跑整批。

轻量入口统一为：

```bash
.venv/bin/python tools/run_contextual_user_memory.py \
  --config configs/contextual-memory-v3-default.json \
  --output artifacts/contextual-user-memory/v3-default-smoke-1 \
  --phase develop
```

[默认配置](../configs/contextual-memory-v3-default.json) 使用 ordinary，只含一条已暴露筛选题，最多 24 次生成／150,000 生成 tokens，默认不叠加六个候选。它是可运行配置，新增后仅检查 JSON、路径、题数、身份散列与加载，不额外调用模型。保留 H5 的明确实验入口为 [确认配置](../configs/contextual-memory-v3-h5-confirmation.json)；筛选与长历史配置分别保存，不能把各轮最佳答案拼成一个方法成绩。CLI 的 `score/report` 使用同批冻结身份；代码修改后需新输出目录，原运行可结合其冻结 `sources.json` 复现对应实现。

本轮只改变 Lab RESEARCH_PROTOTYPE 的工具／checkpoint 合同，旧 v4/v5 快照明确拒绝；没有改变 Product Schema、权限或 canonical 行为，没有引入第三方框架运行时。第三方源码、数据和模型／运行制品保持在 Git 外；没有创建 commit、回滚 tag、推送或核对远端新提交。完整 benchmark、全仓 pytest、其他 STALE 场景以及额外 PersonaMem/LME 模型批次均未运行；受管范围以外的删除、跨服务并发及生产持久库仍不在本轮实现范围。极小材料预算可能容不下引用占位元数据，不能将该情况描述为任意字节上限保证。

## v3.0 D4：H3/H6 单个 STALE 场景的执行结果（2026-09-24）

配置 [contextual-memory-v3-h3-h6-stale.json](../configs/contextual-memory-v3-h3-h6-stale.json)，输出 `artifacts/contextual-user-memory/v3-h3-h6-stale-smoke-1/`，进程退出 0，答案冻结为 PARTIAL。预先固定的首个 T1 场景完整输入 50 个 session、594 条消息，三个原生 probe 从各臂的独立历史快照启动。正常历史需要 17 批，三臂分别为 eager 支持维护、查询相关 pending 维护及提案附带旧原文；未使用 gold 相关会话裁剪。

| 项目 | SUPPORT_EAGER | SUPPORT_PENDING | SUPPORT_RAW_EVIDENCE |
| --- | ---: | ---: | ---: |
| 历史已完成块／应有块 | 17/17 | 17/17 | 12/17 |
| 答案完成／请求 | 2/3 | 1/3 | 0/3 |
| 摄入结构异常 | 1 次重复 refs | 1 次截断＋1 次重复 refs | 3 次截断 |
| 历史请求／tokens | 18 / 392,056 | 19 / 425,185 | 15 / 372,849 |
| 作答请求／tokens | 10 / 100,023 | 4 / 30,832 | 0 / 0 |
| 历史／作答请求壁钟秒 | 210.22 / 20.63 | 282.04 / 6.92 | 237.50 / 0 |
| 当前 pending 数 | 0 | 0 | 0（未完成快照） |

结构异常指一次提案未执行，不等同于 HTTP 失败；此外实际局部变更组分别拒绝 5、6、3 组，其中准确来源范围错误分别 3、3、3，版本冲突分别 2、3、0。这些真实回执没有被算成完整成功。旧 runner 在后续 probe 继续历史的额外尝试计入上表，修正后的单次入口边界见上一节，未重跑覆盖旧证据。

STALE 原生 Judge 要求同场景三个答案共同判定。三臂均未凑齐，实际 **0 次 Judge**；已完成的三份答案均未判定，另外六项 Host 未完成，所有九项保留分母。summary 的 native_types 在已请求分母上的零正确计数不表示九题均被 Judge 判错，本批没有有效的原生任务分数或配对改善／退化结论。

H3 的三个快照都没有 Claim→Claim 支持项，没有产生待复核队列，实际 maintenance 请求为零。状态为 **IMPLEMENTED / RUN / INCONCLUSIVE_UNCOVERED / DROP_DEFAULT**；确定性闭包检查证明机械路径可执行，公开场景没有验证其维护收益。

H6 实际发生 14 次旧原文交付（包含后续失败的提案），共 56 页、49,720 材料字节；单次最多 3,710 字节，显式列出 222 项未展开范围。原始依据确实进入同一次摄入请求，但三次截断使历史未完成、没有最终答案。状态为 **IMPLEMENTED / RUN / INCONCLUSIVE_EXECUTION / DROP_DEFAULT**；不能由其较少总 tokens 得出成本优势，也不能把未得分当作机制无效的证明。当前上限下的长历史提案完成率是保留的真实限制，本轮不加大输出预算或同题反复调参。

本批总计 66 次生成、1,320,945 tokens，82 次 embedding、339,553 tokens，usage 均已知，无遗漏费用。实际 embedding 归 eager 335,802、pending 2,282、原文臂 1,469；独立冷启动输入估计分别 335,802、335,797、119,101，最后一臂是未完成工作量，不作等量成本比较。共享 GPU 归属耗时未知。只运行一个 T1，T2 与其余固定场景均未运行。

## v3.0 D5：H5 固定确认与最终取舍（2026-09-24）

本轮 Lab 开发与约定的小规模比较已完成；研究有效性仍受下述负结果和执行覆盖限制约束。唯一进入确认的候选是 H5，使用 [固定确认配置](../configs/contextual-memory-v3-h5-confirmation.json)，输出 `artifacts/contextual-user-memory/v3-h5-confirmation-1/`，退出 0。四个 valid-selection 确认 ID 为 `v11_000664 / v11_000404 / v11_000462 / v11_000986`，自本次起明确已暴露，不再作未见保留集。另八条 scope/personalized-use 确认题未使用。没有调参后重跑或混选最佳答案。

三臂十二答案全部完成、先整体冻结，再发十二次原生 rubric＋本地 Qwen3.6-35B-A3B-FP8 Judge，同模型自评，无未完成／未判定。SUPPORT 和 SUPPORT_DELTA 逐题共享完全相同的 history_cache_id；普通记忆独立摄入，共实际构建八份单批历史，均无操作错误和 pending。

| 原生指标／成本 | ORDINARY_MEMORY | SUPPORT 全文 | SUPPORT_DELTA |
| --- | ---: | ---: | ---: |
| uses_latest_preference / valid_selection_pass | 2/4 | 3/4 | 2/4 |
| outdated_preference_contamination | 1/4 | 1/4 | 1/4 |
| 历史请求／tokens | 4 / 17,476 | 4 / 18,174 | 共享 SUPPORT |
| 作答请求／tokens | 17 / 213,640 | 24 / 363,767 | 24 / 324,618 |
| Judge 请求／tokens | 4 / 4,216 | 4 / 4,645 | 4 / 4,230 |
| 加回各自历史的独立生成 tokens | 235,332 | 386,586 | 347,022 |
| 历史／作答／Judge 请求壁钟秒 | 17.38 / 32.74 / 2.79 | 9.89 / 56.47 / 2.71 | 共享 / 51.80 / 2.83 |

H5 相对共享快照全文读取改善零题、退化 `v11_000664` 一题；`v11_000404`、`v11_000986` 同时通过，`v11_000462` 同时失败。差量交付的作答 tokens 少 10.8%，加回相同历史与 Judge 后少 10.2%，但没有保持任务质量。19 次交付检查省去 22,035 正文字节，计入元数据后净省 8,715 字节。调用数同为 24；完整 token 差异包含后续工具与回答选择，不能全归因于这些静态字节。

普通记忆在这四题也为 2/4，但独立生成成本比 SUPPORT_DELTA 少；后者高约 47.5%。这属于不同写入流程的系统比较，不是 H5 的单因素归因。本批实际总计 85 次生成、950,766 tokens，35 次 embedding、9,938 tokens，usage 均已知；共享支持历史只计一次。各臂实际 embedding 为普通 9,370、支持 518、差量 50，独立冷启动输入估计为 9,370／8,685／8,572，不能把缓存次序当成候选的内生成本优势。

| 候选 | 实现／运行状态 | 最终去留 |
| --- | --- | --- |
| H1 支持保留修订 | 已实现并筛选；替代支持未被公开切片触发 | DROP_DEFAULT；支持关系保留为生命周期与研究接口，不声称提升效果 |
| H2 更正关联读取 | 已实现并筛选；实际增加的是出处／理解关联，更正机制覆盖不足 | DROP_DEFAULT；保留统一关联读取接口 |
| H3 有界影响维护 | 已实现，T1 尝试没有形成待维护关系 | INCONCLUSIVE_UNCOVERED / DROP_DEFAULT |
| H4 事件区分 | 已实现并筛选；三种新事件操作未激活 | INCONCLUSIVE_UNCOVERED / DROP_DEFAULT |
| H5 当前上下文差量交付 | 已实现、筛选和一次确认；省 tokens 但确认退化一题 | DROP_DEFAULT；保留显式实验 profile，不称为保质降本 |
| H6 必要原文重整理 | 已实现且实际补充原文；T1 提案截断，未完成作答 | INCONCLUSIVE_EXECUTION / DROP_DEFAULT |

最终默认是普通记忆＋共同 BM25/向量检索＋单批提案和批量 embedding。保留的有限候选 profile 用于复现上述负结果及调用生命周期能力，不自动叠加为新的默认系统。六候选均有实现，八类事件有可执行路径和必要机械检查；本轮没有证明任何研究候选在质量和总成本上稳定优于普通记忆。H3/H4 缺少真实机制激活，H6 长历史完成率不足，后续若再研究，应由新的明确范围处理这些问题，而不是自动恢复全量 benchmark。
