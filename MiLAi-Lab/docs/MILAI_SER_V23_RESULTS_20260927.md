# v23：未见三臂小样本，主开发转向记忆生命周期

六条预注册轨迹全部执行并保存。B1 native6/10、dependent0/4；SER-lite与SER-full均native7/10、dependent1/4。全部0exact refresh、0derived demotion，不能把多出的一分当作SER适应收益。共同首要断点仍是早期约定未保存，其后空搜、猜测业务值和动作后记忆未更新。本阶段完成，决定PIVOT主开发到独立Formation/Reconciliation；SER机制及全部结果保留，不推广到Product。

## 调用前冻结与复现

预注册先固定官方MERIT commit `293933d96b1d1849e1f20d1bb324def5de9ed33f`的base_seed3/4，各一个hard原arc、5episode、7公开消息；源码冻结后才生成原任务/world，未筛题或改消息。每seed顺序B1/A3/A4，共30episode、42公开消息机会。源码和输入在首个真实请求前由Luna发布为`f096e40e0b3311d03ce3a483a5d1716576ea889c`并核对remote。

- [预注册](../data/manifests/milai-ser-v23-pre-registration.json) SHA=`7198499ac31f48bc023c52032be4d842b3af638424286e11586555d3f89031a0`。
- [70文件源码锁](../data/locks/milai-ser-v23.lock.json) mapping=`1b90bad524f7ff041fb5484b95fdd91b7f18f9d6240d460ad69afc7ff8f21e07`，lock SHA=`4ebfe530dc71d95f81d153b3cb9c1dbccbef0127e3b231fac581e824535b21eb`。
- [执行冻结](../data/manifests/milai-ser-v23-execution-freeze.json)绑定两份selection/world、六份config/prepared、空namespace及模型身份；[完整汇总](../data/manifests/milai-ser-v23-results.json)绑定六份结果SHA、连续费用和实际退款回执。

新增入口复用同一MERIT loop/scorer；通用frozen loader校验声明的原字节，旧exposed wrapper保留seed0约束。五项必要零模型检查通过，新增旧wrapper成功断言后该窄测再通过；ruff/mypy/CLI/config/CI检查与一次build通过。A3/A4的stage v21方法及R3条件authority不变，无rank截断。无post-outcome方法修改、无第二模型/Judge、无vLLM设置变化。

复现checkout该调用前commit，恢复selection指向的原始字节或用声明的官方generator重建并核对SHA，沿执行freeze的CLI参数、新namespace及输出运行。原容量、世界checker和失败策略不变；不可覆写历史结果或重置账本。包含selection/freeze元数据，不含raw arc/world、私密连接信息或transcript。

## 任务与Host结果

| 原arc | B1 native/dep | A3 native/dep | A4 native/dep |
| --- | --- | --- | --- |
| arc3 | 3/5，0/2 | 3/5，0/2 | 3/5，0/2 |
| arc4 | 3/5，0/2 | 4/5，1/2 | 4/5，1/2 |
| 合计 | 6/10，0/4 | 7/10，1/4 | 7/10，1/4 |

| arm | Host完成消息 | 容量失败 | skipped | 生成 | tokens | embedding请求/tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 | 12/14 | 1 | 1 | 50 | 50603 | 24/242 |
| A3 | 12/14 | 2 | 0 | 55 | 57581 | 29/263 |
| A4 | 13/14 | 1 | 0 | 48 | 49414 | 14/182 |

Root在六条运行全部结束后阅读完整答案、记忆内容、工具参数、原checker事实和实际业务回执。所有21条早期约定/修改观察都没有写入记忆。12个依赖任务机会中，2次正确退款、6次无依据错误退款、4条容量失败。八个实际退款回执均ok=true，错误不是评分器误读或未执行的计划。

arc3正确约定7256和1882均丢失。B1随后猜2000/1900并保存、实际退款；A3两次空搜至容量失败；A4第一依赖任务容量失败，第二猜1000并退款。三臂原地址修改与确认消息通过。B1/A4还各误用manage_memory(query=...)创建一条content=null；普通工具校验/默认值行为保留，未把null称为有效形成。

arc4早期2705约定同样未保存。B1在其依赖消息空搜耗尽额度，因此同episode后续明确1207消息skipped；下一episode猜1000并退款。A3/A4均先猜2000、错误退款，但随后实际收到1207、保存并在下一episode搜出、正确退款。两臂成功后记忆仍写“Do not process ... yet”。A4另有一条null插入。此差异包含容量失败影响后续可见消息的连锁效应，不能用成功后缀替换失败前缀。

所有20个SER臂episode首个实际Provider请求与相应B1请求完整相同；后续轨迹仍不同，说明不能仅凭温度0或源代码相同假定响应确定。A3/A4各4次CURRENT item交付，其余无memory item；无旧版本召回、无exact get、无derived风险降级。A3仍记录12条ordinary lineage、A4记录13条，作为观察开销如实保留。

## Failure Review

Observed failure：确认了未来约定却不保存；之后猜测或空搜索循环，成功动作后pending记忆不变。Expected mechanism：重要观察进入durable memory，版本更新后SER才有可处理的输入。Actual chain：公开约定→业务确认但0写入→下一episode空bank→猜测/容量失败→部分新明确值后来保存→正确使用后不对账。First broken link为Formation；SER旧版本链本轮没有自然机会。

H1：普通Host未稳定识别未来用途；H2：已形成但检索或projection丢失。21次早期观察全无写入、对应Store为空，支持H1并反对H2。H3：局部容量路径和模型轨迹波动造成分差；相同首wire、B1跳过后续1207、A3/A4真正收到并保存该值支持其重要性。不能排除CURRENT authority影响后续消费，但它不是rebase/refresh收益。

通用下一候选为独立prospective-retention cue，提醒普通LLM考虑跨session缺失观察的后果；不得自动写正文、按退款领域路由或强制所有消息保存。Reconciliation另以真实business receipt提出受影响记忆候选，由普通LLM决定更新/no-op；不由程序改自然语言状态。独立基线、数据和费用，不将这些修复归因SER。后续不改本轮prompt或补跑替换六条结果。

Decision：PIVOT主开发优先级，保留SER为受控机制，暂不扩展其大规模效果测试。P10的稳定主效果条件未建立；第二模型族的正式要求仍未完成，当前未配置独立端点，已异步请求该信息，其余开发继续。不能因待配置而标master完成，也不等待它才开展P11/P12。

## 成本与Pareto限制

本轮153生成、input150896/output6702、总157598tokens，67embedding请求/687tokens；exact get0，未知/截断/Judge均0。连续SER为568生成/530611tokens/5057embeddingtokens/75get。四次容量失败另计，历史费用和未知用量历史不清零。

本轮数值上A4以49414tokens、7/10支配B1的50603、6/10及A3的57581、7/10；这是两arc一次轨迹的观测Pareto，不是可复现优势或因果结论。A4较B1少1189tokens（约2.35%），同时有不同失败/可见消息路径且0rebase。A5没有纳入预注册主arm，开发消融保持独立，不能混入该未见Pareto。

projection CPU39399224ns/wall29484202ns；Provider收据wall67.985202秒。trace4680373、instrumentation1163264、checkpoint2166784 bytes；原world/journal/共享Store另计。语义State0不等于总存储0。版本get与observer额外读取分列于各run；stale-consumption、rebase/refresh precision/recall分母0，均undefined。整体可靠性和多模型结论未建立。

## Reflection

1. 支持：Formation及动作后对账是当前普通任务的主要缺口。
2. 反驳：受控SER成功足以推定其会在原任务自然产生收益。
3. 第一断点：早期未来约定没有保存，而非旧证据没被替换。
4. 简单解释：模型轨迹波动和容量失败导致后续消息可见性差异。
5. 简单方法：独立、通用的未来用途提示，随后独立receipt驱动对账。
6. 复杂度：不再扩SER控制结构；保留已证明的版本/lineage组件。
7. 过拟合：两arc只小样本；结果后不改方法，生命周期验证用独立冻结范围。
8. 反例：临时计算不保存；无成功业务收据不误改pending；不相关记忆保持不动。
9. 决定：PIVOT至P11主开发，继续P10必要边界与P12交付。
10. 理由：本轮没有SER触发机会，继续扩大同类回归不能填补上游缺口；先修可证断点并保留反例。

Product API/Schema/权限/Canonical均未改变；方法仍是Lab RESEARCH_PROTOTYPE。Luna发布结果后继续开发，master保持ACTIVE。
