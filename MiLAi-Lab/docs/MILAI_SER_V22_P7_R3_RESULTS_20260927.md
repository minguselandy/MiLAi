# P7 R3：空证据协议开销已消除，端到端收益未成立

A5原十二例7/12，MERIT native4/5、dependent1/2、Host7/7。预先固定的B1参考分别为R1诊断8/12、R2 MERIT4/5和1/2；不是同源新matched运行。全部失败保留，本轮不再为分数调整prompt，进入独立冻结的小规模未见比较。

## 实现与证据

仅stage v21在`projected.items or projected.derived_rebases`成立时追加原authority。历史v19/v20行为、B1分支、工具/schema、核心projection/lineage、容量、R2局部失败策略和vLLM不变。一个mock Provider窄测覆盖完整wire等价、CURRENT/UNKNOWN、assistant-only stale和旧stage；ruff/mypy/CLI检查与一次新锁打包通过，没有重跑全套测试。

源码mapping=`3f8ddd76a143caa9a652faa6ba577ec12a0861a1b4552955ce4ca4910ccd5be7`；[锁](../data/locks/milai-ser-v22-p7r3.lock.json)SHA=`77a8aa63bb50e9c1fe54383adeeb95a93f55783dc1d731304746b6febfe1c46f`。前身`12e654f4ab941dc70ce8ef0a16d63000dbe25b77`已发布。[方案](MILAI_SER_V22_P7_R3_PLAN.md)、[执行冻结](../data/manifests/milai-ser-v22-p7r3-freeze.json)、[汇总](../data/manifests/milai-ser-v22-p7r3-results.json)绑定参数、输入和全部费用。

十二例全部答案、记忆及动作已重评，逐例见[语义记录](../data/manifests/milai-ser-v22-p7r3-a5-diagnostic-semantic.json)。d02回执未保存；d04未按要求以READY结尾；d08/d09/d11已保存但漏搜；其余七例通过。原20个首轮[实际Provider request全部与B1参考相等](../data/manifests/milai-ser-v22-p7r3-actual-empty-wire.json)，没有反事实删改。d11仍给出泛化建议，反对“额外authority是漏搜必要原因”的假设；温度0也不能保证相同请求产生同一轨迹。

MERIT仍未保存早期约定。episode 2先误用manage_memory(action=search)，工具返回输入校验错误后Host改用search_memory；空结果之后凭空保存5000并退款5000，而正确约定为1774，原checker失败。随后同一记忆更新加入用户明确的6595；episode 4真实检索当前版本并正确退款。成功后“Do not process ... yet”仍留在记忆中。episode 3全额16100正确，但5–10工作日到账说明缺少依据。无容量失败、无skipped，单次工具输入错误不改写为Provider rejection。

本轮确有insert→update，却没有先送达旧版本再更新的链路。实际只有6次CURRENT交付，0stale、0demotion、0exact get；不能把新revision计为SER因果收益。形成、无依据行动与动作后维护分别仍是缺口。

## Failure Review 与费用

Observed failure为稳定的形成/检索遗漏及猜测业务参数。Expected mechanism要求记忆可用时普通Host会检索；Actual chain中d11已保存却首轮直接回答，MERIT则先未保存再猜测。First broken link在SER版本处理之前。

H1为无证据authority扰动；H2为Host本身检索选择/形成不稳定；H3为projection丢内容。相同首request仍漏搜支持H2、否定将H1作为唯一原因；完整Store/wire核对反对H3。最小下一步是冻结当前通用方法，在未见原任务上同源比较B1/lite/full。独立Formation/Reconciliation研究随后进行，不能通过追加退款规则或强制每题搜索修分。Decision：Continue至P8/P9，无端到端优势结论。

| 运行 | 生成 | input/output | 总tokens | embedding请求/tokens |
| --- | ---: | ---: | ---: | ---: |
| A5 diagnostic | 34 | 17571/1587 | 19158 | 13/359 |
| A5 MERIT | 21 | 20259/1136 | 21395 | 4/109 |
| 合计 | 55 | 37830/2723 | 40553 | 17/468 |

连续SER415生成/373013tokens/4370embeddingtokens/75版本get，未知/截断/Judge均0，历史账本未清零。49/55请求真实省略authority；63×49=3087为同轨迹片段反事实估计，不额外当作实测节省。诊断比旧A5少1866tokens但答案也有变化；两条新A5合计比固定B1参考多448tokens，不能称总成本优越。

projection CPU15378439ns/wall11934249ns，Provider收据wall24.867078秒。trace1270156、sidecar356352、checkpoint581632 bytes；journal/共享Store另计。persistent semantic State仍为0；rebase/refresh精确率、召回率和stale consumption分母0，均undefined。全部原始轨迹保持ignored，公共结果保留SHA。

## Reflection

1. 支持：机械条件可以消除无证据协议开销。
2. 反驳：去掉authority就能修复d11，或单例分差足以证明方法退化。
3. 第一断点：形成/主动检索，而非版本投影。
4. 简单解释：同wire的模型轨迹变化，以及从未进入记忆的信息不可恢复。
5. 简单方法：保持这一处条件，不再叠加协议补丁。
6. 复杂度：已有机械证据足够，不需要新的语义State或模型。
7. 过拟合：全部仍是开发数据，新正式selection必须预注册。
8. 反例：空wire真实相同却d11失败；CURRENT和只有派生风险时仍保留authority。
9. 决定：冻结后做小规模B1/lite/full未见比较；生命周期独立研究继续。
10. 理由：机制控制成立，暴露差异已定位到非SER链路；效果仍须独立验证，不靠重复已见样本证明。

复现沿用R2 config与R3新锁，freeze列出两个A5 run及固定B1参考。旧R1/R2从各自commit恢复，不能用当前源码覆盖历史锁。Product Schema/API/权限/Canonical未变化。
