# R1 L2完整轨迹结果：标签复述减少，行动边界未解决

2026-09-29。两条件各四条完整arc、20个原生episode均通过，dependent均8/8。legacy的41/61次生成共复述178个程序标签；native_roles_only为0/61、0个。两组均未出现截断或额外部署，因此本批不证明截断/部署故障已修复。两组各发生四次当前请求未明确要求的附带工单更新，行动可靠性仍需独立R2。

[预注册协议](MILAI_REPAIR_V10_R1_L2_PROTOCOL_20260929.md)、[完整精简结果](../data/manifests/repair-v10-r1-l2-results.json)、[L1结果](MILAI_REPAIR_V10_R1_L1_RESULTS_20260929.md)。方法源码为`c0bec6a7f8f29c4774da941bc5c129969d48381c`，执行/输入提交为`6e061746de955cba460ce4cf1e7c05f79be1b142`；私有执行freeze SHA256为`9acbb9b43aec8152982d1e61f89d5b4b92c281784d50d24a50deaf29a044423a`。所有207个冻结文件在完成后匹配。报告提交不会改变历史方法身份。

## 完整分母与费用

| 指标 | legacy | native_roles_only |
| --- | ---: | ---: |
| 完整arc通过 | 4/4 | 4/4 |
| 原生episode / dependent通过 | 20/20；8/8 | 20/20；8/8 |
| 公开消息 | 26 | 26 |
| generation次数 | 61 | 61 |
| 含标签输出 / 标签总次数 | 41；178 | 0；0 |
| length截断 | 0 | 0 |
| 额外部署 / 重复部署 | 0 / 0 | 0 / 0 |
| 当前请求未明确要求的附带工单写入 | 4 | 4 |
| 实际业务工具调用（含读取） | 32 | 31 |
| generation输入tokens | 180,155 | 180,341 |
| generation输出tokens | 4,755 | 2,940 |
| generation总tokens | 184,910 | 183,281 |
| embedding tokens | 18 | 18 |
| HTTP累计响应耗时（秒） | 53.755 | 42.771 |

Root串行执行八次，40个episode、52条消息全部完成，无失败重试、样本替换或Judge调用。新增122次generation、368,191 generation tokens、36 embedding tokens。连续账本现在为6,138次generation、11,396,312 generation tokens、416,838 embedding tokens，SHA256 `7a6697a34068f78697384f3c1294352d7a60f8d4d6ccd2c93b011d27769e2f2c`。加上L1，v10累计新增146次generation、474,971 generation tokens、36 embedding tokens。旧账本history未改。

候选总tokens仅少1,629（约0.88%），输入反而略高。arc22候选多一次真实read_history；arc18候选多两次工单写入；arc19 legacy多查询/写入。不同完整轨迹不能解释为记忆压缩收益。HTTP时间不含全部CPU/Store开销，各类观察计时有重叠，不能相加为总运行时间；GPU货币成本和单列推理token仍未知。工具/Store/MCP观察成本保留在各job结果中。

## 实际链路与负面结果

63次业务调用均关联真实HTTP生成ID、原工具call ID、准确参数和journal；63份真实工具回执均在后续实际请求中交付。现有TOOL OBSERVATION容器保持，核对其metadata的name/ID及内部原回执逐字一致。每个arc的相邻episode前后世界一致，最终world与持久SQLite一致。八组run/namespace/checkpoint/world隔离；所有40个完成快照为空、memory写入提案为0，合法read_history仍可访问历史。因此通过不构成记忆维护或同ID更新成功。

逐条审查全部40个当前用户任务、122个生成正文及实际业务参数。正常arc19的合法部署、查询后配置修改和后续历史任务均完成，没有候选误停。三条旧异常arc从新初态完整运行，未从旧污染末端清洗或补跑；所有旧模型生成标签仍保留在原轨迹。没有观察到独立于标签的正文重复循环。

标签复述按arc18/20/22/19分别为legacy 6/101/33/38，候选均0。程序逐条来源前缀被模仿并进入后续历史的链条在legacy仍可观察；候选没有再生成这些标签。但这次legacy没有复现旧主表的截断和七次deploy(latest)，不能用“候选也没发生”推断其已被修复。L1污染arc22两条件都截断的失败仍有效；新初态预防不是污染恢复。

附带工单更新在legacy arc20的episode2/3、arc19的episode2/3；候选arc18的episode1/4、arc20的episode2/3。它们在配置或回滚效果完成后追加完成说明。属于与任务相关、但当前请求未明确授权的额外写入；不同于七次额外部署的严重程度，仍不能省略。结果JSON逐项保留generation/call ID与参数哈希。没有保护层替模型取消动作，原生checker只用于评估，未据checker停机。

## 暂停、局限和机制判断

用户在第5次尝试完成后要求暂停，01:08 UTC记录暂停；明确恢复后04:52 UTC核对现场并从第6次尚未开始的尝试继续。没有重复前五次或变更顺序。恢复前207文件、账本、三服务及native容器ID/命令/启动时间均一致，无遗留实验进程。约3小时44分间隔属于服务时序混杂；固定temperature=0不能消除运行时非确定性，尤其L1已观察到相同前缀的不同输出。

四个已曝光arc来源、每条件一次完整尝试，不能视为八个独立样本，也不能声称unseen或总体可靠性。两个竞争解释：①逐条可模仿标签造成输出模仿，移除该机制减少复述，符合本批178→0；②服务非确定性与早期轨迹选择解释严重故障未复现及费用/附带动作变化，本批不能排除。首断点的修复范围是请求副本中的assistant标签，不是记忆召回或任务授权。

机械结果检查初版误把带既有TOOL OBSERVATION容器的回执要求为整段相等；已修正为验证容器元数据和原始内部回执。embedding与generation按真实HTTP路径分别累计。初版脚本保留在忽略目录，运行源码、输入、原生评分和轨迹没有因此改变。

决定：接受“显式标签候选减少标签模仿”的局部证据，保留可独立选择的native_roles_only；legacy默认和历史recipe不改。未发现新的严重副作用，但两组附带动作均存在，不能晋级为行动可靠性方案。R1定向诊断完成；继续独立R2和R3，R7按候选证据门槛冻结，不增加本批重复次数求有利结果。完整v10与研究Goal仍未完成，Product NO_GO。

## 复现

检出执行提交，使用协议指向的两份recipe及原生选择manifest，依赖/模型/tokenizer/tool/scorer哈希见各prepared identity。私有根为`artifacts/repair-v10/r1-l2-execution-r1/`，保存freeze、明确暂停/恢复记录、8份Root过程回执、原始trace、journal、SQLite、checkpoint、每episode评分与离线审查。新实验需另建隔离run/runtime，不复用本批已尝试目录或修改其账本。
