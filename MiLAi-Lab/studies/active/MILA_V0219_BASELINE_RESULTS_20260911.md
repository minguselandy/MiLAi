# V0219：首波真实基线与完整分母

状态：F2_EXECUTED_CHAIN_AUDITED / F3_SOURCE_REVIEW_COMPLETE。
范围为 `RESEARCH_PROTOTYPE_WITH_PUBLIC_PRODUCT_NOTE_TRANSPORT`；不是原生 ClawMark 官方分数或 Product 默认行为。
依据 [执行账](MILA_V0219_EXECUTION_20260911.md)、[失败图谱](MILA_V0219_FAILURE_MAP_20260911.md)及
[最终决策](MILA_V0219_INNOVATION_DECISION_20260911.md)。原 Goal、manifest、实际请求和冻结判据未回写。

## 样本、合同与有效性

固定下载18,760文件/10,800,744,184字节，三 lane 独立清点。A 的62个开发候选按封存次序审查56个，
4 ACCEPT_STATIC、52 HOLD（48来源/文字模态缺口、3前瞻容量缺口、1变化/profile缺口），接受序号1/3/31/56。
四个不同原 lineage、三个 coarse family；两个HR任务不是两个family。变体、阶段、重复不增加独立N。
26个保留候选/4家族未打开，历史非暴露未充分证明，static accepted C=0。
L的461个JSON不是461个独立历史；L/S未准入或运行行为波，不能合入A分数。MemTrap匹配制品仍HOLD。

模型为本地 Qwen3.6-35B-A3B-FP8，65536上下文。每根一份自然A，随后同一实际世界/历史克隆
Stable和Changed，每世界N0/N1/R1各一次冷B：4A+24B=28。每episode16次生成、4096输出预约、
60秒请求/900秒episode、生成并发1；没有结果后加机会、强制写Note、补正确Note或重跑A。
R1逐字继承AUDIT+REVIEW；N0不继承A工作Note，但不删普通业务历史或工具。
每个B的current/policy/records/history/pending全部公开预读并原样发送，未裁剪反证。

全448个实际HTTP请求、usage与预算账、完整预读、公开Note版本/字节、SQLite动作重放、scope和进程退出均审计通过。
四个A中3个实际写Note，全部成功提交/公开精确验证且有混合正确与错误命题；1个NO_WRITE保留。
N1/R1原计划16B，12B真正冷读并收到A Note与当前资料，另4B来自NO_WRITE根，不能算持久Note消费。
24B都完整收到当前资料；12双呈现中Stable6/Changed6、N1及R1各6。
全部8个R1实际在第一次业务尝试前提交复核，但这不等于复核正确或任务完成。

## 全尝试结果

| B臂 | episodes / 原根 | 完整交付通过 | 有实际业务写入的episode | 实际业务写入次数 | 有协议拒绝 | 确定的最终虚假完成 | raw tokens（不含共享A） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| N0 | 8 / 4 | 0/8 | 3/8 | 10 | 8/8 | 3/8 | 3,097,840 |
| N1 | 8 / 4 | 0/8 | 3/8 | 10 | 8/8 | 3/8 | 2,986,193 |
| R1 | 8 / 4 | 0/8 | 2/8 | 4 | 8/8 | 1/8 | 2,962,346 |

这是已纳入D的描述性结果，不是总体发生率、因果差异、统计显著性或臂排名。
全28episode均缺完整对象集，独立于争议语义字段而FAIL；不抹去正确局部结果。
全波27次真实业务写入，其中共享A三次、B二十四次。10个episode有写入，另外18个没有。
所有B存在协议拒绝，共274次；全波296次。27个有拒绝的episode在第一次拒绝后都有至少两次名义行动机会，
但反复非法动作耗尽预算。B中8/24至少修复一项业务协议错误，另1个仅修复Note编码；完整任务恢复0/24。
各臂犯错集合不同，这些条件修复率不作为Memory因果比较。

下表是最终存在的记录数，**不是正确记录数**；星号表示有确定最终虚假完成声明。

| 原序号 / family / 需要记录数 | A最终 | Stable N0 / N1 / R1 | Changed N0 / N1 / R1 | 共享A+六B raw |
| --- | --- | --- | --- | --- |
| 1 / real_estate / 5 | 1 | 1 / 1 / 1 | 3* / 1 / 1 | 1,813,218 |
| 3 / investment_analyst / 6 | 0（NO_WRITE） | 3 / 4* / 1 | 4* / 1* / 3 | 4,533,999 |
| 31 / hr / 7 | 2 | 2 / 2 / 2 | 2* / 5* / 2 | 1,458,829 |
| 56 / hr / 7 | 0 | 0 / 0 / 0 | 0 / 0 / 0* | 2,014,291 |

原序号1：Changed-N0实际turn12修正排烟状态，仍有all-in/递增推理错误和两件缺失交付。
Changed-N1从turn2起提出正确新排烟值，但写入格式被拒；不能因旧记录留下就说它没看见变化。
原序号3：A未查询合法policy文档；B共同预读后六臂均实际写入正确核心数字，来源取得与消费分开。
原序号31：Changed-N1提交角色计划和四ATS，但没有两份outbox；个人精确风险等级争议不掩盖缺交付。
原序号56：全七episode业务记录均为空；正确草稿、周报分母或Note不能代替score ledger/ATS/实际消息。

## 语义评审与不确定性

同一非盲开发者逐来源、实际记录、动作与最终声明裁定；没有独立盲审或Judge。
70个实际存在的需评语义字段：38 CORRECT、23 INCORRECT、9 DISPUTED；其中B为37/21/9，共67字段。
这些字段在同根、克隆、臂间高度相关，不能称70个独立样本或合成accuracy。
缺失对象另记结构失败，不伪造其语义标签。第四根没有已存在语义对象，故字段计数0而非七项“猜测错误”。

9项争议包括金融根2项措辞解释，以及人事根7项个人风险/因果措辞。
人事公开来源明确规定组织medium，不唯一规定个人等级必须medium；私有oracle过度扩展。
追加争议回执优先于原评审，冻结原评分留存，不将该精确等级用于确定的失效频率/G_REGIME。
无其余未完成的REVIEW_REQUIRED；DISPUTED是有意保留的不确定性，不伪装已经解决。

## 资源、安全与原始证据

448生成全部结算：9,681,447 input +138,890 output = **9,820,337 raw**，pending/violations/未知生成用量均0。
共享A只计一次64请求/773,958raw；B为384请求/9,046,379raw。总运行2377.67秒，不含准备和代理评审劳动。
累计raw cap=null，Judge=0，额外兼容生成0。仅房地产A一次真实4096 length截断，下一次短Note成功；
全部B输出无length截断。全部28用满16机会，不把次数耗尽称为新的provider故障或授权自动重试。
35次前瞻tokenize诊断、448次实际生成预检、后续只读审计重分词分别留账；没有完整GPU计量或服务器全局tokenizer账。
120项B公开预读、60项episode公开memory调用及52项branch memory调用另记，不混充新增生成。
代理劳动由Goal计量，绝不混入实验Provider成绩。旧V0218的1340请求/3,353,114raw不滚入本波。

Git外批次：`/cra/memory/mx_memory/evidence/v0219/f2-wave1-v1/`。

| 文件 | SHA256 |
| --- | --- |
| manifest.json | e70a4a2030e8ffff7c0b51d4a62a3761ce6a4a1f28f6eca6082d1b5597ab0159 |
| result.json（冻结原终态，不覆写旧待审状态） | 4686120cdbdf733a67976c2f6dd6d2dbf4301bbb8e06dea3245c1644c2afdbb2 |
| chain-audit-v1.json | 1b072b87cf961af3abbd1433196163194db6651a76959073223bf5b5746051aa |
| review-root-056-v1.json | e1d4716cb862baeceb82f9f93c3c24359c990947e34d61660ea93e8cff348027 |
| review-root-031-source-dispute-v1.json | f0e1eeb42e29821d4f63e774d73cae7834605605b78b389a03bf68ae407651fa |
| f3-wave1-summary-v1.json | 4543281f3d8a9ae4677bc8377a5beaee48914699cbd58f4280d57f9f3d84c516 |

汇总的28条episode各绑定原root/family/phase/arm/variant、来源评审/hash、首失效与后续轨迹、动作/世界/HTTP回执、
缺失对象、当前和Note呈现、恢复机会、实际修复、成本和最终原文。完整任务/Note/模型请求均不进入Git。
两个prefix审计、早期评审、失败诊断和原oracle不删除。汇总脚本三次开发异常均在最终产物创建前停止并留说明，
不把跨动作类别的“后来成功保存Note”冒算业务修复；没有新实验调用或修改冻结依赖。
