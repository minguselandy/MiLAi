# v25持久应用、历史边界与质量—成本结论

应用开发及预冻结的八条小规模轨迹完成。短脚本四臂B1/A3/A4/A5分别7/9、7/9、9/9、8/9；medium B1/A4为7/9、8/9；long为7/9、9/9。A4在三档历史中均按最新9单位计划行动，但一次新session维护仍编造业务ID。结论是持久应用接线和受控适应成立，端到端可靠性、稳定未见收益与跨模型泛化尚未成立。

本阶段为`COMPLETE_WITH_KNOWN_AGENT_FAILURES`，总计划仍ACTIVE。没有修改vLLM、Product、SER策略或源锁；没有增加测试规模、cue候选或重复成功轨迹。详见[全部机器可读结果](../data/manifests/milai-application-v25-results.json)、[短四臂完整分析](MILAI_APPLICATION_V25_SHORT_RESULTS_20260927.md)和[公开复现命令](MILAI_APPLICATION_V25_REPRODUCTION_20260927.md)。

## 同源与输入边界

所有运行使用Git `44fb7ac9b6ed90cdfce1da8c17de734638d9b937`、81文件mapping `ff874dc00936261303336963a415007ddbe93bbdf06a87cb87ae0a7409ab6e38`。全部运行后source/validation哈希仍匹配[源锁](../data/locks/milai-application-v25.lock.json)。六项新窄测试、一个受影响旧检查、ruff/mypy及唯一build在运行前完成；之后只分析真实产物和核对文档，不重复测试、构建或调用模型以发布。

三档[输入](../data/manifests/milai-application-v25-history-inputs.json)在任何短脚本请求前已固定。只有一次性无关办公室日志的长度变化，medium/long分别48/192行；九条公开消息、两用户、五阶段、真实搜索、assistant结论、两次revision变更、一次delete、partial failure、restart和新session均保持。用户文本合计354/2013/7053 tokenizer tokens，日志本身50/1709/6749。它们是控制长度扰动，不是自然多月使用分布或满65536窗口压力。

每臂五个独立进程，各自重新打开同一持久状态；每臂独立namespace和业务世界。阶段0操作员通过上游工具seed四条记忆，随后公开update/delete，工具返回的ID绑定alias。世界实际提交预留再返回标签失败；阶段3恢复服务后同ID创建标签，无物理发货。显式用户维护不记为自主Formation/Reconciliation。

## 各长度实际结果

| 长度 | Arm | 严格任务 | Host完成 | 首次动作currentness | 生成 | 输入/输出tokens | 总tokens | embedding请求/tokens | 方法get | 实际最大request输入 | Alice动作request输入 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| short | B1 | 7/9 | 9/9 | 1/2 | 19 | 25834/1099 | 26933 | 12/334 | 0 | 2611 | 2018 |
| short | A3 | 7/9 | 8/9 | 1/2 | 27 | 62370/1218 | 63588 | 23/424 | 7 | 5557 | 2263 |
| short | A4 | 9/9 | 9/9 | 2/2 | 19 | 28679/1138 | 29817 | 13/339 | 7 | 2728 | 2162 |
| short | A5 | 8/9 | 9/9 | 2/2 | 19 | 29860/1105 | 30965 | 13/339 | 4 | 3157 | 2573 |
| medium | B1 | 7/9 | 9/9 | 1/2 | 18 | 33642/1087 | 34729 | 13/323 | 0 | 4300 | 3698 |
| medium | A4 | 8/9 | 9/9 | 2/2 | 18 | 35394/1148 | 36542 | 13/323 | 7 | 4465 | 3867 |
| long | B1 | 7/9 | 8/9 | 1/2 | 27 | 92119/1240 | 93359 | 23/421 | 0 | 9326 | 8725 |
| long | A4 | 9/9 | 9/9 | 2/2 | 19 | 62309/1140 | 63449 | 13/341 | 7 | 9467 | 8881 |

中、长轨迹见[medium逐消息结果](../data/manifests/milai-application-v25-medium-results.json)、[long逐消息结果](../data/manifests/milai-application-v25-long-results.json)。所有分母包含失败，未用后续最好结果替换。合计62/72严格任务、70/72 Host完成；这些是八条相关开发轨迹，不能当作72个独立样本或balanced treatment effect。

八臂世界均最终两条reservation、两次reserve、一次同ID complete_label，无重复reserve。Alice部分失败副作用保留与同ID恢复各2/2；Bob三任务均通过；删除1/1、Alice access及Bob原计划保持2/2；实际Store search namespace和业务user scope均匹配。B1/A3错误6单位预留恢复成功仍是错误行动。Bob记忆中的旧pending状态未被维护，详见短报告限制。

A4三档机械demotion均12/12 precision/recall，short A5为14/14；这是snapshot风险口径，不等于词语相关性。所有方法臂在“无关日志”消息生成前都发生一次计划exact读取，说明当前实现按即将发送的历史证据版本介入，不能声称按当前任务语义零干扰。该消息均仅确认日志，没有额外持久写入或业务操作；语义refresh贡献仍UNKNOWN。

## Pareto与费用归因

短四臂在质量/生成tokens两轴的非支配集合为B1/A4；A5虽然总tokens更高且少一分，但少三次get，三轴评价不能直接说被A4全面支配。medium B1/A4也是质量与费用的权衡：A4多1813tokens、多一分。long数值上A4同时高两分、少29910tokens。

长档差额主要来自fresh-session轨迹，不能归因于长历史压缩。phase4两用户总tokens为B1 39226、A4 8076，相差31150；此前真正携带长历史的phase0–3为B1 54133、A4 55373，A4反而多1240。短、中对应phase0–3 A4也分别多1191、1326tokens。所有八条运行中phase0 Alice/Bob及phase4 Alice/Bob的首个实际request分别逐字段相同，包括schema；phase4没有长日志或旧checkpoint。因此新session里的循环、虚构与工具命中差异是轨迹混杂，不能作为长度因果效果。

| 长度/Arm | Provider/进程wall秒 | projection CPU/wall毫秒 | exact read wall毫秒 | observer CPU/wall毫秒 | trace/sidecar/checkpoint/world字节 |
| --- | ---: | ---: | ---: | ---: | --- |
| medium B1 | 12.193/30.059 | 0/0 | 0 | 95.059/1485.667 | 818338/196608/425984/36864 |
| medium A4 | 12.711/31.965 | 21.094/29.924 | 11.345 | 91.271/1934.384 | 946414/208896/430080/36864 |
| long B1 | 20.801/41.374 | 0/0 | 0 | 138.958/2439.478 | 1532840/311296/1028096/36864 |
| long A4 | 16.019/34.729 | 26.933/32.964 | 13.126 | 99.627/1707.205 | 1080373/237568/761856/36864 |

短四臂对应完整表在短报告；全部文件大小及各阶段tokens在总manifest。A4机械开销本次没有随填充长度单调增加，只有一个轨迹/长度，不能拟合复杂度或声称稳定时延改进。进程wall包括启动及observer，不能与纯Provider latency混用。

全部八条增加166生成、370207输入+9175输出=379382生成tokens、123次embedding/2844tokens、32次方法get。observer每臂16次额外Store读取，共128；Root阶段后两用户快照每臂10次，共80，均独立于方法get。操作员manage共56、Host manage共8，真实无效/错误更新也计入。unknown、截断、Judge均0，两次精确12生成/消息容量失败（short A3、long B1）保留。

连续账本从671生成/604171tokens/6104embeddingtokens/75get增至**837生成/983553tokens/8948embeddingtokens/107get**，无清零或忽略失败。source/build验证成本和工具/observer开销分列，不将少量方法CPU当成总应用成本。

## 新失败的Failure Review

**Observed / Expected：** medium两臂应在新session读取实际业务记录，用真实ID/label状态更新原计划，实际却写入同一虚构`RES-COBALT-001 / Reserved`。long B1应同样读取世界，实际循环至容量上限。

**Actual chain / first broken link：** medium两臂先调用两个search_memory，再直接manage_memory(update)，整个新session没有get_reservation；实际世界分别已有随机RSV-UUID且标签created。虚构常量既不在公开输入也不在World源码中。long B1先两次search，再把原plan ID写回相同pending正文，随后约十次重复搜索reservation status，仍不读世界。断点是从记忆查询转向业务事实获取的工具选择，之后分别产生虚构或循环。世界持久副作用不回滚，Bob后续任务正常完成。

**竞争解释与证据：** H1为业务适配器或跨进程资源不可达；H2为Host在多种工具间错误取证并补全缺失事实；H3为SER或长历史导致fresh-session差异。此前恢复都读到真实记录，long A4也实际search→get命中完整key→原ID更新→完成，反驳确定性不可达。全部初始wire相同且fresh session无旧历史，不能把首步工具差异归因于SER/填充长度。Root和Sol独立只读源码/HTTP/状态复核结论一致。

**通用修复候选与条件判定：** 未来若单开工具事实维护研究，可比较通用的“先获得对应世界对象的实际回执，再维护事实”合同与未知状态保留；不得从rubric自动填ID、修业务参数或引入领域别名。本阶段不再追加措辞、强制CRUD或回环。§38 Capsule要求当前必要证据已送达却仍被旧上下文压制，这些新session根本没有读取世界证据；§39 Action Grounding要求隔离、当前送达、derived demotion后仍旧参数，而A4三档行动均当前。因此两项条件机制都未被此结果触发。

**Confounds / 最小下一步 / 决策：** 一个Qwen模型、每格一次、固定运行顺序、合成日志、显式外部修改与显式维护。停止扩展本开发脚本，完成公开交付；保留未来独立多模型和外部对照缺口。Continue总计划证据补全，Kill“本次9/9即可靠长程Agent”及“long节省证明压缩效率”的强结论，不迁移Product。

## 十项Reflection

1. 支持了什么：三个长度的A4都消费最新计划，持久世界/restart/scope及请求副本边界成立。
2. 反驳了什么：正确版本视图不保证工具选择、事实维护或总成本优势。
3. 第一断点：fresh-session未从memory转向实际world取证；B1动作另有旧值问题。
4. 简单解释：同首请求的不同轨迹和普通模型补全，足以解释部分分差。
5. 简单方法：B1成本较低的短、中结果仍在Pareto；不以机制复杂度代替效果。
6. 复杂度是否合理：小型source adapter和持久模拟足够复现问题，不新增reviewer或语义状态平台。
7. 过拟合风险：修`Cobalt_collection`或`RES-COBALT-001`会变成领域规则，故不做。
8. 需要什么反例：未来独立研究区分真实不存在、错key、正确key、读取遗漏，并保持rubric外置；本次不后改输入。
9. Continue/Pivot/Kill：应用阶段完成且局限保留；F/R提示家族仍停止；总目标继续但Product NO-GO。
10. 原因：源代码和受控机制证据充分，未见收益及至少两模型族的证据仍欠缺，不能用更多同类开发例替代。

## 交付与剩余范围

公开交付包括运行入口、源锁、提前固定的全部输入、每臂/每长度判定、完整成本、错误链与复现命令；原始Provider正文、DSN、数据库和构建产物保持ignored。参照源码Mem0/Memobase/Graphiti/LangMem已固定来源，源码借鉴不等于同域外部实验。

P10的第二模型族尚无可用独立端点；此前已异步请求，未收到资源信息。上游LangMem B1已有实际对照，其他外部系统未完成同域matched比较。主未见收益未建立，§42广泛鲁棒性参数扫描不启动；不能为补表改现有vLLM服务。总[证据表](MILAI_LONG_HORIZON_EVIDENCE_MAP_20260927.md)明确区分完成、条件未触发和未完成，不因v25结束而关闭master。
