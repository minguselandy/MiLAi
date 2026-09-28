# WP1：入口职责与活动指引整理

状态：结构与局部等价验收、最终必要构建通过；[PR53](https://github.com/minguselandy/MiLAi/pull/53)已发布，Fast36328343542及最终gate108646972066已通过。范围为等价结构整理，不改研究方法、模型提示、CRUD行为或实验分数。
本切片按[新计划](MILAI_NEXT_IMPROVEMENT_PLAN_20260927_v1.0.md)和
[执行记录](MILAI_NEXT_IMPROVEMENT_EXECUTION_GOAL.md)推进。尚无新增真实模型调用。

## 来源与分支

C0修复为`ebf7878fc34bef6f72723ce22e445e5bf712d4f3`，
[PR52](https://github.com/minguselandy/MiLAi/pull/52)以main `9515017`为base。
修复后的Fast gate和Full全部21个job均已通过，最终composition为job108643022708，
2026-09-27 14:54 UTC核实，WP0/G0关闭。C1在直接相关检查先通过后开始可逆整理，
其间最后的历史回放也完成；没有拼接前一提交的成功项，没有开始行为实验。

本地`refactor/lab-lsa-runner-20260927`从该C0提交起步，按顺序保留PR51的原结构改动：

| 原提交 | 带来源记录的本地组合提交 |
| --- | --- |
| `26c4f3058691af3fe31cda906f67ffce6bd1986f` | `8337bb6dd233b88f2377e5b7a0a81f122be0e325` |
| `055a0769c1ce75d128d6459ee25773587d9003ae` | `5dc024d3b277915709556af4e3eee4e1e64f06f1` |

组合无冲突。main、C0及PR51原分支未改，原PR未合并或关闭。
PR51原head的71项纯合同仍是原head证据，新的组合按实际源码验证。

## 首断点、解释与最小变更

现有持久阶段执行已在`runners/langmem_application.py`；LSA工具入口仍包含配方、
身份、prepare/run装配。竞争解释为H1缺少另一套执行器，H2现有装配职责放错层。
源码支持H2，故只收拢到包内窄runner，CLI保留参数解析与必要的兼容委托。
协议/controller分工保持；不制造第二套运行算法或通用资源查找平台。

包内调用需要明确的Lab资源根，不能用安装后site-packages的父目录冒充数据根。
CLI继续按原checkout位置传入。实现位于`src/milai_lab/runners/local_state_attention.py`，
`prepare/run`明确接收`lab_root`；CLI仅保留参数解析、委托及四个仍被调用的纯函数别名。
原持久阶段执行继续复用`langmem_application.run_phase`，没有新增执行算法。
唯一源码负责人为Sol xhigh，Root负责本文件及活动指引，Luna high负责Git发布。

## 活动指引与历史保存

Root将此前AGENTS全文逐字节复制为同目录
[AGENTS_HISTORY_PRE_WP1_20260927.md](../AGENTS_HISTORY_PRE_WP1_20260927.md)，
保留其相对链接的原含义。原文件为60237 bytes、753行，SHA256为
`a97255a2ff0891e4586310af5c86f723ed82cd7fe7af2aedacddc66168d1c77d`。
恢复来源是提交`5dc024d3b277915709556af4e3eee4e1e64f06f1`的`MiLAi-Lab/AGENTS.md`。
没有改写或删除旧PAUSED、失败、成本、Product NO-GO及v27限制。

新的[活动AGENTS](../AGENTS.md)集中当前Goal、收尾暂停要求、职责、不可变边界、
冻结/计账及检查入口。旧执行记录转为历史参考，避免多个年代的ACTIVE/PAUSED被并列误读。
当前稿7054 bytes、101行只是文档规模描述，不证明运行复杂度或模型实验成本下降。
历史快照须进入sdist，以保持活动指南中的链接可用；该打包声明由Sol实施。

## 验收范围与当前限制

Root静态核对原CLI与新包AST：七个辅助函数及`ContentLimits`定义相同；身份计算、
prepare/run只增加显式资源根和对应传递。新`_source_paths`继续覆盖全部活动包源码、
CLI与pyproject。身份从146项变为147项：新增runner，CLI及pyproject改变，未移除项。
旧身份从`5dc024d3`的准确Git blob独立计算，不用新磁盘文件伪装旧源码。

实现前后使用相同输入与mock响应，比较完整已解析HTTP payload及JSON键/候选顺序、
U→维护→A、来源、pending、容量、实际业务回执、Store、trace及模拟预算。
这不是原始HTTP字节等价证明。执行中用不排序JSON序列化比较内存中的键序；
落盘的规范化JSON还由Root逐字节核对，三对hash一致。

| 合成情形 | Host / control调用 | 终态及保留项 | 旧/新 |
| --- | --- | --- | --- |
| 预留成功、标签失败；新session续问 | 3 / 8 | 两条消息完成，真实部分副作用保留 | 一致 |
| 每消息control cap=1 | 3 / 2 | 两条完成，2条pending仍保留 | 一致 |
| Host持续查询至容量上限 | 12 / 13 | TERMINAL_WITH_LOCAL_CAPACITY_FAILURE | 一致 |

规范化仅替换案例临时根、`wall_seconds/wall_ns/cpu_ns`；UUID序列和mock请求ID预先固定，
没有过滤业务字段或提示正文。源码identity及prepared identity hash从行为比较中单列。
使用真实本地SQLite checkpoint/合成业务库、InMemoryStore和MockTransport；没有共享
PostgreSQL或真实模型调用。完整摘要、source delta及三对文件hash见
[机器证据](../data/manifests/next-improvement-wp1-equivalence-20260927.json)。
原始合成观测和一次性比较脚本保存在ignored `artifacts/next-improvement/wp1/`。

同一针对性集合整理前后均25 passed；LSA/application相关集合80 passed；移除未用兼容别名后
仅重跑受影响的11项入口检查，全部通过。目标Ruff/Mypy、145活动源码归属matrix、两个边界及
diff-check通过。构建须确认wheel含新runner、sdist含薄CLI与历史AGENTS快照；最终hash留在
包外发布回执，避免把sdist自己的hash写回包含它的文档。

发布预检补出一个遗漏：此前未暂存diff-check未覆盖新增runner；暂存后发现末尾多一个空行。
首次构建本身成功，本地提交`9bc3c9f`保留且当时未推送；Sol只删除最后一个换行字节，
Root核实AST完全相同，更新源码身份。三组差分与局部测试不因该空白变化重复运行；
最终包重新构建，首轮包/日志/hash保留，准确最终hash在发布回执。该修复不改旧AGENTS字节。

该切片减少CLI中的装配职责和活动指南历史歧义，没有减少语义写入路径、依赖或模型调用。
它只接受这三个离线场景中的结构等价，不证明研究质量或成本收益。
不为本文件重复已经通过的71/35纯协议检查或C0全量测试。
若发生提示、策略、阈值、预算或可见材料变化，必须另立行为身份，不能称等价整理。

恢复代码不会恢复已经发生的业务世界。当前无新增真实业务动作，连续实验账本仍为
2768次生成、3420333 generation tokens、18746 embedding tokens。
用户要求在完整当前任务结束后暂停Goal并发布总体报告；本切片完成不等于总目标完成。

发布核对：远端head为`0d04ca68d0e575919773c24b764c3c0b1832de7e`，base为C0分支ebf7878。
最终wheel为`b968f3183fdb4b47ec08526e1a50f58cdb47566da892a16f5eee5796584cd552`；
sdist为`db650a7bb4c4d173d2cdc0ce4382dff12745567535decec211875b4fe0a134f4`。
本段是发布后的结果补记，属于随后C2文档记录，不回写已构建C1分发包。

C1远端终态：Fast36328343542全部按变更选中的必需job及汇总gate成功；
未选中的Product/Archive job为skip，不计为通过。未额外触发C1全量Full；
C0完整组合门禁与C1局部变化检查按各自源码版本分开记录。

C1远端core为5114 passed/142 skipped/14 deselected（525.91秒），并完成分发构建；
单独执行的71项纯协议包含在5114总集合内，不再相加。foundation合计145 passed/1 deselected，
external成功。实际checkout为PR merge tree `98e3c3d8546f7f5118132bb01d87a0fda59a34bb`，
将C1 head组合到C0 base，不表示已合并。日志hash与分发回执补记在机器证据。
