# V0219：最终研究决策与验收

状态：WHOLE_GOAL_COMPLETE_WITH_DECLARED_VALIDITY_GAPS。
结论：`FAILURE_REGIMES_RECORDED + KEEP_SIMPLE_NO_QUALIFIED_REGIME + VALIDITY_GAPS_RECORDED`。
这不是“所有State无效”或“普通Memory已足够”；Memory因果、总体频率与机制创新仍INCONCLUSIVE。

[基线结果](MILA_V0219_BASELINE_RESULTS_20260911.md)和[失败图谱](MILA_V0219_FAILURE_MAP_20260911.md)
给出完成依据；[执行账](MILA_V0219_EXECUTION_20260911.md)保留从准入到终态的逐步历史。
原[Goal](MILA_V0219_外部行为失效区间发现与机制筛选_GOAL_20260911.md)规划状态作为冻结历史保留，不回写。

## 决策

四新原根/三家族的一完整有界波已真实完成：28episode、448生成、9,820,337raw，全部结算。
所有A/B最终缺完整对象集，但保留正确数字、部分业务写入、实际状态修复和诚实部分交付。
实际12B冷旧Note/当前双呈现；不是只有静态校准，也不是把无Note分母换掉。
R1跨根普遍遇到动作协议问题；其他来源明确的R1重复现象尚不满足同一可操作模式跨3根/2家族且排除上游解释。
因此G_REGIME未通过，当前消费profile暂停，零候选。没有为完成阶段编号而强造机制或继续耗题。

F4不触发；F5最终候选卡0、pilot0、消融0、查新主张0；F6不触发，无Seal B或确认模型请求。
未形成候选，所以不做没有对象的论文新颖性比较，也不包装成ENGINEERING_GAIN_ONLY。
未来一般来源发现性、动作schema可用性、执行后置条件校准可以另立共同baseline合同；
这只是建议，不是已实施修复、效果验证或本次新增授权。

## Goal逐项验收

| 要求 | 实际交付/不足 |
| --- | --- |
| F0 corpus、exposure、lineage、lane账 | 全18,760文件/10,800,744,184字节验证，中性三lane目录与暴露回查。历史访问日志不全，UNKNOWN_EXPOSURE保守排除C；不把WMA JSON数当独立历史 |
| F1真实前瞻合同/封存 | Seal A固定62 D/9family与26 reserve/4family；前56顺序审查4接受/52HOLD，原12D排除。C static accepted0；reserve资格未证明。L/S未形成行为准入合同，明确不足而非伪造完成 |
| 至少一个有效有界F2/F3 | 4A/24B全请求/usage/持久链/当前资料/动作世界审计，四根源绑定非盲评审和全分母/首失效图谱。字段判据争议保留；真实missing-object终点独立成立 |
| 条件F4/F5 | G_REGIME不通过：跨根最清楚模式是协议错误，其他模式缺足够无混杂R1根。零候选，不强制实验 |
| pilot/F6判断 | 无候选，pilot/F6/Seal B均NOT_TRIGGERED。26 reserve不消费，candidate57仍未打开；L/S不为补分启动 |
| 最终决策、成本、安全 | 本文与基线/图谱、Git外汇总及终态审计绑定；所有生成用量已知、Judge0/rawcapnull。自有API/PG停止、卷保留、共享vLLM未停；Product/A0/schema/权限/部署不变 |

完成指本Goal允许的有界发现与条件分流已交付，不是所有原生benchmark执行完毕或所有有效性缺口消失。
12根/4family是可按分流提前结束的开发目标，不把首波4根/3family说成目标已跑满。

## 关键残余限制

- 同一非盲开发者构建并裁定，无独立审稿/盲审/Judge。金融2项、人事7项DISPUTED不改写为确定错误。
- 三份自然A Note本来混合正确/错误，第四份NO_WRITE；N0可见业务历史。呈现不是导致。
- 24B全部有协议拒绝，名义16机会不保证能力；唯一A output-length截断及所有失败均留成本。
- 单模型、文字支持适配、四根发现集，没有代表性总体抽样/独立复验。两个HR任务仍只算一个family。
- helpful-history、跨任务交错、长生命周期、L/S边界未得到效用证据；零条件分母写N/A而非零效应。
- HF凭据未进入报告或请求证据；没有新权重、云fallback、OCR/caption、训练、真实邮件/支付/人事决策或部署。

## 账本、安全与软件门

实验总计448请求/9,820,337raw：input9,681,447/output138,890；pending0/violations0、Judge0、active allocation0。
共享A计一次64请求/773,958raw；B384/9,046,379raw。运行2377.67秒。
35个准备tokenize诊断和448个实际生成预检单列；公开预读/Note桥接成本与只读审计也留回执。
代理劳动与实验Provider分账，不声称掌握完整GPU费用。V0218旧1340请求/3,353,114raw原账不变。

主runner/API已退出，自有 `v0212-d0cac455a823-postgres-1` Exited(0)，
`v0212-d0cac455a823_milai_postgres_data` 保留；共享vLLM不操作。
没有删除material evidence、没有重启原批次、没有改变Product全局pin漂移或公开发布件。

最终本轮软件门：1384 passed / 1 optional Host SDK skip（39.80秒），boundary/Ruff/mypy39文件/build/diff通过；
冻结manifest与69实现/依赖校验不变。pytest工具输出截断过，最终计数/退出码完整，未声称保存全终端输出。
新评审/汇总脚本在Git外只增写审计材料；失败的开发尝试在产物创建前停止并保留说明，不修改实验分数。

最终审计回执位于Git外批次 `final-decision-audit-v1.json`；包含本报告/图谱/基线hash、原始输入hash、
冻结依赖再验证、软件门和安全收尾定位。`f3-wave1-summary-v1.json` SHA256
`4543281f3d8a9ae4677bc8377a5beaee48914699cbd58f4280d57f9f3d84c516`。
原result的“待审”状态不覆写，由追加审计及本最终决策完成阶段收口。
