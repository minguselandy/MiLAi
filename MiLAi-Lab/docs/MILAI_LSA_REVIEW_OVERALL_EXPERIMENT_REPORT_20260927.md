# MiLAi 总体实验报告：16轮历史结果与复盘收尾

日期：2026-09-27。范围：MiLAi-Lab / RESEARCH_PROTOTYPE。**按用户要求暂停；研究总目标未完成，Product NO-GO。**

本报告承接[原16轮总体报告](MILAI_LOCAL_STATE_ATTENTION_OVERALL_EXPERIMENT_REPORT_20260927.md)，
汇总此前SER、生命周期、应用和原生Mem0证据，以及复盘后的D0修复、E2条件诊断和在线快照比较。
原16轮数值、源码锁和失败保持原样，不把不同源码和分母合成一个“总准确率”。
[机器清单](../data/manifests/local-state-attention-review-overall-results-20260927.json)保存结果身份与连续费用。

## 可以支持的结论

已实现真实事件维护、局部State、选择与来源展开、跨进程恢复、公共checkpoint历史、滑窗摘要，
并修复部分提交后精确重试重复create的确定缺陷。新增可选回合快照与显式close，默认pre_model保持。
工程检查和小规模真实轨迹支持接线事实，**尚不足以证明稳定的未见收益或State-conditioned Attention的独立价值**。

旧同源重复比较G/L均60/78，LRU59/78；消息嵌套于情景，不是78个独立样本。
短历史完整上下文基线达到相近或更好结果，成本较低；这些是各自历史源码的结果。
本次复盘先定位确定缺陷，再分别测时间边界，没有重跑全部16轮或启动新的大矩阵。

## 前序阶段与历史16轮

| 前序阶段 | 结果 | 解释边界 |
| --- | --- | --- |
| SER最终开发控制 | 13/13 | 不等于未见收益 |
| v23原生MERIT | B1 6/10，A3/A4 7/10 | 无自然refresh/rebase，不能作SER因果归因 |
| v24 formation | 三种提示各0/2 | 已停止措辞路线 |
| v24 reconciliation | strict2/3，所需维护0/1 | CRUD能力不等于正确语义维护 |
| v25应用 | 8次冻结运行 | 保留过期行动、容量循环、错误key和虚构ID |
| v26原生Mem0/B1 | 4/4 vs2/4；53852 vs5324tokens | 已暴露4样本，不同系统契约；ADD-only不证明同ID修订 |

详见[前序证据地图](MILAI_LONG_HORIZON_EVIDENCE_MAP_20260927.md)和[原总体报告](MILAI_LOCAL_STATE_ATTENTION_OVERALL_EXPERIMENT_REPORT_20260927.md)。

| 历史LSA轮次 | 主要结果 | 生成调用 / tokens / embedding tokens |
| --- | --- | --- |
| P1 R1 | title字段契约不一致，未形成State，随后修复 | 6 /5489 /0 |
| P1 R2 | 9/12，完整1/2 | 34 /34388 /9 |
| P2 R1 | 12首响应：3直接正确、2中间步骤、7错误；另3诊断 | 19 /17520 /768 |
| P1 R3 | 原5/12，附加1/2；保留容量失败 | 61 /84307 /181 |
| P1 R4 | all/focus原各7/12 | 96 /115854 /256 |
| P1 R5 | 来源展开on4/6、off3/6；on同ID恢复 | 40 /46862 /88 |
| P3 wiring R1 | G11/12、L9/12 | 72 /93431 /173 |
| P3 wiring R2 | G9/12、L8/12、LRU6/12；U阻断创建 | 130 /142179 /70 |
| P3 wiring R3 | 修共享创建机会后LRU8/12，不替换R2 | 61 /51693 /0 |
| P3 matched R1 | G/L60/78、LRU59/78；完整2/12、3/12、4/12 | 922 /1241742 /6173 |
| maintenance-events R1 | 原高耦合各6/6，新distinct反例LRU3/5 | 108 /135012 /848 |
| Host snapshot R1 | 固定首响应局部正例，无业务执行 | 6 /8062 /0 |
| Host snapshot R2 | 六反例未通过，候选未部署 | 6 /11093 /0 |
| LR wiring R1 | L9/12、LR10/12、LRU8/12；分组分叉 | 150 /153520 /154 |
| History wiring R1 | full/LR均10/12；tokens18508/56198 | 67 /74706 /108 |
| Window summary R1 | summary9/12、full10/12；tokens19703/18501 | 36 /38204 /0 |
| **历史16轮合计** | 不跨轮汇总准确率 | **1814 /2254062 /8828** |

各轮细节和源码身份由[历史清单](../data/manifests/local-state-attention-overall-results-20260927.json)逐一链接。
P3 matched预定36轨迹，35完成，1条原生memory缺ID异常后剩余消息未运行但计入原分母。
旧current_task重复维护缺陷在之后修复，不能把旧分数宣称为最新代码验证。
完整历史与滑窗摘要都保留原checkpoint，不代表物理压缩；summary在第三次更新丢失原简报事实。

## 复盘后已完成工作

D0从真实历史提取10个完整合法前缀，覆盖保持、二次增量、对象key，以及无变化、同文本不同事件、真实改值、内部回执、部分成功。
原输出和rubric与runtime隔离。确定复现混合edit部分提交后精确重试重复create，修复以原子保存的隐藏重试标记防止相同事件集合/编辑位置重复应用。
不同source ID的同文本事件仍可生效。**old+new事件合批不是同一精确集合，本修复不保证模型重新解释时的语义纠错。**
见[D0故障矩阵](MILAI_LSA_REVIEW_D0_FAILURE_MATRIX_20260927.md)。

[E2条件诊断](MILAI_LSA_REVIEW_E2_R1_RESULTS_20260927.md)采用6个实际前缀×2视图×2重复，
post-event为10/12，turn-start为11/12。第二次加一前缀post-event两次输出5、turn-start两次4；
但turn-start一次将实际回执S-2改成计划storage S-2，保留为失败。24次生成/36050tokens，无业务执行、Store写入或embedding。
这是两个已暴露轨迹的条件证据，不是在线维护、持久化收益或740tokens在线节省证明。

当前在线原型在回合开始保存完整State正文，同回合固定展示；正常/容量结束明确close，只维护实际pending事件。
普通异常只收集尾部，不隐藏追加模型调用。真实业务完成与State close分列。
源码由Sol xhigh负责，Root负责冻结、全部真实HTTP、评分和账本，Luna high负责发布；Astra只参与一个跨层边界问题。

## 当前在线比较

源码 `0c5f027750eac1a45245d5a9ac43e48eb5e202e9`，原distinct/partial脚本各一次，
pre_model和turn_end共4轨迹/22消息/8阶段进程。输入、合同、scorer、顺序及状态隔离先冻结；Root串行真实调用。

| 当前源码小比较 | pre_model | turn_end |
| --- | ---: | ---: |
| distinct增量strict | 3/5 | 3/5 |
| partial恢复strict | 4/6 | 4/6 |
| 合计strict / 完整轨迹 | **7/11 /0/2** | **7/11 /0/2** |
| Host调用 / tokens | 19 /32134 | 18 /21072 |
| 维护调用 / tokens | 19 /22319 | 11 /11967 |
| 全生成调用 / tokens | **38 /54453** | **29 /33039** |
| embedding调用 / tokens | 3 /211 | 3 /90 |

快照组这两条样本tokens少39.33%，但质量未改善；各组在线形成内容、普通memory调用、维护节奏、错误路径共同变化，不能称纯时间标签消融或稳定压缩效果。
每格只有一次、两个已暴露脚本，不作显著性或未见推断。

37个Host原始prefix与持久checkpoint匹配；30个维护请求仅使用实际事件且无current_task。
turn_end的11回合快照在18次Host交付中各自稳定，11次close成功且pending清空。
两组Mira均真实读取并沿原ID补标签，没有重复reserve；双owner分离和D-2/10:15保持通过。
没有自然触发同回合崩溃、容量或close失败，不能把离线模拟验证计为真实发生。
[本批详细结果、失败链与复现](MILAI_LSA_REVIEW_E2_SANDBOX_R1_RESULTS_20260927.md)给出完整口径。

## 故障解释与决策

**distinct增量：** 两组维护器都先正确得到2→3→4。pre_model的Host把4再加为5，且用虚构非UUID普通memory ID；
验证错误原样带回提议的5，下一次维护将5写进State，最终真实预约5。turn_end的Host面对快照3和新加一仍写普通memory3，
把旧用户message UUID误用为memory ID（实际发生新insert）；close正确写4，但后续Host沿旧助手答案真实预约3。
两组还将业务destination缩成S-2。第一个错误在第二增量Host提案；时间混淆与旧来源/助手及普通memory身份混淆是竞争解释。
前序条件正例不能覆盖这里的在线反例。决定是保留可选原型、收缩“快照已解决重复消费”的主张；消费层固定前缀诊断留待恢复，不再补措辞。

**对象身份：** 两组partial的Mira/Noel均实际用单数Summit archive crate，违反原复数key。
初始State title已单数化，正文和用户仍为复数；title诱导与Host自行词形归一化未独立区分。
同ID恢复正确不追补初次key错误。恢复无physical dispatch推断，数量/地点/包装和保留access正确。
下一最小候选是固定正确正文仅改变title来源的条件对照，加无State原prefix控制；这些仅是暂停后的候选，不是执行授权。

**保持和选择：** 旧综合卡/滑窗摘要丢无关事实仍未被此次epoch改动解决或重新验证。
E1局部entry尚未实现，同bank A/U的独立价值仍未测试。不会把未运行写成无效，也不会据局部正例宣称整个State–Attention成立。

通用边界仍成立：Store提交不证明内容真实；合法来源引用不证明语义支持；正确原始证据不保证Host精确复制对象key；
真实同ID恢复不追补初次错误key，也不允许无依据推断physical dispatch。当前版本与来源权威不是同一概念。

## 成本与验证

| 累计口径 | 生成调用 | generation tokens | embedding tokens |
| --- | ---: | ---: | ---: |
| 历史16轮LSA | 1814 | 2254062 | 8828 |
| 本次D0离线修复 | 0 | 0 | 0 |
| E2条件诊断 | 24 | 36050 | 0 |
| E2在线小比较 | 67 | 87492 | 301 |
| 本次复盘增量 | **91** | **123542** | **301** |
| 全部LSA（历史16轮＋本次2个真实批次） | **1905** | **2377604** | **9129** |
| 连续账本最终 | **2768** | **3420333** | **18746** |

连续账本从LSA起点863/1042729/9617累加；更早sealed history保留且未重复计入此表。
账本SHA256 `a9d4c681e2bee395c170a4672b4895a442522df47951c9a043e9f6b3a32e3580`；unknown usage为0。
包含失败、工具错误后的维护/修正、控制与Host、embedding及空edit。不是开发代理token成本，也未虚构货币/GPU摊销。

当前批次pre_model方法Store get/search/put为280/172/75，turn_end为315/114/69；
请求/返回逻辑字节分别134062/315983与127158/222398。turn_end额外保存6235快照正文累计字节，
close读checkpoint 11次/26382逻辑字节；这些已进入相应方法指标，不能再按免费视图计算。
普通memory两组各3次成功写入、pre_model另1次无效ID错误；observer额外Store读取各6次。
Root预检和阶段快照另16次search，无embedding。各角色延迟、observer CPU/事务、数据库/日志文件大小见机器清单；
逻辑API/文本指标不代表底层磁盘物理I/O或物理压缩，缺少的历史量不追造。

D0最终6项相关窄测及目标静态通过。E2在线原型17项相邻检查通过，最后边界改动后7项turn_end检查通过；
目标Ruff/Mypy、四次零模型prepare和必要构建通过。这里是有重叠的检查批次，不能相加称24个独立测试。
真实SQLite/checkpoint加模拟HTTP覆盖部分业务成功后State写失败恢复、同回合快照、容量尾部及异常无隐藏调用。
这些离线故障注入与未自然发生的真实模型恢复情形分开报告；发布不重跑已通过检查。

最终构建SHA256：sdist `535e1e5055d1016263a6eff6233d622badbbdcdcb27af57206a6246ddc09be11`；
wheel `c771232d9ed9d4ae4a635a91f3d4d8c56ccb660eca317fb38563d8b53cd67a74`。
无Product API/Schema/权限变更。Lab增加可选epoch行为与内部meta快照；不迁移Product、不改共享vLLM部署。

## 未完成与暂停交接

| 项目 | 状态 |
| --- | --- |
| D0失败集/精确部分提交重试 | 完成离线修复，语义边界明确 |
| D1 E2条件与在线小切片 | 完成本报告范围；不足以代表整个D1 |
| D1 E1局部entry与组合比较 | 未实现/未运行，8个候选转移仅为草稿 |
| D2固定bank A及固定前态U/U=A/oracle | NOT_RUN |
| D3统一最新底座full/G/L/最小LSA重复比较 | NOT_RUN |
| D4代表N/d/a/r/H、R与维护摊销 | NOT_RUN |
| D5模板留出、新MERIT selection、MemoryArena原生评分、独立模型家族 | NOT_RUN |
| D6学习selector | 条件未触发 |
| 归档/重新激活、共享原子组、全链物理删除、真实未知副作用恢复 | 未完成 |
| 论文最小证据包、稳定未见收益、Product | 未完成 / NO-GO |

MERIT seeds0–4已暴露；MemoryArena资源准备不等于benchmark已完成。没有下载/部署v27第二模型。
旧未跟踪 `docs/MILAI_MODEL_SENSITIVITY_V27_GOAL.md` 原样保留且不发布。

暂停依用户明确指令，不能由旧ACTIVE文案覆盖。所有代理开发和真实实验均已收尾，既有共享服务不停止、不调整。
再次开展开发/实验/下载/部署须获得新的明确继续指令。报告整理与GitHub发布是本次收尾授权。
历史原始轨迹、DSN、数据库、环境、模型、缓存、构建产物继续排除Git；按每批source commit复现，续记账本且用新namespace。
[当前执行记录](MILAI_LSA_REVIEW_EXECUTION_GOAL.md)保留完整目标，暂停不冒充目标完成。
