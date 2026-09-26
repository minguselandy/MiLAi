# v20 P3：原三例通过，进入非温度诊断

阶段状态：`PASS_ADVANCE_P4`。A4在原changed/retained/irrelevant三个实例均通过：changed首次实际记录当前8°C，retained实际取得X@2后记录8，irrelevant保持8且没有新增Host搜索。[长程Goal](MILAI_LONG_HORIZON_EXECUTION_GOAL.md)仍在执行，v20也尚未完成非温度验证。

| 实例 | 初始search | 更新后search | exact get | stale-snapshot回复降权 | 获批动作 |
| --- | ---: | ---: | ---: | ---: | --- |
| changed | 1，真实X@1 | 0 | 3，X@2 | 3次投影同一原回复 | 8°C |
| retained | 1，真实X@1 | 0 | 3，X@2 | 3次投影同一原回复 | 8°C |
| irrelevant | 1，真实X和Y | 0 | 3，Y@2 | 3次因Y过期的snapshot降权 | 8°C |

每例3条公开消息、5次生成、批准后1次业务动作；Host memory写入为0。原fixture、业务工具、B1响应schema、24-token authority原则、A3刷新策略和vLLM均保持不变，新增机制为普通助手文本的request-level lineage与请求副本降权。

## 真实链路

changed的checkpoint原回复仍是4°C；外部update后，实际Provider请求中的旧记忆正文替换为X@2当前8°C，生成于X@1 snapshot的原助手回复替换为通用历史marker。第二条公开消息的回复变为8°C，绑定实际送达的X@2；第三条消息前它未被误判为stale。随后业务调用实际参数为8。

三个实例的9次derived_output_rebase都与实际Provider body、生成request、response/AIMessage ID、原/投影hash和版本refs核对。原ToolMessage与助手正文留在checkpoint，已执行tool-call JSON原样保留。lineage跨重启可恢复，同文本不同response不会靠文本误关联。累计9条ordinary response lineage；模型响应schema不增加字段。

机械snapshot rebase precision为9/9，recall为9/9，UNKNOWN绑定事件为0；分母使用投影前实际存在的eligible ordinary replies。这不是逐词语义因果precision。irrelevant仍有3次Y读取及3次旧回复降权，不能称零干预或证明旧回复语义依赖Y；动作稳定只是本例的保留结果。

## 成本与验证

P3共15次生成，输入13669、输出421，合计14090tokens；10次embedding请求、274tokens；9次exact get。无第二模型、Judge、unknown usage、截断或协议拒绝。普通search和业务followup各3次生成，均在15次内。旧repair费用45次/41457tokens/808embeddingtokens保留在history。

projection CPU累计17.466ms、wall26.674ms；其中exact read wall11.695ms，二者不能相加。Provider回执wall6.069秒，不含全部本地运行时间，也不能据此声称速度收益。降权marker为31tokens/次、9次共279片段tokens，已包含在输入账单。

三个run实际文件字节：trace654321、sidecar294912、checkpoint237568、业务journal2418。机械lineage有持久事实metadata，不能因为语义State为0就宣称零存储；更多分项见[accounting](../data/manifests/milai-ser-v20-p3-accounting.json)。共享PostgreSQL物理空间未按run归因。

受影响29条窄测通过，ruff/mypy/两个边界、schema/protocol与配置一致性通过。没有重复decoder probe、full suite或benchmark运行；必要build待v20当前源码阶段完成后做一次。源码冻结62文件mapping `a4a0036bc86cb145adcb6783fcac0ca2fd9ebe54165e95741e5aec53ae838690`；[lock](../data/locks/milai-ser-v20.lock.json) SHA `130b3b8bb99ff95fc24d10be2ec87608afff35d510eeb8f6eccc483f1ff970ef`。见[freeze](../data/manifests/milai-ser-v20-p3-freeze.json)及[逐请求结果](../data/manifests/milai-ser-v20-p3-results.json)。

## Reflection（总计划§32）

| 问题 | 本阶段回答 |
| --- | --- |
| 支持什么假设 | 在当前原changed控制中，处理过期snapshot生成的助手文本后，当前动作可由4改为8。 |
| 反驳什么假设 | 这个实例并非必须新增持续Decision State或第二模型才能适应；但未证明所有任务都如此。 |
| first broken link | 原例未处理的derived context已被机械失效；下一不确定处是非温度、缺失和多版本泛化。 |
| 更简单解释 | 通用marker中的重新评估提示也可能贡献效果，不能把全部收益归因于删除正文。 |
| 更简单方法 | 封存A3在此失败；capsule等替代未比较，不宣称A4是全局最简。 |
| 复杂度是否合理 | 一张机械lineage表、一次request-copy投影，无第二生成；实际成本可测，长期history代价尚待验证。 |
| 是否可能过拟合 | 只有三个已暴露温度实例，明显不足以支持泛化。源码无具体值或case分支仍不等于已证明泛化。 |
| 应加什么反例 | 分类、布尔、删除、多revision、assistant-only stale，以及后续无变化/current冲突/mixed对象。 |
| 下一步 | Continue到P4的五个预先定义非温度控制，再按证据进行P5/P6。 |
| 为什么 | 原三例链路已成立，下一问题是机制边界，不能直接进入formal，也不因一次成功跳过总路线。 |

比较使用历史封存A3与新A4，run namespace/随机ID和自然生成文本不同；没有把不同轮轨迹拼接成matched重复试验。若后续因果问题需要同源A3，CLI已支持，届时独立冻结并计费。

## 当前复现入口

本P3使用新 `tools/run_milai_ser.py`、`configs/milai-ser-v20.json`、上述lock；arm为 `a4_selective_rebase`，matched参考可用 `a3_exact_refresh`。先按相同fixture/freeze执行prepare，再run，参数形式沿[旧复现入口](MILA_FRESHNESS_PROJECTION_V19_REPAIR_REPRODUCTION_20260926.md)，替换CLI、config、lock和arm。使用新run ID、空namespace和独立本地配置；DSN只通过环境变量注入，连续账本不能重置。

原始证据位于ignored `artifacts/ser-v20/p3-a4-{changed,retained,irrelevant}-r1/`。Git仅发布manifest、hash及紧凑结果。后续P4若扩展harness，使用新lock和源码checkpoint，不覆盖本P3身份或轨迹。
