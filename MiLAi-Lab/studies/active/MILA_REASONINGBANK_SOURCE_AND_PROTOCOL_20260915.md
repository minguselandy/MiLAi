---
study_id: MILA-REASONINGBANK-TRANSFER-AND-MULTISESSION-01
status: NATIVE_DEV_RUNNING
kind: RESEARCH_PROTOTYPE
solver: Qwen3.6-35B-A3B-FP8
second_solver: DEFERRED_BY_USER
---

# ReasoningBank 移植来源与研究协议

[完整 Goal](MILA_REASONINGBANK_TRANSFER_AND_MULTISESSION_RESEARCH_GOAL_v1.0_20260915.md) ·
[执行清单](../../data/manifests/reasoningbank-transfer-20260915.json)

用户要求本轮只使用现有 Qwen 求解模型，模型二暂缓。DB F/O、OS F/O、完整旅行组 G、
四主方法及贡献/资源比较仍在范围内。数据与原生环境已取得并验证；DB/OS 四方法 DEV 配对已完成，
完整旅行组正在运行。详见[开发结果](MILA_REASONINGBANK_DEVELOPMENT_RESULTS_20260915.md)，完整研究仍未完成。

原始证据目录：`/cra/memory/mx_memory/evidence/reasoningbank-transfer-20260915-_7fzz854`。
外部项目/数据/环境目录：`/cra/memory/mx_memory/benchmarks/reasoningbank-transfer-20260915-_7fzz854`。
HF凭据只从用户文件读取，不进入仓库或证据。

## 1. 已取得的固定来源

| 来源 | 固定版本 | 取得范围 |
| --- | --- | --- |
| Google reasoning-bank | `ed80611788292ea739f1effd31f16c53823b8a0d` | 完整 checkout；阅读 SWE-Bench 调用、默认 Agent、memory_management、induce_memory 和 instruction |
| LifelongAgentBench | `d6f19b42eb358d9150379f0c68c2985c5a867520` | 完整 checkout；原生 DB/OS、回调、Agent、容器及入口 |
| MemoryArena | `6cd9de14b71915e39ac742a20dc33785e14b6aab` | 完整 checkout；旅行 Agent/环境/数据接口与内置 RB |
| csyq/LifelongAgentBench | HF `75054b60177d4dcddb93b984413ff799b0a1fdbc` | DB/OS 各500项 Parquet，上游 LFS SHA256 匹配 |
| ZexueHe/memoryarena | HF `da1a37c8b19280e18627ca01cf368195a5e1d92e` | 270个完整旅行组，上游 Git blob 散列匹配 |
| 旅行航班数据库 | 官方说明链接中的 `1dNtxHFv7k0PeMHI0smZk8t-dBlWLA0Gz` | 304,807,007 bytes；续传完成，SHA256登记在执行清单 |

前两次 Git TLS 失败及 HF 下载重试保留记录。代码下载成功不代表环境已经验证可运行。
本地 OM 仍是已有 `om-sync-port-v0.1`，引用自身固定 Mastra 来源与同步移植差异；
本轮不将官方 LongMemEval 成绩归到新 benchmark。

## 2. 以 Google SWE-Bench 基础路径为移植参照

| 环节 | 固定源码事实 | 本地移植决定与必要差异 |
| --- | --- | --- |
| 检索对象 | `screening()`缓存历史任务查询向量；不是经验正文向量 | 保留查询索引，不因正文修订重新编码整条轨迹 |
| 当前查询 | 先编码原始查询；非空缓存时再编码带 Instruct/Query 的当前查询 | 原始查询用于待提交记录；检索指令的领域名词改为 interactive task |
| embedding | 默认 Gemini embedding 3072维，缓存和查询作L2归一化，以点积排序 | 用户指定 bge-m3 1024维、cosine；服务与索引身份显式绑定，属于本地移植 |
| top-k | SWE-Bench 实际调用 `select_memory(1, ...)`，取一个历史任务的全部 memory_items | 首版 top-k=1个轨迹；每条最多3个经验，RB与候选一致 |
| 普通消费 | 默认 Agent 将检索内容及“逐项说明是否采用”的提示加入 system | 保留这一普通消费能力；原生业务提示/工具保持各 benchmark 合同 |
| 自判 | `llm_judge_status`接收当前任务与非system可见轨迹；temperature=0；回答success/fail | 保留独立自判调用；不接收原生评分、验证SQL/脚本或旅行答案 |
| 成功/失败提炼 | 分别使用 SUCCESSFUL_SI/FAILED_SI；最多3项、不重复、泛化、Markdown标题/说明/内容 | 两类均保留；仅将开头和任务名词由代码修复推广为交互任务 |
| 原始解析 | 按双换行分块存储，消费时再用双换行连接 | 保留原输出；为修订对象补逻辑条目标识和结构解析，解析失败留作维护失败 |
| 更新时点 | 当前查询在筛选前写入索引，经验在任务完成后追加 | 当前查询先放任务暂存；在线结束后成对提交，冻结测试不污染后题；差异由协议要求产生 |
| 持久化 | JSONL银行与向量缓存，通过task_id关联 | 增加作用域、revision和已提交位置，原子保存；恢复不得重新生成已提交经验 |
| 输出资源 | 原提炼temperature=1、max_output_tokens=65536 | 本地窗口仅65536，角色输出上限需与输入共同预留；具体DEV/正式配置独立冻结和计费 |

固定路径及源文件散列见[政策来源记录](../../configs/policies/reasoning_bank/provenance.json)。
复制/适配提示保留 Apache-2.0 原许可及 Google 版权归属。MaTTS 不在本轮范围内。

MemoryArena 内置同名实现不是这次参照：默认top-k=5，add()实际编码传入的整条content，
OpenAI embedding 路径按其tokenizer截断到4096，提炼temperature=0.7、输出4096，消费使用
memory_context 包装。与Google路径的上述差异足以改变检索与成本，故不将它直接重命名为忠实基础RB。

## 3. 在开发生成前冻结的数据集合

`tools/prepare_reasoningbank_study.py` 将原生数据转换到 Git 外 evaluator 输入；
对外清单只包含ID、标签、来源关系、数量及散列。划分不使用答案或评分。
正式冻结文件为 `frozen-splits/splits.json`，源脚本副本和SHA一并保存。

| 域 | DEV | VALID | SUPPORT | TEST | 保留来源 |
| --- | ---: | ---: | ---: | ---: | ---: |
| DB | 24 | 12 | 40 | 100 | 324 |
| OS | 8（只开发接口） | 0 | 40 | 102 | 350 |
| 旅行完整组 | 8 | 8 | 20 | 50 | 184 |

DB按上游来源hash、具名列结构和规范化任务模板的连通关系分簇；OS按raw_entry_hash、
初始化脚本和规范化任务模板分簇；旅行保留完整组，给定base-person查询相同的组放在同一簇。
数字、引号内容、大小写、空白及DB标识符作机械规范化，技能相同不自动合簇。
DEV/VALID/SUPPORT/TEST无已识别来源簇交叉。缺少完整生成谱系，仍可能有未识别的语义近重复。

TEST分别有99个DB来源簇、64个OS来源簇和49个旅行来源簇。OS按完整簇纳入102项，
没有拆簇凑整100。VALID按独立来源簇取样。全部270个旅行组有5–8个待执行人员会话；
50个TEST组共361个会话，给定base person不计额外Actor运行。

DB/OS各固定5条在线流，保留流内原生数据顺序，方法之间顺序相同、银行独立。
原生正确回放子集、贡献拆解子集和两个资源工作点的子集已从TEST预选，未按候选触发或成绩筛选。
所有缺失任务/人员保留计划分母；来源簇和完整组是配对统计单位，在线以流为相关单位。

## 4. 方法能看到的反馈

| 路径 | 可见 | 不进入主方法输入 |
| --- | --- | --- |
| DB/OS四主方法 | 当前用户任务、原生系统/格式提示、真实动作与工具结果、本方法合法历史 | answer_info、验证SQL/脚本、evaluation_info与原生正确标签 |
| 原生verified replay | 原生标准路径，以及官方按CORRECT+COMPLETED筛选的过往Session | 不与无标签主臂的差值解释为纯算法增量 |
| 旅行四主方法 | 给定基础人员事实/计划、当前人员问题、真实工具反馈、合法前序计划来源 | answers、judge hint/answer；显式judgement_mode=none |
| 自判/提炼/修订 | 本方法实际可见的任务、轨迹与引用来源 | evaluator对象、隐藏正确性、其他方法或实验流银行 |

固定库F每题从同一支持库复制任务工作层，末尾自判/提炼仍计费，结果不提交到下一题。
在线O从空库开始，同一流结束后更新；流间不共享。旅行G每组从固定支持制品的独立副本
开始，组内保留人员顺序与新经验，组间不提交测试经验。不同方法独立形成支持制品。

## 5. 资源与当前边界

仅一个求解模型：Qwen3.6-35B-A3B-FP8，实际 `/v1/models` 返回窗口65,536。
本轮新增bge-m3批量接入检查为1请求、2个1024维向量、29个服务报告tokens、0文本生成；
此前方案样例的2请求/36tokens单独保留，不重复入账。reranker默认关闭。

主评价为DB800、OS816、旅行200组次，共1,816个任务/组方法单位；按真实人员数量共3,060次
原生Agent会话。另有69次原生verified replay（DB20／OS49，保留冻结来源簇），支持集每个记忆方法220会话，开发、版本选择、
拆解和额外资源工作点另列。方法运行单位不等于生成次数或已分配额度。

下一步先在DEV采样成本并完成参考方法/候选及原生接入，再锁定阶段预算、最小有用差异和
资源容忍范围。正式TEST尚未开启。W0–W8整体仍在执行，未形成质量、效率或跨域收益结论。


## 本轮原生适配的明确差异

- RB v0.3 保留原始逻辑条目正文，非标准标题标签不触发语义修复或人工重写。
- DB/OS 使用原生 LanguageModelAgent、Task reset/interact/complete 与 metric；只绑定本地 Provider、镜像与外部固定数据。
  DB 按上游实现初始化并删除当前数据库；OS 按上游实现每题重建容器。辅助记忆请求不占用 SQL/bash 原生业务动作次数，模型成本照计。
- OM 复用现有同步 Observer/Reflector 与覆盖标记；保留当前题完整原生对话，记忆投影中的 raw pages 主要补充恢复状态中的历史；沿用 Host 的 goal 事件表示，当前查询可在该表示中再次出现，但不重复展开当前题的原生工具轨迹。
- 旅行保留原生 Agent 的工具循环、30 步上限和最终计划解析。现有部署缺少 auto tool parser，因此复用模型自己的工具聊天模板，经 completion endpoint 返回 XML，再按声明参数类型解析；四方法统一使用该传输。
- 旅行给定 base plan 依记忆方法接法进入各自记忆，维护计费，未计为 Actor 完成任务。候选原计划来源回读属于额外能力，不能归给 RB。v0.4 在采用前发布这些已知事实，并在采用器和 Actor 中展示原文；只追加消融保留相同展示与回读能力。
- 正确历史回放适配调用上游 PreviousSampleUtilizationCallback，包括 CORRECT 且 COMPLETED 的过滤和原生响应截断；正式参考按冻结清单为 DB20／OS49；DB／OS 正式批次已启动。

当前 v0.4 VALID 另将旅行 HTTP 等待从 180 秒调整为 600 秒；方法政策文本不变。
版本对比包含事实展示与传输等待两项变化，不作单一改动的纯因果解释。正式旅行四臂统一使用 600 秒，
DB／OS 仍为 180 秒；单位准入时间和 worker 总截止时间另外约束。

正式DB／OS支持银行形成后先以2worker执行其冻结评价，与2条旅行支持流并行。
总并发仍不超过4；旅行正式银行在其支持流结束后绑定。所有政策、split和单位资源配置不变。
